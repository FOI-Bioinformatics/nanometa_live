"""Tests for sample_detector module."""

import json
import os

import pytest

from nanometa_live.core.utils.sample_detector import (
    detect_samples_from_fastp,
    detect_samples_from_kraken,
    extract_sample_name,
    get_available_samples,
    invalidate_sample_cache,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear sample detection cache before each test."""
    invalidate_sample_cache()
    yield
    invalidate_sample_cache()


# -- extract_sample_name tests --


class TestExtractSampleName:
    def test_kraken2_report_txt(self):
        assert extract_sample_name("barcode01.kraken2.report.txt") == "barcode01"

    def test_kraken2_report_txt(self):
        assert extract_sample_name("barcode01.kraken2.report.txt") == "barcode01"

    def test_cumulative_kraken2_report(self):
        assert extract_sample_name("barcode01.cumulative.kraken2.report.txt") == "barcode01"

    def test_fastp_json(self):
        assert extract_sample_name("sample_A.fastp.json") == "sample_A"

    def test_batch_suffix_stripped(self):
        assert extract_sample_name("barcode01_batch0.kraken2.report.txt") == "barcode01"

    def test_batch_suffix_with_dot(self):
        assert extract_sample_name("barcode01.batch2.kraken2.report.txt") == "barcode01"

    def test_full_path(self):
        assert extract_sample_name("/some/path/barcode02.kraken2.report.txt") == "barcode02"

    def test_no_extension(self):
        # Falls through without matching any extension
        assert extract_sample_name("sampleX") == "sampleX"


# -- detect_samples_from_kraken tests --


class TestDetectSamplesFromKraken:
    def test_detects_kreport_files(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "barcode01.kraken2.report.txt").write_text("data")
        (kraken_dir / "barcode02.kraken2.report.txt").write_text("data")

        samples = detect_samples_from_kraken(str(kraken_dir))
        assert samples == {"barcode01", "barcode02"}

    def test_detects_cumulative_reports(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "barcode01.cumulative.kraken2.report.txt").write_text("data")

        samples = detect_samples_from_kraken(str(kraken_dir))
        assert "barcode01" in samples

    def test_detects_legacy_format(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "sample1.kraken2.report.txt").write_text("data")

        samples = detect_samples_from_kraken(str(kraken_dir))
        assert "sample1" in samples

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        samples = detect_samples_from_kraken(str(tmp_path / "nonexistent"))
        assert samples == set()

    def test_empty_dir_returns_empty(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        samples = detect_samples_from_kraken(str(kraken_dir))
        assert samples == set()

    def test_nested_v15_structure(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        sample_dir = kraken_dir / "barcode03"
        sample_dir.mkdir()
        (sample_dir / "batch_reports").mkdir()

        samples = detect_samples_from_kraken(str(kraken_dir))
        assert "barcode03" in samples


# -- detect_samples_from_fastp tests --


class TestDetectSamplesFromFastp:
    def test_detects_fastp_files(self, tmp_path):
        fastp_dir = tmp_path / "fastp"
        fastp_dir.mkdir()
        (fastp_dir / "barcode01.fastp.json").write_text("{}")
        (fastp_dir / "barcode02.fastp.json").write_text("{}")

        samples = detect_samples_from_fastp(str(fastp_dir))
        assert samples == {"barcode01", "barcode02"}

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        samples = detect_samples_from_fastp(str(tmp_path / "nonexistent"))
        assert samples == set()


# -- get_available_samples tests --


class TestGetAvailableSamples:
    def test_manifest_based_detection(self, tmp_path):
        """When a canonical manifest exists, it should be used."""
        canonical_dir = tmp_path / "canonical"
        canonical_dir.mkdir()
        manifest = {"samples": ["barcode01", "barcode02"]}
        (canonical_dir / "_manifest.json").write_text(json.dumps(manifest))

        samples = get_available_samples(str(tmp_path))
        assert samples == ["All Samples", "barcode01", "barcode02"]

    def test_glob_fallback_when_no_manifest(self, tmp_path):
        """When no manifest, fall back to glob-based detection."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "sampleA.kraken2.report.txt").write_text("data")

        samples = get_available_samples(str(tmp_path))
        assert "All Samples" in samples
        assert "sampleA" in samples

    def test_empty_directory_returns_all_samples_only(self, tmp_path):
        samples = get_available_samples(str(tmp_path))
        assert samples == ["All Samples"]

    def test_barcode_subdirectory_detection(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "barcode01.kraken2.report.txt").write_text("data")
        (kraken_dir / "barcode02.kraken2.report.txt").write_text("data")

        fastp_dir = tmp_path / "fastp"
        fastp_dir.mkdir()
        (fastp_dir / "barcode01.fastp.json").write_text("{}")

        samples = get_available_samples(str(tmp_path))
        assert "barcode01" in samples
        assert "barcode02" in samples

    def test_combines_multiple_sources(self, tmp_path):
        """Samples from kraken2 and fastp are combined."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "barcode01.kraken2.report.txt").write_text("data")

        fastp_dir = tmp_path / "fastp"
        fastp_dir.mkdir()
        (fastp_dir / "barcode02.fastp.json").write_text("{}")

        samples = get_available_samples(str(tmp_path))
        assert "barcode01" in samples
        assert "barcode02" in samples

    def test_results_are_sorted(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        for name in ["sampleC", "sampleA", "sampleB"]:
            (kraken_dir / f"{name}.kraken2.report.txt").write_text("data")

        samples = get_available_samples(str(tmp_path))
        # First element is "All Samples", rest should be sorted
        assert samples[0] == "All Samples"
        assert samples[1:] == sorted(samples[1:])

    def test_analysis_dir_resolution(self, tmp_path):
        """Resolves to analysis_* subdirectory when present."""
        analysis = tmp_path / "analysis_20260101_120000"
        analysis.mkdir()
        kraken_dir = analysis / "kraken2"
        kraken_dir.mkdir()
        (kraken_dir / "barcode01.kraken2.report.txt").write_text("data")

        samples = get_available_samples(str(tmp_path))
        assert "barcode01" in samples
