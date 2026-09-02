"""A served last-good frame is transient and must never be cached as current.

Round-4 realtime audit, reproduced with scripts/audit_replay_snapshots.py
over the R2 snapshots (docs/audit/realtime-round4-2026-09-02.md, H6/H26/H28):
when a cumulative report is rewritten, the poll that lands inside the 1 s
stability window gets the last-good frame. The caller could not tell that
frame from a real parse and stored it under the file's NEW fingerprint, so
every later poll hit the mtime cache and served the stale frame until the
file was rewritten again (four polls in the replay), and the staleness
registry entry set at that moment never received a parse-ok. A brand-new
cumulative report (the tier switch) had no last-good at all, so the sample
vanished from the aggregate for that poll.
"""

import os
import shutil
import time

import pytest

from nanometa_live.core.utils import staleness
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
from nanometa_live.core.utils.sample_detector import invalidate_sample_cache

pytestmark = pytest.mark.unit

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "realtime_attribution", "kraken2")
SMALL = os.path.join(FIXTURES, "barcode06.cumulative.kraken2.report.txt")   # root 377
LARGE = os.path.join(FIXTURES, "barcode07.cumulative.kraken2.report.txt")


def _root(df):
    return int(df.loc[df["taxid"] == 1, "cumul_reads"].iloc[0])


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _let_window_pass(monkeypatch, seconds=5.0):
    """Advance the clock the loaders read without touching any mtime.

    This is how the window closes on a live run: time passes, the file's
    mtime (and therefore every fingerprint built from it) stays the same.
    """
    from nanometa_live.core.utils import loader_utils
    real = time.time
    monkeypatch.setattr(loader_utils.time, "time", lambda: real() + seconds)


def _place(src, dst, age=30):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    _age(dst, age)


@pytest.fixture(autouse=True)
def _fresh():
    clear_all_loader_caches()
    invalidate_sample_cache()
    staleness.clear()
    yield
    clear_all_loader_caches()
    invalidate_sample_cache()
    staleness.clear()


@pytest.fixture
def results(tmp_path):
    return str(tmp_path)


class TestRewrittenReportIsReReadOnceStable:
    def test_per_sample_value_follows_the_file(self, results, monkeypatch):
        cum = os.path.join(results, "kraken2", "barcode06.cumulative.kraken2.report.txt")
        _place(SMALL, cum)
        first = _root(load_kraken_data(results, "barcode06"))
        assert first == 377

        # The pipeline rewrites the report; the poll lands inside the window.
        _place(LARGE, cum, age=0)
        inside = load_kraken_data(results, "barcode06")
        assert _root(inside) == 377, "inside the window the last-good frame is the right answer"

        # The window closes. Nothing else changes. The next poll must see the file.
        _let_window_pass(monkeypatch)
        after = _root(load_kraken_data(results, "barcode06"))
        large_root = _root(load_kraken_data(os.path.dirname(os.path.dirname(LARGE)), "barcode07"))
        assert after == large_root, (
            "the served fallback was cached as current and the rewritten "
            "report is never re-read until it changes again"
        )

    def test_staleness_clears_once_the_file_parses(self, results, monkeypatch):
        cum = os.path.join(results, "kraken2", "barcode06.cumulative.kraken2.report.txt")
        _place(SMALL, cum)
        load_kraken_data(results, "barcode06")
        _place(LARGE, cum, age=0)
        load_kraken_data(results, "barcode06")
        assert staleness.stale_entries(results, grace_seconds=0), "fallback served: registry must know"
        _let_window_pass(monkeypatch)
        load_kraken_data(results, "barcode06")
        assert not staleness.stale_entries(results, grace_seconds=0), (
            "the file parses again; a flag that stays here is the "
            "'1 sample serving stale data' that sat on a COMPLETE banner for six hours"
        )

    def test_aggregate_value_follows_the_file(self, results, monkeypatch):
        a = os.path.join(results, "kraken2", "barcode06.cumulative.kraken2.report.txt")
        b = os.path.join(results, "kraken2", "barcode08.cumulative.kraken2.report.txt")
        _place(SMALL, a)
        _place(SMALL, b)
        base = _root(load_kraken_data(results, "All Samples"))
        assert base == 2 * 377
        _place(LARGE, a, age=0)
        load_kraken_data(results, "All Samples")
        _let_window_pass(monkeypatch)
        after = _root(load_kraken_data(results, "All Samples"))
        large_root = _root(load_kraken_data(os.path.dirname(os.path.dirname(LARGE)), "barcode07"))
        assert after == large_root + 377


class TestTierSwitchDoesNotDropTheSample:
    def test_fresh_first_cumulative_keeps_the_batch_tier_for_the_poll(self, results, monkeypatch):
        batch = os.path.join(results, "kraken2", "barcode06", "batch_reports",
                             "barcode06_batch0.kraken2.report.txt")
        _place(SMALL, batch)
        assert _root(load_kraken_data(results, "barcode06")) == 377
        # First cumulative flush lands; this poll is inside its window.
        cum = os.path.join(results, "kraken2", "barcode06.cumulative.kraken2.report.txt")
        _place(LARGE, cum, age=0)
        inside = load_kraken_data(results, "barcode06")
        assert not inside.empty, "the sample must not vanish for the poll that meets a fresh cumulative"
        assert _root(inside) == 377
        _let_window_pass(monkeypatch)
        large_root = _root(load_kraken_data(os.path.dirname(os.path.dirname(LARGE)), "barcode07"))
        assert _root(load_kraken_data(results, "barcode06")) == large_root

    def test_aggregate_never_drops_at_the_switch(self, results):
        other = os.path.join(results, "kraken2", "barcode08.cumulative.kraken2.report.txt")
        _place(SMALL, other)
        batch = os.path.join(results, "kraken2", "barcode06", "batch_reports",
                             "barcode06_batch0.kraken2.report.txt")
        _place(SMALL, batch)
        assert _root(load_kraken_data(results, "All Samples")) == 2 * 377
        cum = os.path.join(results, "kraken2", "barcode06.cumulative.kraken2.report.txt")
        _place(LARGE, cum, age=0)
        assert _root(load_kraken_data(results, "All Samples")) >= 2 * 377, (
            "R1 measured 1,614 -> 619 reads at this moment"
        )
