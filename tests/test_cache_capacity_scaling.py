"""Loader cache capacity must scale with the detected sample count.

At 96 barcodes the live key population is ~300 mtime-cache entries
(kraken/seqkit/fastp per sample plus aggregates) against a fixed cap of
100, and ~1,900 report files against a per-file parse LRU of 512. Two
thirds of the cache was evicted on every cleanup pass, so every "cached"
per-tick path became periodically cold — full re-parse waves during live
runs (round-2 audit, 2026-08-22).

The caps are now floors raised dynamically from the detected sample count
by the sample-detection path.
"""

import time

import pytest

from nanometa_live.core.utils import classification_loaders, loader_utils

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_caps():
    lu_cap = loader_utils.CACHE_MAX_ENTRIES
    cl_cap = classification_loaders._REPORT_FRAME_CACHE_MAX
    cleanup_stamp = loader_utils._last_cache_cleanup
    yield
    loader_utils.CACHE_MAX_ENTRIES = lu_cap
    classification_loaders._REPORT_FRAME_CACHE_MAX = cl_cap
    loader_utils._last_cache_cleanup = cleanup_stamp
    with loader_utils._cache_lock:
        loader_utils._kraken_cache.clear()
        loader_utils._fastp_cache.clear()
        loader_utils._file_mtimes.clear()


class TestSetCacheCapacity:
    def test_scales_with_sample_count(self):
        loader_utils.set_cache_capacity(96)
        assert loader_utils.CACHE_MAX_ENTRIES == 4 * 96 + 50
        assert classification_loaders._REPORT_FRAME_CACHE_MAX == 24 * 96

    def test_floors_hold_for_small_runs(self):
        loader_utils.set_cache_capacity(2)
        assert loader_utils.CACHE_MAX_ENTRIES == 100
        assert classification_loaders._REPORT_FRAME_CACHE_MAX == 512

    def test_capacity_never_shrinks_mid_session(self):
        # A transient short sample list (e.g. mid-rewrite detection) must not
        # collapse the cap under a fuller population seen earlier.
        loader_utils.set_cache_capacity(96)
        loader_utils.set_cache_capacity(3)
        assert loader_utils.CACHE_MAX_ENTRIES == 4 * 96 + 50

    def test_cleanup_keeps_all_live_keys_at_96_samples(self):
        """The defect: 96 samples x 3 loaders = ~300 fresh keys against a
        cap of 100 meant two thirds evicted per cleanup pass."""
        loader_utils.set_cache_capacity(96)
        now = time.time()
        with loader_utils._cache_lock:
            loader_utils._file_mtimes.clear()
            for i in range(96):
                for kind in ("kraken", "seqkit", "fastp"):
                    loader_utils._file_mtimes[f"{kind}:/run:barcode{i:02d}"] = (
                        (now, 1, 1), 1, None)
            n_before = len(loader_utils._file_mtimes)
            loader_utils._last_cache_cleanup = 0.0
            loader_utils._cleanup_stale_cache_entries()
            n_after = len(loader_utils._file_mtimes)
        assert n_before == 288
        assert n_after == n_before, (
            f"cleanup evicted {n_before - n_after} live keys; the cap must "
            f"hold the whole live population"
        )


class TestSampleDetectionWiresCapacity:
    def test_get_available_samples_raises_the_caps(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        for i in range(40):
            (kraken_dir / f"barcode{i:02d}.kraken2.report.txt").write_text(
                "100.0\t1\t1\tR\t1\troot\n")
        loader_utils.CACHE_MAX_ENTRIES = 100
        classification_loaders._REPORT_FRAME_CACHE_MAX = 512

        from nanometa_live.core.utils.sample_detector import (
            get_available_samples,
        )
        samples = get_available_samples(str(tmp_path))
        assert len(samples) >= 40  # includes "All Samples"
        assert loader_utils.CACHE_MAX_ENTRIES >= 4 * 40 + 50
        assert classification_loaders._REPORT_FRAME_CACHE_MAX >= 512
