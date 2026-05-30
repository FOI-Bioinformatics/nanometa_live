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
    TaxonomyType,
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
    def test_ncbi_exact_taxid_is_perfect_match(self):
        matcher = TaxonomyMatcher(TaxonomyType.NCBI)
        score = matcher.match_organism(
            detected={"name": "completely different label", "taxid": 562},
            entry_name="Escherichia coli",
            entry_taxid=562,
        )
        assert score == 1.0

    def test_taxid_ignored_when_taxonomy_is_not_ncbi(self):
        # Under non-NCBI taxonomy the taxid branch must not fire; matching
        # falls through to names, which here do not agree -> 0.0.
        matcher = TaxonomyMatcher(TaxonomyType.GTDB)
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


class TestFindMatch:
    """find_match drives the watched-organisms badge count.

    Regression anchor for commit 6d6d3c1: with no usable taxid the correct
    watchlist entry must still be selected by normalized name, so the badge
    count matches the detected cards.
    """

    WATCHLIST = [
        {"name": "Escherichia coli", "taxid_ncbi": 562},
        {"name": "Bacillus anthracis", "taxid_ncbi": 1392},
        {"name": "Staphylococcus aureus", "taxid_ncbi": 1280},
    ]

    def test_name_only_match_selects_correct_entry(self):
        matcher = TaxonomyMatcher(TaxonomyType.GTDB)
        detected = {"name": "s__Bacillus_anthracis", "taxid": None}
        result = matcher.find_match(detected, self.WATCHLIST)
        assert result is not None
        entry, score = result
        assert entry["name"] == "Bacillus anthracis"
        assert score == 1.0

    def test_below_threshold_returns_none(self):
        matcher = TaxonomyMatcher(TaxonomyType.GTDB)
        # Same genus as an entry (score 0.3) but below the default 0.7 threshold.
        detected = {"name": "Escherichia fergusonii", "taxid": None}
        assert matcher.find_match(detected, self.WATCHLIST) is None

    def test_picks_highest_scoring_entry(self):
        matcher = TaxonomyMatcher(TaxonomyType.GTDB)
        detected = {"name": "Escherichia coli", "taxid": None}
        result = matcher.find_match(detected, self.WATCHLIST, threshold=0.5)
        assert result is not None
        entry, score = result
        assert entry["name"] == "Escherichia coli"
        assert score == 1.0


class TestDetectTaxonomyFromReport:
    def test_detects_gtdb_from_prefixed_names(self, tmp_path):
        report = tmp_path / "gtdb.report.txt"
        report.write_text(
            _kraken_line("50.0", 100, 100, "S", 1, "s__Escherichia_coli")
            + _kraken_line("30.0", 60, 60, "S", 2, "s__Bacillus_anthracis")
        )
        matcher = TaxonomyMatcher()
        assert matcher.detect_taxonomy_from_report(str(report)) == TaxonomyType.GTDB

    def test_detects_ncbi_from_spaced_names(self, tmp_path):
        report = tmp_path / "ncbi.report.txt"
        report.write_text(
            _kraken_line("50.0", 100, 100, "S", 562, "Escherichia coli")
            + _kraken_line("30.0", 60, 60, "S", 1392, "Bacillus anthracis")
        )
        matcher = TaxonomyMatcher()
        assert matcher.detect_taxonomy_from_report(str(report)) == TaxonomyType.NCBI

    def test_missing_file_returns_unknown(self, tmp_path):
        matcher = TaxonomyMatcher()
        result = matcher.detect_taxonomy_from_report(str(tmp_path / "nope.txt"))
        assert result == TaxonomyType.UNKNOWN

    def test_detection_sets_taxonomy_type_on_matcher(self, tmp_path):
        report = tmp_path / "ncbi.report.txt"
        report.write_text(_kraken_line("99.0", 100, 100, "S", 562, "Escherichia coli"))
        matcher = TaxonomyMatcher()
        matcher.detect_taxonomy_from_report(str(report))
        assert matcher.taxonomy_type == TaxonomyType.NCBI


class TestTaxonomyIndicatorAndType:
    @pytest.mark.parametrize(
        "ttype,expected",
        [
            (TaxonomyType.NCBI, "NCBI"),
            (TaxonomyType.GTDB, "GTDB"),
            (TaxonomyType.MIXED, "Mixed"),
            (TaxonomyType.UNKNOWN, "Auto"),
        ],
    )
    def test_indicator_strings(self, ttype, expected):
        matcher = TaxonomyMatcher(ttype)
        assert matcher.get_taxonomy_indicator() == expected

    def test_taxonomy_type_setter(self):
        matcher = TaxonomyMatcher()
        matcher.taxonomy_type = TaxonomyType.GTDB
        assert matcher.taxonomy_type == TaxonomyType.GTDB


class TestSingleton:
    def test_returns_same_instance(self):
        assert get_taxonomy_matcher() is get_taxonomy_matcher()

    def test_reset_creates_fresh_instance(self):
        first = get_taxonomy_matcher()
        reset_taxonomy_matcher()
        second = get_taxonomy_matcher()
        assert first is not second
