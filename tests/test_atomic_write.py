"""Tests for atomic_write helpers used by shared-state files."""

import json
import os
import threading

import pytest

from nanometa_live.core.utils.atomic_write import (
    atomic_write_json,
    atomic_write_text,
    file_lock,
)


def test_atomic_write_text_creates_file_and_replaces(tmp_path):
    target = tmp_path / "state.txt"
    atomic_write_text(target, "first")
    assert target.read_text() == "first"

    atomic_write_text(target, "second")
    assert target.read_text() == "second"


def test_atomic_write_text_no_temp_files_left_on_success(tmp_path):
    target = tmp_path / "state.txt"
    atomic_write_text(target, "ok")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.txt"]
    assert leftovers == []


def test_atomic_write_json_round_trip(tmp_path):
    target = tmp_path / "data.json"
    payload = {"taxids": [123, 456], "name": "demo"}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text()) == payload


def test_atomic_write_text_creates_parent_dir(tmp_path):
    target = tmp_path / "nested" / "deeper" / "f.txt"
    atomic_write_text(target, "x")
    assert target.read_text() == "x"


def test_atomic_write_does_not_truncate_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "state.txt"
    atomic_write_text(target, "original-content")

    # Force os.replace to fail; the original file should remain intact.
    real_replace = os.replace

    def boom(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new-content")
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text() == "original-content"
    leftovers = [p.name for p in tmp_path.iterdir()]
    assert leftovers == ["state.txt"]


def test_file_lock_serialises_concurrent_writers(tmp_path):
    target = tmp_path / "shared.txt"
    atomic_write_text(target, "0")

    # Both threads increment the integer in the file under the same
    # lock. Without the lock the test would non-deterministically lose
    # one increment; with the lock the final value must equal the
    # iteration count.
    iterations = 50

    def worker():
        for _ in range(iterations):
            with file_lock(target):
                current = int(target.read_text())
                atomic_write_text(target, str(current + 1))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert int(target.read_text()) == iterations * 2
