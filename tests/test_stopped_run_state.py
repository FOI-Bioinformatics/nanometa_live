"""A stopped run must be recorded and rendered as stopped.

Round-4 realtime audit (docs/audit/realtime-round4-2026-09-02.md, H2/H3/H13).
Three live Stop drills ended the same way: the pipeline was gone within two
seconds, ``.nanometa.run.json`` never received a ``final_status``, the
auto-report read like a report over a run that drained its input, and the
dashboard header reverted to "STANDBY -- Click 'Start Analysis'", the badge
of a run that never started.

The pipeline's own real-time timer (wall-clock) and the GUI's inactivity
backstop end runs the same way, so both paths must leave the same record.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from nanometa_live.core.export.run_status import read_final_run_status
from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


def _meta(out):
    with open(os.path.join(out, ".nanometa.run.json")) as f:
        return json.load(f)


@pytest.fixture
def bm(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    manager = BackendManager(str(tmp_path))
    manager.config = {"results_output_directory": str(out), "auto_report": False}
    manager.workflow_manager = MagicMock()
    manager.workflow_manager.stop.return_value = (True, "stopped")
    manager.workflow_manager.status = {"errors": []}
    manager.workflow_manager.get_status.return_value = {"running": False, "errors": []}
    manager._auto_generate_report = MagicMock(return_value=None)
    manager._release_lock = MagicMock()
    manager.status["running"] = True
    manager.status["pipeline_status"] = "running"
    manager.status["files_processed"] = 33
    return manager


class TestOperatorStopIsRecorded:
    def test_stop_writes_final_status_stopped(self, bm):
        ok, _ = bm.stop()
        assert ok
        meta = _meta(bm.config["results_output_directory"])
        assert meta["final_status"] == "stopped"
        assert meta["stop_reason"] == "operator"
        assert meta["files_processed"] == 33
        assert meta["ended_at"]

    def test_stop_leaves_a_reason_in_status(self, bm):
        bm.stop()
        assert bm.status["pipeline_status"] == "stopped"
        assert bm.status["stop_reason"] == "operator"
        assert bm.get_status()["stopped_run"] is True

    def test_idle_backend_is_not_a_stopped_run(self, tmp_path):
        manager = BackendManager(str(tmp_path))
        manager.workflow_manager = MagicMock()
        manager.workflow_manager.get_status.return_value = {"running": False, "errors": []}
        assert manager.get_status()["stopped_run"] is False


class TestMonitorThreadHonoursStopIntent:
    """H3: stop() blocks in workflow_manager.stop() while status is still
    running; the monitor thread sees the dead process first and used to
    record the aborted run as completed (or error)."""

    def test_terminal_classifier_records_stopped_not_completed(self, bm):
        bm._mark_stop_intent("operator")
        completed = bm._apply_terminal_workflow_status({
            "running": False, "errors": [],
            "processes_complete": 46, "processes_failed": 0, "exit_code": 0,
        })
        assert completed is False, "stop() owns the report; the monitor must not write a second one"
        assert bm.status["pipeline_status"] == "stopped"
        assert _meta(bm.config["results_output_directory"])["final_status"] == "stopped"

    def test_nonzero_exit_under_stop_intent_is_not_an_error(self, bm):
        bm._mark_stop_intent("operator")
        bm._apply_terminal_workflow_status({
            "running": False, "errors": ["Nextflow exited with code 143"],
            "processes_complete": 3, "processes_failed": 0, "exit_code": 143,
        })
        assert bm.status["pipeline_status"] == "stopped"
        assert bm.status["errors"] == []


class TestInactivityStopIsRecorded:
    def test_inactivity_stop_records_reason_and_report(self, bm):
        bm._stop_for_inactivity(timeout_seconds=180, idle_s=200.0)
        meta = _meta(bm.config["results_output_directory"])
        assert meta["final_status"] == "stopped"
        assert "inactivity" in meta["stop_reason"]
        assert bm._auto_generate_report.called
        assert bm.status["running"] is False


class TestRunStatusForTheReport:
    def test_stopped_run_is_reported_as_stopped(self, tmp_path):
        (tmp_path / ".nanometa.run.json").write_text(json.dumps({
            "final_status": "stopped", "stop_reason": "operator",
            "ended_at": "2026-09-01T23:23:45", "files_processed": 58,
        }))
        st = read_final_run_status(str(tmp_path))
        assert st["run_state"] == "stopped"
        assert st["stop_reason"] == "operator"
        assert st["pipeline_error"] is False

    def test_completed_run(self, tmp_path):
        (tmp_path / ".nanometa.run.json").write_text(json.dumps({"final_status": "completed"}))
        assert read_final_run_status(str(tmp_path))["run_state"] == "completed"

    def test_run_with_lock_and_no_final_status_is_active(self, tmp_path):
        """A mid-run export: metadata written at Start, lock held, no terminal status."""
        (tmp_path / ".nanometa.run.json").write_text(json.dumps({"written_at": "2026-09-01T23:07:22"}))
        (tmp_path / ".nanometa.lock").write_text("pid 1")
        assert read_final_run_status(str(tmp_path))["run_state"] == "active"

    def test_no_metadata_is_unknown(self, tmp_path):
        assert read_final_run_status(str(tmp_path))["run_state"] == "unknown"


class TestVerdictCarriesTheStop:
    def test_detection_subtitle_names_the_stop(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        d = select_verdict(
            has_config=True, pipeline_running=False, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=[{"name": "Francisella tularensis", "reads": 500,
                        "threat_level": "critical", "threshold": 10}],
            n_watched=129, validation_has_results=False, total_reads=9697,
            run_stopped=True, stop_reason="operator",
        )
        assert d.state == "ACTION_REQUIRED"
        assert "stopped" in d.subtitle.lower()
        assert "partial" in d.subtitle.lower()

    def test_all_clear_on_a_stopped_run_is_qualified(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        d = select_verdict(
            has_config=True, pipeline_running=False, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True, dangerous=[],
            n_watched=129, validation_has_results=False, total_reads=9697,
            run_stopped=True, stop_reason="inactivity timeout",
        )
        assert d.state == "ALL_CLEAR"
        assert "stopped" in d.subtitle.lower()

    def test_running_verdict_is_unchanged(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True, dangerous=[],
            n_watched=129, validation_has_results=False, total_reads=9697,
        )
        assert "stopped" not in d.subtitle.lower()


class TestHeaderStatusText:
    def test_status_display_names_a_stopped_run(self):
        from dash import Dash
        from nanometa_live.app.callbacks.status import register_status
        from tests.dash_test_utils import get_callback_fn

        app = Dash(__name__)
        register_status(app, MagicMock())
        fn = get_callback_fn(app, "status-indicator", input_contains="backend-status")
        color, text, detail = fn(
            {"running": False, "pipeline_status": "stopped", "stopped_run": True,
             "stop_reason": "operator", "ended_at": "2026-09-01T23:23:45",
             "files_processed": 58},
            {"processing_mode": "realtime"},
        )
        assert text.lower().startswith("stopped")
        assert "58" in detail
        assert "Click 'Start Analysis'" not in detail


class TestFailedTasksAreNamed:
    """H20: an isolated (ignored) task failure drops its reads from every
    count and no surface said so while the run was active."""

    def test_verdict_names_skipped_tasks(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True, dangerous=[],
            n_watched=129, validation_has_results=False, total_reads=9697,
            failed_tasks=1,
        )
        assert d.state == "ALL_CLEAR"
        assert "1 pipeline task failed" in d.subtitle
        assert "not in these counts" in d.subtitle

    def test_header_names_skipped_tasks_while_running(self):
        from dash import Dash
        from nanometa_live.app.callbacks.status import register_status
        from tests.dash_test_utils import get_callback_fn

        app = Dash(__name__)
        register_status(app, MagicMock())
        fn = get_callback_fn(app, "status-indicator", input_contains="backend-status")
        _color, text, detail = fn(
            {"running": True, "files_processed": 66, "files_waiting": 63,
             "processes_failed": 2},
            {"processing_mode": "realtime"},
        )
        assert text == "RUNNING"
        assert "2 tasks failed" in detail


class TestAutoStopCountdownMatchesThePipelineTimer:
    def test_countdown_includes_the_grace_period(self, tmp_path):
        from datetime import datetime
        manager = BackendManager(str(tmp_path))
        manager.config = {"processing_mode": "realtime", "realtime_timeout_minutes": 3}
        manager.status["running"] = True
        manager.status["start_time"] = datetime.now().isoformat()
        remaining = manager._compute_auto_stop_remaining()
        assert 7 * 60 < remaining <= 8 * 60, "3 min timeout + 5 min grace"
