"""Tests for app/callbacks/readiness.py pure helpers + the badge renderer."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.readiness import (
    _serialize_report,
    _empty_readiness_state,
    _readiness_fingerprint,
    _readiness_unchanged,
    register_readiness,
)
from dash_test_utils import get_callback_fn


def _fake_report(ready=True):
    check = SimpleNamespace(
        name="Kraken2 DB", passed=ready,
        severity=SimpleNamespace(value="critical"), message="db ok",
    )
    return SimpleNamespace(
        ready=ready,
        summary=lambda: {"total": 1, "passed": 1 if ready else 0,
                         "failed": 0 if ready else 1,
                         "critical_failures": 0 if ready else 1, "warnings": 0},
        checks=[check],
    )


# --------------------------------------------------------------------------- #
# _serialize_report / _empty_readiness_state
# --------------------------------------------------------------------------- #

def test_serialize_report():
    out = _serialize_report(_fake_report(ready=True))
    assert out["ready"] is True
    assert out["error"] is None
    assert out["summary"]["total"] == 1
    assert out["checks"][0] == {
        "name": "Kraken2 DB", "passed": True, "severity": "critical", "message": "db ok",
    }
    assert "computed_at" in out


def test_empty_readiness_state():
    out = _empty_readiness_state("No configuration loaded")
    assert out["ready"] is False
    assert out["error"] == "No configuration loaded"
    assert out["checks"] == []
    assert out["summary"]["total"] == 0


# --------------------------------------------------------------------------- #
# _readiness_fingerprint
# --------------------------------------------------------------------------- #

def test_fingerprint_no_config():
    assert _readiness_fingerprint(None) == "no-config"


def test_fingerprint_changes_with_watchlist():
    cfg = {"kraken_db": "/db"}
    fp_none = _readiness_fingerprint(cfg, [])
    fp_one = _readiness_fingerprint(cfg, [{"taxid": 562, "enabled": True}])
    assert fp_none != fp_one
    # disabled entries do not affect the fingerprint
    fp_disabled = _readiness_fingerprint(cfg, [{"taxid": 562, "enabled": False}])
    assert fp_disabled == fp_none


def test_fingerprint_stable_for_same_inputs():
    cfg = {"kraken_db": "/db", "blast_validation": True}
    wl = [{"taxid": 1, "enabled": True}]
    assert _readiness_fingerprint(cfg, wl) == _readiness_fingerprint(cfg, wl)


# --------------------------------------------------------------------------- #
# _readiness_unchanged
# --------------------------------------------------------------------------- #

def test_readiness_unchanged():
    a = _serialize_report(_fake_report(ready=True))
    b = _serialize_report(_fake_report(ready=True))   # differs only in computed_at
    assert _readiness_unchanged(a, b) is True
    assert _readiness_unchanged(None, b) is False
    c = _serialize_report(_fake_report(ready=False))
    assert _readiness_unchanged(a, c) is False


# --------------------------------------------------------------------------- #
# render_readiness_badge
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def rd_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_readiness(app, MagicMock())
    return app


def test_badge_ready(rd_app):
    fn = get_callback_fn(rd_app, "readiness-badge")
    children, color, _ = fn(_serialize_report(_fake_report(ready=True)))
    assert color == "success"
    assert "Ready" in str(children)


def test_badge_not_ready_critical(rd_app):
    fn = get_callback_fn(rd_app, "readiness-badge")
    children, color, _ = fn(_serialize_report(_fake_report(ready=False)))
    assert color == "danger"
    assert "0/1 checks" in str(children)


def test_badge_not_configured(rd_app):
    fn = get_callback_fn(rd_app, "readiness-badge")
    children, color, _ = fn(_empty_readiness_state("No configuration loaded"))
    assert color == "secondary"
    assert "Not configured" in str(children)


def test_badge_checking_initial(rd_app):
    fn = get_callback_fn(rd_app, "readiness-badge")
    children, color, _ = fn({})
    assert "Checking" in str(children)
