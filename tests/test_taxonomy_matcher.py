"""
Unit tests for the TaxonomyMatcher (core/watchlist/taxonomy_matcher.py).

This module had zero direct test coverage before this file. The matcher is
the mechanism by which detected Kraken2 organisms are aligned with watchlist
entries, and the name-fallback path here is exactly what the watched-organisms
badge-count fix (commit 6d6d3c1) corrected: when a database carries no usable
taxid, a watched organism must still be matched by normalized name so the badge
count agrees with the number of detected cards.

Assertions target concrete score values and matched entries rather than mere
truthiness, and the network-free normalization layer is exercised directly.
"""

import pytest

from nanometa_live.core.watchlist.taxonomy_matcher import (
    TaxonomyMatcher,
    get_taxonomy_matcher,
    reset_taxonomy_matcher,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton around every test.

    Mirrors the singleton-reset pattern in test_genome_manager_singleton.py
    and test_alert_engine.py so matcher state never leaks between tests.
    """
    reset_taxonomy_matcher()
    yield
    reset_taxonomy_matcher()


def _kraken_line(pct, cumul, reads, rank, taxid, name):
    """Build one tab-separated Kraken2 report line (name is column index 5)."""
    return f"{pct}\t{cumul}\t{reads}\t{rank}\t{taxid}\t{name}\n"


class TestNormalizeName:
    def test_ncbi_name_lowercased(self):
        matcher = TaxonomyMatcher()
        assert matcher.normalize_name("Escherichia coli") == "escherichia coli"

    def test_gtdb_prefixed_underscored_name_canonicalised(self):
        matcher = TaxonomyMatcher()
        # GTDB species prefix stripped and underscores -> spaces.
        assert matcher.normalize_name("s__Bacillus_anthracis") == "bacillus anthracis"

    def test_underscore_name_without_prefix(self):
        matcher = TaxonomyMatcher()
        assert matcher.normalize_name("Bacillus_anthracis") == "bacillus anthracis"

    def test_empty_name_returns_empty(self):
        matcher = TaxonomyMatcher()
        assert matcher.normalize_name("") == ""


class TestGetNameVariants:
    def test_variants_cover_space_and_underscore_and_gtdb_forms(self):
        matcher = TaxonomyMatcher()
        variants = set(matcher.get_name_variants("Escherichia coli"))
        assert "escherichia coli" in variants
        assert "escherichia_coli" in variants
        assert "s__escherichia_coli" in variants

    def test_empty_name_yields_no_variants(self):
        matcher = TaxonomyMatcher()
        assert matcher.get_name_variants("") == []


class TestMatchOrganism:
    def test_matcher_scores_names_only(self):
        """Taxid equality is the caller's job, not the matcher's.

        Both production callers build a database-taxid index and try the
        direct key before falling back to this per-entry name loop, so a
        taxid comparison here would be redundant work at O(entries) cost.
        The taxid paths are covered against the reachable entry points in
        tests/test_custom_db_taxid.py.
        """
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "completely different label", "taxid": 562},
            entry_name="Escherichia coli",
            entry_taxid=562,
        )
        assert score == 0.0

    def test_matching_names_still_score_regardless_of_taxid(self):
        matcher = TaxonomyMatcher()
        assert matcher.match_organism(
            detected={"name": "Escherichia coli", "taxid": 999999},
            entry_name="Escherichia coli",
            entry_taxid=562,
        ) == 1.0

    def test_disagreeing_names_do_not_match(self):
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Staphylococcus aureus", "taxid": 562},
            entry_name="Escherichia coli",
            entry_taxid=562,
        )
        assert score == 0.0

    def test_exact_normalized_name_is_perfect_match(self):
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Escherichia coli", "taxid": None},
            entry_name="escherichia coli",
        )
        assert score == 1.0

    def test_alt_name_match_scores_high(self):
        # Reclassification: detected reports the modern name, watchlist holds the
        # legacy primary name but lists the modern name as an alternative.
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Cutibacterium acnes", "taxid": None},
            entry_name="Propionibacterium acnes",
            entry_alt_names=["Cutibacterium acnes"],
        )
        assert score == 0.95

    def test_genus_and_species_match_when_extra_token_present(self):
        # detected has an extra token so canonical forms differ, but genus +
        # species epithet agree -> 0.85 (checked before the substring branch).
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Escherichia coli extra", "taxid": None},
            entry_name="Escherichia coli",
        )
        assert score == 0.85

    def test_same_genus_only_scores_low(self):
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Escherichia fergusonii", "taxid": None},
            entry_name="Escherichia coli",
        )
        assert score == 0.3

    def test_no_match_scores_zero(self):
        matcher = TaxonomyMatcher()
        score = matcher.match_organism(
            detected={"name": "Staphylococcus aureus", "taxid": None},
            entry_name="Escherichia coli",
        )
        assert score == 0.0


class TestSingleton:
    def test_returns_same_instance(self):
        assert get_taxonomy_matcher() is get_taxonomy_matcher()

    def test_reset_creates_fresh_instance(self):
        first = get_taxonomy_matcher()
        reset_taxonomy_matcher()
        second = get_taxonomy_matcher()
        assert first is not second


class TestSubstringOutranksGenusFallback:
    """The same-genus fallback (0.3) must not shadow a substring match.

    ``match_organism`` returned the 0.3 same-genus score before the
    substring branch (0.7/0.6) was ever tried, so a GTDB polyphyly-suffixed
    report name -- watchlist "Escherichia coli" vs detected
    "Escherichia coli_D" -- scored 0.3 and fell below the 0.7 detection
    threshold: a silent miss for exactly the names GTDB databases produce.
    Audit 2026-08-16, finding L7.
    """

    def test_gtdb_suffixed_species_clears_detection_threshold(self):
        from nanometa_live.core.watchlist.taxonomy_matcher import TaxonomyMatcher

        m = TaxonomyMatcher()
        score = m.match_organism(
            {"taxid": 4005020, "name": "Escherichia coli_D"},
            "Escherichia coli",
        )
        assert score >= 0.7, (
            f"substring match shadowed by the same-genus fallback: {score}"
        )

    def test_descriptive_suffix_clears_threshold(self):
        from nanometa_live.core.watchlist.taxonomy_matcher import TaxonomyMatcher

        m = TaxonomyMatcher()
        score = m.match_organism(
            {"taxid": 777, "name": "Coxiella burnetii-like organism"},
            "Coxiella burnetii",
        )
        assert score >= 0.7

    def test_genuinely_different_species_still_scores_genus_only(self):
        from nanometa_live.core.watchlist.taxonomy_matcher import TaxonomyMatcher

        m = TaxonomyMatcher()
        score = m.match_organism(
            {"taxid": 1428, "name": "Bacillus thuringiensis"},
            "Bacillus anthracis",
        )
        assert score == pytest.approx(0.3)
