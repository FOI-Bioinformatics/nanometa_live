"""
Tests for data_loaders module, particularly file stability checking.

These tests verify that the real-time file stability check works correctly
to prevent reading files that are still being written.
"""

import os
import time
import tempfile
import threading
import pytest
import pandas as pd

from nanometa_live.core.utils.data_loaders import (
    _is_file_stable,
    _parse_kraken2_report,
    FILE_STABILITY_CHECK_INTERVAL_MS,
    FILE_STABILITY_MIN_SIZE_BYTES,
)


class TestFileStability:
    """Tests for file stability checking functionality."""

    def test_stable_file_returns_true(self, tmp_path):
        """A file that is not being modified should be considered stable."""
        test_file = tmp_path / "stable.txt"
        test_file.write_text("This is stable content that is complete.")

        # File should be stable after writing
        assert _is_file_stable(str(test_file)) is True

    def test_empty_file_returns_false(self, tmp_path):
        """An empty file should not be considered stable."""
        test_file = tmp_path / "empty.txt"
        test_file.touch()

        # Empty file should not be stable
        assert _is_file_stable(str(test_file)) is False

    def test_very_small_file_returns_false(self, tmp_path):
        """A file smaller than minimum size should not be considered stable."""
        test_file = tmp_path / "tiny.txt"
        test_file.write_text("X")  # 1 byte

        # File smaller than minimum should not be stable
        assert _is_file_stable(str(test_file)) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        """A nonexistent file should not be considered stable."""
        test_file = tmp_path / "nonexistent.txt"

        assert _is_file_stable(str(test_file)) is False

    def test_file_being_written_returns_false(self, tmp_path):
        """A file that changes size during the check should not be stable."""
        test_file = tmp_path / "growing.txt"

        # Create initial content
        test_file.write_text("Initial content that is sufficient length.")

        # Track results
        results = {"stability": None}

        def grow_file():
            """Append to file while stability check runs."""
            time.sleep(FILE_STABILITY_CHECK_INTERVAL_MS / 2000.0)  # Half the wait
            with open(str(test_file), "a") as f:
                f.write("\nMore content being added during check.")

        # Start growing file in background
        writer_thread = threading.Thread(target=grow_file)
        writer_thread.start()

        # Check stability - should detect the change
        results["stability"] = _is_file_stable(str(test_file))

        writer_thread.join()

        # File should NOT be stable since it was modified during check
        assert results["stability"] is False

    def test_minimum_size_threshold(self, tmp_path):
        """File must be at least MIN_SIZE_BYTES to be considered stable."""
        # File exactly at threshold
        test_file = tmp_path / "at_threshold.txt"
        content = "X" * FILE_STABILITY_MIN_SIZE_BYTES
        test_file.write_text(content)

        assert _is_file_stable(str(test_file)) is True

        # File just below threshold
        test_file_small = tmp_path / "below_threshold.txt"
        content_small = "X" * (FILE_STABILITY_MIN_SIZE_BYTES - 1)
        test_file_small.write_text(content_small)

        assert _is_file_stable(str(test_file_small)) is False


class TestParseKraken2Report:
    """Tests for Kraken2 report parsing with stability check."""

    @pytest.fixture
    def valid_kraken_report(self, tmp_path):
        """Create a valid Kraken2 report file."""
        report_path = tmp_path / "test.kraken2.report.txt"
        content = """100.00\t1000\t1000\tU\t0\tunclassified
0.00\t0\t0\tR\t1\troot
50.00\t500\t200\tD\t2\tBacteria
30.00\t300\t100\tP\t1224\tProteobacteria
20.00\t200\t50\tC\t28211\tAlphaproteobacteria
10.00\t100\t100\tS\t562\t  Escherichia coli
"""
        report_path.write_text(content)
        return report_path

    def test_parse_valid_report(self, valid_kraken_report):
        """Parse a valid Kraken2 report successfully."""
        df = _parse_kraken2_report(str(valid_kraken_report), check_stability=False)

        assert df is not None
        assert len(df) == 6
        assert "taxid" in df.columns
        assert "reads" in df.columns
        assert df.iloc[0]["taxid"] == 0  # unclassified
        assert df.iloc[-1]["taxid"] == 562  # E. coli

    def test_parse_with_stability_check(self, valid_kraken_report):
        """Parse with stability check enabled (default)."""
        df = _parse_kraken2_report(str(valid_kraken_report), check_stability=True)

        # Should succeed - file is stable
        assert df is not None
        assert len(df) == 6

    def test_parse_unstable_file_returns_none(self, tmp_path):
        """Parsing an unstable file should return None."""
        # Create a tiny file that won't pass stability check
        report_path = tmp_path / "tiny.kraken2.report.txt"
        report_path.write_text("X")  # Too small

        df = _parse_kraken2_report(str(report_path), check_stability=True)

        # Should return None due to failed stability check
        assert df is None

    def test_parse_without_stability_check(self, tmp_path):
        """Parsing with stability check disabled should read any file."""
        report_path = tmp_path / "small.kraken2.report.txt"
        # Valid format but small
        content = "100.00\t10\t10\tU\t0\tunclassified\n"
        report_path.write_text(content)

        # With stability check - might fail due to size
        df_with_check = _parse_kraken2_report(str(report_path), check_stability=True)

        # Without stability check - should succeed
        df_no_check = _parse_kraken2_report(str(report_path), check_stability=False)

        assert df_no_check is not None
        assert len(df_no_check) == 1

    def test_parse_invalid_format_returns_none(self, tmp_path):
        """Parsing a file with wrong number of columns should return None."""
        report_path = tmp_path / "invalid.kraken2.report.txt"
        # Invalid format - wrong number of columns
        content = "This is not a valid report\nJust some text\n"
        report_path.write_text(content)

        df = _parse_kraken2_report(str(report_path), check_stability=False)

        assert df is None

    def test_parse_nonexistent_file_returns_none(self, tmp_path):
        """Parsing a nonexistent file should return None."""
        report_path = tmp_path / "nonexistent.kraken2.report.txt"

        df = _parse_kraken2_report(str(report_path), check_stability=False)

        assert df is None


class TestVectorizedTaxaAggregation:
    """Tests for vectorized taxa aggregation (replacement for iterrows)."""

    def test_aggregation_preserves_first_occurrence(self, tmp_path):
        """Ensure taxa ordering preserves first occurrence from reports."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data

        # Create test directory structure
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        # Create two reports with overlapping taxa in different order
        report1_content = """50.00\t500\t500\tS\t562\t  Escherichia coli
30.00\t300\t300\tS\t1280\t  Staphylococcus aureus
20.00\t200\t200\tS\t287\t  Pseudomonas aeruginosa
"""
        (kraken_dir / "sample1.kraken2.report.txt").write_text(report1_content)

        # Second report has same taxa in different order
        report2_content = """40.00\t400\t400\tS\t287\t  Pseudomonas aeruginosa
35.00\t350\t350\tS\t1280\t  Staphylococcus aureus
25.00\t250\t250\tS\t562\t  Escherichia coli
"""
        (kraken_dir / "sample2.kraken2.report.txt").write_text(report2_content)

        # Load and aggregate
        df = load_kraken_data(str(tmp_path), sample=None)

        # Should have aggregated reads from both
        assert df is not None
        assert len(df) == 3

        # First occurrence order should be preserved from report1
        # E. coli should come first (taxid 562)
        assert df.iloc[0]["taxid"] == 562
        assert df.iloc[1]["taxid"] == 1280
        assert df.iloc[2]["taxid"] == 287

        # Reads should be summed
        ecoli_row = df[df["taxid"] == 562]
        assert ecoli_row.iloc[0]["reads"] == 750  # 500 + 250

    def test_aggregation_handles_empty_reports(self, tmp_path):
        """Ensure aggregation handles mix of empty and valid reports."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data

        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        # Valid report
        report_content = """100.00\t1000\t1000\tS\t562\t  Escherichia coli
"""
        (kraken_dir / "valid.kraken2.report.txt").write_text(report_content)

        # Empty/invalid report (should be skipped)
        (kraken_dir / "empty.kraken2.report.txt").write_text("")

        df = load_kraken_data(str(tmp_path), sample=None)

        # Should still have data from valid report
        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["taxid"] == 562
