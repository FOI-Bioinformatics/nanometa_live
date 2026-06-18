"""Callback tests for the Dashboard tab."""

import os
import time
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from dash import Dash, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs import dashboard_tab as dash_mod
from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
from nanometa_live.core.testing.mock_data_generator import (
    generate_test_dataset,
    MockDataScenario,
)
from dash_test_utils import get_callback_fn, make_callback_app


@pytest.fixture(scope="module")
def dash_app():
    return make_callback_app(register_dashboard_callbacks)


@pytest.fixture(scope="module")
def populated_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("dashboard_populated")
    generate_test_dataset(str(d), scenario=MockDataScenario.PATHOGEN_DETECTED, num_samples=3)
    old = time.time() - 30
    for dp, _dirs, files in os.walk(str(d)):
        for f in files:
            try:
                os.utime(os.path.join(dp, f), (old, old))
            except OSError:
                pass
    return str(d)


@contextmanager
def ctx_trigger(triggered_id):
    fake = MagicMock(triggered_id=triggered_id,
                     triggered=[{"prop_id": f"{triggered_id}.data"}])
    with patch.object(dash_mod, "ctx", fake):
        yield


# --------------------------------------------------------------------------- #
# compute_overall_status_cache
# --------------------------------------------------------------------------- #

class TestViewReportModalGuard:
    """Operator feedback #5: the View Report modal reopened on its own after
    being closed, because the alert-panel refresh recreated the pattern-matched
    buttons and re-fired the callback with a persisted/None click value."""

    def _fn(self, app):
        return get_callback_fn(app, "pathogen-report-modal",
                               input_contains="pathogen-view-report")

    def test_spurious_rerender_does_not_reopen(self, dash_app):
        fn = self._fn(dash_app)
        trig = {"type": "pathogen-view-report", "taxid": 263}
        fake = MagicMock(triggered_id=trig, triggered=[{"value": None}])
        with patch.object(dash_mod, "ctx", fake):
            # view_clicks carries a persisted click from before, but the trigger
            # value is None (recreate) -> the modal must stay closed.
            out = fn([1], None, None, False, {}, {}, "All Samples")
        assert out[0] is no_update

    def test_close_button_closes(self, dash_app):
        fn = self._fn(dash_app)
        fake = MagicMock(triggered_id="pathogen-modal-close", triggered=[{"value": 1}])
        with patch.object(dash_mod, "ctx", fake):
            out = fn([1], 1, None, True, {}, {}, "All Samples")
        assert out[0] is False

    def test_genuine_click_opens_modal(self, dash_app):
        """A real click (truthy triggered value) must open the modal even while
        an active run keeps recreating the pattern-matched buttons."""
        fn = self._fn(dash_app)
        trig = {"type": "pathogen-view-report", "taxid": 263}
        fake = MagicMock(triggered_id=trig, triggered=[{"value": 1}])
        with patch.object(dash_mod, "ctx", fake):
            out = fn([1], None, None, False, {}, {}, "All Samples")
        assert out[0] is True  # is_open
        assert str(out[9])  # a taxid string is rendered

    def test_report_build_error_still_opens_with_message(self, dash_app):
        """If the report body cannot be assembled the modal must still open with
        a legible error rather than failing the callback to a silent 500."""
        fn = self._fn(dash_app)
        trig = {"type": "pathogen-view-report", "taxid": 263}
        fake = MagicMock(triggered_id=trig, triggered=[{"value": 1}])
        with patch.object(dash_mod, "ctx", fake), \
             patch("nanometa_live.app.tabs.dashboard_helpers._build_report_payload_inner",
                   side_effect=RuntimeError("boom")):
            out = fn([1], None, None, False, {}, {}, "All Samples")
        assert out[0] is True
        assert "could not be built" in str(out[12])  # notes carry the error


class TestVerdictCountdownRefresh:
    """Operator feedback: the auto-stop countdown froze. The verdict banner is
    debounced on the results fingerprint, which stops advancing once Kraken2
    finishes; while the pipeline runs the banner must still re-render each tick
    so the wall-clock countdown keeps moving."""

    def _fn(self, app):
        return get_callback_fn(app, "dashboard-verdict-banner")

    def _call(self, fn, fingerprint, running):
        fake = MagicMock(triggered_id="update-interval",
                         triggered=[{"prop_id": "update-interval.n_intervals"}])
        with patch.object(dash_mod, "ctx", fake):
            return fn(fingerprint, None, 1, {}, {"running": running}, {}, {}, [])

    def test_running_run_rerenders_on_redundant_interval(self, dash_app):
        fn = self._fn(dash_app)
        first = self._call(fn, "cd_running", running=True)
        assert isinstance(first, (list, tuple))
        # Same fingerprint again on an interval tick: would be debounced, but a
        # running pipeline must still re-render so the countdown advances.
        second = self._call(fn, "cd_running", running=True)
        assert isinstance(second, (list, tuple))

    def test_idle_run_still_debounces_redundant_interval(self, dash_app):
        fn = self._fn(dash_app)
        self._call(fn, "cd_idle", running=False)
        with pytest.raises(PreventUpdate):
            self._call(fn, "cd_idle", running=False)


def test_overall_status_cache_none_when_nothing_to_load(dash_app):
    fn = get_callback_fn(dash_app, "dashboard-overall-status-cache")
    with ctx_trigger("results-fingerprint"):
        # no config/status and no data -> should_load False -> None
        assert fn("fp", 0, {}, {}, ["All Samples"]) is None


def test_overall_status_cache_populated(dash_app, populated_dir):
    fn = get_callback_fn(dash_app, "dashboard-overall-status-cache")
    with ctx_trigger("results-fingerprint"):
        result = fn(
            "fp2", 0,
            {"results_output_directory": populated_dir},
            {"running": True},
            ["All Samples"],
        )
    assert isinstance(result, dict)
    # cache carries the resolved main_dir + per-sample data for downstream callbacks
    assert result.get("_main_dir") == populated_dir
    assert "_samples_data" in result


# --------------------------------------------------------------------------- #
# handle_sample_selection
# --------------------------------------------------------------------------- #

def test_handle_sample_selection(dash_app):
    fn = get_callback_fn(dash_app, "selected-sample", input_contains="dashboard-sample-table")
    assert fn([{"sample": "barcode01"}]) == "barcode01"
    assert fn([]) is no_update
    assert fn([{"no_sample_key": 1}]) is no_update   # KeyError path


# --------------------------------------------------------------------------- #
# update_quality_card (empty path)
# --------------------------------------------------------------------------- #

def test_quality_card_empty_does_not_raise(dash_app):
    fn = get_callback_fn(dash_app, "dashboard-quality-card-content")
    with ctx_trigger("results-fingerprint"):
        result = fn("fp", {}, {})
    assert result is not None
