"""Callback tests for app/callbacks/progress.py (pipeline stage + auto-navigate)."""

from unittest.mock import MagicMock

import pytest
from dash import Dash, no_update
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.progress import register_progress
from dash_test_utils import get_callback_fn


@pytest.fixture(scope="module")
def prog_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_progress(app, MagicMock())
    return app


# --------------------------------------------------------------------------- #
# update_pipeline_stage_display
# --------------------------------------------------------------------------- #

def test_stage_hidden_when_not_running(prog_app):
    fn = get_callback_fn(prog_app, "current-pipeline-stage")
    assert fn(None) == ("", "", {"display": "none"})
    assert fn({"running": False}) == ("", "", {"display": "none"})


def test_stage_shown_with_counts(prog_app):
    fn = get_callback_fn(prog_app, "current-pipeline-stage")
    stage, text, style = fn({
        "running": True, "current_stage": "Kraken2",
        "processes_complete": 2, "processes_running": 1, "processes_failed": 0,
    })
    assert style["display"] == "flex"
    assert "2/3" in text and "1 active" in text
    assert "Kraken2" in str(stage)


def test_stage_running_without_stage_but_with_processes(prog_app):
    fn = get_callback_fn(prog_app, "current-pipeline-stage")
    stage, text, style = fn({"running": True, "processes_complete": 1})
    assert style["display"] == "flex"
    assert "Processing" in str(stage)


# --------------------------------------------------------------------------- #
# auto_navigate_on_completion
# --------------------------------------------------------------------------- #

def test_auto_navigate_on_completion_switches_to_dashboard(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    tab, prev, toast = fn({"running": False}, True, "qc-tab", {"analysis_name": "Run1"})
    assert tab == "dashboard-tab"
    assert prev is False
    assert toast["title"] == "Analysis Complete"
    assert "Run1" in toast["message"]


def test_auto_navigate_already_on_dashboard_only_toasts(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    tab, prev, toast = fn({"running": False}, True, "dashboard-tab", {})
    assert tab is no_update
    assert prev is False
    assert toast["title"] == "Analysis Complete"


def test_auto_navigate_no_transition_is_noupdate(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    # was not running, still not running -> nothing changes
    assert fn({"running": False}, False, "qc-tab", {}) == (no_update, no_update, no_update)


def test_auto_navigate_none_status(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    assert fn(None, True, "qc-tab", {}) == (no_update, False, no_update)
