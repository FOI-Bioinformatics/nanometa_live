"""
Unit tests for the network-free core of core/taxonomy/taxid_mapping.py.

Covers the data structures that back the NCBI<->Kraken2 taxid mapping system:
TaxidMapping (mapped/needs-review logic, JSON round-trip), the lineage walk on
DatabaseTaxonomyIndex, TaxidMappingCollection (statistics + save/load), and the
module-level singletons. The API-driven generate_mappings strategy engine needs
mocked network clients and is intentionally out of scope here.
"""

import pytest

from nanometa_live.core.taxonomy import taxid_mapping as tm
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
    MappingConfidence,
    TaxidMapping,
    TaxidMappingCollection,
    get_database_hash,
    get_mapping_cache_path,
    get_mapping_collection,
    set_mapping_collection,
)


@pytest.fixture(autouse=True)
def _restore_singleton():
    yield
    set_mapping_collection(None)


def _node(taxid, name, rank, parent):
    return DatabaseTaxonomyNode(
        taxid=taxid, name=name, rank=rank, parent_taxid=parent,
        name_normalized=name.lower(),
    )


class TestTaxidMapping:
    def test_unmapped_by_default(self):
        m = TaxidMapping(ncbi_taxid=562, canonical_name="Escherichia coli")
        assert m.is_mapped() is False

    def test_is_mapped_when_db_taxid_and_confidence_set(self):
        m = TaxidMapping(
            ncbi_taxid=562, canonical_name="Escherichia coli",
            db_taxid=999, confidence=MappingConfidence.EXACT,
        )
        assert m.is_mapped() is True

    def test_fuzzy_needs_review(self):
        m = TaxidMapping(
            ncbi_taxid=562, canonical_name="E. coli",
            db_taxid=999, confidence=MappingConfidence.FUZZY,
        )
        assert m.needs_review() is True

    def test_manually_verified_skips_review(self):
        m = TaxidMapping(
            ncbi_taxid=562, canonical_name="E. coli",
            db_taxid=999, confidence=MappingConfidence.FUZZY,
            manually_verified=True,
        )
        assert m.needs_review() is False

    def test_round_trip(self):
        m = TaxidMapping(
            ncbi_taxid=562, canonical_name="Escherichia coli",
            db_taxid=999, confidence=MappingConfidence.EXACT, match_score=1.0,
        )
        restored = TaxidMapping.from_dict(m.to_dict())
        assert restored.ncbi_taxid == 562
        assert restored.db_taxid == 999
        assert restored.confidence == MappingConfidence.EXACT


class TestLineage:
    @pytest.fixture
    def index(self):
        idx = DatabaseTaxonomyIndex(database_path="/db")
        for n in [
            _node(2, "Bacteria", "D", 1),
            _node(1224, "Proteobacteria", "P", 2),
            _node(561, "Escherichia", "G", 1224),
            _node(562, "Escherichia coli", "S", 561),
        ]:
            idx.by_taxid[n.taxid] = n
        return idx

    def test_lineage_is_root_to_species(self, index):
        lineage = index.get_lineage(562)
        assert [n.taxid for n in lineage] == [2, 1224, 561, 562]

    def test_lineage_string(self, index):
        s = index.get_lineage_string(562)
        assert s == (
            "Domain: Bacteria > Phylum: Proteobacteria > "
            "Genus: Escherichia > Species: Escherichia coli"
        )

    def test_unknown_taxid_yields_empty(self, index):
        assert index.get_lineage(99999) == []
        assert index.get_lineage_string(99999) == ""


class TestTaxidMappingCollection:
    def _collection(self):
        coll = TaxidMappingCollection(database_path="/db")
        coll.mappings[562] = TaxidMapping(
            ncbi_taxid=562, canonical_name="Escherichia coli",
            db_taxid=999, confidence=MappingConfidence.EXACT,
        )
        coll.mappings[1280] = TaxidMapping(
            ncbi_taxid=1280, canonical_name="Staphylococcus aureus",
            confidence=MappingConfidence.UNMAPPED,
        )
        return coll

    def test_get_mapping_and_db_taxid(self):
        coll = self._collection()
        assert coll.get_mapping(562).db_taxid == 999
        assert coll.get_db_taxid(562) == 999
        # Unmapped entry resolves to None.
        assert coll.get_db_taxid(1280) is None

    def test_update_statistics(self):
        coll = self._collection()
        coll.update_statistics()
        assert coll.total_entries == 2
        assert coll.mapped_exact == 1
        assert coll.unmapped == 1

    def test_save_and_load_round_trip(self, tmp_path):
        coll = self._collection()
        coll.update_statistics()
        path = tmp_path / "mappings.json"
        assert coll.save(str(path)) is True

        loaded = TaxidMappingCollection.load(str(path))
        assert loaded is not None
        assert loaded.get_db_taxid(562) == 999
        assert loaded.total_entries == 2

    def test_load_missing_returns_none(self, tmp_path):
        assert TaxidMappingCollection.load(str(tmp_path / "nope.json")) is None


class TestModuleHelpers:
    def test_set_get_mapping_collection(self):
        coll = TaxidMappingCollection(database_path="/db")
        set_mapping_collection(coll)
        assert get_mapping_collection() is coll

    def test_database_hash_is_stable_string(self, tmp_path):
        (tmp_path / "hash.k2d").write_bytes(b"abc")
        h1 = get_database_hash(str(tmp_path))
        h2 = get_database_hash(str(tmp_path))
        assert isinstance(h1, str)
        assert h1 == h2

    def test_mapping_cache_path_is_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        path = get_mapping_cache_path(str(tmp_path / "db"))
        assert str(path).endswith(".json")
