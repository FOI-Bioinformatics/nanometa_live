"""Callback tests for app/callbacks/indicators.py (live indicator, stale warning,
last-update tracking, toast rendering)."""

import datetime
import time
from unittest.mock import MagicMock

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.indicators import register_indicators
from dash_test_utils import get_callback_fn, ctx_with


@pytest.fixture(scope="module")
def ind_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_indicators(app, MagicMock())
    return app


# --------------------------------------------------------------------------- #
# update_live_indicator
# --------------------------------------------------------------------------- #

def test_live_indicator_running(ind_app):
    fn = get_callback_fn(ind_app, "live-indicator-dot")
    dot, text, label = fn({"running": True}, {"ts": time.time()}, {})
    assert dot == "live-indicator-dot"
    assert text == "LIVE"
    assert label.startswith("Updated:")


def test_live_indicator_viz_only(ind_app):
    fn = get_callback_fn(ind_app, "live-indicator-dot")
    dot, text, label = fn({}, None, {"visualization_only": True})
    assert "offline" in dot
    assert text == "View Only"
    assert label == "no data yet"   # no fingerprint ts


def test_live_indicator_completed_and_standby(ind_app):
    fn = get_callback_fn(ind_app, "live-indicator-dot")
    _, text_done, _ = fn({"completed": True}, {"ts": time.time()}, {})
    assert text_done == "Complete"
    _, text_standby, _ = fn({}, None, {})
    assert text_standby == "Standby"


# --------------------------------------------------------------------------- #
# update_stale_data_warning
# --------------------------------------------------------------------------- #

def test_stale_warning_hidden_without_config(ind_app):
    fn = get_callback_fn(ind_app, "stale-data-warning")
    assert fn(1, None, None) == {"display": "none"}


def test_stale_warning_hidden_when_recent(ind_app):
    fn = get_callback_fn(ind_app, "stale-data-warning")
    recent = datetime.datetime.now().isoformat()
    assert fn(1, recent, {"update_interval_seconds": 10}) == {"display": "none"}


def test_stale_warning_shown_when_old(ind_app):
    fn = get_callback_fn(ind_app, "stale-data-warning")
    old = (datetime.datetime.now() - datetime.timedelta(seconds=100)).isoformat()
    assert fn(1, old, {"update_interval_seconds": 10}) == {"display": "flex"}


# --------------------------------------------------------------------------- #
# track_last_update_time
# --------------------------------------------------------------------------- #

def test_track_last_update_time(ind_app, tmp_path):
    fn = get_callback_fn(ind_app, "last-update-time")
    assert fn({"ts": 1}, None) is None                         # no config
    assert fn({"ts": 1}, {"results_output_directory": "/nope"}) is None
    stamp = fn({"ts": 1}, {"results_output_directory": str(tmp_path)})
    assert isinstance(stamp, str)
    datetime.datetime.fromisoformat(stamp)                     # parseable ISO


# --------------------------------------------------------------------------- #
# display_toast
# --------------------------------------------------------------------------- #

def test_display_toast_adds_toast(ind_app):
    fn = get_callback_fn(ind_app, "toast-container")
    with ctx_with("toast-message"):
        result = fn({"type": "success", "title": "Done", "message": "ok"}, None, [])
    assert isinstance(result, list)
    assert len(result) == 1


def test_display_toast_noop_without_payload(ind_app):
    fn = get_callback_fn(ind_app, "toast-container")
    with ctx_with("toast-message"):
        assert fn(None, None, []) == []
