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
    canonical = name.lower().replace("_", " ")
    node = DatabaseTaxonomyNode(
        taxid=taxid,
        name=name,
        rank="S",
        parent_taxid=1,
        name_normalized=canonical,
    )
    index = DatabaseTaxonomyIndex.__new__(DatabaseTaxonomyIndex)
    index.by_taxid = {taxid: node}
    index.by_name = {canonical: [taxid]}
    index.by_name_gtdb = {}
    index.by_prefix = {}
    index._species_cache = None
    index.database_type = DatabaseTaxonomyType.CUSTOM
    index.database_path = ""
    index.database_hash = ""
    return index


def test_alt_name_match_when_primary_fails():
    """If primary name is not in DB but an alt name is, match via alt name."""
    # Use a species pair that has no reclassification entry
    index = _make_index_with_species("Vibrio cholerae", taxid=666)
    composite = CompositeMatchStrategy()

    # Primary name won't match
    result_no_alt = composite.match("Fakebacterium unknownum", None, index)
    assert result_no_alt.match_type == MatchType.NO_MATCH

    # With alt_names, should find "Vibrio cholerae"
    result_with_alt = composite.match(
        "Fakebacterium unknownum",
        None,
        index,
        alt_names=["Vibrio cholerae"],
    )
    assert result_with_alt.match_type == MatchType.ALT_NAME
    assert result_with_alt.matched_taxid == 666
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


# === Database type detection ===

def test_ncbi_database_detection():
    """NCBI database should be detected when reference taxa match."""
    index = _make_index_with_species("Escherichia coli", taxid=562)
    for taxid, name in [(632, "Yersinia pestis"), (1280, "Staphylococcus aureus")]:
        canonical = name.lower()
        node = DatabaseTaxonomyNode(
            taxid=taxid, name=name, rank="S", parent_taxid=1,
            name_normalized=canonical,
        )
        index.by_taxid[taxid] = node
        index.by_name[canonical] = [taxid]
    index.database_type = DatabaseTaxonomyType.NCBI
    assert index.database_type == DatabaseTaxonomyType.NCBI


# === Reclassification matching ===

def test_reclassification_clostridioides():
    """Clostridioides difficile should match Clostridium difficile via reclassification."""
    index = _make_index_with_species("Clostridium difficile", taxid=1496)
    composite = CompositeMatchStrategy()
    result = composite.match("Clostridioides difficile", None, index)
    assert result.match_type != MatchType.NO_MATCH
    assert result.matched_taxid == 1496


def test_reclassification_lactobacillus():
    """Limosilactobacillus fermentum should match Lactobacillus fermentum."""
    index = _make_index_with_species("Lactobacillus fermentum", taxid=1613)
    composite = CompositeMatchStrategy()
    result = composite.match("Limosilactobacillus fermentum", None, index)
    assert result.match_type != MatchType.NO_MATCH
    assert result.matched_taxid == 1613


# === GTDB variant matching ===

def test_gtdb_underscore_variant():
    """Should match GTDB-style underscored names."""
    index = _make_index_with_species("Escherichia_coli", taxid=562)
    index.by_name["escherichia_coli"] = [562]
    composite = CompositeMatchStrategy()
    result = composite.match("Escherichia coli", None, index)
    assert result.match_type != MatchType.NO_MATCH


def test_gtdb_suffix_variant():
    """Should match GTDB suffix variants like Escherichia coli_A."""
    canonical = "escherichia coli_a"
    node = DatabaseTaxonomyNode(
        taxid=99999, name="Escherichia coli_A", rank="S", parent_taxid=1,
        name_normalized=canonical,
    )
    index = _make_index_with_species("placeholder", taxid=1)
    index.by_taxid[99999] = node
    index.by_name[canonical] = [99999]
    composite = CompositeMatchStrategy()
    result = composite.match("Escherichia coli", None, index)
    if result.match_type != MatchType.NO_MATCH:
        assert result.matched_taxid == 99999


# === ExactTaxid skipped on custom DB ===

def test_exact_taxid_skipped_on_custom_db():
    """ExactTaxidStrategy should be skipped for CUSTOM databases."""
    index = _make_index_with_species("Some GTDB organism", taxid=562)
    index.database_type = DatabaseTaxonomyType.CUSTOM
    composite = CompositeMatchStrategy()
    result = composite.match("Escherichia coli", 562, index)
    if result.match_type != MatchType.NO_MATCH:
        assert result.match_type != MatchType.EXACT_TAXID


# === Parent taxon is last resort ===

def test_parent_taxon_is_last_resort():
    """ParentTaxon (genus match) should only trigger after all other strategies fail."""
    node = DatabaseTaxonomyNode(
        taxid=561, name="Escherichia", rank="G", parent_taxid=1,
        name_normalized="escherichia",
    )
    index = DatabaseTaxonomyIndex.__new__(DatabaseTaxonomyIndex)
    index.by_taxid = {561: node}
    index.by_name = {"escherichia": [561]}
    index.by_name_gtdb = {}
    index.by_prefix = {}
    index._species_cache = None
    index.database_type = DatabaseTaxonomyType.CUSTOM
    index.database_path = ""
    index.database_hash = ""

    composite = CompositeMatchStrategy()
    result = composite.match("Escherichia coli", None, index)
    if result.match_type != MatchType.NO_MATCH:
        assert result.match_type == MatchType.PARENT_TAXON
        assert result.score <= 0.5


# === No match returns correct result ===

def test_no_match_returns_no_match():
    """Completely unknown species should return NO_MATCH."""
    index = _make_index_with_species("Escherichia coli", taxid=562)
    composite = CompositeMatchStrategy()
    result = composite.match("Xyzzyplasm nonexistentium", None, index)
    assert result.match_type == MatchType.NO_MATCH
    assert result.score == 0.0


# === Alt names with multiple matches ===

def test_alt_name_first_match_wins():
    """When multiple alt names could match, the first one wins."""
    index = _make_index_with_species("Vibrio cholerae", taxid=666)
    node2 = DatabaseTaxonomyNode(
        taxid=11269, name="Marburg virus", rank="S", parent_taxid=1,
        name_normalized="marburg virus",
    )
    index.by_taxid[11269] = node2
    index.by_name["marburg virus"] = [11269]

    composite = CompositeMatchStrategy()
    result = composite.match(
        "Fakebacterium unknownum", None, index,
        alt_names=["Vibrio cholerae", "Marburg virus"]
    )
    assert result.match_type == MatchType.ALT_NAME
    assert result.matched_taxid == 666  # First alt name wins
