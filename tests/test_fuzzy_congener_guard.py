"""Fuzzy name matching must not bind a watchlist entry to a congener.

``FuzzyMatchStrategy`` scored the WHOLE name with ``SequenceMatcher`` at a
0.85 threshold. Candidates are drawn from a genus-prefix search, so the genus
is shared by construction and dominates the ratio: *Burkholderia mallei*
against *Burkholderia pseudomallei* scores 0.864 and was accepted (audit
2026-11-06, finding 1).

What that produced on a minimized field database -- the only situation in
which fuzzy matching runs at all, since exact and variant matching are tried
first -- was a melioidosis sample (*pseudomallei*) raising an alert named
*Burkholderia mallei*: glanders, Tier 1, a different disease and a different
notification path. The mapping was stored as FUZZY with a match_score of
0.864, which clears the 0.7 alert floor in ``_reverse_mapping_hit``, and
carried no ``ambiguous_with`` disclosure. CLAUDE.md requires an inversion
like this to be reported as ambiguity rather than resolved by guess.

The guard compares the species epithets on their own at the same threshold,
so the typo correction fuzzy matching exists for still works.
"""

import pytest

from nanometa_live.core.taxonomy.database_indexer import DatabaseIndexBuilder
from nanometa_live.core.watchlist.validation.match_strategies import (
    FuzzyMatchStrategy,
)
from nanometa_live.core.watchlist.validation.name_normalizer import (
    NameNormalizer,
)

pytestmark = pytest.mark.unit


# A minimized database that kept pseudomallei and pruned mallei -- exactly the
# shape that sends a mallei watchlist entry into the fuzzy strategy. Also
# carries anthracis (for the typo case) and a GTDB-suffixed E. coli node.
INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "30.00\t300\t300\tS\t28450\tBurkholderia pseudomallei\n"
    "20.00\t200\t200\tS\t1392\tBacillus anthracis\n"
    "10.00\t100\t100\tS\t562\tEscherichia coli_D\n"
)


@pytest.fixture
def index(tmp_path):
    f = tmp_path / "inspect.txt"
    f.write_text(INSPECT)
    return DatabaseIndexBuilder().build_from_inspect(str(f), str(tmp_path))


@pytest.fixture
def norm():
    # A fresh normalizer: the module singleton caches across tests.
    return NameNormalizer()


class TestADifferentEpithetIsRefused:
    def test_mallei_does_not_match_pseudomallei(self, index, norm):
        query = norm.normalize("Burkholderia mallei")
        result = FuzzyMatchStrategy().match(query, None, index)

        assert result is None, (
            "fuzzy matching bound Burkholderia mallei (glanders) to the "
            f"pseudomallei node: {result.matched_name if result else ''} -- a "
            "melioidosis sample then alarms under the wrong organism's name"
        )

    def test_the_whole_name_ratio_really_would_have_passed(self, norm):
        """Pin the premise, so this test cannot pass for the wrong reason."""
        strategy = FuzzyMatchStrategy()
        ratio = strategy._calculate_similarity(
            "burkholderia mallei", "burkholderia pseudomallei"
        )
        assert ratio >= strategy.threshold


class TestIntraEpithetTyposStillMatch:
    def test_transposed_letters_in_the_epithet_still_match(self, index, norm):
        query = norm.normalize("Bacillus anthracsi")
        result = FuzzyMatchStrategy().match(query, None, index)

        assert result is not None, (
            "a typo inside the species epithet no longer matches; fuzzy "
            "matching exists for exactly this"
        )
        assert result.matched_taxid == 1392

    def test_a_gtdb_polyphyly_suffix_is_not_a_different_epithet(
        self, index, norm
    ):
        """GTDB splits a species and suffixes the parts alphabetically.

        Which letter a lineage received says nothing about the organism, so
        ``coli`` must still reach ``coli_D``.
        """
        query = norm.normalize("Escherichia coli")
        result = FuzzyMatchStrategy().match(query, None, index)

        assert result is not None, (
            "the GTDB polyphyly suffix was read as a different epithet"
        )
        assert result.matched_taxid == 562

    def test_a_genus_level_entry_is_not_gated(self, index, norm):
        """An entry with no epithet is deliberately broad; nothing to compare."""
        query = norm.normalize("Burkholderia")
        strategy = FuzzyMatchStrategy()
        assert strategy._epithet_compatible(
            query, "burkholderia pseudomallei"
        ) is True
