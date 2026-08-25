"""The "All Samples" aggregate must not re-accumulate every batch file.

Round-3 audit: in the incremental layout the aggregate rebuild parsed and
accumulated ALL batch files of ALL samples on every rebuild -- ~14 min at
96x300 -- and any one sample's new batch triggered it. The per-sample
accumulation cache keeps each sample's summed (agg, order) keyed on that
sample's exact file set, so a rebuild recomputes only the changed sample
and merges per-sample sums.

Byte-identical is the bar: the merge preserves first-occurrence order by
processing samples as contiguous segments of the globally sorted file
list, and falls back to the plain loop when a sample's files interleave
with another's in sort order (possible with prefix names like barcode01 /
barcode010).
"""

import os
import time
from unittest.mock import patch

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import classification_loaders as cl
from nanometa_live.core.utils import report_accumulation as ra


REPORT = ("100.00\t1000\t10\tR\t1\troot\n"
          " 40.00\t400\t400\tS\t101\tSpecies alpha\n"
          " 30.00\t300\t300\tS\t102\tSpecies beta\n")


def _write(path, text=REPORT, age=120):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() - age
    os.utime(path, (t, t))


def _incremental_tree(tmp_path, samples=3, batches=3):
    for i in range(1, samples + 1):
        sdir = tmp_path / "kraken2" / f"barcode{i:02d}"
        (sdir / "stats").mkdir(parents=True, exist_ok=True)
        for b in range(batches):
            _write(sdir / "batch_reports" / f"batch_{b}.kraken2.report.txt")
            _write(sdir / "stats" / f"batch_{b}_report_stats.json", "{}")
    return tmp_path


@pytest.fixture(autouse=True)
def _fresh():
    from nanometa_live.core.utils import loader_utils
    loader_utils.clear_all_loader_caches()
    loader_utils._freshness_epoch = 0
    yield
    loader_utils.clear_all_loader_caches()


def _aggregate(tmp_path):
    return cl.load_kraken_data(str(tmp_path), "All Samples")


class TestEquivalence:
    def test_cached_aggregate_equals_fresh(self, tmp_path):
        _incremental_tree(tmp_path)
        warm = _aggregate(tmp_path)
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_all_loader_caches()
        fresh = _aggregate(tmp_path)
        pd.testing.assert_frame_equal(warm, fresh)

    def test_new_batch_equals_full_recompute(self, tmp_path):
        _incremental_tree(tmp_path)
        _aggregate(tmp_path)  # warm the per-sample cache
        _write(tmp_path / "kraken2" / "barcode02" / "batch_reports"
               / "batch_9.kraken2.report.txt",
               REPORT.replace("400", "888"), age=60)
        incremental = _aggregate(tmp_path)
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_all_loader_caches()
        full = _aggregate(tmp_path)
        pd.testing.assert_frame_equal(incremental, full)

    def test_deleted_sample_equals_full_recompute(self, tmp_path):
        import shutil
        _incremental_tree(tmp_path)
        _aggregate(tmp_path)
        shutil.rmtree(tmp_path / "kraken2" / "barcode03")
        after = _aggregate(tmp_path)
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_all_loader_caches()
        full = _aggregate(tmp_path)
        pd.testing.assert_frame_equal(after, full)

    def test_mixed_tiers_equal_fresh(self, tmp_path):
        # One cumulative-tier sample, one standard-tier, one incremental.
        _incremental_tree(tmp_path, samples=1)
        _write(tmp_path / "kraken2"
               / "barcode08.cumulative.kraken2.report.txt")
        _write(tmp_path / "kraken2" / "barcode09.kraken2.report.txt")
        warm1 = _aggregate(tmp_path)
        warm2 = _aggregate(tmp_path)
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_all_loader_caches()
        fresh = _aggregate(tmp_path)
        pd.testing.assert_frame_equal(warm1, fresh)
        pd.testing.assert_frame_equal(warm2, fresh)

    def test_interleaved_prefix_names_stay_correct(self, tmp_path):
        # barcode01 (nested) and barcode010 (flat legacy) interleave in
        # global sort order; the segment merge must fall back and still
        # produce exactly the plain-loop result.
        _incremental_tree(tmp_path, samples=1)
        _write(tmp_path / "kraken2"
               / "barcode010_batch1.kraken2.report.txt")
        got = _aggregate(tmp_path)
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_all_loader_caches()
        fresh = _aggregate(tmp_path)
        pd.testing.assert_frame_equal(got, fresh)


class TestCost:
    def test_one_new_batch_reaccumulates_one_sample(self, tmp_path):
        _incremental_tree(tmp_path, samples=4, batches=5)
        _aggregate(tmp_path)
        _write(tmp_path / "kraken2" / "barcode02" / "batch_reports"
               / "batch_9.kraken2.report.txt", age=60)

        calls = {"n": 0}
        orig = cl._accumulate_kraken_df

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(ra, "_accumulate", counting):
            _aggregate(tmp_path)
        assert calls["n"] <= 6, (
            "only the changed sample's files may be re-accumulated "
            f"(got {calls['n']} accumulations for a 1-sample change)"
        )

    def test_quiet_rebuild_accumulates_nothing(self, tmp_path):
        _incremental_tree(tmp_path, samples=4, batches=5)
        _aggregate(tmp_path)

        calls = {"n": 0}
        orig = cl._accumulate_kraken_df

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        # Force the outer caches to miss so the rebuild path itself runs.
        from nanometa_live.core.utils import loader_utils
        loader_utils.clear_data_cache()
        with patch.object(ra, "_accumulate", counting):
            _aggregate(tmp_path)
        assert calls["n"] == 0
