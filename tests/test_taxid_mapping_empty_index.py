"""
Regression tests for the empty-index defenses in
``core.taxonomy.taxid_mapping.TaxidMapper``.

These tests cover Bug A from the 2026-05-08 evaluation: after wiping
``~/.nanometa`` (or otherwise leaving a partially-written cache file),
the mapper used to silently produce all-UNMAPPED ("Not Found")
results because ``DatabaseTaxonomyIndex`` tolerated ``nodes=[]`` and
the ``generate_mappings`` guard checked only ``if not self._index``.

The fixes treat an empty ``by_taxid`` as a stale cache, force a
rebuild, and raise on a structurally empty index.
"""

import json
from unittest.mock import patch

import pytest

from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyType,
    DatabaseTaxonomyNode,
    TaxidMapper,
    get_database_hash,
)


def _make_minimal_index_dict(database_path: str = "/tmp/dummy_db") -> dict:
    """Return a serialisable index dict with zero nodes."""
    empty_index = DatabaseTaxonomyIndex(
        database_path=database_path,
        database_type=DatabaseTaxonomyType.NCBI,
    )
    return empty_index.to_dict()


def _make_populated_index(database_path: str = "/tmp/dummy_db") -> DatabaseTaxonomyIndex:
    """Return an index with one species node, suitable for round-tripping."""
    index = DatabaseTaxonomyIndex(
        database_path=database_path,
        database_type=DatabaseTaxonomyType.NCBI,
        total_nodes=1,
        species_count=1,
    )
    node = DatabaseTaxonomyNode(
        taxid=562,
        name="Escherichia coli",
        rank="S",
        parent_taxid=561,
    )
    index.by_taxid[node.taxid] = node
    if node.name_normalized:
        index.by_name.setdefault(node.name_normalized, []).append(node.taxid)
    index.build_prefix_index()
    return index


class TestEmptyCacheRecovery:
    """``load_database`` must treat an empty cache as stale."""

    def test_empty_cache_triggers_rebuild(self, tmp_path):
        """An on-disk cache with ``nodes=[]`` should be deleted and the
        index rebuilt from the live database."""
        cache_dir = tmp_path / "mappings"
        cache_dir.mkdir()
        database_path = str(tmp_path / "dummy_db")
        # The cache filename uses the same hash function the mapper uses.
        db_hash = get_database_hash(database_path)
        cache_file = cache_dir / f"{db_hash}_index.json"
        cache_file.write_text(json.dumps(_make_minimal_index_dict(database_path)))

        mapper = TaxidMapper(cache_dir=str(cache_dir))

        populated = _make_populated_index(database_path)
        with patch.object(
            mapper._index_builder, "build_index", return_value=populated
        ) as build_index:
            assert mapper.load_database(database_path) is True

        build_index.assert_called_once()
        assert mapper._index is not None
        assert mapper._index.by_taxid, "rebuilt index must contain nodes"
        # The empty cache file must have been re-written from the rebuild.
        on_disk = json.loads(cache_file.read_text())
        assert on_disk.get("nodes"), "rebuilt cache should not be empty"

    def test_post_rebuild_empty_index_raises(self, tmp_path):
        """If the rebuild itself produces an empty index, the loader
        must refuse rather than continue with a degenerate index."""
        cache_dir = tmp_path / "mappings"
        cache_dir.mkdir()
        database_path = str(tmp_path / "dummy_db")

        mapper = TaxidMapper(cache_dir=str(cache_dir))
        empty_index = DatabaseTaxonomyIndex(
            database_path=database_path,
            database_type=DatabaseTaxonomyType.NCBI,
        )
        with patch.object(mapper._index_builder, "build_index", return_value=empty_index):
            with pytest.raises(RuntimeError, match="zero"):
                mapper.load_database(database_path)


class TestRoundTripSerialisation:
    """The serialise/deserialise round-trip must preserve nodes."""

    def test_populated_index_round_trip(self, tmp_path):
        """A populated index should survive ``to_dict``/``from_dict``."""
        original = _make_populated_index()
        restored = DatabaseTaxonomyIndex.from_dict(original.to_dict())
        assert restored.by_taxid, "restored index must not be empty"
        assert 562 in restored.by_taxid
        assert restored.by_taxid[562].name == "Escherichia coli"

    def test_empty_dict_yields_empty_index(self):
        """``from_dict`` still tolerates an empty payload at the
        dataclass level; the higher-level guard catches it in
        ``load_database`` and ``generate_mappings``."""
        empty = DatabaseTaxonomyIndex.from_dict(_make_minimal_index_dict())
        assert empty.by_taxid == {}


class TestGenerateMappingsGuard:
    """``generate_mappings`` must reject an empty ``by_taxid``."""

    def test_no_index_raises(self):
        mapper = TaxidMapper.__new__(TaxidMapper)
        mapper._index = None
        with pytest.raises(RuntimeError, match="not loaded or is empty"):
            mapper.generate_mappings([{"name": "Escherichia coli", "taxid": 562}])

    def test_empty_index_raises(self):
        mapper = TaxidMapper.__new__(TaxidMapper)
        mapper._index = DatabaseTaxonomyIndex(
            database_path="/tmp/x",
            database_type=DatabaseTaxonomyType.NCBI,
        )
        with pytest.raises(RuntimeError, match="not loaded or is empty"):
            mapper.generate_mappings([{"name": "Escherichia coli", "taxid": 562}])
