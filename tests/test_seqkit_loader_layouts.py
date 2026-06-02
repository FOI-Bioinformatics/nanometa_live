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
