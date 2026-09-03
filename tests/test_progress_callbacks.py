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
    # Clearer than the old "2/3" form (which read N/N at most snapshots).
    assert "2 done" in text and "1 active" in text
    assert "Kraken2" in str(stage)


def test_stage_progress_omits_active_when_zero(prog_app):
    fn = get_callback_fn(prog_app, "current-pipeline-stage")
    _stage, text, _style = fn({
        "running": True, "current_stage": "Kraken2",
        "processes_complete": 7, "processes_running": 0, "processes_failed": 0,
    })
    assert text == "(7 done)"  # no misleading "7/7"


def test_stage_running_without_stage_but_with_processes(prog_app):
    fn = get_callback_fn(prog_app, "current-pipeline-stage")
    stage, text, style = fn({"running": True, "processes_complete": 1})
    assert style["display"] == "flex"
    assert "Processing" in str(stage)


# --------------------------------------------------------------------------- #
# auto_navigate_on_completion
# --------------------------------------------------------------------------- #

def test_auto_navigate_switches_from_setup_tab(prog_app):
    # From a Setup tab (e.g. configuration), completion pulls the operator to
    # the Dashboard so they see results.
    fn = get_callback_fn(prog_app, "previous-running-state")
    tab, prev, toast, _flag = fn({"running": False}, True, "config-tab",
                                 {"analysis_name": "Run1"}, False)
    assert tab == "dashboard-tab"
    assert prev is False
    assert toast["title"] == "Analysis Complete"
    assert "Run1" in toast["message"]


def test_auto_navigate_stays_on_results_tab(prog_app):
    # Operator feedback: do NOT yank focus off a results tab mid-investigation.
    fn = get_callback_fn(prog_app, "previous-running-state")
    tab, prev, toast, _flag = fn({"running": False}, True, "validation-tab", {}, False)
    assert tab is no_update
    assert prev is False
    assert toast["title"] == "Analysis Complete"


def test_auto_navigate_already_on_dashboard_only_toasts(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    tab, prev, toast, _flag = fn({"running": False}, True, "dashboard-tab", {}, False)
    assert tab is no_update
    assert prev is False
    assert toast["title"] == "Analysis Complete"


def test_auto_navigate_no_transition_is_noupdate(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    # was not running, still not running -> nothing changes
    assert fn({"running": False}, False, "qc-tab", {}, False) == (
        no_update, no_update, no_update, no_update)


def test_auto_navigate_none_status(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    assert fn(None, True, "qc-tab", {}, False) == (
        no_update, False, no_update, no_update)


def test_failed_preflight_is_not_announced_as_complete(prog_app):
    """The optimistic Start write must not arm the completion detector.

    Sequence seen live (audit round 5, A16): click writes
    {running: True, starting: True}; the daemon thread's preflight fails
    ("Nextflow not found"); the next poll writes running: False. The old
    detector saw running -> not running and toasted "Analysis Complete.
    Results are up to date." over a launch that never started a process.
    """
    fn = get_callback_fn(prog_app, "previous-running-state")
    _tab, prev, toast, _flag = fn({"running": True, "starting": True}, False,
                                  "config-tab", {"analysis_name": "Run1"}, False)
    assert prev is no_update, "the optimistic status must not arm the detector"
    _tab, _prev, toast, _flag = fn({"running": False}, False, "config-tab",
                                   {"analysis_name": "Run1"}, False)
    assert toast is no_update


def test_authoritative_running_status_still_arms_the_detector(prog_app):
    fn = get_callback_fn(prog_app, "previous-running-state")
    _tab, prev, _toast, _flag = fn({"running": True, "start_time": "2026-09-03T07:06:48"},
                                   False, "config-tab", {"analysis_name": "Run1"}, False)
    assert prev is True
