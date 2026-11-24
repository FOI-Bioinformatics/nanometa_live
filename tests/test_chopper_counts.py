"""Chopper's own read counts, as nanometanf publishes them.

chopper writes ``Kept K reads out of N reads`` to standard error and keeps no
other record of its input; nanometanf publishes that line per task to
``chopper/<sample>/counts/<sample>.<stamp>.chopper_counts.txt``. Summing N is
the only count of the reads before filtering a chopper run has (Barcelona
exercise feedback, 2026-11-24).
"""

import builtins
import os
import time

import pytest

from nanometa_live.core.utils import chopper_counts as cc
from nanometa_live.core.utils.chopper_counts import ChopperCounts, load_chopper_counts

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_cache():
    cc.clear_chopper_counts_cache()
    yield
    cc.clear_chopper_counts_cache()


def _write(root, sample, stamp, text, age=60):
    d = root / "chopper" / sample / "counts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sample}.{stamp}.chopper_counts.txt"
    p.write_text(text)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_sums_batches_of_one_sample(tmp_path):
    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    _write(tmp_path, "barcode01", "2", "Kept 40 reads out of 50 reads\n")
    assert load_chopper_counts(str(tmp_path), "barcode01") == ChopperCounts(150, 120, 2)


def test_all_samples_sums_every_sample(tmp_path):
    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    _write(tmp_path, "barcode02", "1", "Kept 5 reads out of 10 reads\n")
    assert load_chopper_counts(str(tmp_path), None) == ChopperCounts(110, 85, 2)
    assert load_chopper_counts(str(tmp_path), "All Samples") == ChopperCounts(110, 85, 2)


def test_other_samples_are_not_counted(tmp_path):
    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    _write(tmp_path, "barcode02", "1", "Kept 5 reads out of 10 reads\n")
    assert load_chopper_counts(str(tmp_path), "barcode02") == ChopperCounts(10, 5, 1)


def test_absent_directory_returns_none(tmp_path):
    assert load_chopper_counts(str(tmp_path), None) is None
    assert load_chopper_counts(str(tmp_path), "barcode01") is None


def test_last_summary_line_wins(tmp_path):
    _write(tmp_path, "barcode01", "1",
           "some warning\nKept 1 reads out of 2 reads\nKept 3 reads out of 4 reads\n")
    assert load_chopper_counts(str(tmp_path), "barcode01") == ChopperCounts(4, 3, 1)


def test_file_without_summary_line_is_skipped_and_not_cached(tmp_path):
    p = _write(tmp_path, "barcode01", "1", "")
    assert load_chopper_counts(str(tmp_path), "barcode01") is None
    p.write_text("Kept 7 reads out of 9 reads\n")
    t = time.time() - 30
    os.utime(p, (t, t))
    assert load_chopper_counts(str(tmp_path), "barcode01") == ChopperCounts(9, 7, 1)


def test_unchanged_file_is_not_reopened(tmp_path, monkeypatch):
    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    _write(tmp_path, "barcode01", "2", "Kept 40 reads out of 50 reads\n")
    opened = []
    real_open = builtins.open

    def counting_open(path, *a, **k):
        if str(path).endswith(".chopper_counts.txt"):
            opened.append(str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", counting_open)
    load_chopper_counts(str(tmp_path), "barcode01")
    load_chopper_counts(str(tmp_path), "barcode01")
    assert len(opened) == 2


def test_clear_all_loader_caches_clears_it(tmp_path):
    from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    load_chopper_counts(str(tmp_path), "barcode01")
    assert cc._counts_cache
    clear_all_loader_caches()
    assert not cc._counts_cache


def test_perf_harness_reset_clears_it(tmp_path):
    from scripts.perf.instrument import reset_caches

    _write(tmp_path, "barcode01", "1", "Kept 80 reads out of 100 reads\n")
    load_chopper_counts(str(tmp_path), "barcode01")
    assert cc._counts_cache
    reset_caches()
    assert not cc._counts_cache
