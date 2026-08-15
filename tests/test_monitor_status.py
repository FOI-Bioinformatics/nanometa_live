"""The realtime inactivity stop in ``BackendManager._monitor_status``.

This monitor thread is the only place in the GUI that can SIGTERM a running
pipeline on its own initiative. Reading its clock as a wall-clock cap once
killed a live run mid-flight while hundreds of validation tasks were still
pending (nanometanf issue #29): the downstream results were truncated and the
operator saw a "stopped" run with no explanation beyond a timeout message.

Three guards, all interacting, decide whether the stop fires. Each is pinned
here because each failed-open would resurrect that incident:

1. ``processing_mode == "realtime"`` -- the config validator defaults
   ``realtime_timeout_minutes`` to 60 for every mode, so without this guard a
   batch run is killed at 60 minutes.
2. ``running_now > 0 or finished_count != last_finished_count`` -- either
   signal resets the inactivity clock. A pipeline still completing tasks, or
   sitting in one long task, is not idle.
3. ``pipeline_has_worked`` -- the timeout is deferred until at least one task
   has run or completed. A fresh run's conda-environment build produces no
   task activity for tens of minutes and would otherwise be read as inactivity
   before a single process has started.

The timeout is therefore an INACTIVITY stop measured from the last progress
signal, not from ``start_time``.

The monitor does no file I/O of its own beyond ``_update_file_counts`` (a
no-op with no configured input directory), so the tests drive it with a
scripted ``workflow_manager.get_status()`` and a fake clock substituted for
the module-level ``time``. Nothing sleeps; the fake clock's ``sleep`` advances
the clock and raises a ``BaseException`` sentinel to leave the otherwise
unbounded loop -- ``BaseException`` because the loop's per-cycle
``except Exception`` guard would swallow anything narrower and spin forever.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanometa_live.core.workflow import backend_manager as bm_module
from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


class _LoopExhausted(BaseException):
    """Sentinel used to leave the monitor loop when it will not stop itself.

    Derives from ``BaseException`` so the monitor's broad per-cycle
    ``except Exception`` cannot catch it.
    """


class FakeClock:
    """Stand-in for the ``time`` module as seen from ``backend_manager``."""

    def __init__(self, tick_seconds: float, max_ticks: int = 200):
        self.now = 1_000_000.0
        self.tick_seconds = tick_seconds
        self.max_ticks = max_ticks
        self.ticks = 0

    def time(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.ticks += 1
        if self.ticks > self.max_ticks:
            raise _LoopExhausted
        self.now += self.tick_seconds


def status(running=True, complete=0, failed=0, processes_running=0, errors=None):
    """One scripted ``NextflowManager.get_status()`` return value."""
    return {
        "running": running,
        "processes_running": processes_running,
        "processes_complete": complete,
        "processes_failed": failed,
        "files_processed": 0,
        "current_batch": 0,
        "errors": errors or [],
    }


def make_manager(tmp_path, mode: str, timeout_minutes=10):
    """A BackendManager wired to a mock workflow manager, already 'running'."""
    manager = BackendManager(str(tmp_path / "data"))
    manager.config = {
        "processing_mode": mode,
        "realtime_timeout_minutes": timeout_minutes,
        # No nanopore_output_directory: _update_file_counts stays a no-op.
    }
    manager.workflow_manager = MagicMock()
    manager.status["running"] = True
    manager.status["pipeline_status"] = "running"
    return manager


def run_monitor(manager, monkeypatch, statuses, tick_seconds, max_ticks=200):
    """Drive ``_monitor_status`` over a scripted status sequence.

    The last entry repeats indefinitely, so a test states only the interesting
    prefix. Returns the FakeClock so callers can assert on elapsed time.
    """
    clock = FakeClock(tick_seconds=tick_seconds, max_ticks=max_ticks)
    monkeypatch.setattr(bm_module, "time", clock)

    def next_status(*_args, **_kwargs):
        idx = min(next_status.calls, len(statuses) - 1)
        next_status.calls += 1
        return statuses[idx]

    next_status.calls = 0
    manager.workflow_manager.get_status.side_effect = next_status

    try:
        manager._monitor_status()
    except _LoopExhausted:
        pass
    return clock


class TestBatchModeIsNeverAutoStopped:
    """Guard 1 -- the nanometanf issue #29 regression, exactly."""

    def test_batch_mode_idle_far_past_timeout_does_not_stop_pipeline(
        self, tmp_path, monkeypatch
    ):
        manager = make_manager(tmp_path, mode="batch", timeout_minutes=10)
        # One task ran, then total silence for ~100 minutes -- ten timeout
        # windows. A batch run has no inactivity stop at all.
        statuses = [status(processes_running=1), status(complete=1)]
        clock = run_monitor(
            manager, monkeypatch, statuses, tick_seconds=60.0, max_ticks=100
        )

        assert clock.now - 1_000_000.0 >= 10 * 10 * 60, (
            "test setup: the run must idle well past the configured timeout"
        )
        assert not manager.workflow_manager.stop.called, (
            "a batch run was SIGTERM'd on inactivity -- issue #29: "
            "realtime_timeout_minutes defaults to 60 in every mode, so the "
            "processing_mode guard is the only thing keeping a long batch "
            "run alive"
        )
        assert manager.status["running"] is True, (
            "batch run marked not-running by the realtime inactivity timeout"
        )
        assert manager.status["errors"] == [], (
            "batch run had a timeout error appended to its status"
        )


class TestRunningTasksAreNotInactivity:
    """Guard 2a -- a long-running task keeps the run alive."""

    def test_processes_running_past_timeout_does_not_stop_pipeline(
        self, tmp_path, monkeypatch
    ):
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        # A single task occupies the whole run: nothing ever completes, so
        # finished_count never advances -- only processes_running says so.
        statuses = [status(processes_running=1, complete=0)]
        clock = run_monitor(
            manager, monkeypatch, statuses, tick_seconds=60.0, max_ticks=60
        )

        assert clock.now - 1_000_000.0 >= 6 * 10 * 60, (
            "test setup: the run must last well past the configured timeout"
        )
        assert not manager.workflow_manager.stop.called, (
            "a run with a task actively executing was stopped as idle -- a "
            "single long task (kraken2 on a large DB, a BLAST batch) would be "
            "killed mid-flight and its results truncated"
        )
        assert manager.status["running"] is True


class TestProgressResetsTheInactivityClock:
    """Guard 2b -- an advancing finished count is progress."""

    def test_advancing_finished_count_survives_past_one_timeout_window(
        self, tmp_path, monkeypatch
    ):
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        # Slow but progressing: one task completes every poll, and every poll
        # is 5 minutes apart -- half a timeout window. Cumulative elapsed time
        # crosses several windows; time since the last completion never does.
        # The first poll catches a task mid-execution purely to arm
        # pipeline_has_worked, so this test isolates the finished-count half
        # of the progress signal -- every later poll reports nothing running.
        statuses = [status(processes_running=1, complete=0)] + [
            status(processes_running=0, complete=n) for n in range(1, 13)
        ]
        clock = run_monitor(
            manager, monkeypatch, statuses, tick_seconds=300.0, max_ticks=12
        )

        assert clock.now - 1_000_000.0 >= 2 * 10 * 60, (
            "test setup: total elapsed must exceed the timeout, so only an "
            "inactivity-based reading of the clock can keep the run alive"
        )
        assert not manager.workflow_manager.stop.called, (
            "a slow-but-progressing run was stopped -- the timeout was read "
            "as a wall-clock cap from start_time instead of as time since "
            "the last completed task"
        )
        assert manager.status["running"] is True

    def test_failed_tasks_also_count_as_progress(self, tmp_path, monkeypatch):
        """finished_count is complete + failed; a failing-but-moving run is alive."""
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        statuses = [status(processes_running=1, complete=0)] + [
            status(processes_running=0, complete=0, failed=n)
            for n in range(1, 13)
        ]
        run_monitor(
            manager, monkeypatch, statuses, tick_seconds=300.0, max_ticks=12
        )

        assert not manager.workflow_manager.stop.called, (
            "retrying/failing tasks are still task activity; stopping here "
            "would kill a run that is draining its retry budget"
        )


class TestColdStartIsNotInactivity:
    """Guard 3 -- nothing has run yet because the conda env is still building."""

    def test_no_activity_from_t0_does_not_stop_pipeline(
        self, tmp_path, monkeypatch
    ):
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        # Zero across the board for ~100 minutes: the env-build window of a
        # fresh run. pipeline_has_worked is still False, so the timeout is
        # deferred rather than measured from t=0.
        statuses = [status(processes_running=0, complete=0, failed=0)]
        clock = run_monitor(
            manager, monkeypatch, statuses, tick_seconds=60.0, max_ticks=100
        )

        assert clock.now - 1_000_000.0 >= 10 * 10 * 60, (
            "test setup: the quiet window must exceed the configured timeout"
        )
        assert not manager.workflow_manager.stop.called, (
            "a cold-start run was stopped before any task had run -- a conda "
            "environment build takes tens of minutes and produces no task "
            "activity, so the run dies before it can start"
        )
        assert manager.status["running"] is True


class TestGenuineStallIsStopped:
    """The stop the timeout exists for: work happened, then nothing did."""

    def test_activity_then_silence_past_timeout_stops_and_releases(
        self, tmp_path, monkeypatch
    ):
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        # Two tasks complete, then the finished count freezes with nothing
        # running: a genuinely stalled realtime run.
        statuses = [
            status(processes_running=1, complete=1),
            status(processes_running=0, complete=2),
            status(processes_running=0, complete=2),
        ]
        run_monitor(
            manager, monkeypatch, statuses, tick_seconds=60.0, max_ticks=60
        )

        assert manager.workflow_manager.stop.call_count == 1, (
            "a stalled realtime run was never stopped -- the watchPath stream "
            "stays open and the operator's run hangs indefinitely"
        )
        assert manager.status["running"] is False
        assert manager.status["pipeline_status"] == "stopped"
        assert any("inactivity timeout" in e for e in manager.status["errors"]), (
            "the operator must be told why the run stopped; a bare 'stopped' "
            "status is indistinguishable from a manual stop"
        )
        # The monitor thread owns the results-directory lock while it lives.
        assert manager._lock_fd is None and manager._lock_file_path is None, (
            "the lock was not released on timeout exit, so the next run is "
            "refused with 'another instance is using this directory'"
        )

    def test_stop_failure_does_not_leave_the_run_marked_running(
        self, tmp_path, monkeypatch
    ):
        """A stop() that raises must still leave the state machine consistent."""
        manager = make_manager(tmp_path, mode="realtime", timeout_minutes=10)
        manager.workflow_manager.stop.side_effect = OSError("no such process")
        statuses = [
            status(processes_running=1, complete=1),
            status(processes_running=0, complete=1),
        ]
        run_monitor(
            manager, monkeypatch, statuses, tick_seconds=60.0, max_ticks=60
        )

        assert manager.status["running"] is False, (
            "a failed stop() left the GUI believing the pipeline still runs"
        )
        assert manager._lock_fd is None
