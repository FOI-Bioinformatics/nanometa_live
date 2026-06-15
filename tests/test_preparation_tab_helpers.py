"""Tests for preparation_tab pure helpers + the simple sync callbacks.

The heavy background callbacks (run_preparation/export_bundle) are not exercised
here; these cover the result-banner builder, the export pre-flight guard, and the
visibility/offline sync callbacks.
"""

from types import SimpleNamespace

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.preparation_tab import (
    _build_prep_result,
    _export_preflight,
    register_preparation_callbacks,
)
from dash_test_utils import get_callback_fn


def _result(**kw):
    base = dict(
        success=True, errors=[], warnings=[], stages_failed=[],
        stages_completed=[], genomes_downloaded=0, blast_dbs_built=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# _build_prep_result
# --------------------------------------------------------------------------- #

def test_build_prep_result_failure_banner():
    alert = _build_prep_result(_result(success=False, errors=["disk full"]))
    assert alert.color == "danger"
    assert "disk full" in str(alert)


def test_build_prep_result_clean_success():
    alert = _build_prep_result(_result(
        success=True, stages_completed=["a", "b"],
        genomes_downloaded=3, blast_dbs_built=2,
    ))
    assert alert.color == "success"
    assert "complete" in str(alert).lower()
    assert "3 genomes" in str(alert)


def test_build_prep_result_reports_ready_not_just_newly_built():
    # Regression: the genome manager auto-builds DBs on scan, so during a fresh
    # prep most DBs are already present by the time the prep's own batch runs.
    # The banner must report TOTAL ready (built + present), not just this run's
    # builds -- the old message showed "11 built" when all 35 existed.
    alert = _build_prep_result(_result(
        success=True, stages_completed=["a"],
        genomes_downloaded=35, blast_dbs_built=11, blast_dbs_present=24,
        blast_dbs_failed=[],
    ))
    text = str(alert)
    assert "35 BLAST DBs ready" in text
    assert "11 built now" in text and "24 already present" in text


def test_build_prep_result_completed_with_warnings():
    alert = _build_prep_result(_result(
        success=True, warnings=["genome X missing"],
        stages_failed=["download_genomes"], stages_completed=["a"],
    ))
    assert alert.color == "warning"
    assert "warning" in str(alert).lower()


# --------------------------------------------------------------------------- #
# _export_preflight
# --------------------------------------------------------------------------- #

def test_export_preflight_empty_directory():
    alert = _export_preflight("", {}, False)
    assert alert.color == "warning"


def test_export_preflight_nonexistent_directory():
    alert = _export_preflight("/no/such/dir/xyz", {}, False)
    assert alert.color == "danger"
    assert "does not exist" in str(alert)


def test_export_preflight_valid_directory_passes(tmp_path):
    # Writable, existing dir with (almost certainly) enough space -> None.
    assert _export_preflight(str(tmp_path), {}, False) is None


# --------------------------------------------------------------------------- #
# simple sync callbacks
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def prep_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_preparation_callbacks(app)
    return app


def test_toggle_prewarm_visibility(prep_app):
    fn = get_callback_fn(prep_app, "prewarm-wrapper")
    assert fn("conda") == {}
    assert fn("docker") == {"display": "none"}
    assert fn(None) == {}  # defaults to conda


def test_render_offline_notice(prep_app):
    fn = get_callback_fn(prep_app, "prep-offline-notice")
    assert fn({}) is None
    assert fn({"offline_mode": False}) is None
    alert = fn({"offline_mode": True})
    assert alert is not None
    assert "Offline mode is on" in str(alert)
