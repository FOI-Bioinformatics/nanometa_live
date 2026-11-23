"""Launch, Stop and lock state at the edges of a run (audit 2026-11-06).

Findings 6, 8, 12 and 27 plus two items of 37 were races or ordering defects
in ``BackendManager`` / ``NextflowManager``. Each is pinned here with the
timing injected (an inline thread, a patched ``time.sleep``, a workflow
manager that answers "not running") rather than slept on.
"""

import json
import os
import threading
from unittest.mock import MagicMock

import pytest

from nanometa_live.core.workflow import nextflow_manager as nm
from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


class _InlineThread:
    """A ``threading.Thread`` stand-in that runs its target in ``start()``.

    Reproduces the worst ordering of finding 6 deterministically: the launch
    thread finishes before ``start()`` reaches its next statement.
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _fast_failing_manager(tmp_path):
    m = nm.NextflowManager(str(tmp_path))
    m.params_file_path = "/dev/null"
    m.config_file_path = "/dev/null"
    # Offline mode with a missing conda cache fails inside _run_workflow
    # before Popen; the thread's ``finally`` clears the running flags.
    m._run_config = {"offline_mode": True, "nxf_conda_cachedir": str(tmp_path / "nonexistent")}
    m._check_conda_available = lambda: (True, "ok")
    m._sweep_conda_caches = lambda: []
    m._strip_appledouble_files = lambda *a, **k: 0
    return m


class TestFailedLaunchIsNotRunning:
    """Finding 6: a launch that fails before Popen must not stay 'running'."""

    def test_launch_thread_finishing_first_leaves_the_manager_stopped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nm.threading, "Thread", _InlineThread)
        m = _fast_failing_manager(tmp_path)
        ok, _ = m.start(profile="conda")
        assert ok  # the launch itself was accepted; the failure is the thread's
        assert m.running is False
        assert m.status["running"] is False
        assert m.status["errors"], "the failure must be recorded for the monitor"

    def test_previous_run_errors_are_dropped_at_launch(self, tmp_path):
        m = nm.NextflowManager(str(tmp_path))
        m.status["errors"] = ["Nextflow exited with code 1: old run"]
        m.reset_run_artifacts()
        assert m.status["errors"] == []


class _FakeWorkflow:
    """A workflow manager whose pipeline has already exited cleanly."""

    def __init__(self, running=False, processes_complete=5):
        self.status = {
            "running": running, "errors": [], "processes_complete": processes_complete,
            "processes_failed": 0, "exit_code": 0, "failed_tasks": [],
            "nextflow_pid": None,
        }
        self.stop_calls = 0

    def get_status(self):
        return dict(self.status)

    def stop(self):
        self.stop_calls += 1
        if not self.status["running"]:
            return False, "Pipeline is not running"
        self.status["running"] = False
        return True, "stopped"


def _started_backend(tmp_path, workflow, **config):
    outdir = tmp_path / "results"
    outdir.mkdir(exist_ok=True)
    bm = BackendManager(str(tmp_path / "data"))
    bm.workflow_manager = workflow
    bm.config = {"results_output_directory": str(outdir), "auto_report": False,
                 "nanopore_output_directory": str(tmp_path), "processing_mode": "batch",
                 **config}
    assert bm._acquire_lock(str(outdir))[0]
    with bm._status_lock:
        bm._mark_started_locked()
    BackendManager.write_run_metadata(str(outdir), bm.config)
    return bm, outdir


def _run_meta(outdir):
    with open(os.path.join(outdir, BackendManager.RUN_METADATA_FILENAME)) as f:
        return json.load(f)


class TestLateStopKeepsTheRealOutcome:
    """Finding 8: Stop after the pipeline exited must not relabel the run."""

    def test_stop_on_an_exited_pipeline_records_completed(self, tmp_path):
        bm, outdir = _started_backend(tmp_path, _FakeWorkflow(running=False))
        ok, message = bm.stop()
        assert ok
        assert "already finished" in message
        assert bm.status["running"] is False
        assert bm.status["pipeline_status"] == "completed"
        assert bm._stop_intent is None
        assert bm._lock_fd is None
        meta = _run_meta(outdir)
        assert meta["final_status"] == "completed"
        assert "stop_reason" not in meta

    def test_monitor_pass_after_a_late_stop_agrees(self, tmp_path):
        bm, _ = _started_backend(tmp_path, _FakeWorkflow(running=False))
        bm.stop()
        with bm._status_lock:
            bm._apply_terminal_workflow_status(bm.workflow_manager.get_status())
        assert bm.status["pipeline_status"] == "completed"
        assert bm.status.get("stop_reason") is None

    def test_pipeline_exiting_during_the_stop_call_is_classified(self, tmp_path):
        wf = _FakeWorkflow(running=True)

        def _exit_meanwhile():
            wf.status["running"] = False
            return False, "Pipeline is not running"
        wf.stop = _exit_meanwhile
        bm, _ = _started_backend(tmp_path, wf)
        ok, _ = bm.stop()
        assert ok
        assert bm.status["pipeline_status"] == "completed"
        assert bm._stop_intent is None

    def test_failed_stop_of_a_live_pipeline_keeps_the_lock(self, tmp_path):
        wf = _FakeWorkflow(running=True)
        wf.stop = lambda: (False, "Stop error: EPERM")
        bm, outdir = _started_backend(tmp_path, wf)
        ok, message = bm.stop()
        assert not ok and "EPERM" in message
        assert bm.status["running"] is True
        assert bm._lock_fd is not None, "the pipeline may be alive; its lock stays"
        assert os.path.exists(outdir / ".nanometa.lock")
        assert bm._stop_intent is None, "nothing was stopped"
        bm._release_lock()

    def test_a_real_stop_still_records_operator(self, tmp_path):
        bm, outdir = _started_backend(tmp_path, _FakeWorkflow(running=True))
        ok, _ = bm.stop()
        assert ok
        assert bm.status["pipeline_status"] == "stopped"
        assert _run_meta(outdir)["stop_reason"] == "operator"


class TestMonitorReleasesOnlyItsOwnLock:
    """Finding 12: run 1's monitor must never release run 2's lock."""

    def test_lock_taken_during_the_final_sleep_survives(self, tmp_path, monkeypatch):
        bm, outdir = _started_backend(tmp_path, _FakeWorkflow(running=False))
        seen = {}

        def _sleep(_seconds):
            # Inside the monitor's sleep after it classified run 1: the lock
            # must already be gone, and run 2 takes a new one.
            seen["fd_during_sleep"] = bm._lock_fd
            bm._release_lock()
            assert bm._acquire_lock(str(outdir))[0]
        monkeypatch.setattr("nanometa_live.core.workflow.backend_manager.time.sleep", _sleep)

        bm._monitor_status()

        assert seen["fd_during_sleep"] is None, "released under the lock, before the sleep"
        assert bm._lock_fd is not None, "run 2's lock must still be held"
        assert os.path.exists(outdir / ".nanometa.lock")
        bm._release_lock()

    def test_generation_guarded_release_is_a_noop_for_a_newer_lock(self, tmp_path):
        bm, outdir = _started_backend(tmp_path, _FakeWorkflow())
        old_generation = bm._lock_generation
        bm._release_lock()
        assert bm._acquire_lock(str(outdir))[0]
        bm._release_lock(old_generation)
        assert bm._lock_fd is not None
        bm._release_lock(bm._lock_generation)
        assert bm._lock_fd is None

    def test_monitor_loop_stops_when_a_newer_run_starts(self, tmp_path, monkeypatch):
        wf = _FakeWorkflow(running=True)
        bm, outdir = _started_backend(tmp_path, wf)
        polls = []

        def _sleep(_seconds):
            polls.append(1)
            # Run 2 begins: new lock generation, status running again.
            with bm._status_lock:
                bm._lock_generation += 1
            if len(polls) > 3:
                raise AssertionError("the old monitor kept polling for run 2")
        monkeypatch.setattr("nanometa_live.core.workflow.backend_manager.time.sleep", _sleep)
        bm._monitor_status()
        assert len(polls) == 1
        bm._release_lock()

    def test_start_joins_a_finished_monitor_thread(self, tmp_path):
        bm = BackendManager(str(tmp_path / "data"))
        done = threading.Event()
        bm.status_thread = threading.Thread(target=done.wait, daemon=True)
        bm.status_thread.start()
        done.set()
        bm._join_previous_monitor(timeout=2.0)
        assert not bm.status_thread.is_alive()


class TestProcessExists:
    """Finding 27: a PID we may not signal is alive, not stale."""

    def test_permission_error_means_alive(self, monkeypatch):
        def _kill(pid, sig):
            raise PermissionError
        monkeypatch.setattr(os, "kill", _kill)
        assert BackendManager._process_exists(4242) is True

    def test_lookup_error_means_dead(self, monkeypatch):
        def _kill(pid, sig):
            raise ProcessLookupError
        monkeypatch.setattr(os, "kill", _kill)
        assert BackendManager._process_exists(4242) is False


class TestLockFilePathOrdering:
    """Finding 37: a refused acquire must not adopt the holder's lock path."""

    def test_refused_acquire_leaves_the_holders_file_alone(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        holder = BackendManager(str(tmp_path / "a"))
        other = BackendManager(str(tmp_path / "b"))
        assert holder._acquire_lock(str(results))[0]
        ok, _ = other._acquire_lock(str(results))
        assert not ok
        assert other._lock_file_path is None
        other._release_lock()
        assert os.path.exists(results / ".nanometa.lock"), "the holder's lock survives"
        holder._release_lock()


class TestFinalStatusOutdir:
    """Finding 37: the final status lands where the start record was written."""

    def test_main_dir_only_config_records_final_status(self, tmp_path):
        outdir = tmp_path / "main"
        outdir.mkdir()
        bm = BackendManager(str(tmp_path / "data"))
        bm.workflow_manager = MagicMock()
        bm.config = {"main_dir": str(outdir), "auto_report": False}
        BackendManager.write_run_metadata(bm._run_outdir(), bm.config)
        bm.status["running"] = True
        with bm._status_lock:
            bm._apply_terminal_workflow_status({
                "running": False, "errors": [], "processes_complete": 2,
                "processes_failed": 0, "exit_code": 0,
            })
        assert _run_meta(outdir)["final_status"] == "completed"
