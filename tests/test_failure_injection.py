"""What the dashboard does when the world breaks underneath it.

The suite tests the happy path and a handful of mocked ``OSError``s. It does
not test the three things most likely to actually happen to a field laptop
part-way through a run:

1. The pipeline process dies without warning -- SIGKILL from the OOM killer,
   or an operator force-quitting a terminal.
2. A Kraken2 report is read while the pipeline is still writing it, so the
   loader sees a truncated file.
3. The Kraken2 database goes away between polls, because it lives on a USB
   drive that was unplugged or a network mount that dropped.

All three are recoverable if reported and dangerous if not. The failure that
matters in each case is the SILENT one: a dashboard that keeps saying
"running" over a dead pipeline, or renders a partial report as though it were
the whole picture, tells the operator something false about a biological
sample.

These use real processes and real files rather than mocks, because the
behaviour under test IS the interaction with the operating system -- a mocked
``poll()`` returning -9 proves only that the mock was configured correctly.
"""

from __future__ import annotations

import os
import pathlib
import signal
import threading
import time

import pytest

from nanometa_live.core.utils.kraken_utils import check_kraken_db
from nanometa_live.core.workflow.nextflow_manager import NextflowManager

pytestmark = pytest.mark.integration

#: Bound on how long a status flip may take. The monitor thread polls at 5 s,
#: but the flip under test comes from the run thread's ``finally``, which
#: fires as soon as ``wait()`` returns. Ten seconds is generous.
STATUS_DEADLINE = 10.0


def _wait_until(predicate, deadline=STATUS_DEADLINE, interval=0.05):
    """Poll until predicate holds. Returns True if it did, within deadline."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def manager(tmp_path) -> NextflowManager:
    for sub in ("logs", "work"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return NextflowManager(str(tmp_path))


class TestPipelineProcessKilled:
    """Scenario 1: the pipeline dies without getting to say so.

    Uses a real ``sleep`` subprocess driven through the real ``_run_workflow``
    path, then sends a real SIGKILL. ``_run_workflow`` takes the command as an
    argument, so this needs no patching of Popen -- the process lifecycle under
    test is genuine.
    """

    def _start(self, manager, seconds=60):
        thread = threading.Thread(
            target=manager._run_workflow,
            args=(["sleep", str(seconds)],),
            daemon=True,
        )
        manager.running = True
        manager.status["running"] = True
        thread.start()
        assert _wait_until(lambda: manager.process is not None, deadline=5.0), (
            "the subprocess never started"
        )
        return thread

    def test_status_stops_reporting_running_after_a_sigkill(self, manager):
        """The core property. A dashboard stuck on "running" over a dead
        pipeline is the failure an operator cannot detect for themselves."""
        thread = self._start(manager)
        os.kill(manager.process.pid, signal.SIGKILL)

        flipped = _wait_until(lambda: manager.get_status().get("running") is False)
        thread.join(timeout=STATUS_DEADLINE)

        assert flipped, (
            f"{STATUS_DEADLINE}s after the pipeline process was killed, "
            f"get_status() still reports running=True. The dashboard would "
            f"keep showing an active run over a dead pipeline indefinitely."
        )

    def test_the_kill_is_recorded_as_an_error_not_a_clean_finish(self, manager):
        """A killed run must be distinguishable from a completed one.

        Both end with running=False. Only the error list tells the operator
        their results are incomplete rather than final.
        """
        thread = self._start(manager)
        os.kill(manager.process.pid, signal.SIGKILL)
        _wait_until(lambda: manager.get_status().get("running") is False)
        thread.join(timeout=STATUS_DEADLINE)

        errors = manager.get_status().get("errors") or []
        assert errors, (
            "a SIGKILLed pipeline recorded no error, so it is indistinguishable "
            "from a clean completion; the operator would treat truncated "
            "results as the final answer"
        )

    def test_a_user_requested_stop_is_not_reported_as_an_error(self, manager):
        """The contrast, so the check above cannot pass by flagging everything.

        Stopping a run deliberately is not a fault and must not be reported as
        one, or the error indicator becomes noise the operator learns to skip.
        """
        thread = self._start(manager)
        manager._user_stopped = True
        os.kill(manager.process.pid, signal.SIGTERM)
        _wait_until(lambda: manager.get_status().get("running") is False)
        thread.join(timeout=STATUS_DEADLINE)

        assert manager.get_status().get("running") is False
        assert not (manager.get_status().get("errors") or []), (
            "a user-initiated stop was recorded as a pipeline error"
        )

    def test_the_execution_lock_is_released_so_a_rerun_is_possible(self, manager):
        """A stuck lock bricks the next run, which on a field laptop means the
        operator cannot restart without knowing to kill the app."""
        thread = self._start(manager)
        os.kill(manager.process.pid, signal.SIGKILL)
        _wait_until(lambda: manager.get_status().get("running") is False)
        thread.join(timeout=STATUS_DEADLINE)

        acquired = manager.execution_lock.acquire(timeout=2.0)
        if acquired:
            manager.execution_lock.release()
        assert acquired, (
            "the execution lock was still held after the pipeline died; the "
            "next run attempt would block forever"
        )


VALID_REPORT = (
    "100.00\t34120\t0\tR\t1\troot\n"
    " 99.93\t34096\t20\tS\t263\t  Francisella tularensis\n"
    "  0.01\t     4\t4\tS\t3988\t  Ricinus communis\n"
)


class TestTruncatedKrakenReport:
    """Scenario 2: reading a report the pipeline is still writing.

    Exercises the PRODUCTION parser, ``classification_loaders``, not the
    reader in tests/realdata -- the point is what the dashboard does, and a
    test of the test helper would prove nothing about that.

    A partial read is not itself a bug: the loader may reject the file or
    return what is genuinely there. What it must not do is crash the poll or
    produce a row whose numbers are wrong, because a taxon with a fabricated
    read count is indistinguishable downstream from a real detection.

    ``check_stability=False`` is used throughout. The production default waits
    to see whether the file is still growing, which is the right behaviour for
    a live poll but makes a deterministic test of parse behaviour impossible;
    the stability gate is covered separately below.
    """

    @pytest.fixture
    def report(self, tmp_path) -> pathlib.Path:
        path = tmp_path / "barcode11.kraken2.report.txt"
        path.write_text(VALID_REPORT)
        return path

    def _parse(self, path):
        from nanometa_live.core.utils.classification_loaders import (
            _parse_kraken2_report,
        )

        return _parse_kraken2_report(str(path), check_stability=False)

    def test_a_complete_report_parses(self, report):
        """Baseline, so a truncation test cannot pass by parsing nothing."""
        df = self._parse(report)
        assert df is not None and not df.empty
        assert int(df.loc[df["taxid"] == 263, "cumul_reads"].iloc[0]) == 34096

    def test_an_incomplete_trailing_line_is_dropped(self, report):
        """The realistic shape: the writer stopped part-way through a line.

        Measured behaviour: the two complete records survive and the partial
        third is discarded, which is exactly right -- the operator sees fewer
        taxa for one poll rather than a fabricated one.
        """
        report.write_text(VALID_REPORT[: len(VALID_REPORT) - 30])
        df = self._parse(report)
        assert df is not None and not df.empty
        assert set(df["taxid"]) == {1, 263}, (
            f"expected the two complete records and no partial third, got "
            f"taxids {sorted(df['taxid'])}"
        )

    def test_a_truncated_line_does_not_become_a_wrong_read_count(self, report):
        """The dangerous case, stated as the property that matters.

        If a half-written line survives into the frame, it must not carry a
        read count that differs from what the file actually says. A fabricated
        count for a select agent is the worst possible outcome here.
        """
        truncated = VALID_REPORT[: VALID_REPORT.index("Francisella") + 6]
        report.write_text(truncated)
        df = self._parse(report)

        if df is None or df.empty:
            return  # rejecting the file outright is a valid response
        rows = df.loc[df["taxid"] == 263]
        if not rows.empty:
            assert int(rows["cumul_reads"].iloc[0]) == 34096, (
                f"the truncated line yielded cumul_reads="
                f"{int(rows['cumul_reads'].iloc[0])}, which is not what the "
                f"file contains; a partial record is being read as complete"
            )

    def test_an_empty_file_does_not_raise(self, report):
        """The pipeline creates the file before writing to it."""
        report.write_text("")
        df = self._parse(report)
        assert df is None or df.empty

    def test_a_fragment_of_the_root_line_is_rejected_outright(self, report):
        """Measured behaviour: too few columns, so the file is refused.

        Asserted as rejection rather than as "no root row", because a frame
        with the right columns and the wrong numbers is the outcome that would
        put a made-up total on the sequences-analyzed tile.
        """
        report.write_text("100.00\t341")
        assert self._parse(report) is None, (
            "a two-column fragment was accepted as a parseable report"
        )

    def test_a_file_still_being_written_is_rejected_by_the_stability_gate(
        self, report
    ):
        """The production default exists precisely for this scenario.

        Simulates an active writer by touching the file's mtime forward, which
        is what the gate looks for. With check_stability=True the loader should
        decline rather than parse a moving target.
        """
        from nanometa_live.core.utils.loader_utils import _is_file_stable

        os.utime(report, (time.time() + 5, time.time() + 5))
        assert _is_file_stable(str(report)) is False, (
            "a file whose mtime is in the future was judged stable; a report "
            "still being written would be parsed mid-write"
        )

    def test_a_settled_file_passes_the_stability_gate(self, report):
        """The contrast: the gate must not reject everything."""
        from nanometa_live.core.utils.loader_utils import _is_file_stable

        os.utime(report, (time.time() - 60, time.time() - 60))
        assert _is_file_stable(str(report)) is True


class TestDatabaseDisappearsBetweenPolls:
    """Scenario 3: the USB drive holding the Kraken2 database is unplugged.

    Genuinely common in the field and never tested. The requirement is a clear
    report of what is missing -- an operator who can plug the drive back in
    only needs to be told that is the problem.
    """

    @pytest.fixture
    def database(self, tmp_path) -> pathlib.Path:
        from nanometa_live.core.utils.kraken_utils import KRAKEN_REQUIRED_FILES

        db = tmp_path / "kraken_db"
        db.mkdir()
        for name in KRAKEN_REQUIRED_FILES:
            (db / name).write_bytes(b"\x00" * 16)
        return db

    def test_a_present_database_validates(self, database):
        """Baseline for the removal cases below."""
        ok, missing = check_kraken_db(str(database))
        assert ok, f"a complete database was rejected, missing={missing}"

    def test_removal_is_reported_not_raised(self, database):
        """The unplugged-drive case. It must be a verdict, not a traceback."""
        import shutil

        shutil.rmtree(database)
        ok, missing = check_kraken_db(str(database))
        assert ok is False
        assert missing, "the database vanished but nothing was reported missing"

    def test_a_partially_readable_database_is_rejected(self, database):
        """A drive can go away mid-read, leaving some files visible.

        Accepting this would start a run that fails later, deep in Kraken2,
        with an error the operator cannot map back to the unplugged drive.
        """
        (database / "hash.k2d").unlink()
        ok, missing = check_kraken_db(str(database))
        assert ok is False
        assert any("hash.k2d" in m for m in missing), (
            f"hash.k2d was removed but the report does not name it: {missing}"
        )

    def test_the_check_names_every_missing_file(self, database):
        """One round trip to the drive bay, not one per missing file."""
        from nanometa_live.core.utils.kraken_utils import KRAKEN_REQUIRED_FILES

        for name in list(KRAKEN_REQUIRED_FILES)[:2]:
            (database / name).unlink()
        ok, missing = check_kraken_db(str(database))
        assert ok is False
        assert len(missing) >= 2, (
            f"two files were removed but only {missing} was reported; the "
            f"operator would fix one and hit the next failure immediately"
        )

    def test_a_path_that_was_never_a_database_is_reported_the_same_way(
        self, tmp_path
    ):
        """Misconfiguration and a vanished drive should both be legible."""
        ok, missing = check_kraken_db(str(tmp_path / "never-existed"))
        assert ok is False
        assert missing
