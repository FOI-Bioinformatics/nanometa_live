"""A pipeline outlives the GUI; the lock must know (field audit 2026-10-28, H3).

Nextflow is launched in its own session and survives a GUI crash. The lock
recorded only the GUI's PID, so the next launch read a dead GUI, called the
lock stale, and started a second pipeline into the same outdir and work
dir. The lock now records the pipeline's PID once known; while that
process lives the folder is busy, whoever started it.
"""

import json
import os
import subprocess
import sys

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


@pytest.fixture
def live_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    proc.kill()
    proc.wait()


DEAD_PID = 2_147_483_646


class TestLockRecordsThePipeline:
    def test_nextflow_pid_is_written_once_known(self, tmp_path):
        m = BackendManager(str(tmp_path / "d"))
        results = tmp_path / "results"; results.mkdir()
        assert m._acquire_lock(str(results))[0]
        m._record_nextflow_pid(4242)
        info = json.loads((results / ".nanometa.lock").read_text())
        assert info["pid"] == os.getpid()
        assert info["nextflow_pid"] == 4242
        assert info["nextflow_started_at"]
        m._release_lock()

    def test_live_pipeline_from_a_dead_gui_refuses_the_folder(self, tmp_path, live_process):
        results = tmp_path / "results"; results.mkdir()
        (results / ".nanometa.lock").write_text(json.dumps({
            "pid": DEAD_PID, "nextflow_pid": live_process.pid,
            "nextflow_started_at": "2026-10-28T09:00:00",
        }))
        m = BackendManager(str(tmp_path / "d"))
        ok, msg = m._acquire_lock(str(results))
        assert ok is False
        assert str(live_process.pid) in msg
        assert "earlier Nanometa Live session" in msg
        assert f"kill {live_process.pid}" in msg
        # The lock was not deleted as stale.
        assert (results / ".nanometa.lock").exists()

    def test_dead_pipeline_and_dead_gui_is_stale(self, tmp_path):
        results = tmp_path / "results"; results.mkdir()
        (results / ".nanometa.lock").write_text(json.dumps({
            "pid": DEAD_PID, "nextflow_pid": DEAD_PID - 1,
        }))
        m = BackendManager(str(tmp_path / "d"))
        ok, _ = m._acquire_lock(str(results))
        assert ok is True
        m._release_lock()

    def test_read_orphan_run(self, tmp_path, live_process):
        results = tmp_path / "results"; results.mkdir()
        assert BackendManager.read_orphan_run(str(results)) is None
        (results / ".nanometa.lock").write_text(json.dumps({
            "pid": DEAD_PID, "nextflow_pid": live_process.pid, "user": "op",
        }))
        rec = BackendManager.read_orphan_run(str(results))
        assert rec["nextflow_pid"] == live_process.pid
        assert rec["results_dir"] == str(results)
        # Our own lock is not an orphan.
        (results / ".nanometa.lock").write_text(json.dumps({
            "pid": os.getpid(), "nextflow_pid": live_process.pid,
        }))
        assert BackendManager.read_orphan_run(str(results)) is None

    def test_second_instance_sees_the_holders_info(self, tmp_path):
        # 'w' truncated the holder's JSON before flock refused; the second
        # instance then reported an empty "Lock info".
        results = tmp_path / "results"; results.mkdir()
        m1 = BackendManager(str(tmp_path / "d1"))
        m2 = BackendManager(str(tmp_path / "d2"))
        assert m1._acquire_lock(str(results))[0]
        ok, msg = m2._acquire_lock(str(results))
        assert ok is False
        assert f'"pid": {os.getpid()}' in msg
        info = json.loads((results / ".nanometa.lock").read_text())
        assert info["pid"] == os.getpid()
        m1._release_lock()
