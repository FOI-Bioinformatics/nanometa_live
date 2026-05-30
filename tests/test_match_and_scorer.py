"""
Unit tests for the watchlist matching strategies and confidence scorer
(core/watchlist/validation/match_strategies.py 73%, confidence_scorer.py 81%).

The strategies match a normalized query against a DatabaseTaxonomyIndex; the
scorer turns a MatchResult into a 0-100 confidence with a status. Both are pure;
the index is built from a small synthetic inspect.txt.
"""

import pytest

from nanometa_live.core.taxonomy.database_indexer import DatabaseIndexBuilder
from nanometa_live.core.watchlist.validation.confidence_scorer import (
    ConfidenceScorer,
    ValidationStatus,
)
from nanometa_live.core.watchlist.validation.match_strategies import (
    ExactNameStrategy,
    ExactTaxidStrategy,
    MatchResult,
    MatchType,
)
from nanometa_live.core.watchlist.validation.name_normalizer import get_name_normalizer

pytestmark = pytest.mark.unit

INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "50.00\t500\t500\tS\t562\tEscherichia coli\n"
)


@pytest.fixture
def index(tmp_path):
    f = tmp_path / "inspect.txt"
    f.write_text(INSPECT)
    return DatabaseIndexBuilder().build_from_inspect(str(f), str(tmp_path))


@pytest.fixture
def norm():
    return get_name_normalizer()


class TestExactTaxidStrategy:
    def test_matches_by_taxid(self, index, norm):
        result = ExactTaxidStrategy().match(norm.normalize("anything"), 562, index)
        assert result is not None
        assert result.match_type == MatchType.EXACT_TAXID
        assert result.matched_taxid == 562

    def test_no_taxid_returns_none(self, index, norm):
        assert ExactTaxidStrategy().match(norm.normalize("x"), None, index) is None

    def test_unknown_taxid_returns_none(self, index, norm):
        assert ExactTaxidStrategy().match(norm.normalize("x"), 99999, index) is None


class TestExactNameStrategy:
    def test_matches_species_by_name(self, index, norm):
        result = ExactNameStrategy().match(norm.normalize("Escherichia coli"), None, index)
        assert result is not None
        assert result.match_type == MatchType.EXACT_NAME
        assert result.matched_taxid == 562

    def test_unknown_name_returns_none(self, index, norm):
        assert ExactNameStrategy().match(norm.normalize("Imaginary species"), None, index) is None


class TestConfidenceScorer:
    def _node(self, index):
        return index.get_by_taxid(562)

    def test_exact_taxid_scores_high(self, index):
        mr = MatchResult(MatchType.EXACT_TAXID, self._node(index), 1.0, {})
        score = ConfidenceScorer().calculate_score(mr, query_taxid=562)
        assert score.final_score >= 85
        assert score.has_taxid_match is True

    def test_no_match_scores_zero(self, index):
        mr = MatchResult(MatchType.NO_MATCH, None, 0.0, {})
        score = ConfidenceScorer().calculate_score(mr)
        assert score.base_score == 0.0
        assert score.final_score < 50

    def test_fuzzy_is_mid_range(self, index):
        mr = MatchResult(MatchType.FUZZY, self._node(index), 0.8, {})
        score = ConfidenceScorer().calculate_score(mr)
        assert 0 < score.final_score < 100

    def test_auto_accept_for_exact(self, index):
        mr = MatchResult(MatchType.EXACT_TAXID, self._node(index), 1.0, {})
        score = ConfidenceScorer().calculate_score(mr, query_taxid=562)
        assert ConfidenceScorer().should_auto_accept(score) is True

    def test_no_match_not_auto_accepted(self, index):
        mr = MatchResult(MatchType.NO_MATCH, None, 0.0, {})
        score = ConfidenceScorer().calculate_score(mr)
        assert ConfidenceScorer().should_auto_accept(score) is False

    def test_status_is_validation_status_enum(self, index):
        mr = MatchResult(MatchType.EXACT_NAME, self._node(index), 1.0, {})
        score = ConfidenceScorer().calculate_score(mr)
        assert isinstance(score.status, ValidationStatus)
