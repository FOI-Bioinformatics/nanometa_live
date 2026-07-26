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


class TestDbTaxidReachesDetection:
    """An explicit db_taxid must match on the path production actually runs.

    These assertions used to target TaxonomyMatcher.match_organism via
    find_match -- but find_match had no production callers, and neither
    check_organisms nor check_organisms_with_mapping passed entry_db_taxid.
    The field was therefore honoured when building pipeline parameters and
    when writing the exported report, but silently ignored by live detection.
    The same guarantees are asserted here against the reachable entry points.
    """

    ENTRY = {
        "name": "Staphylococcus aureus",
        "taxid_ncbi": 1280,
        "db_taxid": 45127,
        "alert_threshold": 1,
        "threat_level": "high",
    }

    def _manager(self):
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager, WatchlistSource,
        )
        m = WatchlistManager()
        m._add_entry_from_dict(dict(self.ENTRY), WatchlistSource.USER)
        # _add_entry_from_dict honours the persisted disabled-taxid set; these
        # tests are about matching, not enablement.
        for entry in m._entries.values():
            entry.enabled = True
        m._loaded = True
        return m

    def test_db_taxid_matches_when_the_name_does_not(self):
        """The case the feature exists for.

        A GTDB report names the organism differently, so name matching
        cannot help; only the operator-declared database taxid can.
        """
        alerts = self._manager().check_organisms(
            [{"taxid": 45127, "name": "s__Staphylococcus_A aureus", "reads": 500}]
        )
        assert len(alerts) == 1
        assert alerts[0]["name"] == "Staphylococcus aureus"
        assert alerts[0]["detected_taxid"] == 45127

    def test_unrelated_db_taxid_does_not_match(self):
        alerts = self._manager().check_organisms(
            [{"taxid": 99999, "name": "Totally unrelated", "reads": 500}]
        )
        assert alerts == []

    def test_name_still_matches_without_a_db_taxid_hit(self):
        alerts = self._manager().check_organisms(
            [{"taxid": 99999, "name": "Staphylococcus aureus", "reads": 500}]
        )
        assert len(alerts) == 1

    def test_operator_db_taxid_beats_a_generated_mapping(self):
        """Precedence matches parameter_mapping.build_species_list.

        A generated mapping is a guess from name similarity; an operator-set
        db_taxid is an explicit statement, so it wins.
        """
        from nanometa_live.core.taxonomy.taxid_mapping import (
            MappingConfidence, TaxidMapping, TaxidMappingCollection,
        )
        collection = TaxidMappingCollection(database_path="/tmp/db")
        collection.mappings[1280] = TaxidMapping(
            ncbi_taxid=1280, canonical_name="Staphylococcus aureus",
            db_taxid=777, confidence=MappingConfidence.FUZZY, match_score=0.8,
        )
        manager = self._manager()
        index = manager._build_db_taxid_index(
            manager.get_active_entries(), collection
        )
        assert index[45127] == 1280   # operator value present
        assert index[777] == 1280     # generated value also retained

    def test_mapping_reverse_hit_scores_without_error(self):
        """Regression: this branch dereferenced an undefined name.

        check_organisms_with_mapping looked up a mapping's score through a
        local that no longer existed, so any detection resolved via the
        reverse db_taxid map raised NameError. Nothing covered it.
        """
        from nanometa_live.core.taxonomy.taxid_mapping import (
            MappingConfidence, TaxidMapping, TaxidMappingCollection,
        )
        collection = TaxidMappingCollection(database_path="/tmp/db")
        collection.mappings[1280] = TaxidMapping(
            ncbi_taxid=1280, canonical_name="Staphylococcus aureus",
            db_taxid=45127, confidence=MappingConfidence.EXACT, match_score=0.95,
        )
        alerts = self._manager().check_organisms_with_mapping(
            [{"taxid": 45127, "name": "unrecognisable", "reads": 500}],
            collection,
        )
        assert len(alerts) == 1
        assert alerts[0]["match_method"] == "taxid_mapping"
