"""Tests for canonical_loaders waterfall loading logic."""

import json
import os
import tempfile

import pandas as pd
import pytest

from nanometa_live.core.utils.canonical_loaders import (
    load_canonical_assembly,
    load_canonical_classification,
    load_canonical_qc_stats,
    load_canonical_validation,
    load_manifest,
)


@pytest.fixture
def results_dir(tmp_path):
    """Create a temporary results directory with canonical subdirectories."""
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "classification").mkdir()
    (canonical / "qc").mkdir()
    (canonical / "validation").mkdir()
    (canonical / "assembly").mkdir()
    return str(tmp_path)


# -- load_manifest tests --


class TestLoadManifest:
    def test_valid_manifest(self, results_dir):
        manifest_data = {"samples": ["barcode01", "barcode02"], "version": "2.0"}
        path = os.path.join(results_dir, "canonical", "_manifest.json")
        with open(path, "w") as f:
            json.dump(manifest_data, f)

        result = load_manifest(results_dir)
        assert result is not None
        assert result["samples"] == ["barcode01", "barcode02"]

    def test_missing_manifest(self, results_dir):
        result = load_manifest(results_dir)
        assert result is None

    def test_corrupt_manifest(self, results_dir):
        path = os.path.join(results_dir, "canonical", "_manifest.json")
        with open(path, "w") as f:
            f.write("{invalid json")

        result = load_manifest(results_dir)
        assert result is None

    def test_empty_manifest(self, results_dir):
        path = os.path.join(results_dir, "canonical", "_manifest.json")
        with open(path, "w") as f:
            f.write("")

        result = load_manifest(results_dir)
        assert result is None


# -- load_canonical_classification tests --


class TestLoadCanonicalClassification:
    def test_valid_classification(self, results_dir):
        data = {
            "taxa": [
                {
                    "percent": 95.0,
                    "reads_clade": 950,
                    "reads_direct": 900,
                    "rank": "S",
                    "taxid": 562,
                    "name": "Escherichia coli",
                    "parent_taxid": 561,
                }
            ]
        }
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        df = load_canonical_classification(results_dir, "barcode01")
        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["name"] == "Escherichia coli"
        assert df.iloc[0]["%"] == 95.0
        assert df.iloc[0]["cumul_reads"] == 950
        assert df.iloc[0]["reads"] == 900
        assert df.iloc[0]["taxid"] == 562

    def test_missing_file_returns_none(self, results_dir):
        result = load_canonical_classification(results_dir, "nonexistent")
        assert result is None

    def test_corrupt_json_returns_none(self, results_dir):
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            f.write("not json at all")

        result = load_canonical_classification(results_dir, "barcode01")
        assert result is None

    def test_empty_taxa_returns_empty_df(self, results_dir):
        data = {"taxa": []}
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        df = load_canonical_classification(results_dir, "barcode01")
        assert df is not None
        assert len(df) == 0

    def test_missing_taxa_key_returns_empty_df(self, results_dir):
        data = {"other_key": "value"}
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        df = load_canonical_classification(results_dir, "barcode01")
        assert df is not None
        assert len(df) == 0

    def test_missing_required_column_returns_none(self, results_dir):
        # Taxa without 'rank' column
        data = {
            "taxa": [
                {
                    "percent": 95.0,
                    "reads_clade": 950,
                    "reads_direct": 900,
                    "taxid": 562,
                    "name": "Escherichia coli",
                }
            ]
        }
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        result = load_canonical_classification(results_dir, "barcode01")
        assert result is None

    def test_parent_taxid_defaults_to_zero(self, results_dir):
        data = {
            "taxa": [
                {
                    "percent": 50.0,
                    "reads_clade": 500,
                    "reads_direct": 400,
                    "rank": "S",
                    "taxid": 562,
                    "name": "Escherichia coli",
                }
            ]
        }
        path = os.path.join(
            results_dir, "canonical", "classification",
            "barcode01.classification.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        df = load_canonical_classification(results_dir, "barcode01")
        assert df is not None
        assert df.iloc[0]["parent_taxid"] == 0


# -- load_canonical_qc_stats tests --


class TestLoadCanonicalQcStats:
    def test_valid_qc_stats(self, results_dir):
        data = {
            "before_filtering": {"total_reads": 1000, "total_bases": 500000},
            "after_filtering": {
                "total_reads": 900,
                "total_bases": 450000,
                "q30_rate": 0.92,
            },
            "filtering_result": {
                "passed_filter_reads": 900,
                "low_quality_reads": 50,
                "too_short_reads": 30,
                "too_many_n_reads": 20,
            },
        }
        path = os.path.join(
            results_dir, "canonical", "qc", "barcode01.qc_stats.json"
        )
        with open(path, "w") as f:
            json.dump(data, f)

        stats = load_canonical_qc_stats(results_dir, "barcode01")
        assert stats is not None
        assert stats["total_reads_before"] == 1000
        assert stats["total_reads_after"] == 900
        assert stats["q30_rate_after"] == 0.92
        assert stats["low_quality"] == 50

    def test_missing_file_returns_none(self, results_dir):
        result = load_canonical_qc_stats(results_dir, "nonexistent")
        assert result is None

    def test_corrupt_json_returns_none(self, results_dir):
        path = os.path.join(
            results_dir, "canonical", "qc", "barcode01.qc_stats.json"
        )
        with open(path, "w") as f:
            f.write("{truncated")

        result = load_canonical_qc_stats(results_dir, "barcode01")
        assert result is None

    def test_missing_sections_default_to_zero(self, results_dir):
        # Only after_filtering present
        data = {"after_filtering": {"total_reads": 500}}
        path = os.path.join(
            results_dir, "canonical", "qc", "barcode01.qc_stats.json"
        )
        with open(path, "w") as f:
            json.dump(data, f)

        stats = load_canonical_qc_stats(results_dir, "barcode01")
        assert stats is not None
        assert stats["total_reads_before"] == 0
        assert stats["total_reads_after"] == 500
        assert stats["passed_filter"] == 0


# -- load_canonical_validation tests --


class TestLoadCanonicalValidation:
    def test_valid_validation(self, results_dir):
        data = {"results": [{"sample": "barcode01", "identity": 99.5}]}
        path = os.path.join(
            results_dir, "canonical", "validation", "validation_results.json"
        )
        with open(path, "w") as f:
            json.dump(data, f)

        result = load_canonical_validation(results_dir)
        assert result is not None
        assert result["results"][0]["identity"] == 99.5

    def test_missing_file_returns_none(self, results_dir):
        result = load_canonical_validation(results_dir)
        assert result is None

    def test_corrupt_json_returns_none(self, results_dir):
        path = os.path.join(
            results_dir, "canonical", "validation", "validation_results.json"
        )
        with open(path, "w") as f:
            f.write("bad json{")

        result = load_canonical_validation(results_dir)
        assert result is None

    def test_sample_id_ignored(self, results_dir):
        """sample_id parameter is accepted but unused (aggregate file)."""
        data = {"aggregate": True}
        path = os.path.join(
            results_dir, "canonical", "validation", "validation_results.json"
        )
        with open(path, "w") as f:
            json.dump(data, f)

        result = load_canonical_validation(results_dir, sample_id="barcode01")
        assert result is not None
        assert result["aggregate"] is True


# -- load_canonical_assembly tests --


class TestLoadCanonicalAssembly:
    def test_valid_assembly(self, results_dir):
        data = {"n50": 15000, "total_length": 4800000, "num_contigs": 320}
        path = os.path.join(
            results_dir, "canonical", "assembly",
            "barcode01.assembly_stats.json",
        )
        with open(path, "w") as f:
            json.dump(data, f)

        result = load_canonical_assembly(results_dir, "barcode01")
        assert result is not None
        assert result["n50"] == 15000

    def test_missing_file_returns_none(self, results_dir):
        result = load_canonical_assembly(results_dir, "nonexistent")
        assert result is None

    def test_corrupt_json_returns_none(self, results_dir):
        path = os.path.join(
            results_dir, "canonical", "assembly",
            "barcode01.assembly_stats.json",
        )
        with open(path, "w") as f:
            f.write("{{bad")

        result = load_canonical_assembly(results_dir, "barcode01")
        assert result is None
