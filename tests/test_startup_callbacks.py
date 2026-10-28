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


def _startup_fn(app, name):
    """The unwrapped startup callback by function name. Two startup
    callbacks write toast-message from app-config (missing paths, orphan
    run), so an output/input lookup cannot tell them apart."""
    for spec in app.callback_map.values():
        fn = spec["callback"]
        inner = getattr(fn, "__wrapped__", fn)
        if inner.__name__ == name:
            return inner
    raise AssertionError(f"startup callback {name!r} not registered")


# --------------------------------------------------------------------------- #
# warn_about_missing_paths_on_startup
# --------------------------------------------------------------------------- #

def test_missing_path_warning_emitted(startup_app):
    fn = _startup_fn(startup_app, "warn_about_missing_paths_on_startup")
    toast = fn({"kraken_db": "/definitely/not/here/db"})
    assert isinstance(toast, dict)
    assert toast["type"] == "warning"
    assert "kraken_db" in toast["message"]


def test_no_warning_when_paths_exist(startup_app, tmp_path):
    fn = _startup_fn(startup_app, "warn_about_missing_paths_on_startup")
    # all set path keys exist -> no toast
    assert fn({"kraken_db": str(tmp_path)}) is no_update


def test_no_warning_without_config(startup_app):
    fn = _startup_fn(startup_app, "warn_about_missing_paths_on_startup")
    assert fn(None) is no_update


def test_warning_only_once_per_session(startup_app):
    fn = _startup_fn(startup_app, "warn_about_missing_paths_on_startup")
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


# --------------------------------------------------------------------------- #
# warn_about_orphan_run_on_startup (field audit 2026-10-28, H3)
# --------------------------------------------------------------------------- #

def _orphan_fn(app):
    return _startup_fn(app, "warn_about_orphan_run_on_startup")


def test_orphan_run_is_named_once(startup_app, tmp_path, monkeypatch):
    import subprocess, sys, json
    from nanometa_live.core.workflow.backend_manager import BackendManager
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        results = tmp_path / "results"; results.mkdir()
        (results / ".nanometa.lock").write_text(json.dumps({
            "pid": 2_147_483_646, "nextflow_pid": proc.pid,
            "nextflow_started_at": "2026-10-28T09:00:00",
        }))
        fn = _orphan_fn(startup_app)
        toast = fn(str(results))
        assert isinstance(toast, dict)
        assert toast["type"] == "warning"
        assert str(proc.pid) in toast["message"]
        assert "kill" in toast["message"]
        # Once per session.
        assert fn(str(results)) is no_update
    finally:
        proc.kill(); proc.wait()


def test_no_orphan_toast_for_a_quiet_folder(startup_app, tmp_path):
    results = tmp_path / "results"; results.mkdir()
    fn = _orphan_fn(startup_app)
    assert fn(str(results)) is no_update
