"""
Tests for seqkit output layout discovery.

Regression coverage for F9 / P2-4: the nanometanf pipeline emits seqkit stats
as a flat ``seqkit/<sample>.tsv`` layout. The older nested
``seqkit/<sample>/stats/*.tsv`` layout was retired (only current-pipeline
output is supported); a test pins that nested files are now ignored.
"""

import pandas as pd
import pytest

from nanometa_live.core.utils.qc_loaders import load_seqkit_stats


SEQKIT_HEADER = (
    "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len"
    "\tQ1\tQ2\tQ3\tsum_gap\tN50\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)\n"
)

SEQKIT_ROW = (
    "barcode01.fastq.gz\tFASTQ\tDNA\t100\t120000\t50\t1200\t8000"
    "\t500\t1100\t1800\t0\t1500\t98.5\t90.0\t22.3\t44.0\n"
)


def _write_seqkit_tsv(path, rows=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(SEQKIT_HEADER)
        for _ in range(rows):
            f.write(SEQKIT_ROW)


class TestSeqkitFlatLayout:
    def test_flat_single_sample(self, tmp_path):
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01.tsv")

        df = load_seqkit_stats(str(tmp_path), sample="barcode01")
        assert not df.empty
        assert df.iloc[0]["num_seqs"] == 100
        assert "sample" in df.columns
        assert df.iloc[0]["sample"] == "barcode01"

    def test_flat_all_samples(self, tmp_path):
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01.tsv")
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode02.tsv")

        df = load_seqkit_stats(str(tmp_path), sample=None)
        assert len(df) == 2
        assert set(df["sample"]) == {"barcode01", "barcode02"}


class TestSeqkitNestedLayoutRetired:
    """The pre-current nested ``stats/`` layout is no longer read."""

    def test_nested_single_sample_ignored(self, tmp_path):
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01" / "stats" / "stats.tsv")

        df = load_seqkit_stats(str(tmp_path), sample="barcode01")
        assert df.empty

    def test_nested_all_samples_ignored(self, tmp_path):
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01" / "stats" / "a.tsv")
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode02" / "stats" / "b.tsv")

        df = load_seqkit_stats(str(tmp_path), sample=None)
        assert df.empty


class TestSeqkitMissing:
    def test_missing_directory_returns_empty_df(self, tmp_path):
        df = load_seqkit_stats(str(tmp_path), sample="barcode01")
        assert df.empty

    def test_missing_sample_returns_empty_df(self, tmp_path):
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01.tsv")
        df = load_seqkit_stats(str(tmp_path), sample="barcode99")
        assert df.empty


class TestIncrementalDoesNotDoubleCountMergedSamples:
    """A sample with BOTH a flat merged TSV and batch_stats/ must count once.

    SEQKIT_STATS keeps publishing per-batch files while SEQKIT_MERGE_STATS
    refreshes the flat TSV on the same cadence -- the two coexist for the
    whole run. The incremental aggregator summed batch_stats for every sample
    directory regardless, so the All-Samples concat counted merged samples
    twice. Audit 2026-08-16, finding L13.
    """

    def test_all_samples_counts_a_merged_sample_once(self, tmp_path):
        import os
        import time

        # barcode01: merged flat TSV (authoritative) AND per-batch files.
        _write_seqkit_tsv(tmp_path / "seqkit" / "barcode01.tsv")
        _write_seqkit_tsv(
            tmp_path / "seqkit" / "barcode01" / "batch_stats" / "batch_0.tsv"
        )
        # barcode02: incremental only (mid-run, not merged yet).
        _write_seqkit_tsv(
            tmp_path / "seqkit" / "barcode02" / "batch_stats" / "batch_0.tsv"
        )
        # Batch files pass through the loader's file-stability check.
        old = time.time() - 30
        for p in (tmp_path / "seqkit").rglob("*.tsv"):
            os.utime(p, (old, old))

        df = load_seqkit_stats(str(tmp_path), sample=None)
        counts = df.groupby("sample")["num_seqs"].sum().to_dict()
        assert counts.get("barcode01") == 100, (
            f"merged sample double-counted: {counts}"
        )
        assert counts.get("barcode02") == 100
        assert len(df[df["sample"] == "barcode01"]) == 1
