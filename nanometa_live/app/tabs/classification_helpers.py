"""
Pure visualization helpers for the Classification tab.

Builds the Sankey and Sunburst figures from a parsed Kraken2 dataframe. These
functions perform no Dash callback wiring and no file I/O, so they can be unit
tested directly (see the *_tab.py -> *_helpers.py split used across the
dashboard, main, qc, and validation tabs). The callback wiring lives in
``classification_tab.py``.
"""

import logging

import pandas as pd
import plotly.graph_objects as go

from nanometa_live.app.utils.plotly_theme import apply_theme_to_figure
from nanometa_live.app.tabs.kraken2_helpers import (
    RANK_NAMES,
    TAXONOMY_COLORS,
    recalculate_cumulative_reads,
    build_parent_map,
    get_level_color,
)


# ============================================================================
# Shared by both charts: colour meaning, watched taxa, captions
# ============================================================================

#: Categorical hues for lineages, in fixed order (largest lineage first). The
#: reference data-viz palette minus its red, which is reserved for watched
#: organisms. Validated with the dataviz validator (light surface): every
#: adjacent pair clears CVD dE 9.1 and normal-vision dE 19.6. Three hues sit
#: below 3:1 contrast on white, which is why both charts label nodes directly.
LINEAGE_PALETTE = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
]
#: Lineages beyond the palette fold into one neutral "Other" grey; a ninth
#: generated hue would be indistinguishable from the eight.
LINEAGE_OTHER_COLOR = "#9CA3AF"
#: Ranks above the lineage level (Domain, Kingdom) hold several lineages, so
#: they carry no lineage hue.
LINEAGE_ROOT_COLOR = "#6B7280"
#: Watched organisms: a status colour (critical), never colour alone -- it
#: comes with a warning glyph on the label and a hover line. The Sunburst
#: uses it as a sector outline; the Sankey fills the node with it, because
#: plotly.js draws no per-node outline in a Sankey (given an array it falls
#: back to a black stroke on every node). The lineage palette has no red.
WATCHED_COLOR = "#B42318"
WATCHED_LABEL_PREFIX = "\u26a0 "
#: One title for both views; the caption under it says what is drawn.
CHART_TITLE = "How the reads are classified"

_RANKS_ABOVE_LINEAGE = {"R", "R1", "D", "K"}


def _lineage_level(tax_levels, present_ranks):
    """The rank whose taxa define the lineages (and so the colours).

    The first displayed rank below Kingdom that has taxa: colouring by Domain
    would paint 98% of a typical run one colour.
    """
    for level in tax_levels:
        if level not in _RANKS_ABOVE_LINEAGE and level in present_ranks:
            return level
    return tax_levels[0] if tax_levels else None


def _lineage_colors(keys, rank_of, reads_of, parent_of, tax_levels, tint_by_depth=False):
    """Colour every node by the lineage (anchor-rank ancestor) it belongs to.

    Anchors are ranked by reads; the largest takes ``LINEAGE_PALETTE[0]`` and
    anchors past the palette fold into ``LINEAGE_OTHER_COLOR``. Colour follows
    the lineage, so a taxon keeps its hue across columns or rings and a
    filter that removes one lineage does not repaint the rest of a rank.
    Nodes above the lineage rank get ``LINEAGE_ROOT_COLOR``. With
    ``tint_by_depth`` each rank below the anchor is lightened a step, which
    separates adjacent rings of one lineage in the Sunburst.
    """
    anchor = _lineage_level(tax_levels, {rank_of[k] for k in keys})
    if anchor is None:
        return {k: LINEAGE_OTHER_COLOR for k in keys}
    order = {lvl: i for i, lvl in enumerate(tax_levels)}
    anchors = sorted((k for k in keys if rank_of[k] == anchor),
                     key=lambda k: -reads_of.get(k, 0))
    anchor_color = {
        k: LINEAGE_PALETTE[i] if i < len(LINEAGE_PALETTE) else LINEAGE_OTHER_COLOR
        for i, k in enumerate(anchors)
    }
    colors = {}
    for k in keys:
        rank = rank_of[k]
        if order.get(rank, 0) < order.get(anchor, 0):
            colors[k] = LINEAGE_ROOT_COLOR
            continue
        node, depth = k, 0
        while node is not None and rank_of.get(node) != anchor:
            node = parent_of.get(node)
            depth += 1
        base = anchor_color.get(node, LINEAGE_OTHER_COLOR)
        colors[k] = _tint(base, min(0.45, 0.15 * depth)) if tint_by_depth and depth else base
    return colors


def _text_on(fill):
    """'#FFFFFF' or '#1F2937', whichever has the higher WCAG contrast on ``fill``.

    A fixed luminance cut-off put white on the aqua lineage hue at 2.8:1
    where dark ink gives 5:1. Non-hex fills (rgb() strings from the rank
    palettes) get dark ink.
    """
    if not isinstance(fill, str) or not fill.startswith("#") or len(fill) != 7:
        return "#1F2937"
    def lum(hex_color):
        def lin(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    fill_lum = lum(fill)
    on_white = (1.05) / (fill_lum + 0.05)
    on_dark = (fill_lum + 0.05) / (lum("#1F2937") + 0.05)
    return "#FFFFFF" if on_white >= on_dark else "#1F2937"


def _tint(hex_color, amount):
    """Blend ``hex_color`` toward white by ``amount`` (0..1)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _lineage_legend(keys, rank_of, reads_of, colors, tax_levels):
    """'Colour = <rank> lineage: [sq] A [sq] B ... [sq] Other' for the caption line."""
    anchor = _lineage_level(tax_levels, {rank_of[k] for k in keys})
    anchors = sorted((k for k in keys if rank_of[k] == anchor),
                     key=lambda k: -reads_of.get(k, 0))
    items = [
        f"<span style='color:{colors[k]}'>&#9632;</span> {k.split('_', 1)[1]}"
        for k in anchors[:len(LINEAGE_PALETTE)]
    ]
    if len(anchors) > len(LINEAGE_PALETTE):
        items.append(f"<span style='color:{LINEAGE_OTHER_COLOR}'>&#9632;</span> Other")
    rank_name = RANK_NAMES.get(anchor, anchor or "")
    return f"Colour = {rank_name.lower()} lineage: " + "  ".join(items) if items else ""


def _nearest_displayed_ancestor(taxid, displayed, taxid_to_parent, taxid_to_key):
    """Closest ancestor of ``taxid`` whose composite key is displayed, or None.

    One rule for both charts. Linking only to a parent exactly one selected
    level up lost every lineage that lacks that rank (Bacteria have no
    Kingdom) and every taxon whose parent was capped out.
    """
    cur = taxid_to_parent.get(int(taxid), 0)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        key = taxid_to_key.get(cur)
        if key is not None and key in displayed:
            return key
        cur = taxid_to_parent.get(cur, 0)
    return None


def _classified_unclassified(kraken_df):
    """(classified, unclassified) reads from the root and unclassified rows."""
    if "cumul_reads" not in kraken_df.columns:
        return 0, 0
    names = kraken_df["name"].astype(str).str.strip()
    root = kraken_df.loc[names == "root", "cumul_reads"]
    uncl = kraken_df.loc[names == "unclassified", "cumul_reads"]
    return (int(root.iloc[0]) if len(root) else 0,
            int(uncl.iloc[0]) if len(uncl) else 0)


def _chart_caption(kraken_df, total_reads, shown, hidden):
    """Second title line: what the figure stands on and what it leaves out."""
    _classified, unclassified = _classified_unclassified(kraken_df)
    parts = [f"{total_reads:,} reads"]
    if total_reads:
        parts.append(f"{unclassified / total_reads * 100:.1f}% unclassified (not drawn)")
    parts.append(f"{shown} taxa shown" + (f", {hidden} hidden by filters" if hidden else ""))
    return " \u00b7 ".join(parts)


def _watch_note(protected_taxa, taxid):
    """Hover line for a watched taxon ('' otherwise)."""
    if not protected_taxa or taxid is None:
        return ""
    note = protected_taxa.get(int(taxid))
    return f"<br><b style='color:{WATCHED_COLOR}'>On the watchlist</b>: {note}" if note else ""


def _with_ancestors(protected_taxa, taxid_to_parent):
    """Watched taxids plus every ancestor: a watched organism is drawn with
    its lineage, or it would have no displayed parent to hang from."""
    if not protected_taxa:
        return set()
    keep = set()
    for taxid in protected_taxa:
        cur, seen = int(taxid), set()
        while cur and cur not in seen:
            seen.add(cur)
            keep.add(cur)
            cur = taxid_to_parent.get(cur, 0)
    return keep


def _keep_rows(df, min_reads, protected_taxa):
    """Rows at or above ``min_reads`` cumulative reads, plus watched taxa with reads.

    A watched organism is never hidden by the minimum-reads filter: a select
    agent at 100 reads vanished under the 24-barcode auto-scaled floor of 120.
    """
    keep = df["recalc_cumul"] >= (min_reads or 0)
    if protected_taxa:
        keep |= df["taxid"].astype(int).isin(set(protected_taxa)) & (df["recalc_cumul"] > 0)
    return df[keep]


def _cap_level(level_df, cap, protected_taxa):
    """Top ``cap`` rows of one rank by reads, plus any watched taxa below the cap."""
    level_df = level_df.sort_values("recalc_cumul", ascending=False)
    if not cap:
        return level_df
    top = level_df.head(cap)
    if protected_taxa:
        extra = level_df.iloc[cap:]
        extra = extra[extra["taxid"].astype(int).isin(set(protected_taxa))]
        if not extra.empty:
            top = pd.concat([top, extra])
    return top


# ============================================================================
# Sankey Visualization Functions
# ============================================================================

def create_placeholder_sankey(message="Waiting for data"):
    """
    Create a placeholder Sankey plot with styled empty state.

    Args:
        message: Message to display in the plot

    Returns:
        A Go.Figure object with a placeholder Sankey plot
    """
    placeholder_link = dict(source=[0], target=[1], value=[1])
    placeholder_node = dict(
        label=[message, ""],
        pad=25,
        thickness=10,
        color=["#E5E7EB", "rgba(0,0,0,0)"],
    )

    figure = go.Figure(go.Sankey(
        link=placeholder_link,
        node=placeholder_node,
        textfont=dict(size=13, color="#6B7280", family="Arial, sans-serif"),
    ))

    figure.update_layout(
        height=400,
        margin=dict(l=50, r=50, t=50, b=50),
        paper_bgcolor="white",
        font=dict(family="Arial, sans-serif"),
    )

    return figure



def _calculate_hierarchical_y_positions(nodes, node_ids, tax_levels, nodes_per_level, parent_map, node_values, node_ranks=None):
    """
    Calculate Y positions with space proportional to node values (read counts).

    Algorithm: Sort-by-parent, then proportional-spacing
    1. For each level, sort nodes by their parent's Y position
    2. Allocate Y-space proportional to each node's value (read count)
    3. Larger nodes get more vertical space to prevent visual overlap

    Args:
        nodes: List of node names in order
        node_ids: Dict mapping node name -> node index
        tax_levels: List of taxonomy levels (e.g., ['F', 'G', 'S'])
        nodes_per_level: Dict mapping level -> count of nodes at that level
        parent_map: Dict mapping child node name -> parent node name
        node_values: Dict mapping node name -> read count value
        node_ranks: Dict mapping node name -> taxonomy rank (e.g., 'F', 'G', 'S')

    Returns:
        List of Y positions corresponding to nodes list
    """
    node_y = [0.5] * len(nodes)  # Initialize all to center
    node_y_assigned = {}  # Track assigned Y for each node name

    # Build index lookup: node_name -> index in nodes list
    node_name_to_idx = {name: idx for idx, name in enumerate(nodes)}

    # Vertical bounds
    y_min = 0.001
    y_max = 0.999

    # Minimum fraction of space per node (prevents tiny nodes from having zero space)
    MIN_FRACTION = 0.02  # 2% minimum per node for fixed layout readability

    # Minimum gap between adjacent node centers (prevents label overlap)
    MIN_GAP = 0.03  # 3% of total height

    def calculate_proportional_positions(node_list, start_y, end_y):
        """
        Calculate Y positions for nodes proportional to their values.

        With fixed arrangement, positions must be non-overlapping since Plotly
        will not auto-adjust them. Enforces a minimum gap between nodes.

        Args:
            node_list: List of (node_idx, node_name) tuples
            start_y: Starting Y position
            end_y: Ending Y position

        Returns:
            List of (node_idx, node_name, y_position) tuples
        """
        if not node_list:
            return []

        if len(node_list) == 1:
            idx, name = node_list[0]
            return [(idx, name, (start_y + end_y) / 2)]

        # Get values for each node
        values = []
        for idx, name in node_list:
            val = node_values.get(name, 1)
            values.append(max(val, 1))  # Ensure positive

        total_value = sum(values)

        # Calculate raw fractions
        raw_fractions = [v / total_value for v in values]

        # Apply minimum fraction and normalize
        adjusted_fractions = [max(f, MIN_FRACTION) for f in raw_fractions]
        total_adjusted = sum(adjusted_fractions)
        normalized_fractions = [f / total_adjusted for f in adjusted_fractions]

        # Calculate positions by stacking proportionally
        available_range = end_y - start_y
        positions = []
        current_y = start_y

        for i, (idx, name) in enumerate(node_list):
            allocated_space = normalized_fractions[i] * available_range
            # Position node at center of its allocated space
            y_pos = current_y + allocated_space / 2
            positions.append((idx, name, y_pos))
            current_y += allocated_space

        # Enforce minimum gap between adjacent nodes for fixed layout
        if len(positions) > 1:
            for i in range(1, len(positions)):
                prev_y = positions[i - 1][2]
                curr_y = positions[i][2]
                if curr_y - prev_y < MIN_GAP:
                    # Push this node down to maintain minimum gap
                    new_y = prev_y + MIN_GAP
                    positions[i] = (positions[i][0], positions[i][1], new_y)

            # If pushing nodes down caused overflow past end_y, compress all
            last_y = positions[-1][2]
            if last_y > end_y:
                # Redistribute evenly within bounds
                n = len(positions)
                step = (end_y - start_y) / (n + 1)
                for i in range(n):
                    y_pos = start_y + step * (i + 1)
                    positions[i] = (positions[i][0], positions[i][1], y_pos)

        return positions

    # Group nodes by their rank (handles non-contiguous "Other" nodes)
    nodes_by_level = {level: [] for level in tax_levels}
    if node_ranks:
        for name in nodes:
            rank = node_ranks.get(name, "")
            if rank in nodes_by_level:
                idx = node_name_to_idx[name]
                nodes_by_level[rank].append((idx, name))

    # Pass 1: Position first level nodes with proportional spacing
    first_level = tax_levels[0]
    first_level_nodes = nodes_by_level.get(first_level, [])

    positions = calculate_proportional_positions(first_level_nodes, y_min, y_max)
    for idx, name, y_pos in positions:
        node_y[idx] = y_pos
        node_y_assigned[name] = y_pos

    # Pass 2: For each subsequent level, sort by parent Y then proportional spacing
    for level_idx in range(1, len(tax_levels)):
        level = tax_levels[level_idx]
        level_nodes = nodes_by_level.get(level, [])

        # Collect all nodes at this level with their parent's Y for sorting
        nodes_with_parent_y = []  # [(parent_y, node_idx, node_name), ...]

        for node_idx, node_name in level_nodes:
            parent_name = parent_map.get(node_name)

            if parent_name and parent_name in node_y_assigned:
                parent_y = node_y_assigned[parent_name]
            else:
                # Orphans (including "Other" nodes): use middle position as fallback
                parent_y = 0.5

            nodes_with_parent_y.append((parent_y, node_idx, node_name))

        # Sort by parent Y position (children of top parents first)
        nodes_with_parent_y.sort(key=lambda x: x[0])

        # Extract sorted node list for proportional positioning
        sorted_nodes = [(idx, name) for _, idx, name in nodes_with_parent_y]

        # Calculate proportional positions
        positions = calculate_proportional_positions(sorted_nodes, y_min, y_max)
        for idx, name, y_pos in positions:
            node_y[idx] = y_pos
            node_y_assigned[name] = y_pos

    return node_y


# Shared layout for informational empty-state Sankey figures.
_SANKEY_INFO_LAYOUT = dict(
    height=400,
    paper_bgcolor="white",
    plot_bgcolor="white",
    margin=dict(l=50, r=50, t=50, b=50),
    font=dict(family="Arial, sans-serif"),
)


def _sankey_info_figure(text):
    """Build a centred empty-/info-state Sankey placeholder figure."""
    fig = go.Figure()
    fig.add_annotation(
        text=text,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color="#6B7280"),
    )
    fig.update_layout(**_SANKEY_INFO_LAYOUT)
    return fig


def _total_read_count(kraken_df) -> int:
    """All reads in the report, classified plus unclassified.

    The base of Kraken2's own ``%`` column. Read from the ``root`` and
    ``unclassified`` cumulative counts; when neither row exists, the sum of
    direct reads (each read is assigned directly to exactly one node).
    Summing cumulative reads over every row is NOT a total: it counts each
    read once per rank.
    """
    if "cumul_reads" in kraken_df.columns:
        names = kraken_df["name"].astype(str).str.strip()
        total = int(kraken_df.loc[names.isin(["root", "unclassified"]), "cumul_reads"].sum())
        if total > 0:
            return total
    return int(kraken_df["reads"].sum()) if "reads" in kraken_df.columns else 0


def _domain_taxid_set(kraken_df, taxid_to_parent, domains) -> set:
    """Every taxid at or below the named domains (taxid subtree membership,
    independent of row order). Shared by the Sankey and the Sunburst so the
    Domain selection means the same in both views."""
    children_map: dict = {}
    for taxid, parent_taxid in taxid_to_parent.items():
        children_map.setdefault(parent_taxid, []).append(taxid)

    result = set()
    names = kraken_df["name"].str.strip()
    for domain in domains or []:
        domain_rows = kraken_df[names == domain]
        if domain_rows.empty:
            continue
        stack = [int(domain_rows.iloc[0]["taxid"])]
        while stack:
            tid = stack.pop()
            result.add(tid)
            stack.extend(children_map.get(tid, []))
    return result


def _build_sankey_frames(kraken_df, domains, tax_levels, min_reads=0, protected_taxa=None):
    """Filter the kraken frame to the requested domains and tax levels.

    Returns ``(tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key)``
    or ``None`` when no rows fall under the requested domains. ``domain_df``
    gains ``recalc_cumul`` (cumulative reads) and ``recalc_pct`` columns.
    """
    recalc_cumul = recalculate_cumulative_reads(kraken_df)
    total_reads = _total_read_count(kraken_df) or 1

    # taxid-based parent lookup. parent_taxid is derived from indentation
    # during Kraken2 parsing, so it survives aggregation reordering.
    taxid_to_parent = dict(zip(
        kraken_df["taxid"].astype(int), kraken_df["parent_taxid"].astype(int)
    ))
    # Materialise the string columns with .tolist() before zipping: iterating
    # the arrow-backed rank/name Series directly goes through arrow __iter__
    # per element, a hot-path cost on every rebuild (cProfile, GTDB scale).
    _tids = kraken_df["taxid"].astype(int).tolist()
    _ranks = kraken_df["rank"].tolist()
    _names = kraken_df["name"].tolist()
    taxid_to_key = {
        tid: f"{rank}_{name.strip()}"
        for tid, rank, name in zip(_tids, _ranks, _names)
    }

    domain_taxids_set = _domain_taxid_set(kraken_df, taxid_to_parent, domains)
    domain_df = kraken_df[kraken_df["taxid"].isin(domain_taxids_set)].copy()
    if domain_df.empty:
        return None

    domain_df["recalc_cumul"] = (
        domain_df["rank"] + "_" + domain_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)
    domain_df["recalc_pct"] = domain_df["recalc_cumul"] / total_reads * 100

    # "Minimum DNA Sequences": hide any taxon whose cumulative reads fall
    # below the value. A parent holds at least its children's reads, so the
    # remaining tree stays connected. The argument used to be accepted and
    # ignored here.
    tax_df = _keep_rows(
        domain_df[domain_df["rank"].isin(tax_levels)], min_reads, protected_taxa
    ).copy()
    return tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key


def _build_sankey_nodes(tax_df, tax_levels, max_taxa_per_level, protected_taxa=None):
    """Create node bookkeeping for the top taxa at each level.

    Levels are processed in order so nodes form clean per-rank groups. A
    watched taxon below the per-level cap is kept (see ``_cap_level``).
    Returns ``(nodes, node_ids, node_values, node_pcts, node_ranks,
    node_taxids)``.
    """
    node_id = 0
    node_ids = {}
    nodes = []
    node_values = {}
    node_pcts = {}
    node_ranks = {}
    node_taxids = {}
    for level in tax_levels:
        level_df = _cap_level(tax_df[tax_df["rank"] == level], max_taxa_per_level,
                              protected_taxa)
        level_names = level_df["name"].str.strip().tolist()
        level_cumuls = level_df["recalc_cumul"].tolist()
        level_pcts = level_df["recalc_pct"].tolist()
        level_taxids = level_df["taxid"].astype(int).tolist()
        for name, cumul_val, pct_val, taxid in zip(level_names, level_cumuls,
                                                   level_pcts, level_taxids):
            node_key = f"{level}_{name}"
            if node_key in node_ids:
                continue  # same rank and name twice (GTDB): keep the larger
            node_ids[node_key] = node_id
            nodes.append(node_key)
            node_values[node_key] = cumul_val
            node_pcts[node_key] = pct_val
            node_ranks[node_key] = level
            node_taxids[node_key] = taxid
            node_id += 1
    return nodes, node_ids, node_values, node_pcts, node_ranks, node_taxids


def _build_sankey_links(nodes, node_ids, node_values, node_ranks, node_taxids,
                        tax_levels, taxid_to_parent, taxid_to_key):
    """Link each node to its nearest DISPLAYED ancestor, in any earlier column.

    Walks the taxid parent chain (order-independent) and never links to an
    unrelated node. It used to accept only an ancestor exactly one selected
    level up, so a lineage without that rank (Bacteria and Archaea have no
    Kingdom) and a taxon whose parent was capped out lost their links and
    were pruned -- with the Overview preset Bacteria (98% of reads) vanished.
    The Sunburst already resolved parents this way. Returns ``(links, values,
    parent_outgoing_sum, parent_link_indices, parent_map)``.
    """
    links = []
    values = []
    parent_outgoing_sum = {}   # parent_key -> sum of outgoing link values
    parent_link_indices = {}   # parent_key -> link indices (for scaling)
    parent_map = {}            # child_key -> parent_key (for y positioning)
    order = {lvl: i for i, lvl in enumerate(tax_levels)}
    displayed = set(node_ids)

    for child_key in nodes:
        if order.get(node_ranks[child_key], 0) == 0:
            continue
        ancestor_key = _nearest_displayed_ancestor(
            node_taxids[child_key], displayed, taxid_to_parent, taxid_to_key)
        if ancestor_key is None or ancestor_key == child_key:
            logging.debug("Sankey: no displayed ancestor for %s", child_key)
            continue
        child_value = node_values.get(child_key, 0)
        link_idx = len(links)
        links.append((node_ids[ancestor_key], node_ids[child_key]))
        values.append(child_value)
        parent_outgoing_sum[ancestor_key] = parent_outgoing_sum.get(ancestor_key, 0) + child_value
        parent_link_indices.setdefault(ancestor_key, []).append(link_idx)
        parent_map[child_key] = ancestor_key

    return links, values, parent_outgoing_sum, parent_link_indices, parent_map


def _scale_oversized_parent_links(values, node_values, parent_outgoing_sum, parent_link_indices):
    """Scale down outgoing links where children's reads exceed the parent's.

    Plotly sizes Sankey nodes by the sum of their link values, so unscaled
    children would inflate the parent's visual height. Mutates ``values`` in
    place and updates ``parent_outgoing_sum``.
    """
    for parent_name, outgoing_sum in list(parent_outgoing_sum.items()):
        parent_value = node_values.get(parent_name, 0)
        if outgoing_sum > parent_value > 0:
            scale_factor = parent_value / outgoing_sum
            for link_idx in parent_link_indices.get(parent_name, []):
                values[link_idx] = values[link_idx] * scale_factor
            parent_outgoing_sum[parent_name] = parent_value
            logging.debug(f"Sankey: Scaled {parent_name} links by {scale_factor:.3f} "
                          f"(children sum {outgoing_sum} > parent value {parent_value})")


def _prune_orphan_sankey_nodes(nodes, node_ids, links, node_values, node_pcts, node_ranks):
    """Drop nodes with no incident links and remap link/node indices.

    Returns the possibly-shrunk ``(nodes, node_ids, links, node_values,
    node_pcts, node_ranks)``; the inputs are returned unchanged when nothing
    is orphaned.
    """
    connected_indices = set()
    for src, tgt in links:
        connected_indices.add(src)
        connected_indices.add(tgt)
    if not connected_indices:
        return nodes, node_ids, links, node_values, node_pcts, node_ranks

    old_to_new = {}
    new_nodes = []
    new_node_values = {}
    new_node_pcts = {}
    new_node_ranks = {}
    for old_idx, node_key in enumerate(nodes):
        if old_idx in connected_indices:
            old_to_new[old_idx] = len(new_nodes)
            new_nodes.append(node_key)
            new_node_values[node_key] = node_values.get(node_key, 0)
            new_node_pcts[node_key] = node_pcts.get(node_key, 0)
            new_node_ranks[node_key] = node_ranks.get(node_key, "")

    if len(new_nodes) == len(nodes):
        return nodes, node_ids, links, node_values, node_pcts, node_ranks

    logging.debug(f"Sankey: Removed {len(nodes) - len(new_nodes)} orphan nodes without links")
    links = [(old_to_new[s], old_to_new[t]) for s, t in links]
    node_ids = {key: old_to_new[old_idx] for key, old_idx in node_ids.items()
                if old_idx in old_to_new}
    return new_nodes, node_ids, links, new_node_values, new_node_pcts, new_node_ranks


def _build_sankey_node_colors(nodes, node_ranks, colors):
    """Colour each node by its taxonomy rank."""
    return [colors.get(node_ranks.get(name, ""), "#3B82F6") for name in nodes]


def _build_sankey_link_colors(links, values, node_colors):
    """Colour links by their target node with opacity scaled to read share."""
    total_value = sum(values) if values else 1
    link_colors = []
    for i, (source_idx, target_idx) in enumerate(links):
        # Use target node colour for visual continuity into the next level.
        color_idx = target_idx if target_idx < len(node_colors) else source_idx
        base_color = node_colors[color_idx] if color_idx < len(node_colors) else "#3B82F6"

        link_pct = (values[i] / total_value * 100) if total_value > 0 else 0
        if link_pct > 5:
            opacity = 0.55
        elif link_pct > 1:
            opacity = 0.4
        else:
            opacity = 0.25

        if base_color.startswith("rgba"):
            link_colors.append(base_color)
        elif base_color.startswith("#"):
            hex_color = base_color.lstrip("#")
            r, g, b = tuple(int(hex_color[j:j+2], 16) for j in (0, 2, 4))
            link_colors.append(f"rgba({r},{g},{b},{opacity})")
        else:
            link_colors.append(f"rgba(150,150,150,{opacity})")
    return link_colors


def _build_sankey_node_x(nodes, node_ranks, tax_levels):
    """Distribute nodes horizontally so any subset of levels spans the width."""
    x_min = 0.001
    # The last column's labels are drawn to the LEFT of its nodes (plotly
    # places labels of right-half nodes on their left), so the canvas can
    # run nearly to the edge; 0.85 left a fifth of the width empty.
    x_max = 0.97
    n_levels = len(tax_levels)
    level_to_x = {}
    if n_levels == 1:
        level_to_x[tax_levels[0]] = (x_min + x_max) / 2
    else:
        for i, level in enumerate(tax_levels):
            level_to_x[level] = x_min + (x_max - x_min) * i / (n_levels - 1)
    return [level_to_x.get(node_ranks.get(name, ""), 0.5) for name in nodes]


def _abbreviate_genus(name, rank, parent_key):
    """'Escherichia coli' -> 'E. coli' when its genus is drawn beside it.

    The last column's labels are placed left of their nodes, where the
    genus label of the column before already names the genus; the repeated
    word made the two labels collide. Only species and subspecies whose
    first word is the drawn parent's first word are shortened; the hover
    keeps the full name.
    """
    if rank not in ("S", "S1") or not parent_key or " " not in name:
        return name
    parent_name = parent_key.split("_", 1)[1] if "_" in parent_key else parent_key
    first, rest = name.split(" ", 1)
    if parent_name.split(" ", 1)[0] != first or len(first) < 3:
        return name
    return f"{first[0]}. {rest}"


def _build_sankey_customdata(nodes, node_values, node_pcts, node_ranks,
                             parent_map=None, node_taxids=None, protected_taxa=None):
    """Build node display labels and hover customdata.

    Returns ``(node_labels, node_customdata)`` where each customdata row is
    ``[reads, percentage, rank_name, full_name, pct_of_parent, watch_note]``.
    ``percentage`` is the share of all reads; ``pct_of_parent`` the share of
    the node's drawn parent (of all reads for a first-column node). Long
    labels are truncated; the full name stays in the hover tooltip. A watched
    taxon's label carries a warning glyph.
    """
    parent_map = parent_map or {}
    node_taxids = node_taxids or {}
    MAX_LABEL_LEN = 30
    node_labels = []
    node_customdata = []
    for node_key in nodes:
        display_name = node_key.split("_", 1)[1] if "_" in node_key else node_key
        label = _abbreviate_genus(display_name, node_ranks.get(node_key, ""),
                                  parent_map.get(node_key))
        label = (label[:MAX_LABEL_LEN - 1] + "..."
                 if len(label) > MAX_LABEL_LEN else label)
        note = _watch_note(protected_taxa, node_taxids.get(node_key))
        node_labels.append(WATCHED_LABEL_PREFIX + label if note else label)
        rank = node_ranks.get(node_key, "")
        parent = parent_map.get(node_key)
        value = node_values.get(node_key, 0)
        if parent and node_values.get(parent):
            pct_parent = value / node_values[parent] * 100
        else:
            pct_parent = node_pcts.get(node_key, 0)
        node_customdata.append([
            value,
            node_pcts.get(node_key, 0),
            RANK_NAMES.get(rank, rank),
            display_name,
            pct_parent,
            note,
        ])
    return node_labels, node_customdata


def _resolve_sankey_height(chart_height, nodes_per_level):
    """Pick the figure height: explicit pixels, else adaptive to node density."""
    max_nodes_at_level = max(nodes_per_level.values()) if nodes_per_level else 5
    MIN_HEIGHT = 600
    MAX_HEIGHT = 2500
    PIXELS_PER_NODE = 60  # Generous spacing per node.
    adaptive_height = max(MIN_HEIGHT, min(MAX_HEIGHT, max_nodes_at_level * PIXELS_PER_NODE + 100))
    if chart_height == "auto" or chart_height is None:
        logging.debug(f"Sankey: Using adaptive height={adaptive_height}px (max_nodes_at_level={max_nodes_at_level})")
        return adaptive_height
    try:
        return int(chart_height)
    except (ValueError, TypeError):
        logging.debug(f"Sankey: Invalid height '{chart_height}', falling back to adaptive={adaptive_height}px")
        return adaptive_height


def _build_sankey_legend(tax_levels, colors):
    """Build the rank colour legend shown beneath the Sankey."""
    items = []
    for level in tax_levels:
        color = colors.get(level, "#94A3B8")
        name = RANK_NAMES.get(level, level)
        items.append(f"<span style='color:{color}'>&#9632;</span> {name}")
    return " (broad) " + "  ".join(items) + " (specific)"


def create_sankey_data(kraken_df, domains, tax_levels, min_reads, max_taxa_per_level,
                       chart_height="auto", color_palette=None, color_mode="lineage",
                       protected_taxa=None):
    """
    Create Sankey plot data from Kraken report.

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include
        tax_levels: List of taxonomy levels to include
        min_reads: Minimum number of reads for filtering
        max_taxa_per_level: Maximum number of taxa to show at each level
        chart_height: Chart height - "auto" for adaptive, or pixel value as string
        color_palette: Dictionary mapping taxonomy ranks to colors (used when
            ``color_mode`` is "rank")
        color_mode: "lineage" (default) colours each node by the lineage it
            belongs to; "rank" colours by rank with ``color_palette``.
        protected_taxa: {kraken taxid: note} for watched organisms. They are
            drawn whatever the cap and minimum-reads filter, outlined in
            ``WATCHED_COLOR`` and named in the hover.

    Returns:
        A Go.Figure object with the Sankey plot
    """
    colors = color_palette or TAXONOMY_COLORS
    max_taxa_per_level = max_taxa_per_level or None  # 0 = no cap

    # Ensure clean integer index to prevent duplicate-index issues with .loc[]
    kraken_df = kraken_df.reset_index(drop=True)

    if kraken_df.empty:
        return _sankey_info_figure(
            "No organism classification data available for this sample."
        )

    # Filter to standard taxonomy ranks present in the data. Sub-ranks (S1, S2,
    # F3, ...) are excluded because their cumulative reads are already counted
    # in the parent rank's total, and including them would double-count.
    available_ranks = kraken_df["rank"].unique().tolist()
    tax_levels = [level for level in tax_levels if level in available_ranks]
    logging.debug(f"Sankey: Available ranks in data: {available_ranks}")
    logging.debug(f"Sankey: Using tax_levels: {tax_levels}")

    if not tax_levels:
        logging.debug("Sankey: No matching tax levels found in data")
        return _sankey_info_figure(
            "No matching classification levels in data.<br>"
            "Try adjusting filter settings or selecting a different preset view."
        )

    # Sankey requires at least 2 levels to show parent-child relationships.
    if len(tax_levels) < 2:
        logging.debug(f"Sankey: Need at least 2 taxonomy levels, only have {len(tax_levels)}: {tax_levels}")
        available_names = [RANK_NAMES.get(r, r) for r in available_ranks]
        return _sankey_info_figure(
            "The flow diagram needs at least 2 classification levels to show relationships.<br>"
            f"Currently available: {', '.join(available_names)}<br>"
            "Try the Ring View (Sunburst) or select more levels in Advanced Settings."
        )

    keep_taxa = None
    if protected_taxa and {"taxid", "parent_taxid"} <= set(kraken_df.columns):
        keep_taxa = _with_ancestors(protected_taxa, dict(zip(
            kraken_df["taxid"].astype(int), kraken_df["parent_taxid"].astype(int))))
    frames = _build_sankey_frames(kraken_df, domains, tax_levels, min_reads, keep_taxa)
    if frames is None:
        return None
    tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key = frames

    nodes, node_ids, node_values, node_pcts, node_ranks, node_taxids = _build_sankey_nodes(
        tax_df, tax_levels, max_taxa_per_level, keep_taxa
    )
    logging.debug(f"Sankey: Created {len(nodes)} nodes across {len(tax_levels)} levels")

    links, values, parent_outgoing_sum, parent_link_indices, parent_map = _build_sankey_links(
        nodes, node_ids, node_values, node_ranks, node_taxids, tax_levels,
        taxid_to_parent, taxid_to_key
    )
    _scale_oversized_parent_links(values, node_values, parent_outgoing_sum, parent_link_indices)

    # Drop orphan nodes (no incident links) so they do not float disconnected.
    nodes, node_ids, links, node_values, node_pcts, node_ranks = _prune_orphan_sankey_nodes(
        nodes, node_ids, links, node_values, node_pcts, node_ranks
    )

    logging.debug(f"Sankey: Created {len(links)} links with values sum={sum(values) if values else 0}")
    if not links:
        logging.debug("Sankey: No links created, returning None")
        return None

    # Count nodes per level - drives adaptive height and Y positioning.
    nodes_per_level = {
        level: sum(1 for name in nodes if node_ranks.get(name) == level)
        for level in tax_levels
    }
    if color_mode == "lineage":
        lineage = _lineage_colors(nodes, node_ranks, node_values, parent_map, tax_levels)
        node_colors = [lineage[name] for name in nodes]
    else:
        node_colors = _build_sankey_node_colors(nodes, node_ranks, colors)
    watched = [bool(_watch_note(protected_taxa, node_taxids.get(n))) for n in nodes]
    node_colors = [WATCHED_COLOR if w else c for w, c in zip(watched, node_colors)]
    link_colors = _build_sankey_link_colors(links, values, node_colors)

    source_indices = [link[0] for link in links]
    target_indices = [link[1] for link in links]

    node_x = _build_sankey_node_x(nodes, node_ranks, tax_levels)
    node_y = _calculate_hierarchical_y_positions(
        nodes, node_ids, tax_levels, nodes_per_level, parent_map, node_values, node_ranks
    )

    node_labels, node_customdata = _build_sankey_customdata(
        nodes, node_values, node_pcts, node_ranks,
        parent_map=parent_map, node_taxids=node_taxids, protected_taxa=protected_taxa,
    )

    # Floor link render values so sub-0.5% nodes stay visible (Plotly would
    # otherwise render them nearly invisibly thin).
    max_value = max(values) if values else 1
    min_visible = max_value * 0.005
    display_values = [max(v, min_visible) if v > 0 else v for v in values]

    # Create the Sankey figure with enhanced hover information
    figure = go.Figure(
        go.Sankey(
            arrangement="fixed",
            textfont=dict(size=11, color="#1F2937", family="Arial, sans-serif"),
            domain=dict(
                x=[0.0, 1.0],
                y=[0.02, 0.98]
            ),
            node=dict(
                pad=30,
                thickness=22,
                label=node_labels,
                color=node_colors,
                customdata=node_customdata,
                x=node_x,
                y=node_y,
                line=dict(color="#FFFFFF", width=0.5),
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>"
                    "Level: <i>%{customdata[2]}</i><br>"
                    "DNA sequences: <b>%{customdata[0]:,.0f}</b><br>"
                    "Of all reads: <b>%{customdata[1]:.2f}%</b><br>"
                    "Of parent: <b>%{customdata[4]:.1f}%</b>"
                    "%{customdata[5]}"
                    "<extra></extra>"
                ),
            ),
            link=dict(
                source=source_indices,
                target=target_indices,
                value=display_values,
                color=link_colors,
                hovertemplate=(
                    "<b>%{source.customdata[3]}</b> (%{source.customdata[2]})"
                    " contains "
                    "<b>%{target.customdata[3]}</b> (%{target.customdata[2]})<br>"
                    "DNA sequences: %{value:,.0f}"
                    "<extra></extra>"
                ),
            ),
        )
    )

    final_height = _resolve_sankey_height(chart_height, nodes_per_level)
    if color_mode == "lineage":
        sankey_legend_text = _lineage_legend(nodes, node_ranks, node_values, lineage, tax_levels)
    else:
        sankey_legend_text = _build_sankey_legend(tax_levels, colors)
    if any(watched):
        sankey_legend_text += (f"   <span style='color:{WATCHED_COLOR}'>&#9632; "
                               f"{WATCHED_LABEL_PREFIX}on the watchlist</span>")
    candidates = domain_df[domain_df["rank"].isin(tax_levels) & (domain_df["recalc_cumul"] > 0)]
    hidden = max(0, candidates["taxid"].nunique() - len(nodes))
    caption = _chart_caption(kraken_df, total_reads, len(nodes), hidden)

    # Layout with dynamic height and balanced margins for labels
    figure.update_layout(
        height=final_height,
        title=dict(
            text=(f"<b>{CHART_TITLE}</b><br>"
                  f"<span style='font-size:12px;color:#4B5563'>{caption}</span>"),
            font=dict(size=18, color="#1F2937", family="Arial, sans-serif"),
            x=0.5,
            xanchor="center",
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=80, b=50),
        font=dict(family="Arial, sans-serif"),
        annotations=[
            dict(
                text=sankey_legend_text,
                x=0.5,
                y=-0.03,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=11, color="#6B7280"),
                xanchor="center",
            )
        ],
    )

    return apply_theme_to_figure(figure)


# ============================================================================
# Sunburst Visualization Functions
# ============================================================================


def create_empty_sunburst(message="Waiting for data"):
    """
    Create an empty Sunburst chart with modern styling.

    Args:
        message: Message to display in the chart

    Returns:
        A go.Figure with a styled placeholder message
    """
    fig = go.Figure(go.Sunburst(
        ids=["center"],
        labels=[message],
        parents=[""],
        values=[1],
        marker=dict(
            colors=["#E5E7EB"],
            line=dict(color="#9CA3AF", width=1)
        ),
        textfont=dict(size=14, color="#6B7280"),
        hoverinfo="skip"
    ))

    fig.update_layout(
        height=700,
        margin=dict(l=20, r=20, t=80, b=20),
        title=dict(
            text="Taxonomic Classification",
            font=dict(size=18, color="#374151"),
            x=0.5,
            xanchor="center"
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    return fig


def _resolve_sunburst_parent(node_taxid, taxon_name_full, row_idx, level_idx,
                             tax_levels, added_ids, filtered_df,
                             use_taxid_parents, taxid_to_parent, taxid_to_key):
    """Find the nearest already-added ancestor id for a sunburst node.

    Prefers the taxid parent chain (order-independent, robust to out-of-order
    PlusPFP rows); falls back to Kraken indentation when taxid columns are
    absent. Returns ``"root"`` when no in-chart ancestor is found.
    """
    if level_idx == 0:
        return "root"

    if use_taxid_parents and node_taxid is not None:
        cur = taxid_to_parent.get(int(node_taxid), 0)
        seen = set()
        while cur != 0 and cur not in seen:
            seen.add(cur)
            ancestor_key = taxid_to_key.get(cur)
            if ancestor_key is not None and ancestor_key in added_ids:
                return ancestor_key
            cur = taxid_to_parent.get(cur, 0)
        return "root"

    # Fallback: indentation-based hierarchy from the Kraken report format.
    row_indent = len(taxon_name_full) - len(taxon_name_full.lstrip())
    for check_idx in range(row_idx - 1, -1, -1):
        if check_idx not in filtered_df.index:
            continue
        check_row = filtered_df.loc[check_idx]
        check_indent = len(check_row["name"]) - len(check_row["name"].lstrip())
        check_rank = check_row["rank"]
        # First less-indented row in an ancestor rank decides the parent.
        if check_indent < row_indent and check_rank in tax_levels[:level_idx]:
            candidate_parent_id = f"{check_rank}_{check_row['name'].strip()}"
            if candidate_parent_id in added_ids:
                return candidate_parent_id
            break
    return "root"


def _count_sunburst_levels(filtered_df, tax_levels, cap):
    """Count items per level (for colour variation), bounded by ``cap``.

    The count is bounded by the cap so the within-level brightness spread
    matches the number of nodes actually rendered. Returns
    ``(level_counts, level_positions)`` with positions zero-initialised.
    """
    level_counts = {}
    level_positions = {}
    for level in tax_levels:
        n_level = len(filtered_df[filtered_df["rank"] == level])
        level_counts[level] = min(n_level, cap) if cap else n_level
        level_positions[level] = 0
    return level_counts, level_positions


def _build_sunburst_nodes(filtered_df, tax_levels, total_reads, palette,
                          use_taxid_parents, taxid_to_parent, taxid_to_key,
                          max_taxa_per_level=0, keep_taxa=None, protected_taxa=None):
    """Build the sunburst node arrays under a synthetic ``root``.

    Returns ``(ids, labels, parents, values, colors, custom_data)``. Each
    node's parent is the nearest ancestor already added, keeping the hierarchy
    connected; colour varies by within-level position.

    ``max_taxa_per_level`` (when > 0) keeps only the top-N taxa by recalculated
    cumulative reads at each rank, mirroring the Sankey builder. This bounds the
    node count handed to plotly -- whose per-element trace validation dominates
    sunburst build time -- and keeps a dense chart readable. A node whose direct
    parent was capped out reparents to its nearest still-present ancestor (or
    root) via ``_resolve_sunburst_parent``, so capping never orphans a node.
    """
    ids, labels, parents, values, colors, custom_data = [], [], [], [], [], []
    cap = max_taxa_per_level if max_taxa_per_level and max_taxa_per_level > 0 else None

    level_counts, level_positions = _count_sunburst_levels(filtered_df, tax_levels, cap)

    first_level = tax_levels[0] if tax_levels else "D"
    first_level_reads = filtered_df[filtered_df["rank"] == first_level]["recalc_cumul"].sum()
    logging.debug(f"Sunburst: First level '{first_level}' has {level_counts.get(first_level, 0)} items with total reads {first_level_reads}")

    # Root's value is filled in by _make_values_consistent once its children
    # are known (branchvalues="total" needs parent >= sum(children)).
    ids.append("root")
    labels.append("All Taxa")
    parents.append("")
    values.append(0)
    colors.append("#E5E7EB")
    custom_data.append([
        "Root", first_level_reads,
        (first_level_reads / total_reads * 100) if total_reads > 0 else 0.0,
        "",
    ])

    added_ids = {"root"}
    for level_idx, level in enumerate(tax_levels):
        level_df = _cap_level(filtered_df[filtered_df["rank"] == level], cap, keep_taxa)
        logging.debug(f"Sunburst: Processing level {level} with {len(level_df)} items")

        # Pre-extract columns to avoid iterrows overhead.
        taxon_names_full = level_df["name"].tolist()
        taxon_names_stripped = level_df["name"].str.strip().tolist()
        taxon_reads = level_df["recalc_cumul"].tolist()
        taxon_indices = level_df.index.tolist()
        taxon_taxids = (
            level_df["taxid"].tolist() if use_taxid_parents
            else [None] * len(level_df)
        )

        for taxon_name_full, taxon, reads, row_idx, node_taxid in zip(
            taxon_names_full, taxon_names_stripped, taxon_reads, taxon_indices,
            taxon_taxids,
        ):
            taxon_id = f"{level}_{taxon}"  # Unique across levels.
            parent_id = _resolve_sunburst_parent(
                node_taxid, taxon_name_full, row_idx, level_idx, tax_levels,
                added_ids, filtered_df, use_taxid_parents, taxid_to_parent,
                taxid_to_key,
            )
            pct_of_total = (reads / total_reads * 100) if total_reads > 0 else 0
            color = get_level_color(level, level_positions[level], level_counts[level], palette)
            level_positions[level] += 1

            if taxon_id in added_ids:
                continue  # same rank and name twice (GTDB): keep the larger
            note = _watch_note(protected_taxa, node_taxid)
            ids.append(taxon_id)
            added_ids.add(taxon_id)
            labels.append(WATCHED_LABEL_PREFIX + taxon if note else taxon)
            parents.append(parent_id)
            values.append(reads)
            colors.append(color)
            custom_data.append([RANK_NAMES.get(level, level), reads, pct_of_total, note])

    values = _make_values_consistent(ids, parents, values)
    return ids, labels, parents, values, colors, custom_data


def _make_values_consistent(ids, parents, values):
    """Raise each parent's value to at least the sum of its children's.

    Node values are cumulative (clade) reads, which already satisfy
    parent >= sum(children) for one report and for a per-taxid aggregate. The
    synthetic root carries 0 and needs its children's sum, and a composite-key
    collision (two taxa sharing rank and name) can break the invariant for a
    single node; under branchvalues="total" plotly silently omits such a
    sector and its subtree. Children are appended after their parent, so a
    reverse pass settles every level. The hover keeps the true read count
    (customdata), so this changes sector geometry only where the data was
    inconsistent.
    """
    index = {node_id: i for i, node_id in enumerate(ids)}
    values = list(values)
    child_sum = [0] * len(values)
    for i in range(len(ids) - 1, -1, -1):
        if child_sum[i] > values[i]:
            values[i] = child_sum[i]
        parent_idx = index.get(parents[i])
        if parent_idx is not None:
            child_sum[parent_idx] += values[i]
    return values


def create_sunburst_data(kraken_df, domains, tax_levels, min_reads, config,
                         color_palette=None, max_taxa_per_level=0,
                         chart_height="auto", color_mode="lineage",
                         protected_taxa=None):
    """
    Create a modern, well-styled Sunburst chart from Kraken report.

    Features:
    - Color-coded by taxonomy level for clear hierarchy visualization
    - Professional color palette designed for scientific data
    - Enhanced hover information with full context
    - Clean segment boundaries for readability
    - Optimized text display

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include
        tax_levels: List of taxonomy levels (e.g., ["D", "P", "C", "O", "F", "G", "S"])
        min_reads: Minimum reads for inclusion
        config: Application configuration
        color_palette: Dictionary mapping taxonomy ranks to colors (optional)
        max_taxa_per_level: Keep only the top-N taxa by reads at each rank
            (0 = no cap). Mirrors create_sankey_data; bounds the plotly node
            count so a dense report stays both fast to render and readable.
        chart_height: "auto" (720 px) or a pixel value, shared with the Sankey.
        color_mode: "lineage" (default) or "rank", as for the Sankey.
        protected_taxa: {kraken taxid: note} for watched organisms, kept past
            the cap and minimum-reads filter and outlined, as for the Sankey.

    Returns:
        A go.Figure with the styled Sunburst chart
    """
    # Ensure clean integer index to prevent duplicate-index issues with .loc[]
    kraken_df = kraken_df.reset_index(drop=True)

    # Sub-ranks (S1, S2, F3, etc.) are excluded by the tax_levels filter below.
    # No rank normalization needed — their cumulative reads are already counted
    # in the parent rank, so normalizing would double-count.

    palette = color_palette or TAXONOMY_COLORS
    if not tax_levels:
        tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "K", "P", "C", "O", "F", "G", "S"]
        )
        logging.debug(f"Sunburst: No tax_levels provided, using config: {tax_levels}")
    else:
        logging.debug(f"Sunburst: Using provided tax_levels: {tax_levels}")

    # Check available ranks BEFORE min_reads filtering.
    available_ranks = kraken_df["rank"].unique().tolist()
    tax_levels = [level for level in tax_levels if level in available_ranks]
    logging.debug(f"Sunburst: Available ranks: {available_ranks}")
    logging.debug(f"Sunburst: Selected levels: {tax_levels}")

    # Filter by tax_levels, then by the selected domains (taxid subtree, as
    # in the Sankey; skipped when the frame has no parent links to walk).
    filtered_df = kraken_df[kraken_df["rank"].isin(tax_levels)].copy()
    if domains and {"taxid", "parent_taxid"} <= set(kraken_df.columns):
        in_domains = _domain_taxid_set(
            kraken_df,
            dict(zip(kraken_df["taxid"].astype(int),
                     kraken_df["parent_taxid"].astype(int))),
            domains,
        )
        filtered_df = filtered_df[filtered_df["taxid"].astype(int).isin(in_domains)]

    # Recalculate cumulative reads bottom-up so parent >= children even when
    # aggregating across multiple samples. Composite key f"{rank}_{name}"
    # matches recalculate_cumulative_reads' output.
    recalc_cumul = recalculate_cumulative_reads(kraken_df)
    filtered_df["recalc_cumul"] = (
        filtered_df["rank"] + "_" + filtered_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)

    # "Minimum DNA Sequences" on CUMULATIVE reads at every level, as in the
    # Sankey. It used to apply to species only and on the direct column, so
    # a species whose reads all sit in its subspecies was dropped.
    keep_taxa = None
    if protected_taxa and {"taxid", "parent_taxid"} <= set(kraken_df.columns):
        keep_taxa = _with_ancestors(protected_taxa, dict(zip(
            kraken_df["taxid"].astype(int), kraken_df["parent_taxid"].astype(int))))
    candidates = filtered_df[filtered_df["recalc_cumul"] > 0]
    filtered_df = _keep_rows(filtered_df, min_reads, keep_taxa).copy()
    logging.debug(f"Sunburst: {len(filtered_df)} rows after filtering")

    if filtered_df.empty or not tax_levels:
        logging.debug("Sunburst: No data after filtering")
        return create_empty_sunburst("No data matches the selected filters")

    # Percentage base: all reads in the sample, as for the Sankey and
    # Kraken2's own %, so "Of total" and the Sankey's "Proportion" give one
    # taxon one number. (It was the displayed first level's sum, which
    # excludes unclassified reads and unselected domains.)
    total_reads = _total_read_count(kraken_df) or 1

    # Authoritative parent lookup, same as the Sankey: walk the taxid parent
    # chain when those columns exist, else fall back to indentation.
    use_taxid_parents = (
        "taxid" in kraken_df.columns and "parent_taxid" in kraken_df.columns
    )
    taxid_to_parent = {}
    taxid_to_key = {}
    if use_taxid_parents:
        taxid_to_parent = dict(zip(
            kraken_df["taxid"].astype(int), kraken_df["parent_taxid"].astype(int)
        ))
        # .tolist() before zip: iterating the arrow-backed rank/name Series
        # directly hits arrow __iter__ per element on every rebuild (cProfile,
        # GTDB scale); native lists zip in C.
        _tids = kraken_df["taxid"].astype(int).tolist()
        _ranks = kraken_df["rank"].tolist()
        _names = kraken_df["name"].tolist()
        taxid_to_key = {
            tid: f"{rank}_{name.strip()}"
            for tid, rank, name in zip(_tids, _ranks, _names)
        }

    ids, labels, parents, values, colors, custom_data = _build_sunburst_nodes(
        filtered_df, tax_levels, total_reads, palette,
        use_taxid_parents, taxid_to_parent, taxid_to_key,
        max_taxa_per_level=max_taxa_per_level,
        keep_taxa=keep_taxa, protected_taxa=protected_taxa,
    )

    # The root is the classified reads; its share is of ALL reads. It was
    # "All Taxa" with the filter-dependent sum of what was drawn.
    classified, _unclassified = _classified_unclassified(kraken_df)
    labels[0] = "Classified reads"
    if classified:
        custom_data[0] = ["Root", classified, classified / total_reads * 100, ""]

    node_keys = ids[1:]
    rank_of = {k: k.split("_", 1)[0] for k in node_keys}
    reads_of = dict(zip(ids, values))
    parent_of = {k: (p if p != "root" else None) for k, p in zip(ids, parents)}
    if color_mode == "lineage":
        lineage = _lineage_colors(node_keys, rank_of, reads_of, parent_of, tax_levels,
                                  tint_by_depth=True)
        colors = [colors[0]] + [lineage[k] for k in node_keys]
        legend_text = _lineage_legend(node_keys, rank_of, reads_of,
                                      _lineage_colors(node_keys, rank_of, reads_of,
                                                      parent_of, tax_levels),
                                      tax_levels)
    else:
        legend_text = "Rings, centre to edge: " + " | ".join(
            f"<span style='color:{palette.get(lvl, '#94A3B8')}'>\u25CF</span> "
            f"{RANK_NAMES.get(lvl, lvl)}" for lvl in tax_levels)
    watched = [bool(cd[3]) for cd in custom_data]
    if any(watched):
        legend_text += (f"   <span style='color:{WATCHED_COLOR}'>"
                        f"{WATCHED_LABEL_PREFIX}outlined = on the watchlist</span>")
    hidden = max(0, candidates["taxid"].nunique() - len(node_keys))
    caption = _chart_caption(kraken_df, total_reads, len(node_keys), hidden)

    # Detect orphan parents (referenced but never added).
    orphan_parents = (set(parents) - {""}) - set(ids)
    if orphan_parents:
        logging.warning(f"Sunburst: Found {len(orphan_parents)} orphan parents: {list(orphan_parents)[:5]}...")
    logging.debug(f"Sunburst: Built {len(ids)} nodes, {len(set(parents))} unique parents")

    # Create the sunburst figure using go.Sunburst for full control
    # Values are cumulative (clade) reads, so a parent already contains its
    # children: branchvalues="total". Under "remainder" plotly adds a parent's
    # value on top of its children's, counting each read once per level --
    # deeper branches outweighed shallower ones and "Of parent group" was
    # wrong. _make_values_consistent guarantees parent >= sum(children).
    fig = go.Figure(go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="total",
        marker=dict(
            colors=colors,
            line=dict(
                color=[WATCHED_COLOR if w else "white" for w in watched],
                width=[3 if w else 1.5 for w in watched],
            ),
        ),
        # Text colour per sector from the fill's lightness: white on the
        # dark neutral and saturated rings, dark ink on the pale tints.
        insidetextfont=dict(
            size=11,
            color=[_text_on(c) for c in colors],
            family="Arial, sans-serif",
        ),
        insidetextorientation="auto",
        hovertemplate=(
            "<b>%{label}</b><br>"
            "<span style='color:#9CA3AF'>Level: %{customdata[0]}</span><br>"
            "DNA sequences: <b>%{customdata[1]:,.0f}</b><br>"
            "Of all reads: <b>%{customdata[2]:.1f}%</b><br>"
            "Of parent: <b>%{percentParent:.1%}</b>"
            "%{customdata[3]}"
            "<extra></extra>"
        ),
        customdata=custom_data,
        maxdepth=len(tax_levels) + 1,
    ))

    try:
        height = int(chart_height) if chart_height not in (None, "", "auto") else 720
    except (TypeError, ValueError):
        height = 720

    # Update layout with refined styling
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=80, b=55),
        title=dict(
            text=(f"<b>{CHART_TITLE}</b><br>"
                  f"<span style='font-size:12px;color:#4B5563'>{caption}</span>"),
            font=dict(size=18, color="#1F2937", family="Arial, sans-serif"),
            x=0.5,
            xanchor="center",
            y=0.97
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(family="Arial, sans-serif"),
        annotations=[
            dict(
                text=legend_text,
                x=0.5,
                y=-0.05,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=12, color="#4B5563"),
                xanchor="center"
            )
        ],
        uniformtext=dict(minsize=9, mode="hide"),
    )

    logging.debug(f"Sunburst: Created chart with {len(ids)} nodes")
    return apply_theme_to_figure(fig)
