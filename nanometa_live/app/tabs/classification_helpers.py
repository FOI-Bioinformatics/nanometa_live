"""
Pure visualization helpers for the Classification tab.

Builds the Sankey and Sunburst figures from a parsed Kraken2 dataframe. These
functions perform no Dash callback wiring and no file I/O, so they can be unit
tested directly (see the *_tab.py -> *_helpers.py split used across the
dashboard, main, qc, and validation tabs). The callback wiring lives in
``classification_tab.py``.
"""

import logging

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


def _build_sankey_frames(kraken_df, domains, tax_levels):
    """Filter the kraken frame to the requested domains and tax levels.

    Returns ``(tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key)``
    or ``None`` when no rows fall under the requested domains. ``domain_df``
    gains ``recalc_cumul`` (cumulative reads) and ``recalc_pct`` columns.
    """
    recalc_cumul = recalculate_cumulative_reads(kraken_df)
    total_reads = sum(recalc_cumul.values()) or 1

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

    # Filter by domain via taxid subtree membership (order-independent).
    children_map: dict = {}
    for taxid, parent_taxid in taxid_to_parent.items():
        children_map.setdefault(parent_taxid, []).append(taxid)

    def _collect_subtree(root_taxid):
        """Return the set of all taxids at or below root_taxid."""
        result = set()
        stack = [root_taxid]
        while stack:
            tid = stack.pop()
            result.add(tid)
            stack.extend(children_map.get(tid, []))
        return result

    domain_taxids_set = set()
    for domain in domains:
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]
        if domain_rows.empty:
            continue
        domain_taxid = int(domain_rows.iloc[0]["taxid"])
        domain_taxids_set.update(_collect_subtree(domain_taxid))

    domain_df = kraken_df[kraken_df["taxid"].isin(domain_taxids_set)].copy()
    if domain_df.empty:
        return None

    domain_df["recalc_cumul"] = (
        domain_df["rank"] + "_" + domain_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)
    domain_df["recalc_pct"] = domain_df["recalc_cumul"] / total_reads * 100

    tax_df = domain_df[domain_df["rank"].isin(tax_levels)].copy()
    return tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key


def _build_sankey_nodes(tax_df, tax_levels, max_taxa_per_level):
    """Create node bookkeeping for the top taxa at each level.

    Levels are processed in order so nodes form clean per-rank groups. Returns
    ``(nodes, node_ids, node_values, node_pcts, node_ranks)``.
    """
    node_id = 0
    node_ids = {}
    nodes = []
    node_values = {}
    node_pcts = {}
    node_ranks = {}
    for level in tax_levels:
        level_df = (
            tax_df[tax_df["rank"] == level]
            .sort_values("recalc_cumul", ascending=False)
            .head(max_taxa_per_level)
        )
        level_names = level_df["name"].str.strip().tolist()
        level_cumuls = level_df["recalc_cumul"].tolist()
        level_pcts = level_df["recalc_pct"].tolist()
        for name, cumul_val, pct_val in zip(level_names, level_cumuls, level_pcts):
            node_key = f"{level}_{name}"
            node_ids[node_key] = node_id
            nodes.append(node_key)
            node_values[node_key] = cumul_val
            node_pcts[node_key] = pct_val
            node_ranks[node_key] = level
            node_id += 1
    return nodes, node_ids, node_values, node_pcts, node_ranks


def _build_sankey_links(tax_df, tax_levels, max_taxa_per_level, node_ids,
                        node_values, taxid_to_parent, taxid_to_key):
    """Link each level's nodes to the nearest visible ancestor one level up.

    Walks the taxid parent chain (order-independent) and never falls back to an
    unrelated parent, which would create misleading taxonomic links. Returns
    ``(links, values, parent_outgoing_sum, parent_link_indices)``.
    """
    links = []
    values = []
    parent_outgoing_sum = {}   # parent_key -> sum of outgoing link values
    parent_link_indices = {}   # parent_key -> link indices (for scaling)

    for i in range(len(tax_levels) - 1, 0, -1):
        current_level = tax_levels[i]
        parent_level = tax_levels[i - 1]
        level_df = (
            tax_df[tax_df["rank"] == current_level]
            .sort_values("recalc_cumul", ascending=False)
            .head(max_taxa_per_level)
        )
        child_names_stripped = level_df["name"].str.strip().tolist()
        child_taxids = level_df["taxid"].tolist()
        child_cumuls = level_df["recalc_cumul"].tolist()

        for child_name_stripped, child_taxid, child_cumul in zip(
            child_names_stripped, child_taxids, child_cumuls
        ):
            child_key = f"{current_level}_{child_name_stripped}"
            if child_key not in node_ids:
                continue
            child_value = node_values.get(child_key, child_cumul)

            parent_found = False
            current_taxid = taxid_to_parent.get(int(child_taxid), 0)
            while current_taxid != 0:
                ancestor_key = taxid_to_key.get(current_taxid)
                if ancestor_key is not None:
                    ancestor_rank = ancestor_key.split("_", 1)[0]
                    if ancestor_rank == parent_level:
                        # Found the right rank - only link if it is visible.
                        if ancestor_key in node_ids:
                            link_idx = len(links)
                            links.append((node_ids[ancestor_key], node_ids[child_key]))
                            values.append(child_value)
                            parent_outgoing_sum[ancestor_key] = parent_outgoing_sum.get(ancestor_key, 0) + child_value
                            parent_link_indices.setdefault(ancestor_key, []).append(link_idx)
                            parent_found = True
                        break  # Stop regardless - found the rank, visible or not.
                    elif ancestor_rank in tax_levels and tax_levels.index(ancestor_rank) < tax_levels.index(parent_level):
                        # Passed a displayed rank above parent_level without a hit.
                        break
                current_taxid = taxid_to_parent.get(current_taxid, 0)

            if not parent_found:
                logging.debug(
                    f"Sankey: No parent at {parent_level} found for "
                    f"{child_name_stripped} ({current_level}) - skipping link"
                )

    return links, values, parent_outgoing_sum, parent_link_indices


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
    x_max = 0.85  # Leave 150px right margin for rightmost labels.
    n_levels = len(tax_levels)
    level_to_x = {}
    if n_levels == 1:
        level_to_x[tax_levels[0]] = (x_min + x_max) / 2
    else:
        for i, level in enumerate(tax_levels):
            level_to_x[level] = x_min + (x_max - x_min) * i / (n_levels - 1)
    return [level_to_x.get(node_ranks.get(name, ""), 0.5) for name in nodes]


def _build_sankey_customdata(nodes, node_values, node_pcts, node_ranks):
    """Build node display labels and hover customdata.

    Returns ``(node_labels, node_customdata)`` where each customdata row is
    ``[reads, percentage, rank_name, full_name]``. Long labels are truncated;
    the full name stays in the hover tooltip.
    """
    MAX_LABEL_LEN = 30
    node_labels = []
    node_customdata = []
    for node_key in nodes:
        display_name = node_key.split("_", 1)[1] if "_" in node_key else node_key
        if len(display_name) > MAX_LABEL_LEN:
            node_labels.append(display_name[:MAX_LABEL_LEN - 1] + "...")
        else:
            node_labels.append(display_name)
        rank = node_ranks.get(node_key, "")
        node_customdata.append([
            node_values.get(node_key, 0),
            node_pcts.get(node_key, 0),
            RANK_NAMES.get(rank, rank),
            display_name,
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


def create_sankey_data(kraken_df, domains, tax_levels, min_reads, max_taxa_per_level, chart_height="auto", color_palette=None):
    """
    Create Sankey plot data from Kraken report.

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include
        tax_levels: List of taxonomy levels to include
        min_reads: Minimum number of reads for filtering
        max_taxa_per_level: Maximum number of taxa to show at each level
        chart_height: Chart height - "auto" for adaptive, or pixel value as string
        color_palette: Dictionary mapping taxonomy ranks to colors (optional)

    Returns:
        A Go.Figure object with the Sankey plot
    """
    colors = color_palette or TAXONOMY_COLORS

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

    frames = _build_sankey_frames(kraken_df, domains, tax_levels)
    if frames is None:
        return None
    tax_df, domain_df, total_reads, taxid_to_parent, taxid_to_key = frames

    nodes, node_ids, node_values, node_pcts, node_ranks = _build_sankey_nodes(
        tax_df, tax_levels, max_taxa_per_level
    )
    logging.debug(f"Sankey: Created {len(nodes)} nodes across {len(tax_levels)} levels")

    links, values, parent_outgoing_sum, parent_link_indices = _build_sankey_links(
        tax_df, tax_levels, max_taxa_per_level, node_ids, node_values,
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
    node_colors = _build_sankey_node_colors(nodes, node_ranks, colors)
    link_colors = _build_sankey_link_colors(links, values, node_colors)

    source_indices = [link[0] for link in links]
    target_indices = [link[1] for link in links]

    node_x = _build_sankey_node_x(nodes, node_ranks, tax_levels)
    parent_map = build_parent_map(tax_df, domain_df, tax_levels, node_ids, max_taxa_per_level,
                                   taxid_to_parent=taxid_to_parent, taxid_to_key=taxid_to_key)
    node_y = _calculate_hierarchical_y_positions(
        nodes, node_ids, tax_levels, nodes_per_level, parent_map, node_values, node_ranks
    )

    node_labels, node_customdata = _build_sankey_customdata(
        nodes, node_values, node_pcts, node_ranks
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
                line=dict(color="#E5E7EB", width=0.5),
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>"
                    "Level: <i>%{customdata[2]}</i><br>"
                    "DNA sequences: <b>%{customdata[0]:,.0f}</b><br>"
                    "Proportion: <b>%{customdata[1]:.2f}%</b>"
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
    sankey_legend_text = _build_sankey_legend(tax_levels, colors)

    # Layout with dynamic height and balanced margins for labels
    figure.update_layout(
        height=final_height,
        title=dict(
            text="<b>How Organisms Are Classified</b>",
            font=dict(size=18, color="#1F2937", family="Arial, sans-serif"),
            x=0.5,
            xanchor="center",
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=20, r=150, t=65, b=50),
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
                          max_taxa_per_level=0):
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

    # Root carries no value: branchvalues="remainder" avoids the
    # parent >= sum(children) constraint.
    ids.append("root")
    labels.append("All Taxa")
    parents.append("")
    values.append(0)
    colors.append("#E5E7EB")
    custom_data.append(["Root", first_level_reads, 100.0])

    added_ids = {"root"}
    for level_idx, level in enumerate(tax_levels):
        level_df = filtered_df[filtered_df["rank"] == level].sort_values(
            "recalc_cumul", ascending=False
        )
        if cap:
            level_df = level_df.head(cap)
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

            ids.append(taxon_id)
            added_ids.add(taxon_id)
            labels.append(taxon)
            parents.append(parent_id)
            values.append(reads)
            colors.append(color)
            custom_data.append([RANK_NAMES.get(level, level), reads, pct_of_total])

    return ids, labels, parents, values, colors, custom_data


def create_sunburst_data(kraken_df, domains, tax_levels, min_reads, config,
                         color_palette=None, max_taxa_per_level=0):
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

    # Filter by tax_levels; apply min_reads only to Species.
    level_filtered_df = kraken_df[kraken_df["rank"].isin(tax_levels)].copy()
    if "S" in tax_levels:
        filtered_df = level_filtered_df[
            (level_filtered_df["rank"] != "S") |
            (level_filtered_df["reads"] >= min_reads)
        ].copy()
    else:
        filtered_df = level_filtered_df.copy()
    logging.debug(f"Sunburst: {len(filtered_df)} rows after filtering")

    if filtered_df.empty or not tax_levels:
        logging.debug("Sunburst: No data after filtering")
        return create_empty_sunburst("No data matches the selected filters")

    # Recalculate cumulative reads bottom-up so parent >= children even when
    # aggregating across multiple samples. Composite key f"{rank}_{name}"
    # matches recalculate_cumulative_reads' output.
    recalc_cumul = recalculate_cumulative_reads(kraken_df)
    filtered_df["recalc_cumul"] = (
        filtered_df["rank"] + "_" + filtered_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)

    # Percentage base: the first level's recalculated total (column sum).
    first_level_df = filtered_df[filtered_df["rank"] == tax_levels[0]]
    total_reads = int(first_level_df["recalc_cumul"].sum()) if tax_levels else 1
    if total_reads == 0:
        total_reads = 1  # Avoid division by zero.

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
    )

    # Detect orphan parents (referenced but never added).
    orphan_parents = (set(parents) - {""}) - set(ids)
    if orphan_parents:
        logging.warning(f"Sunburst: Found {len(orphan_parents)} orphan parents: {list(orphan_parents)[:5]}...")
    logging.debug(f"Sunburst: Built {len(ids)} nodes, {len(set(parents))} unique parents")

    # Create the sunburst figure using go.Sunburst for full control
    # CRITICAL FIX: Use branchvalues="remainder" instead of "total"
    # "remainder" mode allows child values to sum to less than parent (or parent=0)
    # This is more forgiving when hierarchy doesn't have perfect parent-child value relationships
    fig = go.Figure(go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        branchvalues="remainder",
        marker=dict(
            colors=colors,
            line=dict(color="white", width=2)
        ),
        textfont=dict(
            size=11,
            color="white",
            family="Arial, sans-serif",
        ),
        insidetextorientation="horizontal",
        hovertemplate=(
            "<b>%{label}</b><br>"
            "<span style='color:#9CA3AF'>Level: %{customdata[0]}</span><br>"
            "DNA sequences: <b>%{customdata[1]:,.0f}</b><br>"
            "Of total: <b>%{customdata[2]:.1f}%</b><br>"
            "Of parent group: <b>%{percentParent:.1%}</b>"
            "<extra></extra>"
        ),
        customdata=custom_data,
        maxdepth=len(tax_levels) + 1,
    ))

    # Create legend annotation showing level colors
    legend_items = []
    for level in tax_levels:
        color = palette.get(level, "#94A3B8")
        name = RANK_NAMES.get(level, level)
        legend_items.append(f"<span style='color:{color}'>\u25CF</span> {name}")

    legend_text = " | ".join(legend_items)

    # Update layout with refined styling
    fig.update_layout(
        height=850,
        margin=dict(l=20, r=20, t=70, b=55),
        title=dict(
            text="<b>Organism Classification Overview</b>",
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
                text=f"<b>Classification levels (center=broad, outer=specific):</b> {legend_text}",
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
