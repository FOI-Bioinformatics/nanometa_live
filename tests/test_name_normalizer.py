"""
Unit tests for core/watchlist/validation/name_normalizer.py (was 76%, no
dedicated test file).

Pure cross-taxonomy name normalisation: GTDB-prefix stripping, binomial parsing,
canonical form, reclassification lookup, similarity scoring and format
detection. All deterministic.
"""

import pytest

from nanometa_live.core.watchlist.validation.name_normalizer import (
    NameNormalizer,
    get_name_normalizer,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def n():
    return NameNormalizer()


class TestNormalize:
    def test_empty_and_none(self, n):
        assert n.normalize("").canonical == ""
        assert n.normalize(None).canonical == ""

    def test_gtdb_prefixed_underscored(self, n):
        result = n.normalize("s__Bacillus_anthracis")
        assert result.canonical == "bacillus anthracis"
        assert result.genus == "bacillus"
        assert result.species_epithet == "anthracis"
        assert "gtdb" in result.taxonomy_hints

    def test_ncbi_spaced(self, n):
        assert n.normalize("Escherichia coli").canonical == "escherichia coli"

    def test_result_is_cached(self, n):
        # Same input returns the cached object (identity).
        assert n.normalize("Escherichia coli") is n.normalize("Escherichia coli")


class TestStripGtdbPrefix:
    @pytest.mark.parametrize("name,stripped,rank", [
        ("s__Foo", "Foo", "species"),
        ("d__Bacteria", "Bacteria", "domain"),
        ("g__Escherichia", "Escherichia", "genus"),
        ("plain name", "plain name", None),
    ])
    def test_prefix(self, n, name, stripped, rank):
        assert n.strip_gtdb_prefix(name) == (stripped, rank)


class TestParseBinomial:
    def test_genus_species(self, n):
        parsed = n.parse_binomial("escherichia coli")
        assert parsed["genus"] == "escherichia"
        assert parsed["species_epithet"] == "coli"


class TestReclassifications:
    def test_known_reclassification(self, n):
        alts = n.get_reclassifications("clostridium difficile")
        assert "clostridioides difficile" in alts

    def test_unknown_returns_empty(self, n):
        assert n.get_reclassifications("escherichia coli") == []


class TestSimilarity:
    def test_exact_match(self, n):
        assert n.calculate_similarity("Escherichia coli", "escherichia coli") == 1.0

    def test_same_genus_partial(self, n):
        sim = n.calculate_similarity("Escherichia coli", "Escherichia albertii")
        assert 0.0 < sim < 1.0

    def test_unrelated_low(self, n):
        sim = n.calculate_similarity("Escherichia coli", "Staphylococcus aureus")
        assert sim < 0.5


class TestFormatDetection:
    def test_gtdb_format(self, n):
        assert n.is_gtdb_format("s__Bacillus_anthracis") is True
        assert n.is_gtdb_format("Bacillus_anthracis") is True
        assert n.is_gtdb_format("Escherichia coli") is False

    def test_ncbi_format(self, n):
        assert n.is_ncbi_format("Escherichia coli") is True
        assert n.is_ncbi_format("Bacillus_anthracis") is False


class TestSingleton:
    def test_get_name_normalizer_is_singleton(self):
        assert get_name_normalizer() is get_name_normalizer()
