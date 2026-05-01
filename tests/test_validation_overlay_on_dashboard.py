"""Tests for the validation overlay on the Dashboard pathogen alert cards.

Two helper functions are exercised here:

  ``_load_validation_lookup(main_dir)`` reads
    ``<main_dir>/validation/validation_results.json`` via
    ``BlastValidationParser`` and returns a (sample, taxid) keyed dict.

  ``_summarise_validation_for_taxid(samples, taxid, lookup)`` collapses
    the per-sample status into a single best-of value for a watchlist
    detection that may span multiple samples.

Plus a smoke test that the three pathogen-alert components accept the
new ``validation`` keyword argument and render a validation badge
without raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _load_validation_lookup
# ---------------------------------------------------------------------------


@pytest.fixture
def validation_run(tmp_path):
    """Build a minimal pipeline output dir with a validation_results.json
    that mimics what nanometanf's AGGREGATE_VALIDATION_RESULTS writes."""
    validation = tmp_path / "validation"
    validation.mkdir()
    payload = {
        "pipeline_version": "1.5.1dev",
        "validation_method": "blast",
        "timestamp": "2026-05-01T07:00:00+00:00",
        "thresholds": {"hit_rate": 0.5, "identity": 90.0},
        "results": {
            "barcode01": {
                "562": {
                    "taxid": 562,
                    "species": "Escherichia coli",
                    "validation_method": "blast",
                    "kraken_reads": 100,
                    "extracted_reads": 100,
                    "validated_reads": 92,
                    "blast_hits": 92,
                    "hit_rate": 0.92,
                    "avg_identity": 96.4,
                    "avg_coverage": 0.85,
                    "validation_status": "confirmed",
                },
                "9606": {
                    "taxid": 9606,
                    "species": "Homo sapiens",
                    "validation_method": "blast",
                    "kraken_reads": 50,
                    "extracted_reads": 50,
                    "validated_reads": 30,
                    "blast_hits": 30,
                    "hit_rate": 0.6,
                    "avg_identity": 92.0,
                    "avg_coverage": 0.4,
                    "validation_status": "partial",
                },
            },
            "barcode02": {
                "562": {
                    "taxid": 562,
                    "species": "Escherichia coli",
                    "validation_method": "blast",
                    "kraken_reads": 80,
                    "extracted_reads": 80,
                    "validated_reads": 18,
                    "blast_hits": 18,
                    "hit_rate": 0.225,
                    "avg_identity": 78.0,
                    "avg_coverage": 0.2,
                    "validation_status": "low",
                },
            },
        },
        "summary": {
            "total_samples": 2,
            "total_taxids_validated": 3,
            "confirmed": 1,
            "uncertain": 0,
            "rejected": 1,
        },
    }
    (validation / "validation_results.json").write_text(json.dumps(payload))
    return tmp_path


class TestLoadValidationLookup:
    def test_reads_validation_results_into_lookup(self, validation_run):
        from nanometa_live.app.tabs.dashboard_helpers import _load_validation_lookup
        lookup = _load_validation_lookup(str(validation_run))
        # Three (sample, taxid) entries from the fixture
        assert len(lookup) == 3
        assert ("barcode01", 562) in lookup
        assert ("barcode01", 9606) in lookup
        assert ("barcode02", 562) in lookup

    def test_status_field_normalised_to_string(self, validation_run):
        from nanometa_live.app.tabs.dashboard_helpers import _load_validation_lookup
        lookup = _load_validation_lookup(str(validation_run))
        # status_display normalises "confirmed" -> "validated" in the
        # parser's to_dict path; the lookup preserves whichever string
        # the parser hands back. We just assert it's a non-empty string.
        for entry in lookup.values():
            assert isinstance(entry["status"], str)
            assert entry["status"] != ""

    def test_identity_method_total_reads_present(self, validation_run):
        from nanometa_live.app.tabs.dashboard_helpers import _load_validation_lookup
        lookup = _load_validation_lookup(str(validation_run))
        entry = lookup[("barcode01", 562)]
        assert entry["identity"] == pytest.approx(96.4)
        assert entry["method"] == "blast"
        assert entry["total_reads"] == 100

    def test_empty_main_dir_returns_empty(self):
        from nanometa_live.app.tabs.dashboard_helpers import _load_validation_lookup
        assert _load_validation_lookup("") == {}

    def test_no_validation_dir_returns_empty(self, tmp_path):
        from nanometa_live.app.tabs.dashboard_helpers import _load_validation_lookup
        assert _load_validation_lookup(str(tmp_path)) == {}


# ---------------------------------------------------------------------------
# _summarise_validation_for_taxid
# ---------------------------------------------------------------------------


class TestSummariseValidationForTaxid:
    def _lookup(self):
        # status_display normalises "confirmed" -> "validated" in some
        # parser versions; accept either form for the rank lookup. The
        # helper itself uses _VALIDATION_RANK with both keys.
        return {
            ("s1", 562): {"status": "confirmed", "identity": 95.0, "method": "blast", "validated_reads": 90, "total_reads": 100, "percent_validated": 90.0},
            ("s2", 562): {"status": "partial",   "identity": 80.0, "method": "blast", "validated_reads": 50, "total_reads": 100, "percent_validated": 50.0},
            ("s3", 562): {"status": "low",       "identity": 60.0, "method": "blast", "validated_reads": 10, "total_reads": 100, "percent_validated": 10.0},
        }

    def test_picks_best_status_across_samples(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        samples = [{"sample": "s1"}, {"sample": "s2"}, {"sample": "s3"}]
        result = _summarise_validation_for_taxid(samples, 562, self._lookup())
        assert result["status"] == "confirmed"
        # Identity is the average across samples
        assert result["identity"] == pytest.approx((95.0 + 80.0 + 60.0) / 3)
        assert result["n_validated"] == 3
        assert result["n_samples"] == 3

    def test_returns_partial_when_no_confirmed(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        lookup = {
            ("s1", 562): {"status": "partial", "identity": 80.0, "method": "blast", "validated_reads": 50, "total_reads": 100, "percent_validated": 50.0},
            ("s2", 562): {"status": "low",     "identity": 60.0, "method": "blast", "validated_reads": 10, "total_reads": 100, "percent_validated": 10.0},
        }
        result = _summarise_validation_for_taxid(
            [{"sample": "s1"}, {"sample": "s2"}], 562, lookup,
        )
        assert result["status"] == "partial"

    def test_no_validation_entry_returns_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        # taxid 999 not in lookup
        result = _summarise_validation_for_taxid(
            [{"sample": "s1"}], 999, self._lookup(),
        )
        assert result is None

    def test_empty_samples_returns_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        assert _summarise_validation_for_taxid([], 562, self._lookup()) is None

    def test_empty_lookup_returns_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        assert _summarise_validation_for_taxid(
            [{"sample": "s1"}], 562, {},
        ) is None

    def test_taxid_none_returns_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import _summarise_validation_for_taxid
        assert _summarise_validation_for_taxid(
            [{"sample": "s1"}], None, self._lookup(),
        ) is None


# ---------------------------------------------------------------------------
# Pathogen alert components accept the validation kwarg
# ---------------------------------------------------------------------------


class TestPathogenAlertComponentsAcceptValidation:
    """Smoke-tests that the three alert components handle the new
    ``validation`` keyword without raising and produce a Dash component."""

    def test_critical_alert_with_confirmed_validation(self):
        from nanometa_live.app.components.pathogen_alert import CriticalPathogenAlert
        component = CriticalPathogenAlert(
            pathogen_name="Bacillus anthracis",
            common_name="Anthrax",
            read_count=120,
            abundance_pct=0.5,
            taxid=1392,
            samples=[{"sample": "barcode01", "reads": 120}],
            validation={
                "status": "confirmed",
                "identity": 95.0,
                "method": "blast",
                "n_validated": 1,
                "n_samples": 1,
            },
        )
        # Component renders without raising
        assert component is not None

    def test_high_risk_alert_with_partial_validation(self):
        from nanometa_live.app.components.pathogen_alert import HighRiskPathogenAlert
        component = HighRiskPathogenAlert(
            pathogen_name="Salmonella enterica",
            read_count=80,
            abundance_pct=0.3,
            taxid=28901,
            validation={
                "status": "partial",
                "identity": 78.0,
                "method": "minimap2",
                "n_validated": 2,
                "n_samples": 3,
            },
        )
        assert component is not None

    def test_watched_alert_with_low_validation(self):
        from nanometa_live.app.components.pathogen_alert import WatchedSpeciesAlert
        component = WatchedSpeciesAlert(
            pathogen_name="Escherichia coli",
            read_count=50,
            abundance_pct=0.2,
            taxid=562,
            validation={
                "status": "low",
                "identity": 60.0,
                "method": "blast",
                "n_validated": 1,
                "n_samples": 1,
            },
        )
        assert component is not None

    def test_pending_validation_renders(self):
        from nanometa_live.app.components.pathogen_alert import CriticalPathogenAlert
        # "pending" represents the case where validation has run for
        # other detections but this one hasn't been validated yet.
        component = CriticalPathogenAlert(
            pathogen_name="Yersinia pestis",
            read_count=30,
            abundance_pct=0.1,
            taxid=632,
            validation={
                "status": "pending",
                "identity": 0.0,
                "method": "",
                "n_validated": 0,
                "n_samples": 1,
            },
        )
        assert component is not None

    def test_no_validation_kwarg_back_compat(self):
        """All three components remain callable without the new kwarg
        (back-compat for tests + external callers)."""
        from nanometa_live.app.components.pathogen_alert import (
            CriticalPathogenAlert,
            HighRiskPathogenAlert,
            WatchedSpeciesAlert,
        )
        assert CriticalPathogenAlert(pathogen_name="X") is not None
        assert HighRiskPathogenAlert(pathogen_name="X") is not None
        assert WatchedSpeciesAlert(pathogen_name="X") is not None
