"""Field audit 2026-10-28, M2 and M3.

M3: ENOSPC inside a pipeline tool exits 1, which error isolation absorbs,
so a run on a full disk ended COMPLETE over truncated reports and nothing
on screen said why. The backend now polls free space on the results volume
each tick and the header and verdict carry it.

M2: a run that exited 0 without running a task (a real-time timer that
fired before any file arrived) was classified "terminated unexpectedly"
and rendered PIPELINE ERROR; and the final trace was never re-read after
Nextflow exited, so tasks finishing in the last poll window were not
counted.
"""

import os
import time
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils import disk_space
from nanometa_live.app.callbacks.status import _completion_note, _disk_note

pytestmark = pytest.mark.unit


class TestDiskSpacePolledByTheBackend:
    def _manager(self, tmp_path):
        m = BackendManager(str(tmp_path / "data"))
        inbox = tmp_path / "inbox"; inbox.mkdir()
        results = tmp_path / "results"; results.mkdir()
        m.config = {"nanopore_output_directory": str(inbox),
                    "results_output_directory": str(results),
                    "sample_handling": "per_file"}
        m._file_count_cached_at = 0.0
        return m

    def test_low_space_is_flagged(self, tmp_path):
        m = self._manager(tmp_path)
        with patch.object(disk_space, "free_gb", return_value=1.25):
            m._update_file_counts()
        assert m.status["disk_free_gb"] == 1.2
        assert "1.2 GB free" in m.status["disk_low"]
        assert "truncated" in m.status["disk_low"]

    def test_ample_space_is_clean(self, tmp_path):
        m = self._manager(tmp_path)
        with patch.object(disk_space, "free_gb", return_value=120.0):
            m._update_file_counts()
        assert m.status["disk_low"] is None
        assert m.status["disk_free_gb"] == 120.0

    def test_unknown_space_is_not_an_alarm(self, tmp_path):
        m = self._manager(tmp_path)
        with patch.object(disk_space, "free_gb", return_value=None):
            m._update_file_counts()
        assert m.status["disk_low"] is None
        assert m.status["disk_free_gb"] is None

    def test_header_notes(self):
        assert _disk_note({"disk_low": "only 1 GB free"}) == " -- only 1 GB free"
        assert _disk_note({}) == ""
        assert _completion_note({"completion_note": "no task ran"}) == " -- no task ran"

    def test_floor_is_shared_with_readiness(self):
        from nanometa_live.core.workflow import readiness_checker as rc
        import inspect
        src = inspect.getsource(rc.ReadinessChecker._check_disk_space)
        assert "LOW_DISK_FLOOR_GB" in src


class TestFreeGb:
    def test_nearest_existing_parent(self, tmp_path):
        gb = disk_space.free_gb(str(tmp_path / "not" / "yet" / "created"))
        assert gb is not None and gb >= 0

    def test_none_for_nothing(self):
        assert disk_space.free_gb("") is None
        assert disk_space.free_gb(None) is None


class TestCleanExitWithoutTasks:
    def test_exit_zero_with_no_task_is_completed_with_a_note(self, tmp_path):
        m = BackendManager(str(tmp_path / "data"))
        m.config = {"results_output_directory": str(tmp_path / "results")}
        (tmp_path / "results").mkdir()
        m.status["running"] = True
        done = m._apply_terminal_workflow_status({
            "running": False, "exit_code": 0, "processes_complete": 0,
            "processes_failed": 0, "errors": [], "failed_tasks": [],
        })
        assert done is True
        assert m.status["pipeline_status"] == "completed"
        assert "no task ran" in m.status["completion_note"]

    def test_crash_without_exit_code_is_still_an_error(self, tmp_path):
        m = BackendManager(str(tmp_path / "data"))
        m.config = {"results_output_directory": str(tmp_path / "results")}
        (tmp_path / "results").mkdir()
        m.status["running"] = True
        done = m._apply_terminal_workflow_status({
            "running": False, "exit_code": 1, "processes_complete": 0,
            "processes_failed": 0, "errors": [], "failed_tasks": [],
        })
        assert done is False
        assert m.status["pipeline_status"] == "error"
