"""Tests for the deterministic pseudo-taxid (A) and first-class custom DB taxid (B).

A: name-only / custom watchlist entries get a STABLE synthetic taxid across
process restarts (builtin hash() randomises str hashing per process, which
orphaned downloaded genomes and the taxid-mapping cache on every restart).

B: an explicit ``db_taxid`` (the organism's taxid in a GTDB/custom Kraken2
database, distinct from its NCBI taxid) is carried from YAML/UI through to
detection matching and pipeline filtering, so an operator running a GTDB DB does
not have to rely on "Scan Database" auto-mapping.
"""

import pytest

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistEntry,
    _stable_pseudo_taxid,
    _PSEUDO_TAXID_BASE,
)
from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader
from nanometa_live.core.watchlist.taxonomy_matcher import TaxonomyMatcher

pytestmark = pytest.mark.unit


class TestDeterministicPseudoTaxid:
    def test_stable_and_case_space_insensitive(self):
        a = _stable_pseudo_taxid("Bacillus anthracis")
        b = _stable_pseudo_taxid("  bacillus ANTHRACIS ")
        assert a == b

    def test_in_dedicated_band_above_ncbi_taxids(self):
        # Band [2e9, 3e9) keeps pseudo-taxids clear of real NCBI taxids (<~10M).
        v = _stable_pseudo_taxid("Clostridium botulinum")
        assert _PSEUDO_TAXID_BASE <= v < _PSEUDO_TAXID_BASE + 1_000_000_000

    def test_distinct_names_distinct_ids(self):
        assert _stable_pseudo_taxid("Yersinia pestis") != _stable_pseudo_taxid("Francisella tularensis")

    def test_name_only_entry_keyed_deterministically(self):
        # A name-only entry's taxid is the stable pseudo-taxid, not a random hash.
        e = WatchlistEntry.from_dict({"name": "Novel sp."})
        # from_dict leaves taxid 0; the manager assigns the pseudo-taxid on add.
        assert e.taxid == 0
        assert _stable_pseudo_taxid("Novel sp.") == _stable_pseudo_taxid("novel sp.")


class TestCustomDbTaxidParsing:
    @pytest.mark.parametrize("key", ["db_taxid", "kraken_taxid", "taxid_custom", "taxid_gtdb"])
    def test_from_dict_accepts_aliases(self, key):
        e = WatchlistEntry.from_dict({"name": "Staphylococcus aureus", "taxid_ncbi": 1280, key: 45127})
        assert e.db_taxid == 45127
        assert e.taxid == 1280  # NCBI taxid preserved separately

    def test_to_dict_round_trips_db_taxid(self):
        e = WatchlistEntry.from_dict({"name": "S. aureus", "taxid_ncbi": 1280, "db_taxid": 45127})
        assert e.to_dict()["db_taxid"] == 45127
        assert WatchlistEntry.from_dict(e.to_dict()).db_taxid == 45127

    def test_absent_db_taxid_is_none_and_omitted(self):
        e = WatchlistEntry.from_dict({"name": "S. aureus", "taxid_ncbi": 1280})
        assert e.db_taxid is None
        assert "db_taxid" not in e.to_dict()

    def test_loader_parses_db_taxid(self, tmp_path):
        from pathlib import Path
        wl = tmp_path / "custom.yaml"
        wl.write_text(
            "name: Custom\n"
            "pathogens:\n"
            "  - name: Bacillus anthracis\n"
            "    taxid_ncbi: 1392\n"
            "    kraken_taxid: 86661\n"
        )
        entries = WatchlistLoader()._load_pathogens_from_file(Path(wl))
        assert entries[0].db_taxid == 86661


class TestMatcherUsesDbTaxid:
    def test_explicit_db_taxid_matches_any_db_type(self):
        m = TaxonomyMatcher()
        # Detected taxid is the report's DB (GTDB) taxid; name is GTDB-mangled.
        score = m.match_organism(
            {"taxid": 45127, "name": "s__Staphylococcus aureus"},
            "Staphylococcus aureus",
            entry_db_taxid=45127,
        )
        assert score == 1.0

    def test_db_taxid_mismatch_falls_through_to_name(self):
        m = TaxonomyMatcher()
        # Wrong db_taxid but the name still matches exactly -> name match wins.
        score = m.match_organism(
            {"taxid": 99999, "name": "Staphylococcus aureus"},
            "Staphylococcus aureus",
            entry_db_taxid=45127,
        )
        assert score == 1.0  # via exact name match, not taxid

    def test_no_match_when_both_differ(self):
        m = TaxonomyMatcher()
        score = m.match_organism(
            {"taxid": 99999, "name": "Totally unrelated"},
            "Staphylococcus aureus",
            entry_db_taxid=45127,
        )
        assert score == 0.0

    def test_find_match_passes_db_taxid(self):
        m = TaxonomyMatcher()
        result = m.find_match(
            {"taxid": 45127, "name": "gtdb_mangled"},
            [{"name": "Staphylococcus aureus", "taxid": 1280, "db_taxid": 45127}],
            threshold=0.8,
        )
        assert result is not None and result[1] == 1.0
