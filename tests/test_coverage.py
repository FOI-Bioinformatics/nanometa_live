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
