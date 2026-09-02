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


class TestNewTabGetsTheLiveRunConfig:
    """H34 (round-4 audit): app.layout is static, so a new tab hydrated
    app-config from the boot-time config and a collision Continue from that
    tab launched with an empty outdir and no negative controls."""

    def _fn(self, backend):
        from dash import Dash
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_startup(app, backend)
        return get_callback_fn(app, "app-config.data", input_contains="tabs")

    def test_running_app_overrides_the_boot_config(self):
        backend = MagicMock()
        backend.config = {"results_output_directory": "/runs/r2",
                          "negative_control_samples": ["unclassified"]}
        backend.status = {"start_time": "2026-09-01T23:07:22", "running": True}
        out = self._fn(backend)(1, "dashboard-tab", {"results_output_directory": "", "kraken_db": "/db"})
        assert out["results_output_directory"] == "/runs/r2"
        assert out["negative_control_samples"] == ["unclassified"]
        assert out["kraken_db"] == "/db", "boot keys the run did not set survive"

    def test_before_any_run_the_boot_config_stands(self):
        from dash import no_update
        backend = MagicMock()
        backend.config = None
        backend.status = {"start_time": None}
        assert self._fn(backend)(1, "dashboard-tab", {"kraken_db": "/db"}) is no_update

    def test_identical_config_is_a_noop(self):
        from dash import no_update
        backend = MagicMock()
        backend.config = {"results_output_directory": "/runs/r2"}
        backend.status = {"start_time": "x"}
        assert self._fn(backend)(1, "dashboard-tab", {"results_output_directory": "/runs/r2"}) is no_update
