"""Unit tests for the background run_all_wizard_steps callback.

The wizard runs in a DiskcacheManager worker; here the unwrapped callback is
driven directly with a mocked set_progress, a mocked step executor, and a
mocked (pre-loaded) watchlist manager, asserting the step state machine and
abort-on-critical-failure behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback
from dash import Dash
from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn
import nanometa_live.app.tabs.preparation_tab as prep
from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks


@pytest.fixture
def run_all_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_preparation_callbacks(app)
    return get_callback_fn(app, "wizard-step-state.data", input_contains="wizard-run-all-btn")


def _call(fn, execute_side_effect=None):
    set_progress = MagicMock()
    loaded_mgr = MagicMock(_loaded=True)
    with patch.object(prep, "_execute_wizard_step", side_effect=execute_side_effect) as ex, \
         patch("nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
               return_value=loaded_mgr):
        state = fn(set_progress, 1, None, {"kraken_db": "/x"})
    return state, set_progress, ex


class TestRunAllWizard:
    def test_all_steps_done(self, run_all_fn):
        state, set_progress, ex = _call(run_all_fn, execute_side_effect=lambda i, c: None)
        assert ex.call_count == 8
        assert all(state["steps"][str(i)] == "done" for i in range(8))
        # Live progress + final summary were pushed.
        assert set_progress.call_count >= 9

    def test_critical_failure_aborts(self, run_all_fn):
        def boom(step_idx, config):
            if step_idx == 1:
                raise RuntimeError("no kraken db")

        state, set_progress, ex = _call(run_all_fn, execute_side_effect=boom)
        # Step 0 ran and passed; step 1 failed and aborted the run.
        assert state["steps"]["0"] == "done"
        assert state["steps"]["1"] == "failed"
        # Steps 2..7 never started.
        assert state["steps"]["2"] == "pending"
        assert ex.call_count == 2

    def test_noncritical_failure_continues(self, run_all_fn):
        def boom(step_idx, config):
            if step_idx == 3:  # genome download is non-critical
                raise RuntimeError("download failed")

        state, set_progress, ex = _call(run_all_fn, execute_side_effect=boom)
        assert state["steps"]["3"] == "failed"
        # Later steps still ran.
        assert state["steps"]["7"] == "done"
        assert ex.call_count == 8

    def test_no_clicks_prevents_update(self, run_all_fn):
        with pytest.raises(PreventUpdate):
            run_all_fn(MagicMock(), None, None, {})
