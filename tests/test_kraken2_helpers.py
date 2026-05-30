"""
Unit tests for app/tabs/kraken2_helpers.py.

These are the pure-pandas transforms behind the Classification tab (no Dash
imports). The headline is apply_authoritative_taxonomy / load_kraken2_taxonomy:
per-sample reports can carry wrong indentation-derived parents, so the parent
chain is rebuilt from the database inspect.txt. Tests also cover rank
normalisation, domain filtering, the parent-map walk and colour generation.
"""

import pandas as pd
import pytest

from nanometa_live.app.tabs import kraken2_helpers as kh
from nanometa_live.app.tabs.kraken2_helpers import (
    apply_authoritative_taxonomy,
    build_parent_map,
    filter_by_domains,
    get_level_color,
    load_kraken2_taxonomy,
    normalize_ranks,
    recalculate_cumulative_reads,
)


@pytest.fixture(autouse=True)
def _clear_taxonomy_cache():
    kh._TAXONOMY_CACHE.clear()
    yield
    kh._TAXONOMY_CACHE.clear()


class TestNormalizeRanks:
    def test_subranks_collapse_to_standard(self):
        df = pd.DataFrame({"rank": ["S1", "P3", "G1", "S", "R"]})
        result = normalize_ranks(df)
        assert result["rank"].tolist() == ["S", "P", "G", "S", "R"]

    def test_original_rank_preserved(self):
        df = pd.DataFrame({"rank": ["S1"]})
        result = normalize_ranks(df)
        assert result["original_rank"].tolist() == ["S1"]

    def test_empty_frame_unchanged(self):
        df = pd.DataFrame()
        assert normalize_ranks(df).empty


class TestLoadKraken2Taxonomy:
    def test_parses_parent_chain_from_indentation(self, tmp_path):
        (tmp_path / "inspect.txt").write_text(
            "100.00\t1000\t0\tR\t1\troot\n"
            "90.00\t900\t0\tD\t2\t  Bacteria\n"
            "50.00\t500\t0\tG\t561\t    Escherichia\n"
            "25.00\t250\t250\tS\t562\t      Escherichia coli\n"
        )
        mapping = load_kraken2_taxonomy(str(tmp_path))
        assert mapping == {1: 0, 2: 1, 561: 2, 562: 561}

    def test_missing_inspect_returns_empty(self, tmp_path):
        assert load_kraken2_taxonomy(str(tmp_path)) == {}

    def test_empty_path_returns_empty(self):
        assert load_kraken2_taxonomy("") == {}


class TestApplyAuthoritativeTaxonomy:
    def test_replaces_parent_taxid_from_mapping(self):
        df = pd.DataFrame({"taxid": [562, 561], "parent_taxid": [99, 99]})
        corrected = apply_authoritative_taxonomy(df, {562: 561, 561: 2})
        assert corrected.loc[corrected["taxid"] == 562, "parent_taxid"].iloc[0] == 561
        assert corrected.loc[corrected["taxid"] == 561, "parent_taxid"].iloc[0] == 2

    def test_unknown_taxid_keeps_existing_parent(self):
        df = pd.DataFrame({"taxid": [999], "parent_taxid": [42]})
        corrected = apply_authoritative_taxonomy(df, {562: 561})
        assert corrected.loc[0, "parent_taxid"] == 42

    def test_empty_mapping_returns_input_unchanged(self):
        df = pd.DataFrame({"taxid": [562], "parent_taxid": [1]})
        result = apply_authoritative_taxonomy(df, {})
        assert result.equals(df)


class TestRecalculateCumulativeReads:
    def test_composite_key_to_cumul_reads(self):
        df = pd.DataFrame({
            "name": ["Escherichia coli", "Bacteria"],
            "rank": ["S", "D"],
            "cumul_reads": [150, 900],
        })
        result = recalculate_cumulative_reads(df)
        assert result["S_Escherichia coli"] == 150
        assert result["D_Bacteria"] == 900

    def test_empty_frame_returns_empty_dict(self):
        assert recalculate_cumulative_reads(pd.DataFrame()) == {}


class TestFilterByDomains:
    def test_selects_domain_and_descendants(self):
        df = pd.DataFrame({"name": [
            "root",
            "  Bacteria",
            "    Escherichia",
            "      Escherichia coli",
            "  Archaea",
            "    Methanococcus",
        ]})
        result = filter_by_domains(df, ["Bacteria"])
        assert [n.strip() for n in result["name"]] == [
            "Bacteria", "Escherichia", "Escherichia coli"
        ]

    def test_no_domains_returns_empty(self):
        df = pd.DataFrame({"name": ["  Bacteria"]})
        assert filter_by_domains(df, []).empty


class TestBuildParentMap:
    def test_walks_taxid_chain_to_parent_level(self):
        tax_levels = ["G", "S"]
        tax_df = pd.DataFrame({
            "rank": ["G", "S"],
            "name": ["Escherichia", "Escherichia coli"],
            "taxid": [561, 562],
            "recalc_cumul": [500, 250],
        })
        node_ids = {"G_Escherichia": 0, "S_Escherichia coli": 1}
        taxid_to_parent = {562: 561, 561: 2}
        taxid_to_key = {561: "G_Escherichia", 562: "S_Escherichia coli"}
        parent_map = build_parent_map(
            tax_df, tax_df, tax_levels, node_ids, top_filter=10,
            taxid_to_parent=taxid_to_parent, taxid_to_key=taxid_to_key,
        )
        assert parent_map == {"S_Escherichia coli": "G_Escherichia"}


class TestGetLevelColor:
    def test_returns_rgb_string(self):
        color = get_level_color("D")
        assert color.startswith("rgb(")

    def test_unknown_rank_uses_default(self):
        # Default #94A3B8 -> rgb(148,163,184) with no variation at total_in_level=1.
        assert get_level_color("ZZZ") == "rgb(148,163,184)"
