"""Start / Stop run in main-process threads; the click returns instantly.

`backend_manager.start()` blocks 25-40 s worst case (git ls-remote,
engine probes, conda-cache walks) and `stop()` up to 30+ s
(`process.wait`), both on the request thread with a frozen button
(round-2 audit, 2026-08-22). They now run in daemon THREADS inside the
main process — a DiskcacheManager worker cannot hold the subprocess
handles — publishing a transition result the status tick surfaces as the
terminal toast (including failures: a preflight error must never be
silent).
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(tmp_path):
    return BackendManager(str(tmp_path))


class TestAsyncTransitions:
    def test_start_async_returns_immediately(self, manager):
        release = {"go": False}

        def slow_start(profile=None, resume=False):
            while not release["go"]:
                time.sleep(0.01)
            return True, "started"

        with patch.object(manager, "start", side_effect=slow_start):
            t0 = time.perf_counter()
            ok, _msg = manager.start_async()
            elapsed = time.perf_counter() - t0
            assert ok is True
            assert elapsed < 0.2
            assert manager.transition_in_progress() is True
            assert manager.consume_transition_result() is None
            release["go"] = True
            for _ in range(200):
                if not manager.transition_in_progress():
                    break
                time.sleep(0.01)

        result = manager.consume_transition_result()
        assert result == {"kind": "start", "success": True,
                          "message": "started"}
        assert manager.consume_transition_result() is None, (
            "the terminal result is consumed exactly once"
        )

    def test_second_start_while_in_progress_is_refused(self, manager):
        release = {"go": False}

        def slow_start(profile=None, resume=False):
            while not release["go"]:
                time.sleep(0.01)
            return True, "started"

        with patch.object(manager, "start", side_effect=slow_start):
            assert manager.start_async()[0] is True
            ok, msg = manager.start_async()
            assert ok is False
            assert "in progress" in msg.lower()
            release["go"] = True
            for _ in range(200):
                if not manager.transition_in_progress():
                    break
                time.sleep(0.01)

    def test_a_start_exception_surfaces_as_a_failed_result(self, manager):
        with patch.object(manager, "start",
                          side_effect=RuntimeError("preflight exploded")):
            manager.start_async()
            for _ in range(200):
                if not manager.transition_in_progress():
                    break
                time.sleep(0.01)
        result = manager.consume_transition_result()
        assert result["success"] is False
        assert "preflight exploded" in result["message"]

    def test_stop_async_publishes_a_stop_result(self, manager):
        with patch.object(manager, "stop", return_value=(True, "stopped")):
            manager.stop_async()
            for _ in range(200):
                if not manager.transition_in_progress():
                    break
                time.sleep(0.01)
        result = manager.consume_transition_result()
        assert result == {"kind": "stop", "success": True,
                          "message": "stopped"}


class TestCallbacksReturnInstantly:
    def _app_fns(self, backend):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.callbacks.start_stop import register_start_stop
        app = make_callback_app(lambda a: register_start_stop(a, backend))
        return app

    def test_start_click_does_not_call_blocking_start(self, tmp_path):
        backend = BackendManager(str(tmp_path))
        backend.detect_existing_results = MagicMock(return_value=[])
        backend.start = MagicMock(
            side_effect=AssertionError("blocking start() on the click path"))
        backend.start_async = MagicMock(return_value=(True, "Starting..."))
        app = self._app_fns(backend)
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "collision-modal",
                             input_contains="start-stop-button")
        out = fn(1, {"analysis_name": "run", "project_dir": str(tmp_path)},
                 {"running": False})
        toast, _cfg, _stop_modal, _cmodal, _cbody, _pending, status = out
        backend.start_async.assert_called_once()
        assert status.get("running") is True and status.get("starting") is True
        assert "start" in toast["title"].lower()

    def test_stop_click_does_not_call_blocking_stop(self, tmp_path):
        backend = BackendManager(str(tmp_path))
        backend.stop = MagicMock(
            side_effect=AssertionError("blocking stop() on the click path"))
        backend.stop_async = MagicMock(return_value=(True, "Stopping..."))
        app = self._app_fns(backend)
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "stop-confirm-modal",
                             input_contains="confirm-stop-analysis")
        import dash
        with patch.object(dash, "ctx",
                          MagicMock(triggered_id="confirm-stop-analysis")):
            is_open, toast, stop_flag = fn(1, None, True)
        backend.stop_async.assert_called_once()
        assert is_open is False
        assert stop_flag is True
        assert "stop" in toast["title"].lower()

    def test_transition_result_surfaces_toast_and_config(self, tmp_path):
        backend = BackendManager(str(tmp_path))
        backend.config = {"results_output_directory": "/x"}
        backend._transition = {"kind": "start", "done": True,
                               "success": True, "message": "started"}
        app = self._app_fns(backend)
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "notification-trigger",
                             input_contains="backend-status")
        toast, cfg = fn({"running": True}, {"analysis_name": "run"})
        assert toast["color"] == "success"
        assert toast.get("navigate_to") == "dashboard-tab"
        assert cfg.get("results_output_directory") == "/x"

    def test_no_pending_transition_prevents_update(self, tmp_path):
        from dash.exceptions import PreventUpdate
        backend = BackendManager(str(tmp_path))
        app = self._app_fns(backend)
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "notification-trigger",
                             input_contains="backend-status")
        with pytest.raises(PreventUpdate):
            fn({"running": False}, {})