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
