"""
Tests for the validation system: JSON round-trip, loader status mapping,
on-demand directory detection, empty directory handling, and coverage
breadth fraction/percentage conversion.
"""

import json
import os
import time
from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationResult,
    ValidationStatus,
)
from nanometa_live.core.utils.validation_loaders import load_blast_validation_data


def _backdate_mtime(path, seconds: int = 5) -> None:
    """Set a file's mtime to *seconds* ago so it passes any stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def on_demand_json(tmp_path: Path) -> Path:
    """
    Write a validation JSON that matches the output of
    OnDemandValidator._save_results() after the field-name fix.
    Returns the path to the JSON file.
    """
    od_dir = tmp_path / "on_demand_validation"
    od_dir.mkdir()
    payload = {
        # Parser-expected fields
        "sample_id": "barcode01",
        "taxid": 562,
        "species": "Escherichia coli",
        "total_reads": 1000,
        "validated_reads": 870,
        "percent_validated": 87.0,
        "percent_identity_mean": 98.5,
        "percent_identity_min": 90.0,
        "percent_identity_max": 100.0,
        "validation_method": "blast",
        "validation_status": "confirmed",
        "hit_rate": 0.87,
        "timestamp": "2026-04-07T10:00:00",
        "coverage_breadth": 0.82,
        # Backward-compat fields for load_validation_result()
        "name": "Escherichia coli",
        "sample": "barcode01",
        "avg_identity": 98.5,
        "extracted_reads": 1000,
        "created_at": "2026-04-07T09:55:00",
        "completed_at": "2026-04-07T10:00:00",
        "genome_path": None,
        "blast_results": None,
    }
    json_file = od_dir / "barcode01_562_validation.json"
    json_file.write_text(json.dumps(payload, indent=2))
    _backdate_mtime(json_file)
    return json_file


@pytest.fixture()
def aggregate_json_dir(tmp_path: Path) -> Path:
    """
    Create a results directory with validation/validation_results.json in
    the nanometanf aggregate format, covering all three status values that
    require mapping (confirmed, uncertain, rejected).
    """
    val_dir = tmp_path / "validation"
    val_dir.mkdir()
    aggregate = {
        "timestamp": "2026-04-07T10:00:00",
        "validation_method": "blast",
        "results": {
            "barcode01": {
                "562": {
                    "species": "Escherichia coli",
                    "kraken_reads": 1500,
                    "blast_hits": 1350,
                    "hit_rate": 0.90,
                    "avg_identity": 98.5,
                    "validation_status": "confirmed",
                },
                "1639": {
                    "species": "Listeria monocytogenes",
                    "kraken_reads": 800,
                    "blast_hits": 450,
                    "hit_rate": 0.56,
                    "avg_identity": 92.0,
                    "validation_status": "uncertain",
                },
                "1280": {
                    "species": "Staphylococcus aureus",
                    "kraken_reads": 200,
                    "blast_hits": 30,
                    "hit_rate": 0.15,
                    "avg_identity": 85.0,
                    "validation_status": "rejected",
                },
            }
        },
    }
    json_file = val_dir / "validation_results.json"
    json_file.write_text(json.dumps(aggregate, indent=2))
    _backdate_mtime(json_file)
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: on-demand JSON round-trip
# ---------------------------------------------------------------------------

class TestOnDemandJsonRoundTrip:
    """
    Verify that a JSON written by the fixed _save_results() is fully
    parseable by BlastValidationParser.parse_validation_json() with
    correct field mapping.
    """

    def test_parse_returns_result(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result is not None

    def test_sample_id_mapped(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.sample_id == "barcode01"

    def test_species_mapped(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.species == "Escherichia coli"

    def test_taxid_mapped(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.taxid == 562

    def test_percent_validated_stored_as_percentage(self, on_demand_json: Path) -> None:
        """percent_validated should be stored as 0-100, not 0-1."""
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.percent_validated == pytest.approx(87.0, rel=1e-3)

    def test_identity_mean_mapped(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.percent_identity_mean == pytest.approx(98.5, rel=1e-3)

    def test_validation_method_present(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.validation_method == "blast"

    def test_status_confirmed_for_high_validation(self, on_demand_json: Path) -> None:
        """87% validated at 98.5% identity should yield CONFIRMED status."""
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert result.status == ValidationStatus.CONFIRMED

    def test_coverage_breadth_read_as_fraction(self, on_demand_json: Path) -> None:
        """coverage_breadth is stored and read as a 0-1 fraction."""
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)

        assert 0.0 <= result.coverage_breadth <= 1.0
        assert result.coverage_breadth == pytest.approx(0.82, rel=1e-3)


# ---------------------------------------------------------------------------
# Test 2: validation loader with aggregate JSON + status mapping
# ---------------------------------------------------------------------------

class TestValidationLoaderAggregateJson:
    """
    Verify that load_blast_validation_data() correctly reads the nanometanf
    aggregate format and maps status values to the UI vocabulary.
    """

    @pytest.fixture()
    def watchlist(self):
        return [
            {"taxid": 562, "name": "Escherichia coli"},
            {"taxid": 1639, "name": "Listeria monocytogenes"},
            {"taxid": 1280, "name": "Staphylococcus aureus"},
        ]

    def test_returns_entries_for_watchlist_taxa(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert 562 in results
        assert 1639 in results
        assert 1280 in results

    def test_confirmed_maps_to_validated(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert results[562]["status"] == "validated"

    def test_uncertain_maps_to_partial(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert results[1639]["status"] == "partial"

    def test_rejected_maps_to_failed(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert results[1280]["status"] == "failed"

    def test_validation_rate_as_percentage(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        """hit_rate 0.90 should be stored as validation_rate 90.0."""
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert results[562]["validation_rate"] == pytest.approx(90.0, rel=1e-2)

    def test_read_counts_preserved(
        self, aggregate_json_dir: Path, watchlist
    ) -> None:
        results = load_blast_validation_data(str(aggregate_json_dir), watchlist)
        assert results[562]["total_reads"] == 1500
        assert results[562]["validated_reads"] == 1350

    def test_taxa_not_in_watchlist_excluded(
        self, aggregate_json_dir: Path
    ) -> None:
        partial_watchlist = [{"taxid": 562, "name": "Escherichia coli"}]
        results = load_blast_validation_data(str(aggregate_json_dir), partial_watchlist)
        assert 1639 not in results
        assert 1280 not in results


# ---------------------------------------------------------------------------
# Test 3: on-demand directory detection via ValidationParser
# ---------------------------------------------------------------------------

class TestOnDemandDirectorySearch:
    """
    Verify ValidationParser can find results in on_demand_validation/ when
    the path is pointed at the on-demand directory directly.
    """

    def test_has_validation_data_true(self, on_demand_json: Path) -> None:
        od_dir = on_demand_json.parent
        parser = ValidationParser(str(od_dir.parent))
        # Point the parser at the on-demand dir to simulate scanning it
        parser.validation_dir = od_dir
        assert parser.has_validation_data() is True

    def test_parse_validation_json_finds_result(self, on_demand_json: Path) -> None:
        parser = ValidationParser(str(on_demand_json.parent.parent))
        result = parser.parse_validation_json(on_demand_json)
        assert result is not None
        assert result.taxid == 562

    def test_get_validation_results_from_individual_file(
        self, on_demand_json: Path
    ) -> None:
        od_dir = on_demand_json.parent
        parser = ValidationParser(str(od_dir.parent))
        parser.validation_dir = od_dir
        results = parser.get_validation_results()
        taxids = [r.taxid for r in results]
        assert 562 in taxids


# ---------------------------------------------------------------------------
# Test 4: empty validation directories handled gracefully
# ---------------------------------------------------------------------------

class TestEmptyValidationDirectories:
    """
    Verify that missing or empty validation directories do not raise
    exceptions and return sensible empty results.
    """

    def test_missing_validation_dir_returns_empty_list(self, tmp_path: Path) -> None:
        parser = ValidationParser(str(tmp_path))
        results = parser.get_validation_results()
        assert results == []

    def test_empty_validation_dir_returns_empty_list(self, tmp_path: Path) -> None:
        (tmp_path / "blast_validation").mkdir()
        parser = ValidationParser(str(tmp_path))
        results = parser.get_validation_results()
        assert results == []

    def test_has_validation_data_false_when_empty(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "blast_validation"
        empty_dir.mkdir()
        parser = ValidationParser(str(tmp_path))
        assert parser.has_validation_data() is False

    def test_load_blast_validation_empty_dir_returns_empty_dict(
        self, tmp_path: Path
    ) -> None:
        watchlist = [{"taxid": 562, "name": "Escherichia coli"}]
        results = load_blast_validation_data(str(tmp_path), watchlist)
        assert results == {}

    def test_load_blast_validation_nonexistent_dir_returns_empty_dict(
        self, tmp_path: Path
    ) -> None:
        nonexistent = tmp_path / "does_not_exist"
        watchlist = [{"taxid": 562, "name": "Escherichia coli"}]
        results = load_blast_validation_data(str(nonexistent), watchlist)
        assert results == {}


# ---------------------------------------------------------------------------
# Test 5: coverage_breadth fraction vs. percentage conversion
# ---------------------------------------------------------------------------

class TestCoverageBreadthConversion:
    """
    Verify that coverage_breadth is stored as a 0-1 fraction in
    ValidationResult and correctly multiplied by 100 for display/export.
    """

    def _make_result(self, breadth: float) -> ValidationResult:
        r = ValidationResult(sample_id="s1", taxid=1, coverage_breadth=breadth)
        return r

    def test_breadth_stored_as_fraction(self) -> None:
        r = self._make_result(0.75)
        assert r.coverage_breadth == pytest.approx(0.75)

    def test_breadth_to_percentage(self) -> None:
        r = self._make_result(0.75)
        assert r.coverage_breadth * 100 == pytest.approx(75.0)

    def test_zero_breadth(self) -> None:
        r = self._make_result(0.0)
        assert r.coverage_breadth == 0.0
        assert r.coverage_breadth * 100 == 0.0

    def test_full_coverage(self) -> None:
        r = self._make_result(1.0)
        assert r.coverage_breadth * 100 == pytest.approx(100.0)

    def test_to_dict_preserves_fraction(self) -> None:
        """to_dict() should keep coverage_breadth as a fraction (0-1)."""
        r = self._make_result(0.87)
        d = r.to_dict()
        assert d["coverage_breadth"] == pytest.approx(0.87)

    def test_parse_validation_json_breadth_as_fraction(
        self, tmp_path: Path
    ) -> None:
        """A JSON file with coverage_breadth 0.82 is read back as a fraction."""
        json_file = tmp_path / "s1_562_validation.json"
        payload = {
            "sample_id": "s1",
            "taxid": 562,
            "species": "Escherichia coli",
            "total_reads": 100,
            "validated_reads": 85,
            "percent_validated": 85.0,
            "percent_identity_mean": 97.0,
            "validation_method": "blast",
            "coverage_breadth": 0.82,
        }
        json_file.write_text(json.dumps(payload))
        parser = ValidationParser(str(tmp_path))
        result = parser.parse_validation_json(json_file)
        assert result is not None
        assert result.coverage_breadth == pytest.approx(0.82)
        # Confirm the display percentage conversion
        assert result.coverage_breadth * 100 == pytest.approx(82.0)


class TestBlastValidationParserCache:
    """Closes P1-T06 (audit-2026-04-28-throughput-gui.md): the validation
    tab fires has_validation_data + get_validation_results +
    get_validation_summary in one tick. Without the per-instance cache
    each call walked the validation directory independently."""

    def _build_validation_dir(self, tmp_path):
        """Build a minimal validation dir with one aggregate JSON."""
        from pathlib import Path
        import json

        validation = tmp_path / "validation"
        validation.mkdir()
        aggregate = validation / "validation_results.json"
        aggregate.write_text(json.dumps({
            "timestamp": "2026-04-29T00:00:00",
            "validation_method": "blast",
            "results": {
                "barcode01": {
                    "562": {
                        "species": "Escherichia coli",
                        "validated_reads": 100,
                        "total_reads": 110,
                        "percent_validated": 90.9,
                        "percent_identity_mean": 98.5,
                        "status": "CONFIRMED",
                    },
                },
            },
        }))
        return validation

    def test_cache_hit_skips_filesystem_walk(self, tmp_path, monkeypatch):
        """Three calls within one tick must hit disk only once."""
        from nanometa_live.core.parsers.blast_validation_parser import BlastValidationParser

        validation = self._build_validation_dir(tmp_path)

        parser = BlastValidationParser(str(tmp_path))
        # First call populates the cache
        first = parser.get_validation_results()
        assert len(first) >= 1
        assert parser._results_cache is not None

        # Track filesystem reads on subsequent calls.
        original_open = open
        open_calls = []
        def counting_open(path, *args, **kwargs):
            open_calls.append(str(path))
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", counting_open)

        second = parser.get_validation_results()
        third = parser.get_validation_summary()  # internally calls get_validation_results

        # Neither subsequent call should have opened any file
        validation_opens = [p for p in open_calls if "validation" in p]
        assert validation_opens == [], (
            f"Expected zero re-opens within unchanged-mtime window, got "
            f"{validation_opens}"
        )
        # Sanity: results equal the cached set
        assert len(second) == len(first)

    def test_cache_invalidates_on_dir_mtime_change(self, tmp_path):
        """Touching the validation directory invalidates the cache."""
        import time
        from nanometa_live.core.parsers.blast_validation_parser import BlastValidationParser

        validation = self._build_validation_dir(tmp_path)
        parser = BlastValidationParser(str(tmp_path))
        parser.get_validation_results()
        assert parser._results_cache is not None
        old_mtime = parser._results_cache_mtime

        # Bump the directory's mtime by writing a new file.
        time.sleep(0.05)
        (validation / "newfile.json").write_text("{}")

        # Next call must re-parse (different fingerprint).
        parser.get_validation_results()
        assert parser._results_cache_mtime != old_mtime
