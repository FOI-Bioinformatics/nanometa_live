"""Structural tests for the Sankey builder in ``classification_helpers``.

``create_sankey_data`` is the launch/visualization-critical flow diagram on the
Taxonomy tab and, at ~1092 LOC, the largest helper module; before this it had no
dedicated test (only ``test_sunburst_tax_levels`` exercised the shared data-prep
path through the Sunburst entry point). These tests assert the actual node/link
STRUCTURE the figure is built from -- exact parent->child edges, node values, link
integrity, the per-level cap, and the graceful-degradation paths -- rather than
merely that a figure is returned.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from nanometa_live.app.tabs.classification_helpers import create_sankey_data


# Kraken2 loader column contract: % cumul_reads reads rank taxid name parent_taxid.
_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _controlled_kraken_df() -> pd.DataFrame:
    """A small, fully-determined Bacteria tree: D -> 2x P -> 1x S each.

    cumul_reads are chosen so the within-level ordering is unambiguous
    (Firmicutes 600 > Proteobacteria 400; aureus 600 > coli 400). Species point
    at their phylum via parent_taxid so the link builder's nearest-visible-
    ancestor walk has a single correct answer with tax_levels D, P, S.
    """
    rows = [
        # %     cumul reads rank  taxid name                      parent
        [2.0, 0, 0, "U", 0, "unclassified", 0],
        [100.0, 1000, 0, "R", 1, "root", 0],
        [100.0, 1000, 0, "D", 2, "Bacteria", 1],
        [60.0, 600, 0, "P", 1239, "Firmicutes", 2],
        [40.0, 400, 0, "P", 1224, "Proteobacteria", 2],
        [60.0, 600, 600, "S", 1280, "Staphylococcus aureus", 1239],
        [40.0, 400, 400, "S", 562, "Escherichia coli", 1224],
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


def _sankey_trace(fig) -> go.Sankey:
    assert isinstance(fig, go.Figure), f"expected a Figure, got {type(fig)}"
    assert len(fig.data) == 1, f"expected one trace, got {len(fig.data)}"
    tr = fig.data[0]
    assert isinstance(tr, go.Sankey), f"expected a Sankey trace, got {type(tr)}"
    return tr


def _names(tr) -> list:
    """Node display names, in node-index order (customdata[3] is the full name)."""
    return [cd[3] for cd in tr.node.customdata]


def _edges_by_name(tr) -> set:
    names = _names(tr)
    return {(names[s], names[t]) for s, t in zip(tr.link.source, tr.link.target)}


def _value_by_name(tr) -> dict:
    """Node read count keyed by name (customdata[0] is the cumulative reads)."""
    return {cd[3]: cd[0] for cd in tr.node.customdata}


class TestSankeyControlledTree:
    """Exact structure on a fully-determined input."""

    def test_nodes_and_edges_follow_the_taxonomy(self):
        fig = create_sankey_data(
            _controlled_kraken_df(), domains=["Bacteria"],
            tax_levels=["D", "P", "S"], min_reads=1, max_taxa_per_level=10,
        )
        tr = _sankey_trace(fig)

        # Five visible nodes: 1 domain, 2 phyla, 2 species.
        assert set(_names(tr)) == {
            "Bacteria", "Firmicutes", "Proteobacteria",
            "Staphylococcus aureus", "Escherichia coli",
        }
        # Edges connect each node to its nearest visible ancestor one level up.
        assert _edges_by_name(tr) == {
            ("Bacteria", "Firmicutes"),
            ("Bacteria", "Proteobacteria"),
            ("Firmicutes", "Staphylococcus aureus"),
            ("Proteobacteria", "Escherichia coli"),
        }

    def test_node_values_are_cumulative_reads(self):
        fig = create_sankey_data(
            _controlled_kraken_df(), domains=["Bacteria"],
            tax_levels=["D", "P", "S"], min_reads=1, max_taxa_per_level=10,
        )
        vals = _value_by_name(_sankey_trace(fig))
        assert vals["Bacteria"] == 1000
        assert vals["Firmicutes"] == 600
        assert vals["Proteobacteria"] == 400
        assert vals["Staphylococcus aureus"] == 600
        assert vals["Escherichia coli"] == 400

    def test_skipping_an_intermediate_level_reparents_to_nearest_ancestor(self):
        # With only D and S selected, each species must link straight to the
        # domain (its phylum is no longer a visible node).
        fig = create_sankey_data(
            _controlled_kraken_df(), domains=["Bacteria"],
            tax_levels=["D", "S"], min_reads=1, max_taxa_per_level=10,
        )
        tr = _sankey_trace(fig)
        assert _edges_by_name(tr) == {
            ("Bacteria", "Staphylococcus aureus"),
            ("Bacteria", "Escherichia coli"),
        }


class TestSankeyLinkIntegrity:
    """Invariants that must hold for any Sankey, checked on real fixture data."""

    def _trace(self, df):
        fig = create_sankey_data(
            df, domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1, max_taxa_per_level=10,
        )
        return _sankey_trace(fig)

    def test_link_indices_in_range_and_no_self_links(self, kraken_data_medium):
        tr = self._trace(kraken_data_medium)
        n = len(tr.node.label)
        assert n > 0
        for s, t in zip(tr.link.source, tr.link.target):
            assert 0 <= s < n and 0 <= t < n, f"link index out of range: ({s},{t}) n={n}"
            assert s != t, "a node must not link to itself"

    def test_parallel_node_arrays_are_consistent_length(self, kraken_data_medium):
        tr = self._trace(kraken_data_medium)
        n = len(tr.node.label)
        assert len(tr.node.color) == n
        assert len(tr.node.customdata) == n
        assert len(tr.node.x) == n
        assert len(tr.node.y) == n

    def test_link_values_are_positive(self, kraken_data_medium):
        tr = self._trace(kraken_data_medium)
        assert len(tr.link.value) > 0
        assert all(v > 0 for v in tr.link.value)


class TestSankeyCap:
    """max_taxa_per_level bounds the nodes shown at each rank."""

    def _trace(self, df, cap):
        fig = create_sankey_data(
            df, domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1, max_taxa_per_level=cap,
        )
        return _sankey_trace(fig)

    def test_cap_bounds_nodes_per_rank(self, kraken_data_medium):
        cap = 2
        tr = self._trace(kraken_data_medium, cap)
        # customdata[2] is the human rank name; count nodes per rank.
        per_rank: dict = {}
        for cd in tr.node.customdata:
            per_rank[cd[2]] = per_rank.get(cd[2], 0) + 1
        for rank_name, count in per_rank.items():
            assert count <= cap, f"rank {rank_name} has {count} nodes, cap was {cap}"

    def test_tighter_cap_yields_no_more_nodes(self, kraken_data_medium):
        loose = len(self._trace(kraken_data_medium, 10).node.label)
        tight = len(self._trace(kraken_data_medium, 2).node.label)
        assert tight <= loose


class TestSankeyGracefulDegradation:
    """Insufficient or absent data returns a placeholder/None, never raises."""

    def test_empty_dataframe_returns_info_placeholder(self):
        fig = create_sankey_data(
            pd.DataFrame(columns=_COLUMNS), domains=["Bacteria"],
            tax_levels=["D", "P", "S"], min_reads=1, max_taxa_per_level=10,
        )
        assert isinstance(fig, go.Figure)
        # The info placeholder carries no Sankey trace.
        assert len(fig.data) == 0

    def test_single_level_returns_info_placeholder(self):
        # A flow diagram needs >= 2 levels; one level cannot show relationships.
        fig = create_sankey_data(
            _controlled_kraken_df(), domains=["Bacteria"],
            tax_levels=["S"], min_reads=1, max_taxa_per_level=10,
        )
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_unknown_domain_returns_none(self):
        fig = create_sankey_data(
            _controlled_kraken_df(), domains=["Nonexistent Domain"],
            tax_levels=["D", "P", "S"], min_reads=1, max_taxa_per_level=10,
        )
        assert fig is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
