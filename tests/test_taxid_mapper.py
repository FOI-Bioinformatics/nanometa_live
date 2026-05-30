"""
End-to-end tests for the TaxidMapper engine in core/taxonomy/taxid_mapping.py.

generate_mappings and set_manual_mapping match watchlist entries against the
locally-built database index (no network), so the full flow is exercised here:
load a database from a synthetic inspect.txt, map entries (exact-taxid hit vs
unmapped), and apply / reject a manual override. All caches are redirected to
tmp_path via NANOMETA_DATA_DIR and an explicit cache_dir so the real
~/.nanometa is never touched.
"""

import pytest

from nanometa_live.core.taxonomy import taxid_mapping as tm
from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    TaxidMapper,
    set_database_index,
    set_mapping_collection,
)

INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "50.00\t500\t500\tS\t562\tEscherichia coli\n"
    "30.00\t300\t300\tS\t1280\tStaphylococcus aureus\n"
)


@pytest.fixture(autouse=True)
def _reset_globals():
    yield
    set_mapping_collection(None)
    set_database_index(None)


@pytest.fixture
def mapper(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    db_dir = tmp_path / "kraken2_db"
    db_dir.mkdir()
    (db_dir / "inspect.txt").write_text(INSPECT)
    m = TaxidMapper(cache_dir=str(tmp_path / "idxcache"))
    assert m.load_database(str(db_dir)) is True
    return m


class TestGenerateMappings:
    def test_exact_taxid_entry_is_mapped(self, mapper):
        collection = mapper.generate_mappings([
            {"name": "Escherichia coli", "taxid": 562},
        ])
        assert collection.get_db_taxid(562) == 562
        assert collection.get_mapping(562).is_mapped() is True

    def test_unknown_entry_is_unmapped(self, mapper):
        collection = mapper.generate_mappings([
            {"name": "Imaginary nonexistus", "taxid": 99999},
        ])
        assert collection.get_db_taxid(99999) is None

    def test_statistics_reflect_entries(self, mapper):
        collection = mapper.generate_mappings([
            {"name": "Escherichia coli", "taxid": 562},
            {"name": "Staphylococcus aureus", "taxid": 1280},
        ])
        assert collection.total_entries == 2

    def test_generate_without_loaded_index_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        fresh = TaxidMapper(cache_dir=str(tmp_path / "c"))
        with pytest.raises(RuntimeError):
            fresh.generate_mappings([{"name": "X", "taxid": 1}])


class TestSetManualMapping:
    def test_manual_override_applied(self, mapper):
        mapper.generate_mappings([{"name": "Imaginary", "taxid": 99999}])
        ok = mapper.set_manual_mapping(99999, 562, reason="verified by hand")
        assert ok is True
        mapping = tm.get_mapping_collection().get_mapping(99999)
        assert mapping.db_taxid == 562
        assert mapping.confidence == MappingConfidence.MANUAL
        assert mapping.manually_verified is True

    def test_manual_mapping_to_unknown_db_taxid_fails(self, mapper):
        mapper.generate_mappings([{"name": "Escherichia coli", "taxid": 562}])
        assert mapper.set_manual_mapping(562, 88888, reason="bad target") is False
