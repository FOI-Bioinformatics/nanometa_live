"""State-machine / locking / path-validation tests for BackendManager.

Complements test_backend_manager_collision.py (fingerprint/archive) and
test_backend_manager_metadata.py (run metadata) by covering the lock lifecycle,
path validation guards, process-existence check, and resume detection -- the
previously-dark parts of the run state machine.
"""

import json
import os

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager


@pytest.fixture
def manager(tmp_path):
    return BackendManager(str(tmp_path / "data"))


# --------------------------------------------------------------------------- #
# _validate_path / _validate_path_for_output
# --------------------------------------------------------------------------- #

def test_validate_path_rejects_empty():
    with pytest.raises(ValueError, match="Empty"):
        BackendManager._validate_path("", "input")
    with pytest.raises(ValueError):
        BackendManager._validate_path("   ", "input")


def test_validate_path_rejects_traversal():
    with pytest.raises(ValueError, match="traversal"):
        BackendManager._validate_path("/home/user/../etc/passwd", "input")


@pytest.mark.parametrize("blocked", ["/etc", "/usr/local", "/var/data", "/proc/1"])
def test_validate_path_rejects_system_dirs(blocked):
    with pytest.raises(ValueError, match="system directory"):
        BackendManager._validate_path(blocked, "input")


def test_validate_path_accepts_existing_and_resolves(tmp_path):
    target = tmp_path / "in"
    target.mkdir()
    resolved = BackendManager._validate_path(str(target), "input")
    assert resolved == str(target.resolve())


def test_validate_path_missing_required_raises(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        BackendManager._validate_path(str(tmp_path / "nope"), "input")


def test_validate_path_for_output_allows_missing_with_existing_parent(tmp_path):
    out = tmp_path / "results"  # parent (tmp_path) exists, results does not
    resolved = BackendManager._validate_path_for_output(str(out), "outdir")
    assert resolved == str(out.resolve())


def test_validate_path_for_output_rejects_missing_parent(tmp_path):
    out = tmp_path / "missing_parent" / "results"
    with pytest.raises(ValueError, match="Parent directory"):
        BackendManager._validate_path_for_output(str(out), "outdir")


# --------------------------------------------------------------------------- #
# _process_exists
# --------------------------------------------------------------------------- #

def test_process_exists_for_current_process():
    assert BackendManager._process_exists(os.getpid()) is True


def test_process_exists_false_for_dead_pid():
    # PID 2^31-1 is effectively never a live process
    assert BackendManager._process_exists(2_147_483_646) is False


# --------------------------------------------------------------------------- #
# _acquire_lock / _release_lock
# --------------------------------------------------------------------------- #

def test_acquire_then_release_lock(manager, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    ok, msg = manager._acquire_lock(str(results))
    assert ok is True
    lock_file = results / ".nanometa.lock"
    assert lock_file.exists()
    info = json.loads(lock_file.read_text())
    assert info["pid"] == os.getpid()

    manager._release_lock()
    assert not lock_file.exists()


def test_second_acquire_is_blocked(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    m1 = BackendManager(str(tmp_path / "d1"))
    m2 = BackendManager(str(tmp_path / "d2"))
    assert m1._acquire_lock(str(results))[0] is True
    ok, msg = m2._acquire_lock(str(results))
    assert ok is False
    assert "already running" in msg
    m1._release_lock()


def test_stale_lock_from_dead_pid_is_reclaimed(manager, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    # Plant a stale lock owned by a dead PID.
    (results / ".nanometa.lock").write_text(json.dumps({"pid": 2_147_483_646}))
    ok, _ = manager._acquire_lock(str(results))
    assert ok is True
    manager._release_lock()


def test_release_lock_is_safe_without_lock(manager):
    # No lock held -> must not raise.
    manager._release_lock()


# --------------------------------------------------------------------------- #
# can_resume
# --------------------------------------------------------------------------- #

def test_can_resume_false_without_work_dir(manager):
    assert manager.can_resume() is False


def test_can_resume_true_with_nextflow_work_dir(tmp_path):
    data = tmp_path / "data"
    (data / "work" / "ab").mkdir(parents=True)  # 2-char hex work prefix
    m = BackendManager(str(data))
    assert m.can_resume() is True


def test_can_resume_true_with_nextflow_cache(tmp_path):
    data = tmp_path / "data"
    (data / "work").mkdir(parents=True)
    (data / ".nextflow").mkdir()
    m = BackendManager(str(data))
    assert m.can_resume() is True


# --------------------------------------------------------------------------- #
# Bug-hunt #2: realtime auto-stop must not kill batch runs
# --------------------------------------------------------------------------- #

def test_auto_stop_countdown_only_for_realtime(manager):
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(minutes=1)).isoformat()
    manager.status = {"running": True, "start_time": old, "errors": []}

    # Batch mode: no realtime timeout, so no countdown (and no auto-stop).
    manager.config = {"processing_mode": "batch", "realtime_timeout_minutes": 60}
    assert manager._compute_auto_stop_remaining() is None

    # Realtime mode: a positive remaining time.
    manager.config = {"processing_mode": "realtime", "realtime_timeout_minutes": 60}
    remaining = manager._compute_auto_stop_remaining()
    assert remaining is not None and remaining > 0


# --------------------------------------------------------------------------- #
# Bug-hunt #4: get_status must expose a top-level `completed` boolean
# --------------------------------------------------------------------------- #

def test_get_status_sets_completed_boolean(manager):
    from unittest.mock import MagicMock
    manager.workflow_manager.get_status = MagicMock(return_value={"running": False})

    manager.status["running"] = False
    manager.status["pipeline_status"] = "completed"
    assert manager.get_status()["completed"] is True

    manager.status["pipeline_status"] = "stopped"
    assert manager.get_status()["completed"] is False


# --------------------------------------------------------------------------- #
# Lock target resolution (audit 2026-08-16, finding W2)
# --------------------------------------------------------------------------- #

class TestLockTargetsTheRealOutputDirectory:
    """The exclusive lock must guard the directory the pipeline writes to.

    start() locked ``main_dir`` -- but setup_project generates a fresh,
    uniquely timestamped main_dir on every launch, so two operators pointing
    different instances at the SAME ``results_output_directory`` each locked
    their own never-colliding path and both pipelines ran concurrently into
    the same kraken2/validation tree with no warning.
    """

    def test_lock_target_prefers_results_output_directory(self, tmp_path):
        m = BackendManager(str(tmp_path / "data"))
        out = tmp_path / "shared_results"
        m.config = {
            "results_output_directory": str(out),
            "main_dir": str(tmp_path / "internal_a"),
        }
        assert m._lock_target_dir() == str(out)

    def test_lock_target_falls_back_to_main_dir_then_data_dir(self, tmp_path):
        m = BackendManager(str(tmp_path / "data"))
        m.config = {"main_dir": str(tmp_path / "internal")}
        assert m._lock_target_dir() == str(tmp_path / "internal")
        m.config = {}
        assert m._lock_target_dir() == m.data_dir

    def test_two_instances_sharing_an_outdir_collide(self, tmp_path):
        out = tmp_path / "shared_results"
        out.mkdir()
        m1 = BackendManager(str(tmp_path / "d1"))
        m2 = BackendManager(str(tmp_path / "d2"))
        m1.config = {
            "results_output_directory": str(out),
            "main_dir": str(tmp_path / "internal_a"),
        }
        m2.config = {
            "results_output_directory": str(out),
            "main_dir": str(tmp_path / "internal_b"),
        }

        assert m1._acquire_lock(m1._lock_target_dir())[0] is True
        ok, msg = m2._acquire_lock(m2._lock_target_dir())
        assert ok is False, (
            "two instances with different main_dirs but the same output "
            "directory did not collide on the lock"
        )
        m1._release_lock()
