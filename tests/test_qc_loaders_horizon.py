"""
Tests for the cumulative vs latest-batch horizon behaviour in
``get_sample_statistics_summary``.

Regression coverage for: the Sample Breakdown table previously reported
``kraken_df['reads'].sum()`` over whatever report happened to be on disk,
which produced latest-batch numbers when only batch files existed. The
Stage Strip used ``root.cumul_reads + unclassified.cumul_reads``, so the
two surfaces disagreed for the same sample.
"""

import os
import time
import json

import pytest

from nanometa_live.core.utils.qc_loaders import get_sample_statistics_summary


def _backdate_mtime(path, seconds=5):
    """Make a file look stable to the loader's stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


def _write_kraken_report(path, classified, unclassified):
    """Write a minimal Kraken2 report with the given classified and
    unclassified totals on ``root`` and ``unclassified`` rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate_c = (classified / (classified + unclassified) * 100) if (classified + unclassified) else 0
    rate_u = 100 - rate_c
    content = (
        f"{rate_u:.2f}\t{unclassified}\t{unclassified}\tU\t0\tunclassified\n"
        f"{rate_c:.2f}\t{classified}\t0\tR\t1\troot\n"
        f"{rate_c:.2f}\t{classified}\t{classified}\tS\t562\t  Escherichia coli\n"
    )
    path.write_text(content)
    _backdate_mtime(path)


def _write_empty_fastp(fastp_dir, sample):
    """Force the loader to skip FASTP and use Kraken2 for read totals."""
    fastp_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "summary": {
            "before_filtering": {"total_reads": 0, "total_bases": 0},
            "after_filtering": {"total_reads": 0, "total_bases": 0, "q30_bases": 0},
        },
        "filtering_result": {},
    }
    fp = fastp_dir / f"{sample}.fastp.json"
    fp.write_text(json.dumps(data))
    _backdate_mtime(fp)


class TestSampleSummaryHorizons:
    """Verify that both horizons are surfaced with the expected values."""

    def test_cumulative_and_latest_when_only_batches_exist(self, tmp_path):
        """With only batch files, cumulative uses the highest-numbered
        batch and latest-batch matches it (single batch = same horizon)."""
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode01")

        _write_kraken_report(
            kraken_dir / "barcode01_batch0.kraken2.report.txt",
            classified=150, unclassified=50,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        assert len(df) == 1
        row = df.iloc[0]
        assert row["sample"] == "barcode01"
        assert row["reads_cumul"] == 200
        assert row["reads_latest"] == 200
        assert row["classified_cumul"] == 150
        assert row["classified_rate_cumul_num"] == 75.0

    def test_cumulative_preferred_over_batch_for_cumul_horizon(self, tmp_path):
        """When both a cumulative report and batch files exist, the
        cumulative report drives the cumulative horizon and the highest
        batch file drives the latest horizon."""
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode01")

        # Cumulative snapshot: 800 filtered reads
        _write_kraken_report(
            kraken_dir / "barcode01.cumulative.kraken2.report.txt",
            classified=600, unclassified=200,
        )
        # Latest batch: only 216 reads (reproduces the reported bug shape)
        _write_kraken_report(
            kraken_dir / "barcode01_batch3.kraken2.report.txt",
            classified=170, unclassified=46,
        )
        # Earlier batch that should be ignored for the latest horizon
        _write_kraken_report(
            kraken_dir / "barcode01_batch1.kraken2.report.txt",
            classified=90, unclassified=20,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        row = df.iloc[0]
        # Cumulative must NOT equal the latest-batch number
        assert row["reads_cumul"] == 800
        assert row["reads_latest"] == 216
        assert row["classified_cumul"] == 600
        assert row["classified_latest"] == 170
        assert row["classified_rate_cumul_num"] == 75.0
        # Legacy alias must also report cumulative, not latest-batch
        assert row["reads"] == 800

    def test_latest_falls_back_to_cumulative_when_no_batches(self, tmp_path):
        """Completed batch-mode runs emit a single cumulative report with
        no batch files. The latest-batch horizon should collapse to the
        cumulative values rather than showing zero."""
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode02")

        _write_kraken_report(
            kraken_dir / "barcode02.cumulative.kraken2.report.txt",
            classified=400, unclassified=100,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        row = df.iloc[0]
        assert row["reads_cumul"] == 500
        assert row["reads_latest"] == 500
        assert row["classified_rate_latest_num"] == row["classified_rate_cumul_num"]

    def test_status_driven_by_cumulative_classification_rate(self, tmp_path):
        """Status should track the cumulative classification rate so that
        a poor latest batch does not flip a healthy run to 'Issue'."""
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode03")

        _write_kraken_report(
            kraken_dir / "barcode03.cumulative.kraken2.report.txt",
            classified=900, unclassified=100,
        )
        # Latest batch is noisy
        _write_kraken_report(
            kraken_dir / "barcode03_batch4.kraken2.report.txt",
            classified=10, unclassified=40,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        row = df.iloc[0]
        assert row["classified_rate_cumul_num"] == 90.0
        assert row["classified_rate_latest_num"] == 20.0
        assert "Complete" in row["status"]


class TestLatestBatchEqualsCumulative:
    """The dedup guard that lets the summary skip a redundant parse."""

    def test_true_for_standard_report_only(self, tmp_path):
        """A lone standard report (no cumulative, no batch) -> horizons equal."""
        from nanometa_live.core.utils.classification_loaders import (
            latest_batch_equals_cumulative,
        )
        kraken_dir = tmp_path / "kraken2"
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt",
            classified=150, unclassified=50,
        )
        assert latest_batch_equals_cumulative(str(tmp_path), "barcode01") is True

    def test_false_when_cumulative_present(self, tmp_path):
        from nanometa_live.core.utils.classification_loaders import (
            latest_batch_equals_cumulative,
        )
        kraken_dir = tmp_path / "kraken2"
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt", classified=150, unclassified=50,
        )
        _write_kraken_report(
            kraken_dir / "barcode01.cumulative.kraken2.report.txt",
            classified=150, unclassified=50,
        )
        assert latest_batch_equals_cumulative(str(tmp_path), "barcode01") is False

    def test_false_when_batch_present(self, tmp_path):
        from nanometa_live.core.utils.classification_loaders import (
            latest_batch_equals_cumulative,
        )
        kraken_dir = tmp_path / "kraken2"
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt", classified=150, unclassified=50,
        )
        _write_kraken_report(
            kraken_dir / "barcode01_batch0.kraken2.report.txt",
            classified=150, unclassified=50,
        )
        assert latest_batch_equals_cumulative(str(tmp_path), "barcode01") is False

    def test_summary_dedup_path_matches_horizons(self, tmp_path):
        """With only a standard report, the dedup reuses cumul_df and the
        latest horizon equals the cumulative one (no separate parse)."""
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode01")
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt",
            classified=300, unclassified=100,
        )
        df = get_sample_statistics_summary(str(tmp_path))
        row = df.iloc[0]
        assert row["reads_cumul"] == 400
        assert row["reads_latest"] == 400
        assert row["classified_cumul"] == row["classified_latest"] == 300
        assert row["classified_rate_latest_num"] == row["classified_rate_cumul_num"]


def _write_nanostats(path, reads, total_bases, quality, n50):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"Mean read length: {total_bases / reads:,.1f}\n"
        f"Mean read quality: {quality}\n"
        f"Median read length: 1000\n"
        f"Median read quality: {quality}\n"
        f"Number of reads: {reads:,}\n"
        f"Read length N50: {n50:,}\n"
        f"Total bases: {total_bases:,}\n"
    )
    _backdate_mtime(path)


class TestZeroReadSampleDoesNotBorrowAggregateStats:
    """A zero-read barcode must not display the whole run's statistics.

    When a sample's own NanoPlot/seqkit stats showed 0 reads, the summary
    substituted the ALL-SAMPLES aggregate with no gate on the sample count.
    Intended for single-sample mode (where the aggregate IS the sample), it
    fired identically under by_barcode: a failed barcode -- or a negative
    control -- showed the run's combined reads/bases/N50 as its own QC row.
    Audit 2026-08-16, finding L11.
    """

    def test_zero_read_barcode_keeps_its_own_zeros_in_multi_sample_mode(
        self, tmp_path
    ):
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "barcode01")
        _write_empty_fastp(tmp_path / "fastp", "barcode02")
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt",
            classified=900, unclassified=100,
        )
        _write_kraken_report(
            kraken_dir / "barcode02.kraken2.report.txt",
            classified=2, unclassified=0,
        )
        # NanoPlot stats exist only for barcode01.
        _write_nanostats(
            tmp_path / "nanoplot" / "barcode01" / "NanoStats.txt",
            reads=1000, total_bases=5_000_000, quality=12.5, n50=8000,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        row2 = df[df["sample"] == "barcode02"].iloc[0]

        assert row2["n50"] in (0, "N/A"), (
            "a barcode with no QC stats displayed the whole run's N50 as "
            "its own"
        )
        assert row2["base_pairs"] != 5_000_000
        assert row2["mean_quality"] in (0, "N/A")
        # Read total still falls back to this sample's own Kraken2 count.
        assert row2["reads_cumul"] == 2

    def test_single_sample_mode_still_uses_the_aggregate(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        _write_empty_fastp(tmp_path / "fastp", "sample1")
        _write_kraken_report(
            kraken_dir / "sample1.kraken2.report.txt",
            classified=900, unclassified=100,
        )
        # Aggregate-level NanoPlot output only (single-sample runs publish
        # to the nanoplot/ root, not a per-sample subdir).
        _write_nanostats(
            tmp_path / "nanoplot" / "NanoStats.txt",
            reads=1000, total_bases=5_000_000, quality=12.5, n50=8000,
        )

        df = get_sample_statistics_summary(str(tmp_path))
        row = df[df["sample"] == "sample1"].iloc[0]
        assert row["n50"] == 8000
        assert row["base_pairs"] == 5_000_000
