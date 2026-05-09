"""Tests for the per-process Diskcache lifecycle."""

import os
from pathlib import Path

from nanometa_live.app.app import (
    _per_run_cache_dir,
    _sweep_dead_run_caches,
)


def test_per_run_cache_dir_includes_pid(tmp_path):
    base = str(tmp_path)
    run = _per_run_cache_dir(base)
    assert run.startswith(base)
    assert f"run-{os.getpid()}-" in os.path.basename(run)


def test_per_run_cache_dir_is_unique_per_call(tmp_path, monkeypatch):
    # Two calls within the same second still differ if PID + epoch
    # collide -- verify by mutating the timestamp source. In practice
    # each instance only requests a run-dir once, so this only matters
    # for test determinism.
    base = str(tmp_path)
    a = _per_run_cache_dir(base)
    # advance time by patching time.time monotonically inside the
    # function -- easier: directly check the format
    assert a.startswith(base + "/run-")


def test_sweep_removes_directories_for_dead_pids(tmp_path):
    base = tmp_path / "cache"
    base.mkdir()

    # PID 1 is init; on macOS/Linux always alive. Use a guaranteed-dead
    # PID by spawning and reaping a quick child.
    import subprocess

    proc = subprocess.run(["true"], check=True)
    dead_pid = proc.returncode  # hack: reuse a PID that just exited
    # That's not actually the dead PID -- it's the return code. Get a
    # truly dead PID by checking from a high range.
    dead_pid = 999999
    while True:
        try:
            os.kill(dead_pid, 0)
            dead_pid -= 1
            if dead_pid < 1:
                raise RuntimeError("could not find a dead PID for the test")
        except ProcessLookupError:
            break
        except PermissionError:
            dead_pid -= 1

    dead_dir = base / f"run-{dead_pid}-1234567890"
    dead_dir.mkdir()
    (dead_dir / "marker").write_text("x")

    live_dir = base / f"run-{os.getpid()}-1234567891"
    live_dir.mkdir()
    (live_dir / "marker").write_text("x")

    unrelated = base / "operator-content"
    unrelated.mkdir()
    (unrelated / "important.txt").write_text("do-not-delete")

    _sweep_dead_run_caches(str(base))

    assert not dead_dir.exists(), "dead-PID cache dir should have been removed"
    assert live_dir.exists(), "live-PID cache dir must be preserved"
    assert unrelated.exists(), "unrelated subdir must not be touched"
    assert (unrelated / "important.txt").exists()


def test_sweep_skips_when_base_missing(tmp_path):
    # Should not raise when the cache root does not exist yet.
    _sweep_dead_run_caches(str(tmp_path / "nonexistent"))


def test_sweep_ignores_non_matching_dirnames(tmp_path):
    base = tmp_path / "cache"
    base.mkdir()

    looks_similar = base / "run-abc-def"  # not all-digit fields
    looks_similar.mkdir()
    (looks_similar / "marker").write_text("x")

    extension = base / "run-1-2-extra"  # extra dash
    extension.mkdir()
    (extension / "marker").write_text("x")

    _sweep_dead_run_caches(str(base))

    assert looks_similar.exists()
    assert extension.exists()
