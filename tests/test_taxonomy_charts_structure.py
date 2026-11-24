"""Taxonomy-tab charts: structure, colour meaning, watched taxa, captions.

Live test of 2026-11-24 (tester a4, port 8074):
- The Sankey linked a node only to an ancestor exactly ONE selected level up,
  so when a selected rank is absent from a lineage (Bacteria and Archaea have
  no Kingdom rank) or the parent was capped out, the branch lost its links and
  was pruned as an orphan: with the Overview preset Bacteria (98% of reads)
  vanished, and at the default cap of 10 F. tularensis (28,806 reads) was
  missing while the Sunburst showed it.
- The Subspecies Focus preset could not show subspecies: the callback's
  canonical level order had no "S1".
- The Life Domains selection was a State, so it waited for an unrelated
  Apply button.
- Colour encoded rank only, which column/ring position already shows, so a
  lineage could not be followed across the chart, and watched organisms were
  indistinguishable from background.
- The Sunburst root carried a filter-dependent sum labelled "All Taxa", and
  unclassified reads appeared nowhere.
"""

import pandas as pd
import pytest

from nanometa_live.app.tabs.classification_helpers import (
    LINEAGE_OTHER_COLOR,
    LINEAGE_PALETTE,
    WATCHED_COLOR,
    create_sankey_data,
    create_sunburst_data,
)

pytestmark = pytest.mark.unit

COLS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


def _tree():
    """1000 reads: 100 unclassified; Bacteria 880 (no Kingdom rank);
    Eukaryota 20 under a Kingdom."""
    return _df([
        [10.0, 100, 100, "U", 0, "unclassified", 0],
        [90.0, 900, 0, "R", 1, "root", 0],
        [88.0, 880, 0, "D", 2, "Bacteria", 1],
        [60.0, 600, 0, "P", 10, "Pseudomonadota", 2],
        [60.0, 600, 0, "F", 100, "Enterobacteriaceae", 10],
        [50.0, 500, 0, "G", 1000, "Escherichia", 100],
        [50.0, 500, 500, "S", 1001, "Escherichia coli", 1000],
        [10.0, 100, 0, "G", 1100, "Klebsiella", 100],
        [10.0, 100, 100, "S", 1101, "Klebsiella pneumoniae", 1100],
        [28.0, 280, 0, "P", 20, "Bacillota", 2],
        [28.0, 280, 0, "F", 200, "Francisellaceae", 20],
        [2.0, 20, 0, "G", 2000, "Francisella", 200],
        [2.0, 20, 0, "S", 2001, "Francisella tularensis", 2000],
        [2.0, 20, 20, "S1", 2002, "F. tularensis holarctica", 2001],
        [26.0, 260, 0, "G", 2100, "Bacillus", 200],
        [26.0, 260, 260, "S", 2101, "Bacillus subtilis", 2100],
        [2.0, 20, 0, "D", 3, "Eukaryota", 1],
        [2.0, 20, 0, "K", 30, "Metazoa", 3],
        [2.0, 20, 0, "P", 31, "Chordata", 30],
        [2.0, 20, 20, "S", 3101, "Homo sapiens", 31],
    ])


ALL_DOMAINS = ["Bacteria", "Archaea", "Eukaryota", "Viruses"]


def _sankey(levels, cap=10, min_reads=1, protected=None, **kw):
    return create_sankey_data(_tree(), ALL_DOMAINS, levels, min_reads, cap,
                              protected_taxa=protected, **kw)


def _sankey_names(fig):
    return [cd[3] for cd in fig.data[0].node.customdata]


def _sankey_edges(fig):
    tr = fig.data[0]
    names = _sankey_names(fig)
    return {(names[s], names[t]) for s, t in zip(tr.link.source, tr.link.target)}


# --- Structure -------------------------------------------------------------

def test_a_lineage_without_the_kingdom_rank_still_flows_from_its_domain():
    fig = _sankey(["D", "K", "P"])
    edges = _sankey_edges(fig)
    assert ("Bacteria", "Pseudomonadota") in edges
    assert ("Bacteria", "Bacillota") in edges
    assert ("Eukaryota", "Metazoa") in edges


def _spread_tree():
    """Genus Spread (700) holds seven 100-read species; genus Big (300) holds
    one 300-read species. At a cap of 1 the genus column shows Spread only,
    while the species column shows Big's species -- whose genus is capped
    out (the shape that hid F. tularensis in the live test)."""
    rows = [
        [100.0, 1000, 0, "R", 1, "root", 0],
        [100.0, 1000, 0, "D", 2, "Bacteria", 1],
        [100.0, 1000, 0, "F", 10, "Fam", 2],
        [70.0, 700, 0, "G", 100, "Spread", 10],
        [30.0, 300, 0, "G", 200, "Big", 10],
        [30.0, 300, 300, "S", 201, "Big one", 200],
    ]
    rows += [[10.0, 100, 100, "S", 101 + i, f"Spread sp{i}", 100] for i in range(7)]
    return _df(rows)


def test_a_species_whose_genus_is_capped_out_hangs_off_the_nearest_shown_ancestor():
    fig = create_sankey_data(_spread_tree(), ALL_DOMAINS, ["F", "G", "S"], 1, 1)
    names = _sankey_names(fig)
    assert "Big one" in names and "Big" not in names
    assert ("Fam", "Big one") in _sankey_edges(fig)


def test_both_views_draw_the_same_taxa_under_a_cap():
    sankey = set(_sankey_names(create_sankey_data(
        _spread_tree(), ALL_DOMAINS, ["F", "G", "S"], 1, 1)))
    sb = create_sunburst_data(_spread_tree(), ALL_DOMAINS, ["F", "G", "S"], 1, {},
                              max_taxa_per_level=1).data[0]
    sunburst = set(sb.labels) - {sb.labels[0]}
    assert sankey == sunburst


def test_subspecies_level_is_drawn():
    fig = _sankey(["G", "S", "S1"], cap=0)
    assert "F. tularensis holarctica" in _sankey_names(fig)
    assert ("Francisella tularensis", "F. tularensis holarctica") in _sankey_edges(fig)


def test_subspecies_is_in_the_callback_level_order():
    from nanometa_live.app.tabs.classification_tab import CHART_LEVEL_ORDER
    assert CHART_LEVEL_ORDER.index("S1") == CHART_LEVEL_ORDER.index("S") + 1


# --- Watched taxa ------------------------------------------------------------

def test_a_watched_taxon_survives_cap_and_min_reads_and_is_outlined():
    protected = {2001: "Francisella tularensis (critical)"}
    fig = _sankey(["F", "G", "S"], cap=1, min_reads=100, protected=protected)
    names = _sankey_names(fig)
    assert "Francisella tularensis" in names
    i = names.index("Francisella tularensis")
    node = fig.data[0].node
    # plotly.js draws no per-node outline in a Sankey (an array falls back to
    # a black stroke on every node), so a watched node is filled with the
    # reserved warning colour, which the lineage palette does not use.
    assert node.color[i] == WATCHED_COLOR
    assert WATCHED_COLOR not in LINEAGE_PALETTE
    assert node.label[i].startswith("\u26a0")
    assert isinstance(node.line.color, str)
    assert "critical" in str(node.customdata[i][5])


def test_sunburst_outlines_a_watched_taxon_too():
    protected = {2001: "Francisella tularensis (critical)"}
    sb = create_sunburst_data(_tree(), ALL_DOMAINS, ["F", "G", "S"], 100, {},
                              max_taxa_per_level=1,
                              protected_taxa=protected).data[0]
    labels = list(sb.labels)
    i = next(k for k, lab in enumerate(labels) if "Francisella tularensis" in lab)
    assert sb.marker.line.color[i] == WATCHED_COLOR


# --- Colour by lineage -------------------------------------------------------

def test_descendants_share_their_lineage_colour():
    fig = _sankey(["D", "P", "F", "G", "S"], cap=0, color_mode="lineage")
    names = _sankey_names(fig)
    col = dict(zip(names, fig.data[0].node.color))
    assert col["Pseudomonadota"] == col["Escherichia coli"] == col["Enterobacteriaceae"]
    assert col["Bacillota"] == col["Bacillus subtilis"]
    assert col["Pseudomonadota"] != col["Bacillota"]
    # The largest lineage takes the first palette slot.
    assert col["Pseudomonadota"] == LINEAGE_PALETTE[0]


def test_lineages_beyond_the_palette_fold_into_other():
    rows = [[100.0, 1000, 0, "R", 1, "root", 0], [100.0, 1000, 0, "D", 2, "Bacteria", 1]]
    n = len(LINEAGE_PALETTE) + 2
    for i in range(n):
        rows.append([1.0, 100 - i, 100 - i, "P", 100 + i, f"Phylum{i}", 2])
    fig = create_sankey_data(_df(rows), ALL_DOMAINS, ["D", "P"], 1, 0,
                             color_mode="lineage")
    col = dict(zip(_sankey_names(fig), fig.data[0].node.color))
    assert col[f"Phylum{n - 1}"] == LINEAGE_OTHER_COLOR
    assert col["Phylum0"] == LINEAGE_PALETTE[0]


# --- Hover and captions --------------------------------------------------------

def test_sankey_hover_carries_share_of_parent():
    fig = _sankey(["P", "F", "G"], cap=0)
    names = _sankey_names(fig)
    cd = fig.data[0].node.customdata[names.index("Escherichia")]
    # 500 of Enterobacteriaceae's 600.
    assert cd[4] == pytest.approx(500 / 600 * 100)


def test_caption_states_unclassified_share_and_hidden_taxa():
    fig = _sankey(["F", "G", "S"], cap=1)
    title = fig.layout.title.text
    assert "10.0% unclassified" in title
    assert "hidden" in title


def test_sunburst_root_is_named_for_what_it_holds():
    sb = create_sunburst_data(_tree(), ALL_DOMAINS, ["P", "F"], 1, {}).data[0]
    assert sb.labels[0] == "Classified reads"
    # Its share is of ALL reads: 900 classified of 1000.
    assert sb.customdata[0][2] == pytest.approx(90.0)


def test_both_views_share_one_title():
    sk = _sankey(["P", "F"]).layout.title.text
    sb = create_sunburst_data(_tree(), ALL_DOMAINS, ["P", "F"], 1, {}).layout.title.text
    assert sk.split("<br>")[0] == sb.split("<br>")[0]


# --- Callback wiring -----------------------------------------------------------

def test_domain_selection_redraws_without_apply():
    from nanometa_live.app.tabs.classification_tab import register_classification_callbacks
    from tests.dash_test_utils import make_callback_app

    app = make_callback_app(register_classification_callbacks)
    spec = next(s for k, s in app.callback_map.items()
                if "classification-plot.figure" in k)
    inputs = {i["id"] + "." + i["property"] for i in spec["inputs"]}
    assert "classification-domains-input.value" in inputs


def test_species_labels_abbreviate_a_genus_drawn_beside_them():
    """Leaf labels sit left of their node and collided with the genus label
    in the column before ("Staphylococcus|Staphylococcus aureus")."""
    fig = _sankey(["G", "S", "S1"], cap=0)
    labels = dict(zip(_sankey_names(fig), fig.data[0].node.label))
    assert labels["Escherichia coli"] == "E. coli"
    assert labels["F. tularensis holarctica"] == "F. tularensis holarctica"
    assert labels["Escherichia"] == "Escherichia"
    # The hover keeps the full name.
    assert "Escherichia coli" in _sankey_names(fig)


def _contrast(a, b):
    def lum(h):
        def lin(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, bb = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(bb)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_sunburst_text_contrasts_with_each_sector():
    """Dark ink on the dark neutral Domain ring and on saturated lineage
    hues was unreadable; the text colour now follows each fill."""
    sb = create_sunburst_data(_tree(), ALL_DOMAINS, ["D", "P", "F", "G", "S"], 1, {}).data[0]
    for fill, ink in zip(sb.marker.colors, sb.insidetextfont.color):
        assert _contrast(fill, ink) >= 3.0, (fill, ink)
