"""
Tests for the start/stop orchestration callback in app/callbacks.py.

start_or_prompt_stop is the most stateful core callback: it either starts a run,
prompts to stop a running one, warns about an output collision, or errors on a
missing config. backend_manager is injected into register_core_callbacks, so a
MagicMock lets us drive every branch and assert the 7-output tuple (notification,
config, stop-modal, collision-modal, collision-body, pending, backend-status)
without launching any pipeline.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.callback
from dash import Dash, no_update

from dash_test_utils import get_callback_fn
from nanometa_live.app.callbacks import register_core_callbacks

# Output tuple indices for readability.
NOTIF, CONFIG, STOP_MODAL, COLLISION_MODAL, COLLISION_BODY, PENDING, STATUS = range(7)


@pytest.fixture
def start_stop():
    app = Dash(__name__, suppress_callback_exceptions=True)
    backend = MagicMock()
    register_core_callbacks(app, backend)
    return get_callback_fn(app, "collision-decision-pending.data"), backend


class TestStartOrPromptStop:
    def test_no_clicks_is_all_noop(self, start_stop):
        fn, _ = start_stop
        result = fn(0, {"main_dir": "/x"}, {"running": False})
        assert all(r is no_update for r in result)

    def test_running_opens_stop_modal(self, start_stop):
        fn, _ = start_stop
        result = fn(1, {"main_dir": "/x"}, {"running": True})
        assert result[STOP_MODAL] is True

    def test_missing_config_errors(self, start_stop):
        fn, _ = start_stop
        result = fn(1, None, {"running": False})
        assert result[NOTIF]["color"] == "danger"

    def test_clean_outdir_starts_run(self, start_stop):
        fn, backend = start_stop
        backend.detect_existing_results.return_value = []
        backend.start.return_value = (True, "Pipeline started")
        result = fn(1, {"results_output_directory": "/out"}, {"running": False})
        backend.start.assert_called_once()
        assert result[NOTIF]["title"] == "Analysis Started"
        # Optimistic backend-status flips running True on success.
        assert result[STATUS]["running"] is True
        assert result[STATUS]["starting"] is True

    def test_start_failure_reports_error_without_status_flip(self, start_stop):
        fn, backend = start_stop
        backend.detect_existing_results.return_value = []
        backend.start.return_value = (False, "conda env broken")
        result = fn(1, {"results_output_directory": "/out"}, {"running": False})
        assert result[NOTIF]["title"] == "Error"
        assert result[NOTIF]["color"] == "danger"
        assert result[STATUS] is no_update

    def test_existing_results_opens_collision_modal(self, start_stop):
        fn, backend = start_stop
        backend.detect_existing_results.return_value = ["kraken2", "fastp"]
        backend.fingerprint_matches.return_value = True
        result = fn(1, {"results_output_directory": "/out"}, {"running": False})
        assert result[COLLISION_MODAL] is True
        assert result[PENDING]["outdir"] == "/out"
        assert result[PENDING]["found"] == ["kraken2", "fastp"]
        # A collision must NOT start the pipeline.
        backend.start.assert_not_called()
