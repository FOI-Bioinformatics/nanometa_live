"""Smoke tests for the get_genome_manager singleton.

Pinned behaviour:
  * First call returns a fresh GenomeDownloadManager.
  * Subsequent calls without arguments return the same instance.
  * Passing a different cache_dir reinitialises the singleton.
  * Passing offline_mode mutates the existing instance.
  * Concurrent first calls do NOT race -- under the
    double-checked-locking pattern landed 2026-05-02 the global is
    only ever assigned by one thread, so all callers see the same
    instance.

These tests do not exercise the network or subprocess code paths;
they only pin the locking and singleton-management contract.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from nanometa_live.core.utils import genome_manager as gm_module
from nanometa_live.core.utils.genome_manager import (
    GenomeDownloadManager,
    get_genome_manager,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Wipe the module-level instance before and after each test."""
    gm_module._genome_manager = None
    yield
    gm_module._genome_manager = None


class TestGetGenomeManagerSingleton:
    def test_first_call_returns_genome_manager(self, tmp_path):
        gm = get_genome_manager(cache_dir=str(tmp_path))
        assert isinstance(gm, GenomeDownloadManager)

    def test_subsequent_calls_return_same_instance(self, tmp_path):
        first = get_genome_manager(cache_dir=str(tmp_path))
        second = get_genome_manager()
        assert first is second

    def test_different_cache_dir_reinits(self, tmp_path):
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        path_a.mkdir()
        path_b.mkdir()
        first = get_genome_manager(cache_dir=str(path_a))
        second = get_genome_manager(cache_dir=str(path_b))
        assert first is not second
        assert second.cache_dir.resolve() == path_b.resolve()

    def test_offline_mode_toggle_mutates_existing(self, tmp_path):
        first = get_genome_manager(cache_dir=str(tmp_path), offline_mode=False)
        same = get_genome_manager(offline_mode=True)
        assert first is same
        assert same.offline_mode is True

    def test_offline_mode_toggle_back(self, tmp_path):
        get_genome_manager(cache_dir=str(tmp_path), offline_mode=True)
        again = get_genome_manager(offline_mode=False)
        assert again.offline_mode is False


class TestGetGenomeManagerThreadSafety:
    """Confirms double-checked locking actually works.

    The naive (lock-less) implementation would let two threads each
    construct a GenomeDownloadManager and race the global assignment;
    one of them is then orphaned. After the lock landed
    (2026-05-02), every concurrent caller sees the same instance.
    """

    def test_concurrent_first_calls_share_instance(self, tmp_path):
        cache = str(tmp_path)
        # 16 threads all trying to lazy-init at once. The barrier makes
        # them attempt the call closer to simultaneously than a plain
        # pool.submit loop would.
        n_threads = 16
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            return get_genome_manager(cache_dir=cache)

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            instances = list(pool.map(lambda _: worker(), range(n_threads)))

        # Every thread must observe the same singleton.
        first = instances[0]
        for inst in instances[1:]:
            assert inst is first, (
                "concurrent get_genome_manager() must not race; "
                "double-checked lock should serialise the first init"
            )
