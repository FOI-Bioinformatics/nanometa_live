"""Watchlist entries sharing an NCBI taxid must each get their own mapping.

``TaxidMappingCollection.mappings`` is a dict keyed by NCBI taxid, and
``generate_mappings`` wrote ``mappings[ncbi_taxid]`` per entry. GTDB splits a
polyphyletic species into several nodes and NCBI has no separate id for many
subspecies, so several watchlist entries legitimately carry ONE NCBI taxid and
different ``db_taxid`` values: the Bioshield list holds *E. coli*,
*E. coli_E* and *E. coli_F* on NCBI 562. Those three overwrote each other and
the collection kept one (audit 2026-11-06, finding 30).

That is a detection hole, not bookkeeping. ``_build_db_taxid_index`` builds the
database-taxid -> watchlist-entry map from exactly these mappings, so two of
the three database nodes resolved to no entry and a detection landing there
fell through to name matching or to nothing -- while ``WatchlistManager``
itself keeps all three entries, keyed by ``_identity_key``. The two structures
have to agree.

Entries that name the SAME node, or where either side states none, still share
the key: that is one organism arriving from two watchlist files.
"""

import pytest

from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    TaxidMapper,
    TaxidMappingCollection,
    set_database_index,
    set_mapping_collection,
    slim_mapping_store_payload,
)

pytestmark = pytest.mark.unit


# Three GTDB nodes for one NCBI species, plus an unrelated organism.
INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "40.00\t400\t400\tS\t4000549\tEscherichia coli\n"
    "20.00\t200\t200\tS\t4000558\tEscherichia coli_E\n"
    "10.00\t100\t100\tS\t4000553\tEscherichia coli_F\n"
    "10.00\t100\t100\tS\t1280\tStaphylococcus aureus\n"
)

COLI_TRIO = [
    {"name": "Escherichia coli", "taxid": 562, "db_taxid": 4000549},
    {"name": "Escherichia coli_E", "taxid": 562, "db_taxid": 4000558},
    {"name": "Escherichia coli_F", "taxid": 562, "db_taxid": 4000553},
]


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


def _db_taxids(collection):
    return {m.db_taxid for m in collection.mappings.values()}


class TestForksEachGetAMapping:
    def test_all_three_variants_are_mapped(self, mapper):
        collection = mapper.generate_mappings(COLI_TRIO)

        assert len(collection.mappings) == 3, (
            "entries sharing an NCBI taxid overwrote each other; "
            f"only {sorted(_db_taxids(collection))} is watched"
        )

    def test_every_database_node_is_reachable(self, mapper):
        collection = mapper.generate_mappings(COLI_TRIO)

        assert _db_taxids(collection) == {4000549, 4000558, 4000553}

    def test_the_reverse_index_resolves_each_node(self, mapper):
        """What detection actually reads."""
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )
        collection = mapper.generate_mappings(COLI_TRIO)
        index = WatchlistManager._build_db_taxid_index({}, collection)

        for node in (4000549, 4000558, 4000553):
            assert index.get(node), (
                f"database node {node} resolves to no watchlist entry"
            )

    def test_each_mapping_keeps_its_real_ncbi_taxid(self, mapper):
        """The fork key must not corrupt the NCBI identity a genome needs."""
        collection = mapper.generate_mappings(COLI_TRIO)

        assert {m.ncbi_taxid for m in collection.mappings.values()} == {562}

    def test_the_primary_entry_stays_on_its_ncbi_key(self, mapper):
        collection = mapper.generate_mappings(COLI_TRIO)

        assert 562 in collection.mappings
        assert collection.mappings[562].db_taxid == 4000549


class TestGenuineDuplicatesStillShareAKey:
    def test_the_same_node_twice_is_one_mapping(self, mapper):
        collection = mapper.generate_mappings([
            {"name": "Escherichia coli", "taxid": 562, "db_taxid": 4000549},
            {"name": "Escherichia coli", "taxid": 562, "db_taxid": 4000549},
        ])

        assert len(collection.mappings) == 1

    def test_an_entry_with_no_declared_node_keeps_the_taxid_key(self, mapper):
        collection = mapper.generate_mappings([
            {"name": "Staphylococcus aureus", "taxid": 1280},
        ])

        assert set(collection.mappings) == {1280}


class TestPersistence:
    def test_a_round_trip_keeps_three_mappings(self, mapper, tmp_path):
        collection = mapper.generate_mappings(COLI_TRIO)
        path = tmp_path / "mappings.json"
        assert collection.save(str(path)) is True

        reloaded = TaxidMappingCollection.load(str(path))

        assert reloaded is not None
        assert len(reloaded.mappings) == 3, (
            "the fork keys were not persisted, so a reload re-collapses the "
            "collection"
        )
        assert _db_taxids(reloaded) == {4000549, 4000558, 4000553}

    def test_a_rescan_does_not_duplicate_the_forks(self, mapper):
        mapper.generate_mappings(COLI_TRIO)
        collection = mapper.generate_mappings(COLI_TRIO, preserve_manual=True)

        assert len(collection.mappings) == 3

    def test_a_legacy_file_without_entry_key_still_loads(self, tmp_path):
        """Files written before the fix carry no entry_key."""
        path = tmp_path / "legacy.json"
        path.write_text(
            '{"version": "1.0", "database_path": "/db", "mappings": ['
            '{"ncbi_taxid": 562, "canonical_name": "Escherichia coli", '
            '"db_taxid": 4000549, "confidence": "manual"}]}'
        )

        collection = TaxidMappingCollection.load(str(path))

        assert collection is not None
        assert set(collection.mappings) == {562}
        assert collection.mappings[562].confidence == MappingConfidence.MANUAL


class TestTheBrowserStore:
    def test_the_slim_payload_keeps_every_variant(self, mapper):
        collection = mapper.generate_mappings(COLI_TRIO)

        payload = slim_mapping_store_payload(collection.to_dict())

        assert len(payload["mappings"]) == 3
        # The UI looks a row up by its NCBI taxid; the primary entry is there.
        assert "562" in payload["mappings"]
