"""A bare trinomial watchlist entry must resolve to the subspecies node.

``parse_binomial`` set ``NormalizedName.subspecies`` only for the explicit
``subsp.`` spelling. So *Francisella tularensis holarctica* -- how the
Bioshield lists and most report rows spell it -- parsed as the species with an
ignored third word, and its variant list carried the species-only form.
``VariantMatchStrategy`` returns the FIRST variant that hits, so against a
database whose S1 node is named ``Francisella tularensis subsp. holarctica``
the entry resolved to the parent species node (audit 2026-11-06, finding 15).

The consequence is the one the subspecies feature exists to prevent: Type A
(*tularensis*, markedly more virulent) and Type B (*holarctica*, the LVS
lineage) both land on the species node and the clinical distinction is gone --
and both entries then dedupe to one alert, since the matched node decides
identity.
"""

import pytest

from nanometa_live.core.taxonomy.database_indexer import DatabaseIndexBuilder
from nanometa_live.core.watchlist.validation.match_strategies import (
    VariantMatchStrategy,
)
from nanometa_live.core.watchlist.validation.name_normalizer import (
    NameNormalizer,
)

pytestmark = pytest.mark.unit


# A database that spells its subspecies nodes with "subsp." (NCBI's own
# convention, and what flextaxd carries over for backbone taxa).
INSPECT_SUBSP = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "50.00\t500\t100\tS\t263\tFrancisella tularensis\n"
    "30.00\t300\t300\tS1\t119857\tFrancisella tularensis subsp. holarctica\n"
    "10.00\t100\t100\tS1\t263243\tFrancisella tularensis subsp. tularensis\n"
)


@pytest.fixture
def index(tmp_path):
    f = tmp_path / "inspect_subsp.txt"
    f.write_text(INSPECT_SUBSP)
    return DatabaseIndexBuilder().build_from_inspect(str(f), str(tmp_path))


@pytest.fixture
def norm():
    # Fresh: the module singleton caches normalized names across tests.
    return NameNormalizer()


class TestTheParse:
    def test_a_third_word_is_the_subspecies(self, norm):
        assert norm.normalize(
            "Francisella tularensis holarctica").subspecies == "holarctica"

    def test_the_subsp_spelling_is_generated(self, norm):
        variants = norm.normalize("Francisella tularensis holarctica").variants
        assert "francisella tularensis subsp. holarctica" in variants

    def test_the_subspecies_forms_outrank_the_species(self, norm):
        variants = norm.normalize("Francisella tularensis holarctica").variants
        assert (variants.index("francisella tularensis subsp. holarctica")
                < variants.index("francisella tularensis"))

    @pytest.mark.parametrize("name,expected", [
        # A rank word, not a subspecies epithet.
        ("Salmonella enterica serovar Typhi", None),
        ("Bacillus cereus group", None),
        # Carries punctuation/digits: a serovar code.
        ("Escherichia coli O157:H7", None),
        # Two words: nothing to promote.
        ("Bacillus anthracis", None),
    ])
    def test_a_qualifier_is_not_promoted_to_subspecies(
        self, norm, name, expected
    ):
        assert norm.normalize(name).subspecies == expected


class TestTheMatch:
    def test_a_bare_trinomial_lands_on_its_own_s1_node(self, index, norm):
        query = norm.normalize("Francisella tularensis holarctica")
        result = VariantMatchStrategy().match(query, None, index)

        assert result is not None
        assert result.matched_taxid == 119857, (
            "the bare trinomial resolved to "
            f"{result.matched_name!r} (taxid {result.matched_taxid}) instead "
            "of its own subspecies node"
        )

    def test_two_subspecies_of_one_species_stay_distinct(self, index, norm):
        a = VariantMatchStrategy().match(
            norm.normalize("Francisella tularensis tularensis"), None, index)
        b = VariantMatchStrategy().match(
            norm.normalize("Francisella tularensis holarctica"), None, index)

        assert a is not None and b is not None
        assert a.matched_taxid != b.matched_taxid, (
            "Type A and Type B resolved to the same node, so the clinical "
            "distinction the subspecies feature exists for is lost"
        )

    def test_the_species_form_is_still_the_fallback(self, tmp_path, norm):
        """A database with no S1 node must still match the species."""
        f = tmp_path / "inspect_species_only.txt"
        f.write_text(
            "100.00\t1000\t0\tR\t1\troot\n"
            "50.00\t500\t500\tS\t263\tFrancisella tularensis\n"
        )
        index = DatabaseIndexBuilder().build_from_inspect(
            str(f), str(tmp_path))

        result = VariantMatchStrategy().match(
            norm.normalize("Francisella tularensis holarctica"), None, index)

        assert result is not None
        assert result.matched_taxid == 263
