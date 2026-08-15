"""What a watchlist can actually be screened for against a given database.

Written against the shapes a real flextaxd field database produces: an NCBI
backbone with GTDB-derived clades grafted in at high taxids, minimized so
that some organisms are pruned entirely. Each test names the operational
consequence it protects against, because the failure mode here is silence --
an organism that cannot be detected reports exactly like one that was looked
for and not found.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.taxonomy.coverage import analyse_coverage
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
    MappingConfidence,
    TaxidMapping,
    TaxidMappingCollection,
)

pytestmark = pytest.mark.unit


def _collection(*rows):
    """rows: (ncbi_taxid, entry_name, db_taxid, db_name, confidence)."""
    c = TaxidMappingCollection(database_path="/tmp/db")
    for ncbi_taxid, name, db_taxid, db_name, confidence in rows:
        c.mappings[ncbi_taxid] = TaxidMapping(
            ncbi_taxid=ncbi_taxid, canonical_name=name,
            db_taxid=db_taxid, db_name=db_name, confidence=confidence,
        )
    return c


def _index(*nodes):
    """nodes: (taxid, name, rank)."""
    idx = DatabaseTaxonomyIndex(database_path="/tmp/db")
    for taxid, name, rank in nodes:
        idx.by_taxid[taxid] = DatabaseTaxonomyNode(
            taxid=taxid, name=name, rank=rank, name_normalized=name.lower()
        )
    return idx


class TestAbsentOrganisms:
    def test_unmapped_entry_is_reported_absent(self):
        """The safety case: a pruned organism cannot produce a negative result.

        Field databases are minimized to fit a laptop's RAM, so watchlist
        organisms are sometimes simply not present. Reported on a real
        Bioshield build for Giardia, Entamoeba, Cryptosporidium and Poliovirus.
        """
        cov = analyse_coverage(_collection(
            (5741, "Giardia duodenalis", None, None, MappingConfidence.UNMAPPED),
        ))
        assert cov.absent == ["Giardia duodenalis"]
        assert cov.has_gaps is True
        assert "cannot be detected at all" in cov.warnings()[0]

    def test_absent_leads_the_warnings(self):
        """It is the one an operator cannot mitigate by reading more carefully."""
        cov = analyse_coverage(_collection(
            (1, "Absent organism", None, None, MappingConfidence.UNMAPPED),
            (2, "Shared a", 900, "Shared node", MappingConfidence.FUZZY),
            (3, "Shared b", 900, "Shared node", MappingConfidence.FUZZY),
        ))
        assert "cannot be detected at all" in cov.warnings()[0]


class TestAmbiguousNodes:
    def test_entries_sharing_a_node_are_flagged(self):
        """Real case: every Shigella species sits under Escherichia coli.

        Previously these silently overwrote each other in the reverse lookup,
        so all but one vanished with no warning -- and which one survived was
        arbitrary.
        """
        cov = analyse_coverage(_collection(
            (623, "Shigella flexneri", 4001, "Escherichia coli", MappingConfidence.FUZZY),
            (624, "Shigella sonnei", 4001, "Escherichia coli", MappingConfidence.FUZZY),
            (562, "Escherichia coli", 4001, "Escherichia coli", MappingConfidence.EXACT),
        ), _index((4001, "Escherichia coli", "S")))
        assert set(cov.ambiguous["Escherichia coli"]) == {
            "Shigella flexneri", "Shigella sonnei", "Escherichia coli"
        }
        assert "cannot tell them apart" in " ".join(cov.warnings())

    def test_two_select_agents_on_one_node_is_surfaced(self):
        """Burkholderia mallei and pseudomallei are distinct select agents.

        A real Bioshield build carries pseudomallei only as a subspecies of
        mallei, so a detection cannot say which disease it indicates --
        glanders or melioidosis.
        """
        cov = analyse_coverage(_collection(
            (13373, "Burkholderia mallei", 4003703, "Burkholderia mallei",
             MappingConfidence.EXACT),
            (28450, "Burkholderia pseudomallei", 4003703, "Burkholderia mallei",
             MappingConfidence.PARTIAL),
        ), _index((4003703, "Burkholderia mallei", "S")))
        assert len(cov.ambiguous) == 1

    def test_distinct_nodes_are_not_flagged(self):
        cov = analyse_coverage(_collection(
            (1, "Organism one", 100, "Node one", MappingConfidence.EXACT),
            (2, "Organism two", 200, "Node two", MappingConfidence.EXACT),
        ), _index((100, "Node one", "S"), (200, "Node two", "S")))
        assert cov.ambiguous == {}
        assert cov.has_gaps is False


class TestGenusOnly:
    def test_species_entry_matching_a_genus_is_flagged(self):
        """A genus hit is not a species detection.

        Brucella abortus resolving to the bare genus means any Brucella --
        including species that are not select agents -- would alert as
        B. abortus.
        """
        cov = analyse_coverage(_collection(
            (235, "Brucella abortus", 4005, "Brucella", MappingConfidence.PARTIAL),
        ), _index((4005, "Brucella", "G")))
        assert cov.genus_only == [("Brucella abortus", "Brucella")]

    def test_family_level_entry_matching_a_family_is_not_flagged(self):
        """Do not cry wolf.

        A watchlist entry that names a family got exactly what it asked for.
        Flagging it would bury the real gaps and train operators to skip the
        report.
        """
        cov = analyse_coverage(_collection(
            (10508, "Adenoviridae", 4009, "Adenoviridae", MappingConfidence.EXACT),
            (12059, "Enterovirus", 4010, "Enterovirus", MappingConfidence.EXACT),
        ), _index((4009, "Adenoviridae", "F"), (4010, "Enterovirus", "G")))
        assert cov.genus_only == []
        assert set(cov.detectable) == {"Adenoviridae", "Enterovirus"}

    def test_species_match_is_detectable(self):
        cov = analyse_coverage(_collection(
            (1392, "Bacillus anthracis", 4005020, "Bacillus_A anthracis",
             MappingConfidence.FUZZY),
        ), _index((4005020, "Bacillus_A anthracis", "S")))
        assert cov.detectable == ["Bacillus anthracis"]
        assert cov.genus_only == []

    def test_subspecies_counts_as_species_level(self):
        """S1 nodes are finer than species, not broader."""
        cov = analyse_coverage(_collection(
            (263, "Francisella tularensis", 4007187,
             "Francisella tularensis holarctica", MappingConfidence.EXACT),
        ), _index((4007187, "Francisella tularensis holarctica", "S1")))
        assert cov.detectable == ["Francisella tularensis"]


class TestSummary:
    def test_counts_every_entry_exactly_once(self):
        cov = analyse_coverage(_collection(
            (1, "Detectable sp", 100, "Detectable sp", MappingConfidence.EXACT),
            (2, "Genus sp", 200, "Genus", MappingConfidence.PARTIAL),
            (3, "Missing sp", None, None, MappingConfidence.UNMAPPED),
        ), _index((100, "Detectable sp", "S"), (200, "Genus", "G")))
        assert cov.total == 3
        assert "1/3 detectable at species level" in cov.summary()
        assert "1 genus-only" in cov.summary()
        assert "1 absent from database" in cov.summary()

    def test_clean_database_says_so_without_caveats(self):
        cov = analyse_coverage(_collection(
            (1, "Organism one", 100, "Organism one", MappingConfidence.EXACT),
        ), _index((100, "Organism one", "S")))
        assert cov.summary() == "1/1 detectable at species level"
        assert cov.warnings() == []

    def test_empty_watchlist_is_not_an_error(self):
        cov = analyse_coverage(_collection())
        assert cov.total == 0
        assert "No watchlist entries" in cov.summary()


class TestRankFallback:
    def test_works_without_an_index(self):
        """The index is optional; name shape is the weaker fallback."""
        cov = analyse_coverage(_collection(
            (1, "Genus sp", 200, "Genus", MappingConfidence.PARTIAL),
            (2, "Species one", 100, "Species one", MappingConfidence.EXACT),
        ))
        assert cov.genus_only == [("Genus sp", "Genus")]
        assert cov.detectable == ["Species one"]


class TestSharedNodeReachesTheAlert:
    """A detection on a shared node must not name one organism confidently.

    GTDB treats Burkholderia mallei as a lineage within pseudomallei, so a
    flextaxd database built on it carries one node for both. Glanders and
    melioidosis are different diseases; announcing one when the data cannot
    distinguish them is a false identification on a biothreat panel. This is
    an upstream taxonomy limitation, not something the app can resolve, so
    the app has to report it rather than hide it.
    """

    def _manager_with_shared_node(self):
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager, WatchlistSource,
        )
        m = WatchlistManager()
        for d in (
            {"name": "Burkholderia mallei", "taxid_ncbi": 13373,
             "threat_level": "critical", "alert_threshold": 1},
            {"name": "Burkholderia pseudomallei", "taxid_ncbi": 28450,
             "threat_level": "critical", "alert_threshold": 1},
        ):
            m._add_entry_from_dict(d, WatchlistSource.USER)
        for e in m._entries.values():
            e.enabled = True
        m._loaded = True
        return m

    def _collection(self):
        c = TaxidMappingCollection(database_path="/db")
        for ncbi, name in ((13373, "Burkholderia mallei"),
                           (28450, "Burkholderia pseudomallei")):
            c.mappings[ncbi] = TaxidMapping(
                ncbi_taxid=ncbi, canonical_name=name, db_taxid=4003703,
                db_name="Burkholderia mallei",
                confidence=MappingConfidence.EXACT, match_score=1.0,
            )
        return c

    def test_alert_names_the_other_organism(self):
        alerts = self._manager_with_shared_node().check_organisms_with_mapping(
            [{"taxid": 4003703, "name": "Burkholderia mallei", "reads": 900}],
            self._collection(),
        )
        assert len(alerts) == 1
        assert alerts[0]["ambiguous_with"] == ["Burkholderia pseudomallei"]

    def test_unshared_node_carries_no_ambiguity(self):
        """Do not attach a caveat where the identification is sound."""
        c = TaxidMappingCollection(database_path="/db")
        c.mappings[13373] = TaxidMapping(
            ncbi_taxid=13373, canonical_name="Burkholderia mallei",
            db_taxid=4003703, db_name="Burkholderia mallei",
            confidence=MappingConfidence.EXACT, match_score=1.0,
        )
        alerts = self._manager_with_shared_node().check_organisms_with_mapping(
            [{"taxid": 4003703, "name": "Burkholderia mallei", "reads": 900}], c
        )
        assert alerts[0]["ambiguous_with"] == []

    def test_no_watchlist_entry_is_dropped_by_a_shared_node(self):
        """Both entries survive in the index, in a stable order.

        Last-writer-wins previously kept an arbitrary one and discarded the
        rest without a word.
        """
        m = self._manager_with_shared_node()
        index = m._build_db_taxid_index(m.get_active_entries(), self._collection())
        assert index[4003703] == [13373, 28450]


class TestOrganismsTabAgreesWithItsBanner:
    """The badge/cards path and the alert-banner path must agree.

    ``filter_detected_species`` drives the alert banner and
    ``get_all_watchlist_with_detection`` drives the cards. Their own comments
    say they must use the same matching strategy, but they guarded on
    different inputs: the banner bailed whenever the legacy ``watchlist``
    argument was empty, even with a fully populated WatchlistManager. A run
    whose watchlist comes from YAML rather than legacy config therefore
    showed detections on the cards while the banner stayed silent.
    """

    def _setup(self, monkeypatch):
        import nanometa_live.core.watchlist.watchlist_manager as wm
        from nanometa_live.core.taxonomy.taxid_mapping import (
            set_mapping_collection,
        )
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager, WatchlistSource,
        )
        m = WatchlistManager()
        m._add_entry_from_dict(
            {"name": "Escherichia coli", "taxid_ncbi": 562,
             "threat_level": "high", "alert_threshold": 1},
            WatchlistSource.USER,
        )
        for e in m._entries.values():
            e.enabled = True
        m._loaded = True
        monkeypatch.setattr(wm, "_watchlist_manager", m)

        coll = TaxidMappingCollection(database_path="/db")
        coll.mappings[562] = TaxidMapping(
            ncbi_taxid=562, canonical_name="Escherichia coli", db_taxid=4001,
            db_name="Escherichia coli", confidence=MappingConfidence.EXACT,
            match_score=1.0,
        )
        set_mapping_collection(coll)
        return m

    def _kraken(self):
        import pandas as pd
        return pd.DataFrame([{
            "taxid": 4001, "name": "Escherichia coli", "rank": "S",
            "reads": 5000, "cumul_reads": 5000, "%": 4.2,
        }])

    def test_banner_fires_when_only_the_manager_is_populated(self, monkeypatch):
        from nanometa_live.app.tabs import main_tab_helpers as mth
        self._setup(monkeypatch)
        detected = mth.filter_detected_species(self._kraken(), [])
        assert [d["name"] for d in detected] == ["Escherichia coli"]

    def test_both_paths_report_the_same_organism(self, monkeypatch):
        from nanometa_live.app.tabs import main_tab_helpers as mth
        self._setup(monkeypatch)
        kraken = self._kraken()
        banner = {d["name"] for d in mth.filter_detected_species(kraken, [])}
        cards = {r["name"] for r in mth.get_all_watchlist_with_detection(kraken, [])
                 if r["detected"]}
        assert banner == cards

    def test_empty_everywhere_still_returns_nothing(self, monkeypatch):
        """The guard must still short-circuit when there is genuinely nothing."""
        import nanometa_live.core.watchlist.watchlist_manager as wm
        from nanometa_live.app.tabs import main_tab_helpers as mth
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager
        empty = WatchlistManager()
        empty._loaded = True
        monkeypatch.setattr(wm, "_watchlist_manager", empty)
        assert mth.filter_detected_species(self._kraken(), []) == []

    def test_entries_sharing_a_node_all_appear_on_the_cards(self, monkeypatch):
        """Five watchlist entries on one database node yield five rows."""
        import nanometa_live.core.watchlist.watchlist_manager as wm
        from nanometa_live.app.tabs import main_tab_helpers as mth
        from nanometa_live.core.taxonomy.taxid_mapping import set_mapping_collection
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager, WatchlistSource,
        )
        shigella = [("Escherichia coli", 562), ("Shigella flexneri", 623),
                    ("Shigella sonnei", 624), ("Shigella boydii", 625)]
        m = WatchlistManager()
        for name, taxid in shigella:
            m._add_entry_from_dict(
                {"name": name, "taxid_ncbi": taxid, "threat_level": "high",
                 "alert_threshold": 1}, WatchlistSource.USER)
        for e in m._entries.values():
            e.enabled = True
        m._loaded = True
        monkeypatch.setattr(wm, "_watchlist_manager", m)

        coll = TaxidMappingCollection(database_path="/db")
        for name, taxid in shigella:
            coll.mappings[taxid] = TaxidMapping(
                ncbi_taxid=taxid, canonical_name=name, db_taxid=4001,
                db_name="Escherichia coli",
                confidence=MappingConfidence.EXACT, match_score=1.0)
        set_mapping_collection(coll)

        rows = mth.get_all_watchlist_with_detection(self._kraken(), [])
        assert {r["name"] for r in rows if r["detected"]} == {n for n, _ in shigella}
