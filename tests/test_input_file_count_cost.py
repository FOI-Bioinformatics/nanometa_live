"""Counting input files must not stat every FASTQ on every refresh.

``BackendManager._update_file_counts`` runs from ``get_status`` on every
dashboard tick (5 s TTL) and listed every input directory and stat'ed every
FASTQ in it for the newest mtime: 113 ms per refresh at 96 barcodes x 500
files on local APFS, slower on a USB or network input, while the status
lock the monitor thread also needs was held. A directory whose own mtime is
unchanged has gained, lost and renamed nothing, so its count is reused and
only its newest file is re-stat'ed (data appended to the latest file still
moves the auto-stop anchor).
"""

import os
import time
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow import backend_manager as bm_mod
from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit

N_DIRS, N_FILES = 4, 25


@pytest.fixture
def manager(tmp_path):
    inbox = tmp_path / "inbox"
    for b in range(N_DIRS):
        d = inbox / f"barcode{b + 1:02d}"
        d.mkdir(parents=True)
        for i in range(N_FILES):
            (d / f"reads_{i}.fastq.gz").write_text("@r\nA\n+\nI\n")
    m = BackendManager(str(tmp_path / "data"))
    m.config = {"nanopore_output_directory": str(inbox),
                "sample_handling": "by_barcode"}
    return m, inbox


def _refresh(m):
    m._file_count_cached_at = 0.0   # past the TTL
    m._update_file_counts()


def _count_stats(m):
    real = os.stat
    calls = {"n": 0}

    def counting(path, *a, **kw):
        if str(path).endswith(".fastq.gz"):
            calls["n"] += 1
        return real(path, *a, **kw)

    with patch.object(bm_mod.os, "stat", counting):
        _refresh(m)
    return calls["n"]


def test_counts_are_correct(manager):
    m, _ = manager
    _refresh(m)
    assert m.status["files_waiting"] == N_DIRS * N_FILES


def test_unchanged_directories_are_not_rescanned(manager):
    m, _ = manager
    _refresh(m)
    stats = _count_stats(m)
    # Only each directory's newest read file is re-stat'ed (the root holds
    # none), not all N_DIRS x N_FILES.
    assert stats <= N_DIRS
    assert m.status["files_waiting"] == N_DIRS * N_FILES


def test_a_new_file_is_counted_and_moves_the_anchor(manager):
    m, inbox = manager
    _refresh(m)
    time.sleep(0.01)
    new = inbox / "barcode02" / "reads_new.fastq.gz"
    new.write_text("@r\nA\n+\nI\n")
    future = time.time() + 30
    os.utime(new, (future, future))
    # Directory mtime granularity: make sure the dir visibly changed.
    os.utime(inbox / "barcode02", (future, future))
    _refresh(m)
    assert m.status["files_waiting"] == N_DIRS * N_FILES + 1
    assert m._newest_input_mtime == pytest.approx(future)


def test_append_to_the_newest_file_moves_the_anchor(manager):
    m, inbox = manager
    _refresh(m)
    newest = max((inbox / "barcode01").iterdir(), key=lambda p: p.stat().st_mtime)
    future = time.time() + 60
    os.utime(newest, (future, future))
    _refresh(m)
    assert m._newest_input_mtime == pytest.approx(future)
