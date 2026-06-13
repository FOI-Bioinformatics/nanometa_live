"""Tests for NextflowManager._parse_trace_file hardening.

The trace parser drives the GUI's pipeline-status display. It must:
- count CACHED tasks (a -resume cache hit is a finished task) as completed,
- not silently drop unrecognised status values (format drift -> log once),
- keep the last-known status (not reset to empty) when the trace header changes.
"""

import os
import time

import pytest

from nanometa_live.core.workflow.nextflow_manager import NextflowManager


def _write_trace(mgr, rows, header="task_id\tname\tstatus\texit"):
    """Write a trace.txt with the given (name, status) rows and back-date it so
    the parser's >=1s file-stability guard does not short-circuit the read."""
    path = os.path.join(mgr.log_dir, "trace.txt")
    lines = [header]
    for name, status in rows:
        lines.append(f"1\t{name}\t{status}\t0")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    old = time.time() - 5
    os.utime(path, (old, old))
    return path


@pytest.fixture
def mgr(tmp_path):
    return NextflowManager(str(tmp_path))


def test_counts_basic_statuses(mgr):
    _write_trace(mgr, [
        ("NF:QC:FASTP (b01)", "COMPLETED"),
        ("NF:CLASS:KRAKEN2 (b01)", "RUNNING"),
        ("NF:VAL:BLASTN (b01)", "FAILED"),
    ])
    res = mgr._parse_trace_file()
    assert res["processes_complete"] == 1
    assert res["processes_running"] == 1
    assert res["processes_failed"] == 1
    assert res["total_processes"] == 3


def test_cached_counts_as_completed(mgr):
    # A -resume run: cache hits must not be dropped (they are finished tasks).
    _write_trace(mgr, [
        ("NF:QC:FASTP (b01)", "CACHED"),
        ("NF:QC:FASTP (b02)", "CACHED"),
        ("NF:CLASS:KRAKEN2 (b01)", "COMPLETED"),
    ])
    res = mgr._parse_trace_file()
    assert res["processes_complete"] == 3, "CACHED tasks must count as completed"
    assert res["processes_failed"] == 0


def test_unknown_status_logged_once_and_not_counted(mgr, caplog):
    _write_trace(mgr, [
        ("NF:QC:FASTP (b01)", "COMPLETED"),
        ("NF:X:Y (b01)", "BIZARRE_NEW_STATUS"),
        ("NF:X:Y (b02)", "BIZARRE_NEW_STATUS"),
    ])
    import logging
    with caplog.at_level(logging.WARNING):
        res = mgr._parse_trace_file()
    # Unknown status is not counted as complete/running/failed.
    assert res["processes_complete"] == 1
    assert res["processes_running"] == 0 and res["processes_failed"] == 0
    # ...but it is surfaced exactly once (drift visibility without per-poll spam).
    warns = [r for r in caplog.records if "unrecognised task status" in r.getMessage()]
    assert len(warns) == 1
    # A second parse does not re-log the same unknown status.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        mgr._parse_trace_file()
    assert not [r for r in caplog.records if "unrecognised task status" in r.getMessage()]


def test_missing_columns_keeps_last_known_and_warns_once(mgr, caplog):
    # First a good trace so there is a last-known status.
    _write_trace(mgr, [("NF:QC:FASTP (b01)", "COMPLETED")])
    good = mgr._parse_trace_file()
    assert good["processes_complete"] == 1
    # Now a trace whose header lacks name/status (format drift).
    _write_trace(mgr, [("x", "y")], header="task_id\twrong\tcols\texit")
    import logging
    with caplog.at_level(logging.WARNING):
        res = mgr._parse_trace_file()
    # Keeps the last-known status rather than resetting the GUI to empty.
    assert res["processes_complete"] == 1
    assert [r for r in caplog.records if "missing required columns" in r.getMessage()]


def test_new_and_pending_are_uncounted(mgr):
    _write_trace(mgr, [
        ("NF:A (b01)", "COMPLETED"),
        ("NF:B (b01)", "NEW"),
        ("NF:C (b01)", "PENDING"),
    ])
    res = mgr._parse_trace_file()
    assert res["processes_complete"] == 1
    assert res["processes_running"] == 0 and res["processes_failed"] == 0
