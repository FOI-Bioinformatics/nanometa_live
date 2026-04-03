"""
Integration tests for data loading, sample detection, taxid consistency,
error handling, and cache management in Nanometa Live v2.0.

These tests verify the end-to-end data flow from pipeline output files
through the parsing and loading layers to the dashboard callbacks.
"""

import pytest
import pandas as pd
import json
import os
import time
from pathlib import Path


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


class TestKraken2FileDiscoveryPrecedence:
    """Verify that Kraken2 report file selection follows the expected priority order."""

    def test_cumulative_preferred_over_standard(self, realtime_output_dir: Path) -> None:
        """Cumulative reports should take precedence over standard reports."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df = load_kraken_data(str(realtime_output_dir), sample="barcode01")

        ecoli = df[df["taxid"] == 562]
        assert not ecoli.empty, "Expected taxid 562 in loaded data"
        assert ecoli.iloc[0]["cumul_reads"] == 150

    def test_standard_preferred_over_batch(self, batch_output_dir: Path) -> None:
        """Standard reports should be selected when no cumulative report exists."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df = load_kraken_data(str(batch_output_dir), sample="barcode01")

        ecoli = df[df["taxid"] == 562]
        assert not ecoli.empty, "Expected taxid 562 in loaded data"
        assert ecoli.iloc[0]["cumul_reads"] == 200

    def test_batch_files_aggregated_when_no_standard(self, tmp_path: Path) -> None:
        """When only batch files exist, their read counts should be aggregated."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        batch0 = (
            " 0.00\t0\t0\tU\t0\tunclassified\n"
            "100.00\t50\t0\tR\t1\troot\n"
            "100.00\t50\t0\tD\t2\t  Bacteria\n"
            "100.00\t50\t50\tS\t562\t    Escherichia coli\n"
        )
        batch1 = (
            " 0.00\t0\t0\tU\t0\tunclassified\n"
            "100.00\t75\t0\tR\t1\troot\n"
            "100.00\t75\t0\tD\t2\t  Bacteria\n"
            "100.00\t75\t75\tS\t562\t    Escherichia coli\n"
        )
        (kraken_dir / "barcode01_batch0.kraken2.report.txt").write_text(batch0)
        (kraken_dir / "barcode01_batch1.kraken2.report.txt").write_text(batch1)
        _backdate_mtime(kraken_dir / "barcode01_batch0.kraken2.report.txt")
        _backdate_mtime(kraken_dir / "barcode01_batch1.kraken2.report.txt")

        clear_data_cache()
        df = load_kraken_data(str(tmp_path), sample="barcode01")

        ecoli = df[df["taxid"] == 562]
        assert not ecoli.empty, "Expected taxid 562 in aggregated batch data"
        assert ecoli.iloc[0]["cumul_reads"] == 125

    def test_batch_excluded_when_cumulative_exists(self, realtime_output_dir: Path) -> None:
        """Batch files should be ignored when a cumulative report is available."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df = load_kraken_data(str(realtime_output_dir), sample="barcode01")

        ecoli = df[df["taxid"] == 562]
        assert not ecoli.empty
        # Should use cumulative (150), not batch (50)
        assert ecoli.iloc[0]["cumul_reads"] == 150


class TestSampleDetection:
    """Verify sample name extraction and discovery from output directories."""

    def test_detect_from_all_data_sources(self, realtime_output_dir: Path) -> None:
        """Samples should be detected from kraken2 and fastp output files."""
        from nanometa_live.core.utils.sample_detector import get_available_samples
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        clear_data_cache()
        samples = get_available_samples(str(realtime_output_dir))
        assert "barcode01" in samples

    def test_strip_batch_suffix(self) -> None:
        """Batch suffixes should be removed to unify sample names."""
        from nanometa_live.core.utils.sample_detector import extract_sample_name
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        clear_data_cache()
        assert extract_sample_name("barcode01_batch0.kreport2.txt") == "barcode01"

    def test_strip_cumulative_suffix(self) -> None:
        """Cumulative report suffixes should be removed from sample names."""
        from nanometa_live.core.utils.sample_detector import extract_sample_name
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        clear_data_cache()
        assert extract_sample_name("barcode01.cumulative.kraken2.report.txt") == "barcode01"

    def test_resolve_most_recent_analysis_dir(self, multi_analysis_dir: Path) -> None:
        """The most recent timestamped analysis directory should be selected."""
        from nanometa_live.core.utils.sample_detector import resolve_analysis_directory
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        clear_data_cache()
        resolved = resolve_analysis_directory(str(multi_analysis_dir))
        assert "20240102" in resolved

    def test_skip_empty_analysis_dir(self, tmp_path: Path) -> None:
        """Empty analysis directories should be skipped in favour of those with data."""
        from nanometa_live.core.utils.sample_detector import resolve_analysis_directory
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        # Empty analysis dir (has kraken2/ but no files)
        empty_dir = tmp_path / "analysis_20240101_120000" / "kraken2"
        empty_dir.mkdir(parents=True)

        # Valid analysis dir with a report
        valid_dir = tmp_path / "analysis_20240102_120000" / "kraken2"
        valid_dir.mkdir(parents=True)
        report = (
            " 0.00\t0\t0\tU\t0\tunclassified\n"
            "100.00\t100\t0\tR\t1\troot\n"
            "100.00\t100\t0\tD\t2\t  Bacteria\n"
            "100.00\t100\t100\tS\t562\t    Escherichia coli\n"
        )
        (valid_dir / "barcode01.kraken2.report.txt").write_text(report)
        _backdate_mtime(valid_dir / "barcode01.kraken2.report.txt")

        clear_data_cache()
        resolved = resolve_analysis_directory(str(tmp_path))
        assert "20240102" in resolved


class TestTaxidConsistency:
    """Ensure taxid values maintain consistent integer types across the data flow."""

    def test_taxid_int_after_kraken_parse(self, realtime_output_dir: Path) -> None:
        """Taxid column should contain integer values after Kraken2 report parsing."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df = load_kraken_data(str(realtime_output_dir), sample="barcode01")

        assert not df.empty
        assert pd.api.types.is_integer_dtype(df["taxid"])

    def test_taxid_int_in_validation_results(self, tmp_path: Path) -> None:
        """Taxid values in validation JSON output should parse as integers."""
        from nanometa_live.core.utils.data_loaders import load_validation_data, clear_data_cache

        validation_dir = tmp_path / "validation"
        validation_dir.mkdir()
        results = {
            "results": {
                "barcode01": {
                    "562": {
                        "sample_id": "barcode01",
                        "taxid": 562,
                        "species": "E. coli",
                        "total_reads": 100,
                        "validated_reads": 80,
                        "percent_validated": 80.0,
                        "percent_identity_mean": 95.0,
                        "status": "confirmed",
                    }
                }
            }
        }
        (validation_dir / "validation_results.json").write_text(json.dumps(results))

        clear_data_cache()
        data = load_validation_data(str(tmp_path), sample="barcode01")

        # Validation data may be returned as list of dicts; check taxid type
        for entry in data:
            if "taxid" in entry:
                assert isinstance(entry["taxid"], int)

    def test_taxid_type_matches_watchlist(self, realtime_output_dir: Path) -> None:
        """Kraken2 taxid values should be directly comparable to watchlist integer taxids."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df = load_kraken_data(str(realtime_output_dir), sample="barcode01")

        # Simulate a watchlist entry with integer taxid
        watchlist_taxid = 562
        matches = df[df["taxid"] == watchlist_taxid]
        assert not matches.empty, "Integer taxid comparison should find matching rows"


class TestErrorPaths:
    """Verify graceful handling of missing, malformed, and corrupt input files."""

    def test_missing_kraken_dir_returns_empty_df(self, tmp_path: Path) -> None:
        """Loading from a directory without kraken2/ should return an empty DataFrame."""
        from nanometa_live.core.utils.data_loaders import (
            load_kraken_data, clear_data_cache, KRAKEN2_EXPECTED_COLUMNS,
        )

        clear_data_cache()
        df = load_kraken_data(str(tmp_path))

        assert df.empty
        assert list(df.columns) == KRAKEN2_EXPECTED_COLUMNS

    def test_malformed_report_skipped(self, malformed_output_dir: Path) -> None:
        """Reports with incorrect column counts should be rejected."""
        from nanometa_live.core.utils.data_loaders import _parse_kraken2_report, clear_data_cache

        clear_data_cache()
        bad_file = str(malformed_output_dir / "kraken2" / "bad_columns.kraken2.report.txt")
        result = _parse_kraken2_report(bad_file, check_stability=False)
        assert result is None

    def test_truncated_file_skipped(self, malformed_output_dir: Path) -> None:
        """Truncated files that are too small should be rejected."""
        from nanometa_live.core.utils.data_loaders import _parse_kraken2_report, clear_data_cache

        clear_data_cache()
        truncated_file = str(malformed_output_dir / "kraken2" / "truncated.kraken2.report.txt")
        result = _parse_kraken2_report(truncated_file, check_stability=False)
        assert result is None

    def test_corrupt_fastp_returns_empty_stats(self, malformed_output_dir: Path) -> None:
        """Corrupt FASTP JSON should result in empty default statistics."""
        from nanometa_live.core.utils.data_loaders import (
            load_fastp_data, clear_data_cache, _empty_fastp_stats,
        )

        clear_data_cache()
        stats = load_fastp_data(str(malformed_output_dir), sample="corrupt")

        expected_keys = set(_empty_fastp_stats().keys())
        assert expected_keys.issubset(set(stats.keys()))

    def test_empty_paf_returns_empty_dict(self, malformed_output_dir: Path) -> None:
        """An empty PAF file should produce an empty coverage dictionary."""
        from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage
        from nanometa_live.core.utils.data_loaders import clear_data_cache

        clear_data_cache()
        paf_file = malformed_output_dir / "validation" / "minimap2" / "empty.paf"
        result = parse_paf_coverage(paf_file)
        assert result == {}


class TestCacheManagement:
    """Verify that the data loader cache behaves correctly."""

    def test_cache_returns_copy(self, realtime_output_dir: Path) -> None:
        """Cached DataFrames should be independent copies to prevent mutation leaks."""
        from nanometa_live.core.utils.data_loaders import load_kraken_data, clear_data_cache

        clear_data_cache()
        df1 = load_kraken_data(str(realtime_output_dir), sample="barcode01")
        df1.drop(columns=["taxid"], inplace=True)

        df2 = load_kraken_data(str(realtime_output_dir), sample="barcode01")
        assert "taxid" in df2.columns, "Cache should return independent copies"

    def test_cache_expires_after_ttl(self, realtime_output_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cached entries should be considered invalid after the TTL elapses."""
        from nanometa_live.core.utils import data_loaders
        from nanometa_live.core.utils.data_loaders import (
            load_kraken_data, clear_data_cache, _is_cache_valid, CACHE_TTL_SECONDS,
        )

        clear_data_cache()
        load_kraken_data(str(realtime_output_dir), sample="barcode01")

        # Simulate time advancing beyond TTL
        original_time = time.time
        monkeypatch.setattr(time, "time", lambda: original_time() + CACHE_TTL_SECONDS + 1)

        assert not _is_cache_valid(original_time() - 1)

    def test_clear_cache(self, realtime_output_dir: Path) -> None:
        """Clearing the cache should remove all stored entries."""
        from nanometa_live.core.utils.data_loaders import (
            load_kraken_data, clear_data_cache, _kraken_cache,
        )

        clear_data_cache()
        load_kraken_data(str(realtime_output_dir), sample="barcode01")
        assert len(_kraken_cache) > 0, "Cache should be populated after loading"

        clear_data_cache()
        assert len(_kraken_cache) == 0, "Cache should be empty after clearing"
