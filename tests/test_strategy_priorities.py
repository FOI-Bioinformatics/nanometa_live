"""Test that taxid mapping strategies run in the correct priority order."""

from nanometa_live.core.watchlist.validation.match_strategies import (
    CompositeMatchStrategy,
    ExactTaxidStrategy,
    ExactNameStrategy,
    VariantMatchStrategy,
    ReclassificationStrategy,
    FuzzyMatchStrategy,
    ParentTaxonStrategy,
    SubstringMatchStrategy,
)


def test_strategy_priority_order():
    """ParentTaxon and Substring must run AFTER Reclassification and Fuzzy."""
    composite = CompositeMatchStrategy()
    strategy_names = [s.name for s in composite.strategies]

    reclass_idx = strategy_names.index("reclassification")
    fuzzy_idx = strategy_names.index("fuzzy")
    parent_idx = strategy_names.index("parent_taxon")
    substring_idx = strategy_names.index("substring")

    assert reclass_idx < parent_idx, (
        f"Reclassification (idx={reclass_idx}) must run before ParentTaxon (idx={parent_idx})"
    )
    assert fuzzy_idx < parent_idx, (
        f"Fuzzy (idx={fuzzy_idx}) must run before ParentTaxon (idx={parent_idx})"
    )
    assert fuzzy_idx < substring_idx, (
        f"Fuzzy (idx={fuzzy_idx}) must run before Substring (idx={substring_idx})"
    )


def test_strategy_priority_values():
    """Verify exact priority values after fix."""
    assert ExactTaxidStrategy.priority == 1
    assert ExactNameStrategy.priority == 2
    assert VariantMatchStrategy.priority == 3
    assert ReclassificationStrategy.priority == 35
    assert FuzzyMatchStrategy.priority == 40
    assert SubstringMatchStrategy.priority == 45
    assert ParentTaxonStrategy.priority == 50


from unittest.mock import MagicMock
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
    DatabaseTaxonomyType,
)
from nanometa_live.core.watchlist.validation.match_strategies import (
    MatchType,
)


def _make_index_with_species(name, taxid=99999):
    """Create a minimal DatabaseTaxonomyIndex containing one species."""
    node = DatabaseTaxonomyNode(
        taxid=taxid,
        name=name,
        rank="S",
        parent_taxid=1,
    )
    index = DatabaseTaxonomyIndex.__new__(DatabaseTaxonomyIndex)
    index.by_taxid = {taxid: node}
    canonical = name.lower().replace("_", " ")
    index.by_name = {canonical: [taxid]}
    index.by_name_gtdb = {}
    index.prefix_index = {}
    index.database_type = DatabaseTaxonomyType.CUSTOM
    index.database_path = ""
    index.database_hash = ""
    return index


def test_alt_name_match_when_primary_fails():
    """If primary name is not in DB but an alt name is, match via alt name."""
    index = _make_index_with_species("Zaire ebolavirus", taxid=186538)
    composite = CompositeMatchStrategy()

    # Primary name won't match
    result_no_alt = composite.match("Orthoebolavirus zairense", None, index)
    assert result_no_alt.match_type == MatchType.NO_MATCH

    # With alt_names, should find "Zaire ebolavirus"
    result_with_alt = composite.match(
        "Orthoebolavirus zairense",
        None,
        index,
        alt_names=["Zaire ebolavirus", "Ebola virus"],
    )
    assert result_with_alt.match_type == MatchType.ALT_NAME
    assert result_with_alt.matched_taxid == 186538
    assert result_with_alt.score >= 0.85


def test_alt_name_not_used_when_primary_matches():
    """If primary name matches, alt names should not be tried."""
    index = _make_index_with_species("Escherichia coli", taxid=562)
    composite = CompositeMatchStrategy()
    result = composite.match(
        "Escherichia coli",
        None,
        index,
        alt_names=["E. coli"],
    )
    assert result.match_type == MatchType.EXACT_NAME
    assert result.matched_taxid == 562
