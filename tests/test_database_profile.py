"""Detection of the two taxonomy axes, and the operator override.

The axes are independent, and the tests are written to prove that rather than
to restate the implementation: a database can use NCBI-style binomial names
while having remapped its taxids, which the old single enum could not express
(its ``MIXED`` member was produced but never read anywhere).
"""

from __future__ import annotations

import json

import pytest

from nanometa_live.core.taxonomy.database_indexer import DatabaseIndexBuilder
from nanometa_live.core.taxonomy.database_profile import (
    DatabaseProfile,
    Nomenclature,
    apply_override,
    clear_override,
    load_override,
    save_override,
)
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
)

pytestmark = pytest.mark.unit


def _index(nodes) -> DatabaseTaxonomyIndex:
    """Build an index from (taxid, name, rank) triples."""
    index = DatabaseTaxonomyIndex(database_path="/tmp/db")
    for taxid, name, rank in nodes:
        index.by_taxid[taxid] = DatabaseTaxonomyNode(
            taxid=taxid, name=name, rank=rank,
            name_normalized=name.lower().replace("_", " "),
        )
    return index


NCBI_REFERENCE_NODES = [
    (562, "Escherichia coli", "S"),
    (632, "Yersinia pestis", "S"),
    (1392, "Bacillus anthracis", "S"),
    (287, "Pseudomonas aeruginosa", "S"),
    (1280, "Staphylococcus aureus", "S"),
]


class TestTaxidAxis:
    def test_matching_reference_taxa_means_ncbi_taxids(self):
        builder = DatabaseIndexBuilder()
        ok, evidence = builder._detect_taxids_are_ncbi(_index(NCBI_REFERENCE_NODES))
        assert ok is True
        assert "reference taxa match" in evidence

    def test_one_mismatch_is_enough_to_reject(self):
        """The rule is strict on purpose.

        A database that assigns its own taxids reuses these numbers for
        unrelated organisms. Accepting a majority would let a mostly-NCBI
        database with a few remapped entries claim taxid authority it does
        not have.
        """
        nodes = list(NCBI_REFERENCE_NODES)
        nodes[0] = (562, "Prochlorococcus marinus", "S")  # 562 is not this
        builder = DatabaseIndexBuilder()
        ok, _ = builder._detect_taxids_are_ncbi(_index(nodes))
        assert ok is False

    def test_absent_reference_taxa_defaults_to_not_ncbi(self):
        """Unverified taxids must not be trusted.

        A false exact-taxid match names the wrong organism on a pathogen
        dashboard. A missed one merely falls through to name matching, which
        is why False is the safe default rather than an optimistic True.
        """
        builder = DatabaseIndexBuilder()
        ok, evidence = builder._detect_taxids_are_ncbi(
            _index([(99001, "Unknown organism", "S")])
        )
        assert ok is False
        assert "no reference taxa" in evidence


class TestNomenclatureAxis:
    def test_rank_prefixes_mean_gtdb(self):
        builder = DatabaseIndexBuilder()
        nom, evidence = builder._detect_nomenclature(
            _index([(1, "s__Escherichia coli", "S"), (2, "s__Bacillus cereus", "S")])
        )
        assert nom is Nomenclature.GTDB
        assert "rank prefixes" in evidence

    def test_a_single_suffixed_genus_is_enough(self):
        """One GTDB polyphyly suffix anywhere is conclusive.

        These genera are rare in absolute terms. Requiring a majority -- or
        sampling only the head of the node dict, as the previous detector did
        -- would systematically miss a database that carries a handful.
        """
        nodes = [(i, f"Streptococcus species{i}", "S") for i in range(300)]
        nodes.append((999, "Escherichia_A coli", "S"))
        builder = DatabaseIndexBuilder()
        nom, evidence = builder._detect_nomenclature(_index(nodes))
        assert nom is Nomenclature.GTDB
        assert "genus suffix" in evidence

    def test_binomial_names_mean_ncbi(self):
        builder = DatabaseIndexBuilder()
        nom, _ = builder._detect_nomenclature(_index(NCBI_REFERENCE_NODES))
        assert nom is Nomenclature.NCBI

    def test_unrecognisable_names_stay_unknown(self):
        builder = DatabaseIndexBuilder()
        nom, _ = builder._detect_nomenclature(
            _index([(1, "contig00001", "S"), (2, "scaffold7", "S")])
        )
        assert nom is Nomenclature.UNKNOWN

    def test_empty_database_is_unknown(self):
        builder = DatabaseIndexBuilder()
        nom, evidence = builder._detect_nomenclature(_index([]))
        assert nom is Nomenclature.UNKNOWN
        assert "no taxa" in evidence


class TestAxesAreIndependent:
    def test_ncbi_names_with_remapped_taxids(self):
        """The combination the old single enum could not express.

        This is what most real "mixed" databases are, and the reason MIXED
        was never readable: one axis was trying to answer two questions.
        """
        nodes = [
            (900001, "Escherichia coli", "S"),
            (900002, "Yersinia pestis", "S"),
            (900003, "Bacillus anthracis", "S"),
        ]
        profile = DatabaseIndexBuilder()._detect_profile(_index(nodes))
        assert profile.taxids_are_ncbi is False
        assert profile.nomenclature is Nomenclature.NCBI
        assert profile.display_label == "NCBI names, remapped taxids"

    def test_gtdb_names_with_ncbi_taxids(self):
        nodes = list(NCBI_REFERENCE_NODES) + [(700, "s__Nitrospira defluvii", "S")]
        profile = DatabaseIndexBuilder()._detect_profile(_index(nodes))
        assert profile.taxids_are_ncbi is True
        assert profile.nomenclature is Nomenclature.GTDB

    def test_evidence_is_recorded_for_both_axes(self):
        """detected_by is what makes the override an informed correction."""
        profile = DatabaseIndexBuilder()._detect_profile(_index(NCBI_REFERENCE_NODES))
        assert "reference taxa" in profile.detected_by
        assert "binomial" in profile.detected_by


class TestVariantGating:
    @pytest.mark.parametrize(
        "nomenclature,expected",
        [
            (Nomenclature.GTDB, True),
            (Nomenclature.UNKNOWN, True),   # misdetection must not lose matches
            (Nomenclature.NCBI, False),
        ],
    )
    def test_generates_gtdb_variants(self, nomenclature, expected):
        profile = DatabaseProfile(nomenclature=nomenclature)
        assert profile.generates_gtdb_variants is expected


class TestSerialisation:
    def test_round_trip(self):
        original = DatabaseProfile(
            taxids_are_ncbi=True, nomenclature=Nomenclature.GTDB,
            detected_by="5/5 reference taxa match",
        )
        assert DatabaseProfile.from_dict(original.to_dict()) == original

    def test_missing_or_broken_input_degrades_to_default(self):
        """Read from an on-disk cache an operator may have hand-edited."""
        assert DatabaseProfile.from_dict(None) == DatabaseProfile()
        assert DatabaseProfile.from_dict({}) == DatabaseProfile()
        assert DatabaseProfile.from_dict(
            {"nomenclature": "klingon"}
        ).nomenclature is Nomenclature.UNKNOWN

    def test_index_carries_the_profile_through_serialisation(self):
        index = _index(NCBI_REFERENCE_NODES)
        index.profile = DatabaseProfile(
            taxids_are_ncbi=True, nomenclature=Nomenclature.NCBI
        )
        restored = DatabaseTaxonomyIndex.from_dict(index.to_dict())
        assert restored.profile == index.profile

    def test_index_cache_declares_version_two(self):
        """A v1 cache has no name evidence, so it must be rebuilt not migrated."""
        assert DatabaseTaxonomyIndex(database_path="/x").to_dict()["version"] == "2.0"


class TestOperatorOverride:
    def test_round_trip_and_clear(self, tmp_path):
        profile = DatabaseProfile(
            taxids_are_ncbi=True, nomenclature=Nomenclature.NCBI
        )
        save_override("abc123", tmp_path, profile)
        loaded = load_override("abc123", tmp_path)
        assert loaded.taxids_are_ncbi is True
        assert loaded.overridden is True
        assert clear_override("abc123", tmp_path) is True
        assert load_override("abc123", tmp_path) is None
        assert clear_override("abc123", tmp_path) is False

    def test_override_wins_but_keeps_the_detector_evidence(self, tmp_path):
        """An operator disagreeing should not erase what was detected."""
        detected = DatabaseProfile(
            taxids_are_ncbi=False, nomenclature=Nomenclature.GTDB,
            detected_by="0/5 reference taxa match",
        )
        save_override(
            "abc123", tmp_path,
            DatabaseProfile(taxids_are_ncbi=True, nomenclature=Nomenclature.NCBI),
        )
        result = apply_override(detected, "abc123", tmp_path)
        assert result.taxids_are_ncbi is True
        assert result.overridden is True
        assert "0/5 reference taxa match" in result.detected_by

    def test_no_override_is_a_passthrough(self, tmp_path):
        detected = DatabaseProfile(taxids_are_ncbi=True)
        assert apply_override(detected, "nothing", tmp_path) == detected

    def test_unreadable_override_is_ignored_not_fatal(self, tmp_path):
        (tmp_path / "abc123_profile_override.json").write_text("{not json")
        assert load_override("abc123", tmp_path) is None

    def test_override_survives_an_index_rebuild(self, tmp_path):
        """The reason it is a sibling file rather than a field in the index.

        The index cache is deleted and regenerated on a version bump; an
        operator correction stored inside it would be silently lost.
        """
        save_override("abc123", tmp_path, DatabaseProfile(taxids_are_ncbi=True))
        index_cache = tmp_path / "abc123_index.json"
        index_cache.write_text(json.dumps({"version": "2.0"}))
        index_cache.unlink()  # what a version bump does
        assert load_override("abc123", tmp_path) is not None


class TestVariantGatingReachesMatching:
    """The gate must narrow work without ever losing a GTDB match.

    This is the safety-relevant half of the change: a false negative here
    means a watchlist organism present in the run is not detected. The
    existing strategy tests all leave nomenclature at its UNKNOWN default,
    which generates variants, so they cannot catch a gate that is stuck on.
    """

    ENTRY_NAME = "Bacillus anthracis"
    GTDB_FORM = "bacillus_a anthracis"

    def _index_with(self, db_name, nomenclature):
        from nanometa_live.core.taxonomy.database_profile import DatabaseProfile
        index = _index([(1, db_name, "S")])
        index.by_name[db_name.lower()] = [1]
        index.profile = DatabaseProfile(nomenclature=nomenclature)
        return index

    def _match(self, index):
        from nanometa_live.core.watchlist.validation.match_strategies import (
            VariantMatchStrategy,
        )
        from nanometa_live.core.watchlist.validation.name_normalizer import (
            get_name_normalizer,
        )
        query = get_name_normalizer().normalize(self.ENTRY_NAME)
        return VariantMatchStrategy().match(query, None, index)

    def test_gtdb_database_still_matches_a_suffixed_genus(self):
        """The match that must not be lost."""
        index = self._index_with(self.GTDB_FORM, Nomenclature.GTDB)
        assert self._match(index) is not None

    def test_undetected_database_still_matches_a_suffixed_genus(self):
        """A misdetection must not cost a detection."""
        index = self._index_with(self.GTDB_FORM, Nomenclature.UNKNOWN)
        assert self._match(index) is not None

    def test_ncbi_database_does_not_probe_suffixed_forms(self):
        """The saving. On an NCBI database these forms are provably absent."""
        index = self._index_with(self.GTDB_FORM, Nomenclature.NCBI)
        assert self._match(index) is None

    def test_ncbi_database_still_matches_ordinary_names(self):
        """Gating the GTDB forms must not disturb normal matching."""
        index = self._index_with("bacillus_anthracis", Nomenclature.NCBI)
        assert self._match(index) is not None


class TestVariantCost:
    def test_gtdb_forms_are_not_generated_up_front(self):
        """78 of 83 variants per name were being built for every database."""
        from nanometa_live.core.watchlist.validation.name_normalizer import (
            get_name_normalizer,
        )
        name = get_name_normalizer().normalize("Bacillus anthracis")
        assert len(name.variants) < 10
        assert len(name.gtdb_genus_variants) == 78
        assert len(name.all_variants(include_gtdb=False)) == len(name.variants)
        assert len(name.all_variants()) > len(name.variants)


class TestCrossKingdomDatabases:
    """A database with no bacteria must still be recognised as NCBI.

    Found against a real virus/plant/fungal database (enovation_small): every
    probe taxon was bacterial, so a database covering other kingdoms matched
    none of them, was reported as having remapped taxids, and silently lost
    the exact-taxid shortcut despite using genuine NCBI ids. Synthetic
    fixtures could not have caught it -- they all happened to be bacterial.
    """

    EUKARYOTE_VIRUS_NODES = [
        (9606, "Homo sapiens", "S"),
        (4932, "Saccharomyces cerevisiae", "S"),
        (3702, "Arabidopsis thaliana", "S"),
        (4565, "Triticum aestivum", "S"),
        (5833, "Plasmodium falciparum", "S"),
        (2697049, "Severe acute respiratory syndrome coronavirus 2", "S"),
        (10298, "Human alphaherpesvirus 1", "S"),
    ]

    def test_virus_and_eukaryote_database_is_ncbi(self):
        profile = DatabaseIndexBuilder()._detect_profile(
            _index(self.EUKARYOTE_VIRUS_NODES)
        )
        assert profile.taxids_are_ncbi is True, (
            "a database with NCBI taxids but no bacteria was reported as "
            "remapped, which disables exact-taxid matching"
        )
        assert profile.nomenclature is Nomenclature.NCBI

    def test_remapped_eukaryote_database_is_still_caught(self):
        """The widened probe must not have become permissive."""
        nodes = [(t, n, r) for t, n, r in self.EUKARYOTE_VIRUS_NODES]
        nodes[0] = (9606, "Gallus gallus", "S")  # 9606 is not chicken
        profile = DatabaseIndexBuilder()._detect_profile(_index(nodes))
        assert profile.taxids_are_ncbi is False


class TestNameAgreement:
    """Probe-name comparison is anchored on the first token, not a substring.

    With a cross-kingdom probe set, bare substring matching on short tokens
    ("mus", "human") would match unrelated organisms and turn the check into
    a coin flip in exactly the cases it exists to catch.
    """

    @pytest.mark.parametrize("actual,expected", [
        ("Bacillus anthracis", "Bacillus anthracis"),
        ("Bacillus anthracis str. Ames", "Bacillus anthracis"),   # strain suffix
        ("Escherichia_coli", "Escherichia coli"),                 # underscores
        ("Homo sapiens", "Homo sapiens"),
        ("Severe acute respiratory syndrome coronavirus 2",
         "Severe acute respiratory syndrome coronavirus 2"),
    ])
    def test_agrees(self, actual, expected):
        from nanometa_live.core.taxonomy.database_indexer import _names_agree
        assert _names_agree(actual, expected) is True

    @pytest.mark.parametrize("actual,expected", [
        ("Gallus gallus", "Homo sapiens"),
        ("Musca domestica", "Mus musculus"),        # would pass a substring test
        ("Human immunodeficiency virus 1", "Human alphaherpesvirus 1"),
        ("", "Homo sapiens"),
    ])
    def test_disagrees(self, actual, expected):
        from nanometa_live.core.taxonomy.database_indexer import _names_agree
        assert _names_agree(actual, expected) is False


class TestKnownRenamesDoNotDisqualifyTheDatabase:
    """A legitimately renamed taxon must not flip taxids_are_ncbi off.

    ICTV renamed SARS-CoV-2 (2697049) to Betacoronavirus pandemicum, and real
    flextaxd/Bioshield builds carry the new name on the ORIGINAL taxid. The
    all-must-match probe read that as "taxid remapped" and disabled the
    exact-taxid shortcut database-wide -- for exactly the database family the
    shortcut was preserved for (it rescued four detections on a real run).
    Only names in the explicit known-renames table are tolerated; an unknown
    mismatch stays fatal (see test_one_mismatch_is_enough_to_reject).
    Audit 2026-08-16, finding L9.
    """

    def test_renamed_sars_cov_2_still_counts_as_a_match(self):
        nodes = list(NCBI_REFERENCE_NODES) + [
            (2697049, "Betacoronavirus pandemicum", "S"),
        ]
        builder = DatabaseIndexBuilder()
        ok, evidence = builder._detect_taxids_are_ncbi(_index(nodes))
        assert ok is True, (
            "a documented ICTV rename disqualified the whole database's "
            f"taxid authority: {evidence}"
        )

    def test_unknown_name_on_that_taxid_still_rejects(self):
        nodes = list(NCBI_REFERENCE_NODES) + [
            (2697049, "Prochlorococcus marinus", "S"),
        ]
        builder = DatabaseIndexBuilder()
        ok, _ = builder._detect_taxids_are_ncbi(_index(nodes))
        assert ok is False
