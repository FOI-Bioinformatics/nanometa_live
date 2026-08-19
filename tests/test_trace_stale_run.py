"""A new run must not report the previous run's process counts.

Found while launching a real run against a second database (2026-08-18).
Nextflow's trace file is an output artifact that lives at a fixed path
(<data_dir>/logs/trace.txt) and is only replaced once the new run starts
emitting tasks. Until then the monitor thread reads the PREVIOUS run's
completed trace -- which is stable and old, so the "file is being written"
guard does not catch it -- and the dashboard shows that run's totals,
including its failures, attributed to the run just started.

Observed live: starting a run showed "46 processes complete, 1 failed"
(the prior run's numbers) for roughly a minute before self-correcting.
That is the same class as the loader-cache and output-collision bleeds
already guarded elsewhere: a fresh run must never present an earlier run's
result as its own.
"""

import os
import time

import pytest

from nanometa_live.core.workflow.nextflow_manager import NextflowManager

pytestmark = pytest.mark.unit


def _write_stale_trace(mgr, rows):
    path = os.path.join(mgr.log_dir, "trace.txt")
    os.makedirs(mgr.log_dir, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("task_id\tname\tstatus\texit\n")
        for i, (name, status) in enumerate(rows):
            fh.write(f"{i}\t{name}\t{status}\t0\n")
    old = time.time() - 600  # a previous run: long since written
    os.utime(path, (old, old))
    return path


class TestStaleTraceCleared:
    def test_previous_trace_is_removed_at_launch(self, tmp_path):
        mgr = NextflowManager(str(tmp_path))
        path = _write_stale_trace(mgr, [
            ("NF:QC:CHOPPER (b01)", "COMPLETED"),
            ("NF:ASSEMBLY:FLYE (b16)", "FAILED"),
        ])
        assert os.path.exists(path)

        mgr.reset_run_artifacts()

        assert not os.path.exists(path), (
            "the previous run's trace must not survive into a new run")

    def test_parser_reports_nothing_after_reset(self, tmp_path):
        mgr = NextflowManager(str(tmp_path))
        _write_stale_trace(mgr, [
            ("NF:QC:CHOPPER (b01)", "COMPLETED"),
            ("NF:ASSEMBLY:FLYE (b16)", "FAILED"),
        ])
        # Prime the in-memory fallback the way a real poll would.
        primed = mgr._parse_trace_file()
        assert primed["processes_complete"] == 1
        assert primed["processes_failed"] == 1

        mgr.reset_run_artifacts()

        after = mgr._parse_trace_file()
        assert after.get("processes_complete", 0) == 0
        assert after.get("processes_failed", 0) == 0, (
            "a cleared trace must not fall back to the previous run's counts")

    def test_status_counters_are_zeroed(self, tmp_path):
        mgr = NextflowManager(str(tmp_path))
        mgr.status["processes_complete"] = 46
        mgr.status["processes_failed"] = 1
        mgr.status["exit_code"] = 1
        mgr.status["failed_tasks"] = ["FLYE (b16)"]

        mgr.reset_run_artifacts()

        assert mgr.status["processes_complete"] == 0
        assert mgr.status["processes_failed"] == 0
        assert mgr.status["exit_code"] is None
        assert mgr.status["failed_tasks"] == []

    def test_missing_trace_is_not_an_error(self, tmp_path):
        mgr = NextflowManager(str(tmp_path))
        mgr.reset_run_artifacts()  # nothing to remove
        assert mgr._parse_trace_file() == {}
