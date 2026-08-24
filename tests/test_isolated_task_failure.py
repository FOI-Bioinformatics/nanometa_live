"""An isolated (ignored) task failure must not fail the whole run.

Found by the 2026-08-17 multiplex assembly E2E. nanometanf's
conf/error_isolation.config sets errorStrategy 'ignore' on per-sample
processes such as FLYE, so one barcode failing is by design: Nextflow runs
every other sample to completion, publishes all outputs, prints "Pipeline
completed successfully, but with errored process(es)" and exits 0.

The trace file still records that task as FAILED (Nextflow does not
distinguish "ignored" there), and BackendManager treated any
processes_failed > 0 as a run-level failure. Consequences on the real run:
the dashboard declared a successful 3-barcode run failed, and the
auto-generated operator report -- the artifact that survives closing the
dashboard -- was never written.

The Nextflow exit code is the authority: 0 means the run completed,
whatever individual tasks were isolated.
"""

from unittest.mock import MagicMock

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


def _statuses(bm, workflow_status):
    """Drive the terminal-state branch with a given workflow status."""
    bm.status["running"] = True
    bm.status["errors"] = []
    return bm._apply_terminal_workflow_status(workflow_status)


@pytest.fixture
def bm(tmp_path):
    manager = BackendManager(str(tmp_path))
    manager.config = {"results_output_directory": str(tmp_path / "out"),
                      "auto_report": False}
    manager.workflow_manager = MagicMock()
    return manager


class TestIsolatedFailure:
    def test_ignored_failure_with_exit_zero_completes(self, bm):
        run_completed = _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 46, "processes_failed": 1,
            "exit_code": 0,
            "failed_tasks": ["FLYE (barcode16)"],
        })
        assert bm.status["pipeline_status"] == "completed"
        assert run_completed is True, "the auto-report must still be generated"

    def test_ignored_failure_is_reported_not_hidden(self, bm):
        _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 46, "processes_failed": 1,
            "exit_code": 0,
            "failed_tasks": ["FLYE (barcode16)"],
        })
        warnings = " ".join(bm.status.get("warnings", []))
        assert "FLYE (barcode16)" in warnings
        assert "isolated" in warnings.lower() or "did not" in warnings.lower()
        # A warning, not an error: the run genuinely completed.
        assert bm.status["errors"] == []

    def test_real_failure_with_nonzero_exit_still_errors(self, bm):
        run_completed = _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 9, "processes_failed": 1,
            "exit_code": 1,
            "failed_tasks": ["CANONICAL_ASSEMBLY_WRITER (LVS_1)"],
        })
        assert bm.status["pipeline_status"] == "error"
        assert run_completed is False
        assert any("failed process" in e for e in bm.status["errors"])

    def test_unknown_exit_code_keeps_conservative_error(self, bm):
        # exit_code absent (older manager state): keep the prior behaviour
        # rather than assuming success.
        run_completed = _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 9, "processes_failed": 1,
        })
        assert bm.status["pipeline_status"] == "error"
        assert run_completed is False

    def test_clean_run_unaffected(self, bm):
        run_completed = _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 47, "processes_failed": 0,
            "exit_code": 0,
        })
        assert bm.status["pipeline_status"] == "completed"
        assert run_completed is True

    def test_explicit_workflow_errors_still_error(self, bm):
        run_completed = _statuses(bm, {
            "running": False, "errors": ["Nextflow exited with code 1"],
            "processes_complete": 5, "processes_failed": 0,
            "exit_code": 1,
        })
        assert bm.status["pipeline_status"] == "error"
        assert run_completed is False

    def test_no_completed_processes_is_startup_crash(self, bm):
        run_completed = _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 0, "processes_failed": 0,
            "exit_code": 1,
        })
        assert bm.status["pipeline_status"] == "error"
        assert run_completed is False


class TestTraceFailedTasks:
    def test_parser_reports_failed_task_labels(self, tmp_path):
        import os
        import time
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        mgr = NextflowManager(str(tmp_path))
        path = os.path.join(mgr.log_dir, "trace.txt")
        with open(path, "w") as fh:
            fh.write("task_id\tname\tstatus\texit\n")
            fh.write("1\tNF:ASSEMBLY:FLYE (barcode16)\tFAILED\t1\n")
            fh.write("2\tNF:ASSEMBLY:FLYE (barcode11)\tCOMPLETED\t0\n")
        old = time.time() - 5
        os.utime(path, (old, old))

        out = mgr._parse_trace_file()
        assert out["processes_failed"] == 1
        assert out["failed_tasks"] == ["FLYE (barcode16)"]


class TestFinalStatusOnDisk:
    """The terminal classification is recorded into .nanometa.run.json.

    Round-3 parity rule: the exported report reads the run's terminal
    status from disk (the export worker cannot see the live backend), so
    a report over a crashed run can refuse the green banner. The write is
    best-effort -- a missing outdir must never fail the classification.
    """

    def _meta(self, bm):
        import json, os
        path = os.path.join(bm.config["results_output_directory"],
                            ".nanometa.run.json")
        with open(path) as f:
            return json.load(f)

    def test_error_run_records_final_status(self, bm, tmp_path):
        (tmp_path / "out").mkdir()
        _statuses(bm, {
            "running": False, "errors": ["Nextflow exited with code 137"],
            "processes_complete": 3, "processes_failed": 0,
            "exit_code": 137,
        })
        meta = self._meta(bm)
        assert meta["final_status"] == "error"
        assert any("137" in e for e in meta["final_errors"])

    def test_completed_run_records_final_status(self, bm, tmp_path):
        (tmp_path / "out").mkdir()
        _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 46, "processes_failed": 0,
            "exit_code": 0,
        })
        assert self._meta(bm)["final_status"] == "completed"

    def test_existing_metadata_keys_survive(self, bm, tmp_path):
        import json
        out = tmp_path / "out"
        out.mkdir()
        (out / ".nanometa.run.json").write_text(
            json.dumps({"fingerprint": "abc", "watchlists": ["bio"]}))
        _statuses(bm, {
            "running": False, "errors": [],
            "processes_complete": 46, "processes_failed": 0,
            "exit_code": 0,
        })
        meta = self._meta(bm)
        assert meta["fingerprint"] == "abc"
        assert meta["watchlists"] == ["bio"]
        assert meta["final_status"] == "completed"

    def test_missing_outdir_never_raises(self, bm):
        _statuses(bm, {
            "running": False, "errors": ["boom"],
            "processes_complete": 0, "processes_failed": 0,
            "exit_code": 1,
        })
        assert bm.status["pipeline_status"] == "error"
