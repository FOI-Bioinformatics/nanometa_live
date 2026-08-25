"""Memory ceilings for the loader caches (round 3, phase 4).

The phase-2 harness measured 3.8 GB of parsed frames resident at the
96-barcode envelope: the frame cache's LRU is count-capped (24N) and
size-blind, superseded report versions linger until count pressure, and
every load stored THREE copies of its result (return + TTL + mtime).
An overnight field-laptop run must plateau, so the caches become
byte-budgeted and copy-free.
"""

import os
import time

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import classification_loaders as cl
from nanometa_live.core.utils import loader_utils


REPORT = ("100.00\t1000\t10\tR\t1\troot\n"
          + "".join(f" 1.00\t{10 + i}\t{10 + i}\tS\t{100 + i}\t"
                    f"Species organismus{i}\n" for i in range(50)))


@pytest.fixture(autouse=True)
def _fresh():
    loader_utils.clear_all_loader_caches()
    loader_utils._freshness_epoch = 0
    yield
    loader_utils.clear_all_loader_caches()


def _write_report(path, text=REPORT, age=120):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() - age
    os.utime(path, (t, t))


class TestSupersededVersionsEvictEagerly:
    def test_rewritten_report_leaves_one_cache_entry(self, tmp_path):
        report = tmp_path / "kraken2" / "b01.cumulative.kraken2.report.txt"
        for i in range(4):
            _write_report(report, REPORT.replace("1000", str(1000 + i)),
                          age=120 - i)
            cl._parse_kraken2_report(str(report))
        realpath = os.path.realpath(str(report))
        with cl._report_frame_cache_lock:
            versions = [k for k in cl._report_frame_cache if k[0] == realpath]
        assert len(versions) == 1, (
            f"{len(versions)} versions of one rewritten report resident; "
            "each batch rewrite must evict its predecessor eagerly"
        )


class TestByteBudget:
    def test_budget_evicts_lru_frames(self, tmp_path, monkeypatch):
        frame_bytes = None
        paths = []
        for i in range(6):
            p = tmp_path / "kraken2" / f"b{i:02d}.kraken2.report.txt"
            _write_report(p)
            paths.append(p)
        first = cl._parse_kraken2_report(str(paths[0]))
        frame_bytes = int(first.memory_usage(deep=True).sum())
        # Budget for ~3 frames (plus their last-good twins).
        monkeypatch.setattr(cl, "_FRAME_CACHE_BUDGET_BYTES", frame_bytes * 6)
        for p in paths[1:]:
            cl._parse_kraken2_report(str(p))
        assert cl.report_frame_cache_bytes() <= frame_bytes * 6 + frame_bytes, (
            "the frame caches must respect the byte budget"
        )

    def test_last_good_survives_while_plain_entries_exist(self, tmp_path,
                                                          monkeypatch):
        # The honesty fallback is evicted only under real pressure: with a
        # budget fitting a few frames, the LAST parsed report keeps both its
        # plain and last-good entries.
        p = tmp_path / "kraken2" / "keep.kraken2.report.txt"
        _write_report(p)
        cl._parse_kraken2_report(str(p))
        realpath = os.path.realpath(str(p))
        with cl._report_frame_cache_lock:
            assert realpath in cl._last_good_frame


class TestNoRedundantCopies:
    def test_ttl_and_mtime_caches_share_one_frame(self, tmp_path):
        _write_report(tmp_path / "kraken2" / "b01.kraken2.report.txt")
        df = cl.load_kraken_data(str(tmp_path), "b01")
        assert not df.empty
        key = loader_utils._get_cache_key(str(tmp_path), "b01")
        with loader_utils._cache_lock:
            ttl_frame = loader_utils._kraken_cache[key][1]
            mtime_entries = [
                v[2] for k, v in loader_utils._file_mtimes.items()
                if k.startswith("kraken:") and v[2] is not None
            ]
        assert any(m is ttl_frame for m in mtime_entries), (
            "the TTL and mtime caches must share one frame object -- "
            "each load stored three copies"
        )


class TestOrganismsMemoEpochEviction:
    def test_new_epoch_drops_stale_epochs(self):
        from nanometa_live.app.utils import organisms_memo as om
        om._memo.clear()
        for epoch in (1, 2, 3, 4):
            om._memo[("/run", ("a",), epoch, "")] = {"payload": epoch}
            om._evict_stale_epochs(current_epoch=epoch)
        epochs = {k[2] for k in om._memo}
        assert epochs <= {3, 4}, (
            f"epochs {epochs} resident; each 50-120 MB entry from a dead "
            "epoch is pure waste (keep at most current + previous)"
        )
        om._memo.clear()


class TestBreadthCacheSupersession:
    def test_rewritten_paf_evicts_old_key(self, tmp_path):
        from nanometa_live.core.parsers import paf_coverage_parser as pcp
        pcp._breadth_cache.clear()
        paf = tmp_path / "b01_taxid5.paf"
        line = ("r0\t500\t0\t500\t+\tref\t1900000\t1000\t1500\t500\t500"
                "\t60\n")
        for i in range(5):
            paf.write_text(line * (i + 1))
            t = time.time() - 60 + i
            os.utime(paf, (t, t))
            pcp.paf_breadth(str(paf))
        keys = [k for k in pcp._breadth_cache if k[0] == str(paf)]
        assert len(keys) == 1, (
            f"{len(keys)} superseded PAF versions resident; the cache grew "
            "monotonically for the life of the process"
        )
        pcp._breadth_cache.clear()


class TestLogDirPruning:
    """Each launch starts a new timestamped rotation family and nothing
    pruned the old ones -- ~/.nanometa/logs grew without limit across
    restarts (round 3). setup_logging prunes families beyond the newest
    K launches, never the current one."""

    def _family(self, log_dir, stamp):
        for name in (f"nanometa_live_{stamp}.log", f"api_calls_{stamp}.log"):
            (log_dir / name).write_text("x")

    def test_old_families_pruned_on_setup(self, tmp_path):
        from nanometa_live.core.utils.logging_utils import (
            _prune_log_families, KEEP_LOG_FAMILIES,
        )
        for i in range(KEEP_LOG_FAMILIES + 4):
            self._family(tmp_path, f"202608{10 + i:02d}_000000")
        _prune_log_families(str(tmp_path))
        stamps = {f.name.split("nanometa_live_")[-1].split(".log")[0]
                  for f in tmp_path.glob("nanometa_live_*.log")}
        assert len(stamps) == KEEP_LOG_FAMILIES
        assert f"202608{10 + KEEP_LOG_FAMILIES + 3:02d}_000000" in stamps, (
            "the newest families must survive"
        )

    def test_rotation_backups_of_kept_families_survive(self, tmp_path):
        from nanometa_live.core.utils.logging_utils import (
            _prune_log_families, KEEP_LOG_FAMILIES,
        )
        self._family(tmp_path, "20260801_000000")
        (tmp_path / "nanometa_live_20260801_000000.log.1").write_text("x")
        _prune_log_families(str(tmp_path))
        assert (tmp_path / "nanometa_live_20260801_000000.log.1").exists()

    def test_unrelated_files_untouched(self, tmp_path):
        from nanometa_live.core.utils.logging_utils import _prune_log_families
        (tmp_path / "trace.txt").write_text("keep me")
        _prune_log_families(str(tmp_path))
        assert (tmp_path / "trace.txt").exists()


class TestEndurancePlateau:
    def test_cache_bytes_plateau_across_rewrites(self, tmp_path):
        """Simulated realtime endurance: 12 samples x 30 cumulative
        rewrites. With eager supersession the resident bytes must stay at
        one version per sample (x2 for the last-good twin), not grow with
        the rewrite count."""
        reports = []
        for i in range(12):
            p = (tmp_path / "kraken2"
                 / f"b{i:02d}.cumulative.kraken2.report.txt")
            _write_report(p)
            cl._parse_kraken2_report(str(p))
            reports.append(p)
        after_first = cl.report_frame_cache_bytes()
        for round_no in range(30):
            for p in reports:
                _write_report(p, REPORT.replace("1000", str(2000 + round_no)),
                              age=90 - round_no)
                cl._parse_kraken2_report(str(p))
        after_endurance = cl.report_frame_cache_bytes()
        assert after_endurance <= after_first * 1.5, (
            f"cache grew {after_first} -> {after_endurance} bytes across "
            "rewrites; superseded versions are accumulating"
        )
