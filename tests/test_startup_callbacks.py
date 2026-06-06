"""Callback tests for app/callbacks/startup.py (missing-path warning + toast relay)."""

from unittest.mock import MagicMock

import pytest
from dash import Dash, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.startup import register_startup
from dash_test_utils import get_callback_fn


@pytest.fixture
def startup_app():
    # Function-scoped: the once-per-session guard is a closure inside
    # register_startup, so a fresh registration resets it for each test.
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_startup(app, MagicMock())
    return app


# --------------------------------------------------------------------------- #
# warn_about_missing_paths_on_startup
# --------------------------------------------------------------------------- #

def test_missing_path_warning_emitted(startup_app):
    fn = get_callback_fn(startup_app, "toast-message", input_contains="app-config")
    toast = fn({"kraken_db": "/definitely/not/here/db"})
    assert isinstance(toast, dict)
    assert toast["type"] == "warning"
    assert "kraken_db" in toast["message"]


def test_no_warning_when_paths_exist(startup_app, tmp_path):
    fn = get_callback_fn(startup_app, "toast-message", input_contains="app-config")
    # all set path keys exist -> no toast
    assert fn({"kraken_db": str(tmp_path)}) is no_update


def test_no_warning_without_config(startup_app):
    fn = get_callback_fn(startup_app, "toast-message", input_contains="app-config")
    assert fn(None) is no_update


def test_warning_only_once_per_session(startup_app):
    fn = get_callback_fn(startup_app, "toast-message", input_contains="app-config")
    first = fn({"kraken_db": "/definitely/not/here/db"})
    assert isinstance(first, dict)
    # guard now set -> second call suppressed
    assert fn({"kraken_db": "/definitely/not/here/db"}) is no_update


# --------------------------------------------------------------------------- #
# relay_internet_check_toast
# --------------------------------------------------------------------------- #

def test_relay_internet_check_toast(startup_app):
    fn = get_callback_fn(startup_app, "toast-message", input_contains="internet-check-toast")
    payload = {"type": "warning", "title": "No Internet Detected", "message": "x"}
    assert fn(payload) == payload
    with pytest.raises(PreventUpdate):
        fn(None)
