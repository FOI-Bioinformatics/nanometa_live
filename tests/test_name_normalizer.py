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


class TestSubspeciesVariants:
    """A subspecies-qualified name must generate trinomial variants and rank
    them ahead of the species-only form.

    The subspecies epithet was parsed into ``NormalizedName.subspecies`` and
    then never used: every variant was genus+species only, so on a database
    that names its S1 node without the literal "subsp." token, both
    *F. tularensis* subsp. *tularensis* (Type A) and subsp. *holarctica*
    (Type B) resolved to the parent species node -- collapsing the clinical
    distinction the subspecies feature exists for. Audit 2026-08-16,
    finding L5.
    """

    def test_trinomial_variants_are_generated(self, n):
        r = n.normalize("Francisella tularensis subsp. holarctica")
        assert r.subspecies == "holarctica"
        assert "francisella tularensis holarctica" in r.variants
        assert "francisella_tularensis_holarctica" in r.variants
        assert "s__francisella_tularensis_holarctica" in r.variants

    def test_trinomial_outranks_species_only(self, n):
        """Variants are tried in order and the first hit wins, so the
        subspecies form must come before the parent-species form."""
        r = n.normalize("Francisella tularensis subsp. holarctica")
        trinomial_idx = r.variants.index("francisella tularensis holarctica")
        species_idx = r.variants.index("francisella tularensis")
        assert trinomial_idx < species_idx, (
            "the parent species outranks the subspecies form, so a "
            "subspecies entry resolves to the species node even when the "
            "correct S1 node exists"
        )

    def test_species_only_form_still_present_as_fallback(self, n):
        r = n.normalize("Francisella tularensis subsp. holarctica")
        assert "francisella tularensis" in r.variants

    def test_names_without_subspecies_are_unchanged(self, n):
        r = n.normalize("Bacillus anthracis")
        assert r.subspecies is None
        assert r.variants[0] == "bacillus anthracis"
        # Species-only stays the highest-priority non-canonical variant.
        assert not any(" subsp" in v for v in r.variants)
