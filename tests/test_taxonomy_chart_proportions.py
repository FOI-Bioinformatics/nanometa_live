"""Taxonomy-tab charts must show proportions of the reads, counted once.

Sankey: a node's "Proportion" was its cumulative reads over the sum of
cumulative reads across EVERY row of the report (root, domain, phylum, ...),
which counts each read once per rank, so every percentage was low by roughly
the number of ranks. The denominator is the run's read total, classified plus
unclassified -- the same base as Kraken2's own ``%`` column.

Sunburst: node values are cumulative (clade) reads, but the trace used
``branchvalues="remainder"``, under which plotly adds a parent's value on top
of its children's. A read was then counted once per level, so a branch that
reaches species outweighed one that stops at genus, and the "Of parent group"
hover was wrong. Cumulative values need ``branchvalues="total"``.
"""

import pandas as pd
import pytest

from nanometa_live.app.tabs.classification_helpers import (
    create_sankey_data,
    create_sunburst_data,
)

pytestmark = pytest.mark.unit

_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _df():
    """100 reads: 20 unclassified, 80 Bacteria -> Proteo -> GenA (60) / GenB (20).

    GenA resolves to one species; GenB stops at genus, so the two branches
    have different depths.
    """
    rows = [
        [20.0, 20, 20, "U", 0, "unclassified", 0],
        [80.0, 80, 0, "R", 1, "root", 0],
        [80.0, 80, 0, "D", 2, "Bacteria", 1],
        [80.0, 80, 0, "P", 10, "Proteo", 2],
        [60.0, 60, 0, "G", 100, "GenA", 10],
        [20.0, 20, 20, "G", 200, "GenB", 10],
        [60.0, 60, 60, "S", 101, "GenA spA", 100],
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


# --- Sankey ---------------------------------------------------------------

def _sankey_pct_by_name():
    fig = create_sankey_data(
        _df(), domains=["Bacteria"], tax_levels=["D", "P", "G", "S"],
        min_reads=1, max_taxa_per_level=10,
    )
    tr = fig.data[0]
    return {cd[3]: cd[1] for cd in tr.node.customdata}


@pytest.mark.parametrize("name,expected", [
    ("Bacteria", 80.0),
    ("Proteo", 80.0),
    ("GenA", 60.0),
    ("GenB", 20.0),
    ("GenA spA", 60.0),
])
def test_sankey_proportion_is_share_of_all_reads(name, expected):
    assert _sankey_pct_by_name()[name] == pytest.approx(expected)


# --- Sunburst ---------------------------------------------------------------

def _rendered_sizes(trace):
    """Sector size per node id under the trace's branchvalues semantics.

    "total": a node's size is its value. "remainder": its value plus the
    sizes of its children (plotly's documented behaviour).
    """
    ids = list(trace.ids)
    parents = list(trace.parents)
    values = dict(zip(ids, trace.values))
    children = {}
    for i, p in zip(ids, parents):
        children.setdefault(p, []).append(i)

    def size(node):
        if trace.branchvalues == "total":
            return values[node]
        return values[node] + sum(size(c) for c in children.get(node, []))

    return {i: size(i) for i in ids}


def _sunburst():
    return create_sunburst_data(
        _df(), domains=["Bacteria"], tax_levels=["D", "P", "G", "S"],
        min_reads=1, config={},
    ).data[0]


def test_sunburst_sector_sizes_follow_read_counts():
    sizes = _rendered_sizes(_sunburst())
    # GenA (60 reads) and GenB (20 reads) are siblings: 3:1, whatever the
    # depth below each.
    assert sizes["G_GenA"] / sizes["G_GenB"] == pytest.approx(3.0)
    # Proteo holds all of Bacteria's reads.
    assert sizes["P_Proteo"] / sizes["D_Bacteria"] == pytest.approx(1.0)


def test_sunburst_values_are_consistent_for_total_mode():
    tr = _sunburst()
    assert tr.branchvalues == "total"
    values = dict(zip(tr.ids, tr.values))
    child_sum = {}
    for i, p in zip(tr.ids, tr.parents):
        if p:
            child_sum[p] = child_sum.get(p, 0) + values[i]
    for parent, total in child_sum.items():
        # plotly drops a "total" sector whose children exceed it.
        assert values[parent] >= total, parent


# --- Filters the Taxonomy tab offers ---------------------------------------
#
# "Minimum DNA Sequences: hide organisms with fewer sequences than this
# value". create_sankey_data accepted min_reads and never used it; the
# Sunburst applied it to species on the DIRECT read column, so a species
# whose reads sit in its subspecies vanished. The Sunburst also ignored the
# Domain selection. Both charts now hide any taxon whose cumulative reads
# are below the value, and both honour the domains.

def _two_domain_df():
    rows = [
        [10.0, 10, 10, "U", 0, "unclassified", 0],
        [90.0, 90, 0, "R", 1, "root", 0],
        [80.0, 80, 0, "D", 2, "Bacteria", 1],
        [80.0, 80, 0, "G", 100, "GenA", 2],
        [75.0, 75, 0, "S", 101, "GenA spA", 100],     # all reads in S1
        [75.0, 75, 75, "S1", 102, "GenA spA sub1", 101],
        [5.0, 5, 5, "S", 103, "GenA spB", 100],
        [10.0, 10, 0, "D", 10239, "Viruses", 1],
        [10.0, 10, 0, "G", 200, "VirG", 10239],
        [10.0, 10, 10, "S", 201, "VirG spV", 200],
    ]
    return pd.DataFrame(rows, columns=_COLUMNS)


def _sankey_names(min_reads, domains=("Bacteria",)):
    fig = create_sankey_data(
        _two_domain_df(), domains=list(domains), tax_levels=["D", "G", "S"],
        min_reads=min_reads, max_taxa_per_level=10)
    return {cd[3] for cd in fig.data[0].node.customdata}


def _sunburst_labels(min_reads, domains=("Bacteria",)):
    fig = create_sunburst_data(
        _two_domain_df(), domains=list(domains), tax_levels=["D", "G", "S"],
        min_reads=min_reads, config={})
    return set(fig.data[0].labels)


def test_sankey_hides_taxa_below_minimum_reads():
    assert "GenA spB" in _sankey_names(1)
    assert "GenA spB" not in _sankey_names(10)


def test_sunburst_keeps_a_species_whose_reads_sit_in_subspecies():
    labels = _sunburst_labels(10)
    assert "GenA spA" in labels
    assert "GenA spB" not in labels


def test_sunburst_honours_the_domain_selection():
    assert "VirG spV" not in _sunburst_labels(1, domains=("Bacteria",))
    assert "VirG spV" in _sunburst_labels(1, domains=("Bacteria", "Viruses"))


def test_both_views_state_the_same_share_of_all_reads():
    """Sankey "Proportion" and Sunburst "Of total" describe one taxon with
    one number: its share of all reads in the sample (Kraken2's %). The
    Sunburst divided by the reads it displayed, so Firmicutes read 71.5% in
    one view and about 79% in the other on the same data."""
    sankey = _sankey_pct_by_name()
    sb = _sunburst()
    sunburst = {label: cd[2] for label, cd in zip(sb.labels, sb.customdata)}
    for name in ("Bacteria", "Proteo", "GenA", "GenB"):
        assert sunburst[name] == pytest.approx(sankey[name]), name
