"""
Tests for qc_loaders incremental seqkit layout detection.

Regression coverage for the nanometanf v1.5 streaming layout, where each
batch is published as a separate TSV at
``seqkit/<sample>/batch_stats/*.tsv`` and the merged cumulative file is
only written at end-of-stream. A realtime run that hits the timeout
therefore exposes only per-batch files; the loader must detect this and
sum the batches itself rather than reporting a single batch as the
total.
"""

import os
import time

import pandas as pd
import pytest

from nanometa_live.core.utils.qc_loaders import (
    _is_incremental_seqkit_layout,
    load_seqkit_stats,
)


SEQKIT_HEADER_INCREMENTAL = (
    "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len"
    "\tQ1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\tsum_n\n"
)


def _backdate_mtime(path, seconds=5):
    """Make a file look stable to the loader's stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


def _write_incremental_batch(path, num_seqs, sum_len, q20=90.0, q30=80.0,
                             avgqual=20.0, gc=40.0, min_len=100, max_len=10000,
                             sample_name="sample"):
    """Write a single-batch seqkit TSV in the incremental layout's column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    avg_len = (sum_len / num_seqs) if num_seqs > 0 else 0.0
    row = (
        f"{sample_name}.chopped.fastq.gz\tFASTQ\tDNA"
        f"\t{num_seqs}\t{sum_len}\t{min_len}\t{avg_len:.1f}\t{max_len}"
        f"\t{avg_len * 0.75:.1f}\t{avg_len:.1f}\t{avg_len * 1.5:.1f}"
        f"\t0\t{int(avg_len)}\t{num_seqs // 2}"
        f"\t{q20:.2f}\t{q30:.2f}\t{avgqual:.2f}\t{gc:.2f}\t0\n"
    )
    with open(path, "w") as f:
        f.write(SEQKIT_HEADER_INCREMENTAL)
        f.write(row)
    _backdate_mtime(path)


SEQKIT_HEADER_FLAT = (
    "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len"
    "\tQ1\tQ2\tQ3\tsum_gap\tN50\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\n"
)


def _write_flat_tsv(path, num_seqs=100, sum_len=120000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(SEQKIT_HEADER_FLAT)
        f.write(
            "barcode01.fastq.gz\tFASTQ\tDNA"
            f"\t{num_seqs}\t{sum_len}\t50\t1200\t8000"
            "\t500\t1100\t1800\t0\t1500\t98.5\t90.0\t22.3\t44.0\n"
        )
    _backdate_mtime(path)


class TestIsIncrementalSeqkitLayout:
    def test_only_batch_stats_returns_true(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=59, sum_len=135883, sample_name="combined_sample",
        )

        assert _is_incremental_seqkit_layout(str(seqkit_dir), "combined_sample") is True
        assert _is_incremental_seqkit_layout(str(seqkit_dir)) is True

    def test_only_flat_returns_false(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        _write_flat_tsv(seqkit_dir / "barcode01.tsv")

        assert _is_incremental_seqkit_layout(str(seqkit_dir), "barcode01") is False
        assert _is_incremental_seqkit_layout(str(seqkit_dir)) is False

    def test_neither_layout_returns_false(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        seqkit_dir.mkdir()

        assert _is_incremental_seqkit_layout(str(seqkit_dir)) is False
        assert _is_incremental_seqkit_layout(str(seqkit_dir), "missing") is False

    def test_missing_directory_returns_false(self, tmp_path):
        # seqkit_dir does not exist at all
        assert _is_incremental_seqkit_layout(str(tmp_path / "seqkit")) is False

    def test_flat_companion_disables_dispatch(self, tmp_path):
        # When the merge step has run, both layouts coexist; the flat
        # cumulative file is authoritative, so the loader should not
        # re-aggregate the per-batch files.
        seqkit_dir = tmp_path / "seqkit"
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=59, sum_len=135883, sample_name="combined_sample",
        )
        _write_flat_tsv(
            seqkit_dir / "combined_sample.tsv", num_seqs=77, sum_len=167270,
        )

        assert _is_incremental_seqkit_layout(str(seqkit_dir), "combined_sample") is False


class TestLoadSeqkitStatsIncrementalLayout:
    def test_sums_batches_for_named_sample(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        # 59/18/0 mirrors the run4_D realtime_single audit fixture; the
        # zero-read batch should not contribute to min_len.
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=59, sum_len=135883, min_len=1030, max_len=13533,
            q20=91.92, q30=85.40, avgqual=19.68, gc=32.19,
            sample_name="combined_sample",
        )
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_1.tsv",
            num_seqs=18, sum_len=31387, min_len=1036, max_len=3979,
            q20=87.24, q30=71.07, avgqual=18.64, gc=34.42,
            sample_name="combined_sample",
        )
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_2.tsv",
            num_seqs=0, sum_len=0, min_len=0, max_len=0,
            q20=0.0, q30=0.0, avgqual=0.0, gc=0.0,
            sample_name="combined_sample",
        )

        df = load_seqkit_stats(str(tmp_path), sample="combined_sample")

        assert not df.empty
        assert len(df) == 1
        assert int(df.iloc[0]["num_seqs"]) == 77
        assert int(df.iloc[0]["sum_len"]) == 135883 + 31387
        # Empty batch (min_len=0) must not pull the cumulative min_len
        # down to 0.
        assert int(df.iloc[0]["min_len"]) == 1030
        assert int(df.iloc[0]["max_len"]) == 13533
        assert df.iloc[0]["sample"] == "combined_sample"

    def test_aggregates_when_sample_is_none(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=59, sum_len=135883, sample_name="combined_sample",
        )
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_1.tsv",
            num_seqs=18, sum_len=31387, sample_name="combined_sample",
        )

        df = load_seqkit_stats(str(tmp_path), sample=None)

        assert not df.empty
        # Aggregate row for combined_sample only; no other sample present.
        assert (df["sample"] == "combined_sample").any()
        cumulative = df[df["sample"] == "combined_sample"].iloc[0]
        assert int(cumulative["num_seqs"]) == 77

    def test_weighted_quality_metrics(self, tmp_path):
        seqkit_dir = tmp_path / "seqkit"
        # Two equal-length batches with distinct Q20 values: the cumulative
        # Q20(%) must be the per-base weighted average, not a simple mean.
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=10, sum_len=10000, q20=80.0,
            sample_name="combined_sample",
        )
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_1.tsv",
            num_seqs=10, sum_len=30000, q20=90.0,
            sample_name="combined_sample",
        )

        df = load_seqkit_stats(str(tmp_path), sample="combined_sample")
        # Weighted by sum_len: (80*10000 + 90*30000) / 40000 = 87.5
        assert df.iloc[0]["Q20(%)"] == pytest.approx(87.5, abs=0.01)


class TestLoadSeqkitStatsLegacyLayouts:
    """Pin the existing flat / nested behaviour so the dispatch does not
    regress callers that rely on the pre-incremental layouts."""

    def test_flat_layout_returns_single_file_value(self, tmp_path):
        _write_flat_tsv(
            tmp_path / "seqkit" / "barcode01.tsv", num_seqs=100, sum_len=120000,
        )

        df = load_seqkit_stats(str(tmp_path), sample="barcode01")

        assert not df.empty
        assert len(df) == 1
        assert int(df.iloc[0]["num_seqs"]) == 100

    def test_flat_layout_with_existing_merged_file_takes_precedence(self, tmp_path):
        # When the upstream merge step has produced both the per-batch
        # files and the cumulative flat file, the flat file is
        # authoritative; the dispatch must read it without re-aggregating.
        seqkit_dir = tmp_path / "seqkit"
        _write_incremental_batch(
            seqkit_dir / "combined_sample" / "batch_stats" / "batch_0.tsv",
            num_seqs=59, sum_len=135883, sample_name="combined_sample",
        )
        _write_flat_tsv(
            seqkit_dir / "combined_sample.tsv", num_seqs=77, sum_len=167270,
        )

        df = load_seqkit_stats(str(tmp_path), sample="combined_sample")

        # The flat file is read; the per-batch summation is not used.
        assert int(df.iloc[0]["num_seqs"]) == 77


# --------------------------------------------------------------------------- #
# Bug-hunt: multi-sample NanoStats means must be read-weighted
# --------------------------------------------------------------------------- #

def test_nanoplot_multisample_mean_is_read_weighted(tmp_path):
    from nanometa_live.core.utils.qc_loaders import load_nanoplot_stats
    nd = tmp_path / "nanoplot"
    (nd / "barcode01").mkdir(parents=True)
    (nd / "barcode02").mkdir(parents=True)
    (nd / "barcode01" / "NanoStats.txt").write_text(
        "Mean read length: 1,000.0\nMean read quality: 10.0\n"
        "Number of reads: 1,000\nTotal bases: 1,000,000\nRead length N50: 1,200\n"
    )
    (nd / "barcode02" / "NanoStats.txt").write_text(
        "Mean read length: 5,000.0\nMean read quality: 20.0\n"
        "Number of reads: 10\nTotal bases: 50,000\nRead length N50: 6,000\n"
    )
    agg = load_nanoplot_stats(str(tmp_path), None)
    # read-weighted length = 1,050,000 / 1,010 ~= 1039.6 (NOT the naive 3000)
    assert 1000 < agg["mean_read_length"] < 1100
    # read-weighted quality = (10*1000 + 20*10) / 1010 ~= 10.1 (NOT 15)
    assert 10.0 <= agg["mean_read_quality"] < 10.3
    assert agg["number_of_reads"] == 1010
    assert agg["total_bases"] == 1_050_000
