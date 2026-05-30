"""
Unit tests for core/utils/offline_cache.py.

A JSON-backed TTL cache for taxonomy lookups, used to support air-gapped
operation. All state is written under a tmp_path cache dir; the module-level
singleton is reset between tests and NANOMETA_DATA_DIR is redirected so the
factory never touches the real ~/.nanometa.

Expiry is forced with a negative TTL rather than sleeps to stay deterministic.
"""

import json

import pytest

from nanometa_live.core.utils import offline_cache as oc
from nanometa_live.core.utils.offline_cache import OfflineTaxonomyCache


@pytest.fixture(autouse=True)
def _reset_singleton():
    oc._cache_instance = None
    yield
    oc._cache_instance = None


@pytest.fixture
def cache(tmp_path):
    return OfflineTaxonomyCache(cache_dir=str(tmp_path / "cache"))


class TestGetSet:
    def test_round_trip(self, cache):
        assert cache.set("Escherichia coli", {"rank": "species"}, cache_type="gtdb")
        assert cache.get("Escherichia coli", cache_type="gtdb") == {"rank": "species"}

    def test_miss_returns_none(self, cache):
        assert cache.get("never cached") is None

    def test_expired_entry_returns_none(self, cache):
        cache.set("x", {"v": 1}, ttl=-100)
        assert cache.get("x") is None

    def test_offline_mode_serves_expired(self, tmp_path):
        cache = OfflineTaxonomyCache(cache_dir=str(tmp_path / "c"), offline_mode=True)
        cache.set("x", {"v": 1}, ttl=-100)
        assert cache.get("x") == {"v": 1}


class TestTypedHelpers:
    def test_species_info_round_trip(self, cache):
        cache.cache_species_info(562, {"name": "Escherichia coli"})
        assert cache.get_species_info(562) == {"name": "Escherichia coli"}

    def test_gtdb_and_ncbi_namespaces_are_separate(self, cache):
        cache.cache_gtdb_taxonomy("E. coli", {"src": "gtdb"})
        cache.cache_ncbi_taxonomy(562, {"src": "ncbi"})
        assert cache.get_gtdb_taxonomy("E. coli") == {"src": "gtdb"}
        assert cache.get_ncbi_taxonomy(562) == {"src": "ncbi"}
        # The gtdb key must not leak into the species namespace.
        assert cache.get_species_info(562) is None


class TestSnapshots:
    def test_load_then_export_round_trip(self, cache, tmp_path):
        snapshot = tmp_path / "snap.json"
        snapshot.write_text(json.dumps({
            "gtdb": {"E. coli": {"a": 1}},
            "ncbi": {"562": {"b": 2}},
            "species": {"562": {"c": 3}},
        }))
        loaded = cache.load_snapshot(str(snapshot))
        assert loaded == 3

        out = tmp_path / "out.json"
        exported = cache.export_snapshot(str(out))
        assert exported == 3
        data = json.loads(out.read_text())
        # Export keys are the filename-sanitised identifiers, so a name with a
        # space round-trips in its sanitised form ("E. coli" -> "E._coli").
        assert data["gtdb"]["E._coli"] == {"a": 1}
        assert data["species"]["562"] == {"c": 3}

    def test_missing_snapshot_loads_nothing(self, cache, tmp_path):
        assert cache.load_snapshot(str(tmp_path / "nope.json")) == 0


class TestClear:
    def test_clear_expired_removes_only_expired(self, cache):
        cache.set("fresh", {"v": 1}, cache_type="species")
        cache.set("stale", {"v": 2}, cache_type="species", ttl=-100)
        removed = cache.clear_expired()
        assert removed == 1
        assert cache.get("fresh", cache_type="species") == {"v": 1}
        assert cache.get("stale", cache_type="species") is None

    def test_clear_all(self, cache):
        cache.set("a", {"v": 1}, cache_type="gtdb")
        cache.set("b", {"v": 2}, cache_type="ncbi")
        assert cache.clear_all() == 2
        assert cache.get("a", cache_type="gtdb") is None


class TestStats:
    def test_counts_entries_by_type(self, cache):
        cache.cache_gtdb_taxonomy("E. coli", {"x": 1})
        cache.cache_ncbi_taxonomy(562, {"x": 1})
        cache.set("stale", {"v": 1}, cache_type="species", ttl=-100)
        stats = cache.get_stats()
        assert stats["gtdb_entries"] == 1
        assert stats["ncbi_entries"] == 1
        assert stats["species_entries"] == 1
        assert stats["total_entries"] == 3
        assert stats["expired_entries"] == 1


class TestGetCacheFactory:
    def test_returns_singleton(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        first = oc.get_cache()
        second = oc.get_cache()
        assert first is second

    def test_offline_mode_toggle_updates_instance(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        inst = oc.get_cache(offline_mode=False)
        assert inst.offline_mode is False
        same = oc.get_cache(offline_mode=True)
        assert same is inst
        assert same.offline_mode is True
