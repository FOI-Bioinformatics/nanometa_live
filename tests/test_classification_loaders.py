"""
Tests for classification_loaders module.

Covers Kraken2 report parsing edge cases, empty report handling,
and race-condition resilience (file disappearance, partial writes).
"""

import os
import time

import pandas as pd
import pytest

from nanometa_live.core.utils.classification_loaders import (
    KRAKEN2_EXPECTED_COLUMNS,
    _parse_kraken2_report,
    _deduplicate_batch_files,
    load_kraken_data,
)


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


class TestParseKraken2ReportEdgeCases:
    """Edge cases for _parse_kraken2_report."""

    def test_empty_file_returns_none(self, tmp_path):
        """An empty file should return None."""
        report = tmp_path / "empty.kraken2.report.txt"
        report.write_text("")
        _backdate_mtime(report)
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_wrong_column_count_returns_none(self, tmp_path):
        """A file with wrong number of tab-separated columns should return None."""
        report = tmp_path / "bad_cols.kraken2.report.txt"
        report.write_text("col1\tcol2\tcol3\n")
        _backdate_mtime(report)
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_non_numeric_reads_coerced(self, tmp_path):
        """Non-numeric values in reads column should be coerced and dropped."""
        report = tmp_path / "bad_reads.kraken2.report.txt"
        content = (
            "50.00\t500\t500\tS\t562\t  Escherichia coli\n"
            "50.00\tNaN\tBAD\tS\t1280\t  Staphylococcus aureus\n"
        )
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        # Only E. coli row should survive; S. aureus has invalid reads/taxid
        assert len(df) >= 1
        assert 562 in df["taxid"].values

    def test_file_disappears_during_parse(self, tmp_path):
        """If a file is removed between exists-check and read, return None."""
        report = tmp_path / "ghost.kraken2.report.txt"
        # File does not exist
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_parent_taxid_hierarchy(self, tmp_path):
        """Verify parent_taxid is built from indentation hierarchy."""
        report = tmp_path / "hierarchy.kraken2.report.txt"
        content = (
            "100.00\t1000\t0\tR\t1\troot\n"
            "80.00\t800\t0\tD\t2\t  Bacteria\n"
            "50.00\t500\t500\tS\t562\t    Escherichia coli\n"
        )
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        assert len(df) == 3
        # root has no parent
        assert df.iloc[0]["parent_taxid"] == 0
        # Bacteria's parent is root (taxid 1)
        assert df.iloc[1]["parent_taxid"] == 1
        # E. coli's parent is Bacteria (taxid 2)
        assert df.iloc[2]["parent_taxid"] == 2

    def test_single_row_report(self, tmp_path):
        """A single-row report should parse correctly."""
        report = tmp_path / "single.kraken2.report.txt"
        content = "100.00\t1000\t1000\tU\t0\tunclassified\n"
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["taxid"] == 0


class TestDeduplicateBatchFiles:
    """Tests for _deduplicate_batch_files."""

    def test_empty_list(self):
        assert _deduplicate_batch_files([]) == []

    def test_no_batch_pattern(self):
        """Files without batch pattern should all be kept."""
        files = ["/path/sample1.kraken2.report.txt", "/path/sample2.kraken2.report.txt"]
        result = _deduplicate_batch_files(files)
        assert len(result) == 2

    def test_deduplicates_same_batch(self):
        """Same (sample, batch) from different dirs should be deduplicated."""
        files = [
            "/results/kraken2/sample1_batch0.kraken2.report.txt",
            "/results/kraken2/sample1/batch_reports/sample1_batch0.kraken2.report.txt",
        ]
        result = _deduplicate_batch_files(files)
        assert len(result) == 1
        # Should prefer batch_reports/
        assert "batch_reports" in result[0]

    def test_different_batches_kept(self):
        """Different batch numbers should all be kept."""
        files = [
            "/results/kraken2/sample1_batch0.kraken2.report.txt",
            "/results/kraken2/sample1_batch1.kraken2.report.txt",
            "/results/kraken2/sample1_batch2.kraken2.report.txt",
        ]
        result = _deduplicate_batch_files(files)
        assert len(result) == 3


class TestLoadKrakenDataRaceConditions:
    """Tests for load_kraken_data handling of race conditions and edge cases."""

    def test_missing_kraken_dir(self, tmp_path):
        """Missing kraken2/ directory should return empty DataFrame."""
        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0
        assert list(df.columns) == KRAKEN2_EXPECTED_COLUMNS

    def test_empty_kraken_dir(self, tmp_path):
        """Empty kraken2/ directory should return empty DataFrame."""
        (tmp_path / "kraken2").mkdir()
        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0

    def test_all_empty_reports(self, tmp_path):
        """If all report files are empty, return empty DataFrame."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        for name in ("s1.kraken2.report.txt", "s2.kraken2.report.txt"):
            p = kraken_dir / name
            p.write_text("")
            _backdate_mtime(p)

        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0

    def test_sample_not_found(self, tmp_path):
        """Requesting a non-existent sample should return empty DataFrame."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        df = load_kraken_data(str(tmp_path), sample="nonexistent_barcode")
        assert df is not None
        assert len(df) == 0

    def test_cumulative_preferred_over_standard(self, tmp_path):
        """Cumulative reports should be preferred over standard reports."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        # Standard report with 100 reads
        standard = kraken_dir / "sample1.kraken2.report.txt"
        standard.write_text("100.00\t100\t100\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(standard)

        # Cumulative report with 500 reads (should be preferred)
        cumul = kraken_dir / "sample1.cumulative.kraken2.report.txt"
        cumul.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(cumul)

        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 1
        # Should have loaded the cumulative report (500 reads)
        assert df.iloc[0]["reads"] == 500
