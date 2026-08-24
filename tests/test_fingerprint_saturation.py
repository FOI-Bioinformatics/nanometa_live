"""Fingerprint saturation must degrade to TTL refresh, not freeze.

Round-3 finding: ``_get_path_fingerprint`` stats only the first
``_MAX_FINGERPRINT_FILES`` files (default 50,000). Past the cap the walk
keeps counting but stops stat'ing, so an IN-PLACE REWRITE of a late file
changes neither the mtime, the size, nor the count -- the fingerprint is
frozen and the mtime cache serves the stale result INDEFINITELY, not for
one poll. At 96 barcodes x 300 batches the kraken2 tree alone crosses the
cap.

The fix folds a TTL time-bucket into any SATURATED fingerprint, so both
cache layers (the per-key mtime cache and the freshness epoch) re-validate
at least every ``CACHE_TTL_SECONDS`` on trees too big to stat exhaustively
-- honest degradation instead of silence.
"""

import os
import time

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import loader_utils


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(loader_utils, "_MAX_FINGERPRINT_FILES", 3)
    monkeypatch.setattr(loader_utils, "_freshness_epoch", 0)
    yield


def _tree(tmp_path, n=6):
    d = tmp_path / "kraken2"
    d.mkdir()
    back = time.time() - 120
    for i in range(n):
        p = d / f"f{i}.txt"
        p.write_text("x" * 10)
        os.utime(p, (back, back))
    return str(d)


class TestSaturatedFingerprint:
    def test_saturated_fingerprint_moves_across_ttl_buckets(
            self, tmp_path, small_cap, monkeypatch):
        d = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "CACHE_TTL_SECONDS", 0.05)
        fp1 = loader_utils._get_path_fingerprint([d])
        time.sleep(0.12)
        fp2 = loader_utils._get_path_fingerprint([d])
        assert fp1 != fp2, (
            "a saturated fingerprint must roll over with the TTL bucket, "
            "or late in-place rewrites are invisible forever"
        )

    def test_unsaturated_fingerprint_is_stable(self, tmp_path, monkeypatch):
        d = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "CACHE_TTL_SECONDS", 0.05)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 0)
        fp1 = loader_utils._get_path_fingerprint([d])
        time.sleep(0.12)
        fp2 = loader_utils._get_path_fingerprint([d])
        assert fp1 == fp2, "below the cap nothing may change"

    def test_mtime_cache_refreshes_within_one_ttl_when_saturated(
            self, tmp_path, small_cap, monkeypatch):
        d = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "CACHE_TTL_SECONDS", 0.05)
        loader_utils._store_mtime_cache("sat-key", [d], "result1")
        assert loader_utils._check_mtime_cache("sat-key", [d]) == "result1"
        time.sleep(0.12)
        assert loader_utils._check_mtime_cache("sat-key", [d]) is None, (
            "a saturated entry older than one TTL must re-validate"
        )

    def test_freshness_epoch_bumps_across_ttl_when_saturated(
            self, tmp_path, small_cap, monkeypatch):
        monkeypatch.setattr(loader_utils, "CACHE_TTL_SECONDS", 0.05)
        monkeypatch.setattr(loader_utils, "_last_freshness_fingerprint", "")
        _tree(tmp_path)
        loader_utils.check_data_freshness(str(tmp_path))
        epoch1 = loader_utils._freshness_epoch
        time.sleep(0.12)
        loader_utils.check_data_freshness(str(tmp_path))
        assert loader_utils._freshness_epoch > epoch1

    def test_dir_latest_mtime_saturation_rolls_over(
            self, tmp_path, small_cap, monkeypatch):
        d = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "CACHE_TTL_SECONDS", 0.05)
        v1 = loader_utils._get_dir_latest_mtime(d)
        time.sleep(0.12)
        v2 = loader_utils._get_dir_latest_mtime(d)
        assert v1 != v2
