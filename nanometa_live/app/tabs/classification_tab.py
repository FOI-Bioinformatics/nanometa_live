"""
Classification tab callbacks for Nanometa Live v2.0.

This module combines Sankey and Sunburst visualizations into a single tab
with toggleable views, supporting both per-sample and aggregated analysis.
"""

import os
import logging
import pandas as pd
from typing import Optional

from dash import Dash, Input, Output, State, no_update, html, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px

from nanometa_live.core.utils.data_loaders import load_kraken_data
from nanometa_live.app.utils.callback_helpers import (
    validate_config_and_get_main_dir,
    log_callback_error,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.app.utils.plotly_theme import apply_theme_to_figure
from nanometa_live.app.utils.debounce import should_skip_update, get_trigger_type
from nanometa_live.app.tabs.kraken2_helpers import (
    RANK_NAMES,
    RANK_NORMALIZATION,
    STANDARD_RANKS,
    CANONICAL_RANK_ORDER,
    COLORS_TABLEAU,
    COLORS_VIRIDIS,
    COLORS_PASTEL,
    COLORS_DARK,
    COLORS_NATURE,
    COLORS_OCEAN,
    COLOR_SCHEMES,
    TAXONOMY_COLORS,
    recalculate_cumulative_reads,
    build_parent_map,
    filter_by_domains,
    get_level_color,
    load_kraken2_taxonomy,
    apply_authoritative_taxonomy,
)


def register_classification_callbacks(app: Dash):
    """
    Register callbacks for the unified Classification tab.

    Args:
        app: Dash application
    """

    @app.callback(
        Output("classification-filter-input", "value"),
        Output("classification-filter-input", "placeholder"),
        Input("available-samples", "data"),
        Input("selected-sample", "data"),
        State("classification-filter-input", "value"),
        prevent_initial_call=False,
    )
    def scale_min_reads_default(available_samples, selected_sample, current_value):
        """Scale the minimum-DNA-sequences default upward when an
        aggregated 24-barcode view is selected.

        Closes P1-T04 from docs/audit-2026-04-28-throughput-ux.md: a
        per-sample 1-read detection becomes 24 reads in the All-Samples
        aggregate view and survives the static ``min_reads=10`` default,
        producing taxonomic noise chains that look real on the
        Sankey/Sunburst.

        Heuristic: when "All Samples" is selected and >=12 barcodes are
        loaded, set the default floor to ``max(10, 5 * N)``. Only
        applied when the input still holds the static layout default
        of 10, so an operator who typed a custom value keeps it.
        """
        is_aggregate = selected_sample in (None, "All Samples")
        real_samples = [s for s in (available_samples or []) if s != "All Samples"]
        n = len(real_samples)

        # Recommended floor is independent of which view is selected --
        # operator can see it in the placeholder even when looking at a
        # single sample.
        floor = max(10, 5 * n) if n >= 12 else 10
        placeholder = f"min reads ({floor} recommended at {n} samples)" if n >= 12 \
            else "min reads (10 default)"

        if is_aggregate and n >= 12 and (current_value in (None, 10)):
            return floor, placeholder
        # Only update the placeholder hint, leave value as-is.
        return current_value if current_value is not None else 10, placeholder

    @app.callback(
        Output("classification-levels-input", "value"),
        Input("classification-level-preset", "value"),
        prevent_initial_call=False
    )
    def update_levels_from_preset(preset):
        """
        Sync the multi-select levels dropdown with the selected preset.

        Args:
            preset: Selected preset value

        Returns:
            List of taxonomy levels corresponding to the preset
        """
        presets = {
            'standard': ['P', 'C', 'O', 'F', 'G', 'S'],
            'overview': ['D', 'K', 'P', 'C'],
            'species_focus': ['F', 'G', 'S'],
            'clinical': ['F', 'G', 'S'],
            'full': ['D', 'K', 'P', 'C', 'O', 'F', 'G', 'S'],
        }
        if preset == 'custom':
            return no_update
        return presets.get(preset, ['P', 'C', 'O', 'F', 'G', 'S'])

    @app.callback(
        [
            Output("classification-plot", "figure"),
            Output("classification-info-message", "children"),
            Output("classification-plot", "style"),
        ],
        [
            Input("results-fingerprint", "data"),
            Input("apply-classification-settings", "n_clicks"),
            Input("classification-view-type", "value"),
            Input("selected-sample", "data"),  # Sample changes trigger updates
            Input("classification-levels-input", "value"),  # CRITICAL FIX: Level changes trigger updates
            Input("classification-level-preset", "value"),  # CRITICAL FIX: Preset changes trigger updates
            Input("classification-color-scheme", "value"),  # Color scheme selection
            Input("classification-max-taxa", "value"),  # Max taxa per level filter
            Input("classification-chart-height", "value"),  # Chart height control
        ],
        [
            State("classification-filter-input", "value"),
            State("classification-domains-input", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_classification_plot(
        _fingerprint,
        filter_clicks,
        view_type,
        selected_sample,
        tax_levels,       # Now an Input - triggers on change
        preset,           # Now an Input - triggers on preset selection
        color_scheme,     # Color scheme selection
        max_taxa_value,   # Max taxa per level filter
        chart_height,     # Chart height control
        filter_value,     # State
        domains,          # State
        config,
        status,
    ):
        """
        Update classification visualization based on view type and filters.

        Switches between Sankey and Sunburst based on view_type selection.
        Supports per-sample and aggregated data views.

        Returns:
            Tuple of (figure, info_message_children, graph_style)
        """

        # Debounce interval-triggered refreshes
        if get_trigger_type(ctx) == "interval":
            if should_skip_update("classification_plot", debounce_ms=2000):
                raise PreventUpdate

        # Style constants for showing/hiding the graph
        graph_visible = {"width": "100%"}
        graph_hidden = {"width": "100%", "display": "none"}

        # Empty state for when no data is available
        empty_state = EmptyStateMessage(
            title="No Classification Data Yet",
            message="This view will show how detected organisms are grouped and "
                    "related once analysis results are available. "
                    "Check that a sample is selected and the pipeline is running.",
            icon="bi-diagram-3"
        )

        # Helper to create a minimal empty figure (used when graph is hidden)
        def _empty_figure():
            fig = go.Figure()
            fig.update_layout(
                height=50,
                margin=dict(l=0, r=0, t=0, b=0),
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
            )
            return fig

        # Validate config and get output directory using centralized helper
        main_dir = validate_config_and_get_main_dir(config)
        if not main_dir or not os.path.isdir(main_dir):
            return _empty_figure(), empty_state, graph_hidden

        # CRITICAL FIX: Ensure selected_sample is a string, not a list
        # If it's a list, it means parameters are mismatched - use default
        if isinstance(selected_sample, list) or selected_sample is None:
            logging.warning(f"selected_sample has wrong type: {type(selected_sample)} = {selected_sample}")
            logging.debug(f"  filter_value={filter_value}, domains={domains}, tax_levels={tax_levels}")
            selected_sample = "All Samples"  # Use safe default

        # Set defaults
        filter_value = filter_value or 10
        domains = domains or ["Bacteria", "Archaea", "Eukaryota", "Viruses"]

        # Process max_taxa parameter
        max_taxa = int(max_taxa_value) if max_taxa_value else 10
        if max_taxa == 0:
            max_taxa = 9999  # Effectively no limit

        # Get taxonomy levels with defaults
        # Canonical ordering includes K (Kingdom) between D and P
        canonical_order = ["D", "K", "P", "C", "O", "F", "G", "S"]
        all_tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "P", "C", "O", "F", "G", "S"]
        )
        # Ensure K is always in the allowed set so user can select it even if config omits it
        if "K" not in all_tax_levels:
            all_tax_levels = canonical_order
        if not tax_levels:
            tax_levels = config.get("default_hierarchy_letters", ["D", "C", "G", "S"])

        # Keep only valid taxonomy levels in canonical order
        tax_levels = [level for level in canonical_order if level in tax_levels]

        try:
            # Load Kraken2 data (per-sample or aggregated)
            logging.debug(f"Loading Kraken data for sample='{selected_sample}' (type={type(selected_sample)})")
            kraken_df = load_kraken_data(main_dir, selected_sample)

            if kraken_df.empty:
                return _empty_figure(), empty_state, graph_hidden

            # Replace indentation-derived parent_taxid with authoritative values
            # from the Kraken2 database's inspect.txt. Per-sample reports from
            # PlusPFP can have out-of-order nodes that break the indentation
            # parser; inspect.txt is always in correct DFS order.
            kraken_db_path = config.get("kraken_db", "") if config else ""
            if kraken_db_path:
                taxonomy = load_kraken2_taxonomy(kraken_db_path)
                if taxonomy:
                    kraken_df = apply_authoritative_taxonomy(kraken_df, taxonomy)

            # Get the selected color palette (default to tableau)
            color_palette = COLOR_SCHEMES.get(color_scheme or "tableau", COLORS_TABLEAU)

            # Generate visualization based on type
            if view_type == "sunburst":
                figure = create_sunburst_data(kraken_df, domains, tax_levels, filter_value, config, color_palette)
                if figure is None:
                    return create_empty_sunburst("No data matches the selected filters"), None, graph_visible
                return figure, None, graph_visible
            else:  # sankey
                figure = create_sankey_data(kraken_df, domains, tax_levels, filter_value, max_taxa, chart_height, color_palette)
                if figure is None:
                    return create_placeholder_sankey("No data matches the selected filters"), None, graph_visible
                return figure, None, graph_visible

        except Exception as e:
            logging.error(f"Error updating classification plot: {e}")
            if view_type == "sunburst":
                return create_empty_sunburst(f"Error: {str(e)}"), None, graph_visible
            else:
                return create_placeholder_sankey(f"Error: {str(e)}"), None, graph_visible

    # NOTE: toggle_levels_visibility callback removed (Dash 4 cleanup).
    # It always returned {"display": "block"} regardless of input.
    # The classification-levels-container should have style={"display": "block"}
    # set directly in the layout instead.

    @app.callback(
        Output("classification-help-section", "children"),
        Input("classification-view-type", "value"),
    )
    def update_help_section(view_type):
        """Update help section to show guidance for the selected visualization."""
        if view_type == "sunburst":
            chart_help = [
                html.H6("Reading the Sunburst Chart", className="fw-bold mb-2"),
                html.Ul([
                    html.Li([html.Strong("Center: "), "Broadest categories (Domain)"]),
                    html.Li([html.Strong("Outer rings: "), "More specific classifications (toward Species)"]),
                    html.Li([html.Strong("Slice size: "), "Proportion of DNA sequences - larger = more abundant"]),
                    html.Li([html.Strong("Click slices: "), "Zoom in to explore sub-categories"]),
                ], className="mb-1"),
                html.Small("Best for seeing overall community structure and relative abundances at a glance.",
                           className="text-muted"),
            ]
        else:
            chart_help = [
                html.H6("Reading the Sankey Diagram", className="fw-bold mb-2"),
                html.Ul([
                    html.Li([html.Strong("Left side: "), "Broad classification categories (Domain, Class)"]),
                    html.Li([html.Strong("Right side: "), "Specific organisms (Genus, Species)"]),
                    html.Li([html.Strong("Flow width: "), "Number of DNA sequences - wider = more abundant"]),
                    html.Li([html.Strong("Follow paths: "), "Trace classification from general to specific"]),
                ], className="mb-1"),
                html.Small("Best for understanding how the analysis classified your sequences step-by-step.",
                           className="text-muted"),
            ]

        return dbc.Accordion([
            dbc.AccordionItem(
                dbc.Row([
                    dbc.Col(chart_help, md=7),
                    dbc.Col([
                        html.H6([html.I(className="bi bi-lightbulb me-2"), "Tips"], className="fw-bold mb-2"),
                        html.Ul([
                            html.Li("Increase 'Minimum DNA Sequences' to focus on abundant organisms"),
                            html.Li("Try both views for different perspectives on the same data"),
                            html.Li("Use the Export button to save for reports"),
                        ], className="mb-0", style={"fontSize": "0.9rem"})
                    ], md=5),
                ]),
                title="How to Read This Visualization",
            )
        ], start_collapsed=True, className="mb-4")

    @app.callback(
        Output("classification-export-modal", "is_open"),
        [
            Input("export-classification-button", "n_clicks"),
            Input("confirm-classification-export", "n_clicks"),
            Input("cancel-classification-export", "n_clicks"),
        ],
        State("classification-export-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_export_modal(export_clicks, confirm_clicks, cancel_clicks, is_open):
        """Toggle the export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input("confirm-classification-export", "n_clicks"),
        [
            State("classification-export-filename", "value"),
            State("classification-export-dir", "value"),
            State("classification-plot", "figure"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_classification_plot(n_clicks, filename, export_dir, figure, config):
        """Export the classification plot as an HTML file."""
        if not n_clicks or not figure:
            return no_update

        try:
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

            # Use provided directory or default to reports/
            if export_dir:
                reports_dir = export_dir
            else:
                reports_dir = os.path.join(main_dir, "reports")

            os.makedirs(reports_dir, exist_ok=True)

            # Set default filename if none provided
            if not filename:
                filename = "classification_plot"

            # Ensure .html extension
            if not filename.endswith(".html"):
                filename += ".html"

            # Save the figure
            output_path = os.path.join(reports_dir, filename)

            import plotly.io as pio
            pio.write_html(figure, file=output_path, auto_open=False)

            return {
                "title": "Export Successful",
                "message": f"Classification plot exported to {output_path}",
                "color": "success",
            }

        except Exception as e:
            return {
                "title": "Export Failed",
                "message": f"Failed to export plot: {str(e)}",
                "color": "danger",
            }

    # Note: Sankey label repositioning is handled by a MutationObserver
    # in assets/custom.js (workaround for plotly.js#7445).


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
    # Use provided color palette or default
    colors = color_palette or TAXONOMY_COLORS
    # Shared layout for informational empty-state figures
    _info_layout = dict(
        height=400,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=50, r=50, t=50, b=50),
        font=dict(family="Arial, sans-serif"),
    )

    # Ensure clean integer index to prevent duplicate-index issues with .loc[]
    kraken_df = kraken_df.reset_index(drop=True)

    # Handle empty dataframe
    if kraken_df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No organism classification data available for this sample.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # Filter to standard taxonomy ranks only — sub-ranks (S1, S2, F3, etc.)
    # are excluded because their cumulative reads are already counted in the
    # parent rank's cumulative total, and including them would double-count.
    available_ranks = kraken_df["rank"].unique().tolist()
    tax_levels = [level for level in tax_levels if level in available_ranks]

    logging.debug(f"Sankey: Available ranks in data: {available_ranks}")
    logging.debug(f"Sankey: Using tax_levels: {tax_levels}")

    # If no valid tax levels after filtering, return informative message
    if not tax_levels:
        logging.debug("Sankey: No matching tax levels found in data")
        fig = go.Figure()
        fig.add_annotation(
            text=f"No matching classification levels in data.<br>Try adjusting filter settings or selecting a different preset view.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # Sankey requires at least 2 levels to show parent-child relationships
    if len(tax_levels) < 2:
        logging.debug(f"Sankey: Need at least 2 taxonomy levels, only have {len(tax_levels)}: {tax_levels}")
        rank_names_local = {"D": "Domain", "K": "Kingdom", "P": "Phylum", "C": "Class", "O": "Order", "F": "Family", "G": "Genus", "S": "Species"}
        available_names = [rank_names_local.get(r, r) for r in available_ranks]
        fig = go.Figure()
        fig.add_annotation(
            text=f"The flow diagram needs at least 2 classification levels to show relationships.<br>Currently available: {', '.join(available_names)}<br>Try the Ring View (Sunburst) or select more levels in Advanced Settings.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # Build cumulative reads lookup (composite key -> reads)
    recalc_cumul = recalculate_cumulative_reads(kraken_df)

    # Calculate total reads for percentage calculation
    total_reads = sum(recalc_cumul.values())
    if total_reads == 0:
        total_reads = 1

    # Build taxid-based parent lookup from the parent_taxid column.
    # parent_taxid is computed during Kraken2 report parsing from indentation,
    # making it robust to aggregation reordering.
    taxid_to_parent = dict(zip(
        kraken_df["taxid"].astype(int), kraken_df["parent_taxid"].astype(int)
    ))

    # Build composite-key lookup: taxid -> f"{rank}_{name}"
    # Used for parent-finding via taxid_to_parent (order-independent).
    taxid_to_key = {
        int(tid): f"{rank}_{name.strip()}"
        for tid, rank, name in zip(
            kraken_df["taxid"], kraken_df["rank"], kraken_df["name"]
        )
    }

    # Filter by domains using taxid subtree membership (order-independent).
    # Build a children map then do BFS/DFS from each domain taxid downward.
    children_map: dict = {}
    for taxid, parent_taxid in taxid_to_parent.items():
        if parent_taxid not in children_map:
            children_map[parent_taxid] = []
        children_map[parent_taxid].append(taxid)

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

    # Add cumulative reads to domain_df for sorting and link values
    domain_df["recalc_cumul"] = (
        domain_df["rank"] + "_" + domain_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)

    # Add percentage for hover display
    domain_df["recalc_pct"] = domain_df["recalc_cumul"] / total_reads * 100

    # Filter by taxonomy levels
    tax_df = domain_df[domain_df["rank"].isin(tax_levels)].copy()

    # Generate node IDs
    node_id = 0
    node_ids = {}
    nodes = []
    node_values = {}  # Store recalculated cumulative reads for each node
    node_pcts = {}  # Store percentage for each node
    node_ranks = {}  # Store rank for each node

    # Process levels in the order specified (original dev2 algorithm)
    # This creates clean node groups: all Family nodes, then all Genus nodes, then all Species nodes
    # With "fixed" arrangement, explicit x/y positions control layout precisely
    # Sort by recalculated cumulative reads for proper hierarchy representation
    for level in tax_levels:
        level_df = tax_df[tax_df["rank"] == level].sort_values("recalc_cumul", ascending=False)

        # Take top N at this level
        level_df = level_df.head(max_taxa_per_level)

        # Vectorized node creation - extract columns as lists
        level_names = level_df["name"].str.strip().tolist()
        level_cumuls = level_df["recalc_cumul"].tolist()
        level_pcts = level_df["recalc_pct"].tolist()

        for name, cumul_val, pct_val in zip(level_names, level_cumuls, level_pcts):
            node_key = f"{level}_{name}"
            node_ids[node_key] = node_id
            nodes.append(node_key)
            # Store recalculated cumulative value and percentage for this node
            node_values[node_key] = cumul_val
            node_pcts[node_key] = pct_val
            node_ranks[node_key] = level
            node_id += 1

    logging.debug(f"Sankey: Created {len(nodes)} nodes across {len(tax_levels)} levels")
    logging.debug(f"Sankey: Nodes: {nodes[:5]}...")  # Log first 5 nodes

    # Create links
    links = []
    values = []

    # Track parent outgoing totals for scaling and sink node creation
    # This ensures parents have correct visual height
    parent_outgoing_sum = {}  # parent_name -> sum of outgoing link values
    parent_link_indices = {}  # parent_name -> list of link indices (for scaling)

    # For each level (except the highest), create links to parent level
    for i in range(len(tax_levels) - 1, 0, -1):
        current_level = tax_levels[i]
        parent_level = tax_levels[i - 1]

        # Get nodes at this level that made it to the visualization
        # Sort by recalculated cumulative reads for consistency
        level_df = (
            tax_df[tax_df["rank"] == current_level]
            .sort_values("recalc_cumul", ascending=False)
            .head(max_taxa_per_level)
        )

        # Pre-extract data for faster iteration (avoid iterrows overhead)
        child_names_stripped = level_df["name"].str.strip().tolist()
        child_taxids = level_df["taxid"].tolist()
        child_cumuls = level_df["recalc_cumul"].tolist()

        for child_name_stripped, child_taxid, child_cumul in zip(
            child_names_stripped, child_taxids, child_cumuls
        ):
            child_key = f"{current_level}_{child_name_stripped}"
            if child_key not in node_ids:
                continue

            # Get child's cumulative value
            child_value = node_values.get(child_key, child_cumul)

            # Walk up the taxid parent chain to find the nearest ancestor
            # at the expected parent_level that is in the visualization.
            # This is order-independent and works correctly after aggregation.
            parent_found = False
            current_taxid = taxid_to_parent.get(int(child_taxid), 0)
            while current_taxid != 0:
                ancestor_key = taxid_to_key.get(current_taxid)
                if ancestor_key is not None:
                    ancestor_rank = ancestor_key.split("_", 1)[0]
                    if ancestor_rank == parent_level:
                        # Found the right rank - only link if it's in the visualization
                        if ancestor_key in node_ids:
                            parent_key = ancestor_key
                            link_idx = len(links)
                            links.append((node_ids[parent_key], node_ids[child_key]))
                            values.append(child_value)
                            parent_outgoing_sum[parent_key] = parent_outgoing_sum.get(parent_key, 0) + child_value
                            if parent_key not in parent_link_indices:
                                parent_link_indices[parent_key] = []
                            parent_link_indices[parent_key].append(link_idx)
                            parent_found = True
                        break  # Stop regardless - found the rank, whether visible or not
                    elif ancestor_rank in tax_levels and tax_levels.index(ancestor_rank) < tax_levels.index(parent_level):
                        # Reached a displayed rank above parent_level without finding parent
                        break
                current_taxid = taxid_to_parent.get(current_taxid, 0)

            # If no parent found, skip this child - do NOT fallback to an
            # unrelated parent, as that creates misleading taxonomic links
            # (e.g. linking Bacillus subtilis to Staphylococcus genus)
            if not parent_found:
                logging.debug(
                    f"Sankey: No parent at {parent_level} found for "
                    f"{child_name_stripped} ({current_level}) - skipping link"
                )

    # SCALING FIX: When children's cumul_reads sum exceeds parent's cumul_reads,
    # scale down the outgoing links proportionally to prevent parent appearing too large.
    # This happens because Plotly Sankey sizes nodes by sum of link values.
    scaled_parents = 0
    for parent_name, outgoing_sum in list(parent_outgoing_sum.items()):
        parent_value = node_values.get(parent_name, 0)
        if outgoing_sum > parent_value > 0:
            # Children sum exceeds parent - scale down proportionally
            scale_factor = parent_value / outgoing_sum
            link_indices = parent_link_indices.get(parent_name, [])
            for link_idx in link_indices:
                values[link_idx] = values[link_idx] * scale_factor
            # Update the outgoing sum after scaling
            parent_outgoing_sum[parent_name] = parent_value
            scaled_parents += 1
            logging.debug(f"Sankey: Scaled {parent_name} links by {scale_factor:.3f} "
                         f"(children sum {outgoing_sum} > parent value {parent_value})")

    if scaled_parents > 0:
        logging.debug(f"Sankey: Scaled down links for {scaled_parents} parents to prevent inflation")

    # Note: Sink nodes removed for fixed arrangement - they caused visual artifacts
    # when Plotly cannot auto-adjust positions. Parent node heights may not perfectly
    # match cumulative reads, but the layout is cleaner and more predictable.

    # Remove orphan nodes (no incoming or outgoing links) to avoid
    # disconnected floating nodes in the Sankey diagram
    connected_indices = set()
    for src, tgt in links:
        connected_indices.add(src)
        connected_indices.add(tgt)

    if connected_indices:
        # Build mapping from old index to new index
        old_to_new = {}
        new_nodes = []
        new_node_values = {}
        new_node_pcts = {}
        new_node_ranks = {}
        for old_idx, node_key in enumerate(nodes):
            if old_idx in connected_indices:
                new_idx = len(new_nodes)
                old_to_new[old_idx] = new_idx
                new_nodes.append(node_key)
                new_node_values[node_key] = node_values.get(node_key, 0)
                new_node_pcts[node_key] = node_pcts.get(node_key, 0)
                new_node_ranks[node_key] = node_ranks.get(node_key, "")

        removed = len(nodes) - len(new_nodes)
        if removed > 0:
            logging.debug(f"Sankey: Removed {removed} orphan nodes without links")
            # Remap link indices
            links = [(old_to_new[s], old_to_new[t]) for s, t in links]
            # Update node_ids for downstream Y-position calculation
            node_ids = {key: old_to_new[old_idx] for key, old_idx in node_ids.items()
                        if old_idx in old_to_new}
            nodes = new_nodes
            node_values = new_node_values
            node_pcts = new_node_pcts
            node_ranks = new_node_ranks

    # Create figure
    logging.debug(f"Sankey: Created {len(links)} links with values sum={sum(values) if values else 0}")

    if not links:
        logging.debug("Sankey: No links created, returning None")
        return None

    # Create node colors based on taxonomy level
    # Track which level each node belongs to
    node_colors = []
    nodes_per_level = {}

    # Count nodes per level from actual nodes list
    for level in tax_levels:
        nodes_per_level[level] = sum(1 for name in nodes if node_ranks.get(name) == level)

    # Assign colors to each node based on their rank
    for name in nodes:
        level = node_ranks.get(name, "")
        base_color = colors.get(level, "#3B82F6")
        node_colors.append(base_color)

    logging.debug(f"Sankey: Created {len(node_colors)} node colors for {len(nodes)} nodes")
    logging.debug(f"Sankey: First 3 node colors: {node_colors[:3]}")

    # Debug: Log actual link details
    source_indices = [link[0] for link in links]
    target_indices = [link[1] for link in links]
    logging.debug(f"Sankey: Source indices (first 5): {source_indices[:5]}")
    logging.debug(f"Sankey: Target indices (first 5): {target_indices[:5]}")
    logging.debug(f"Sankey: Values (first 5): {values[:5]}")
    logging.debug(f"Sankey: Max source idx: {max(source_indices)}, Max target idx: {max(target_indices)}, Num nodes: {len(nodes)}")

    # Create link colors with transparency scaled by read proportion
    # Color links based on TARGET node's color for visual flow continuity
    total_value = sum(values) if values else 1
    link_colors = []
    for i, link in enumerate(links):
        source_idx = link[0]
        target_idx = link[1]

        # Use target node color for visual continuity into the next level
        color_idx = target_idx if target_idx < len(node_colors) else source_idx
        base_color = node_colors[color_idx] if color_idx < len(node_colors) else "#3B82F6"

        # Scale opacity by proportion of total reads:
        # Major links (>5%) get higher opacity, minor links fade out
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

    # Create explicit X positions for nodes based on taxonomy level
    # Dynamically distribute levels across the available width so that
    # any subset of levels (e.g. P-C-O-F-G-S) uses the full chart width,
    # not just the canonical positions designed for all 8 levels.
    x_min = 0.001
    x_max = 0.85  # Leave 150px right margin for rightmost labels
    n_levels = len(tax_levels)
    level_to_x = {}
    if n_levels == 1:
        level_to_x[tax_levels[0]] = (x_min + x_max) / 2
    else:
        for i, level in enumerate(tax_levels):
            level_to_x[level] = x_min + (x_max - x_min) * i / (n_levels - 1)

    node_x = []
    for name in nodes:
        level = node_ranks.get(name, "")
        x_pos = level_to_x.get(level, 0.5)
        node_x.append(x_pos)

    # Build parent map for hierarchical Y positioning
    parent_map = build_parent_map(tax_df, domain_df, tax_levels, node_ids, max_taxa_per_level,
                                   taxid_to_parent=taxid_to_parent, taxid_to_key=taxid_to_key)
    logging.debug(f"Sankey: Built parent map with {len(parent_map)} entries")

    # Calculate hierarchical Y positions with proportional spacing based on read counts
    node_y = _calculate_hierarchical_y_positions(
        nodes, node_ids, tax_levels, nodes_per_level, parent_map, node_values, node_ranks
    )

    logging.debug(f"Sankey: Node X positions (first 5): {node_x[:5]}")
    logging.debug(f"Sankey: Node Y positions (first 5): {node_y[:5]}")
    logging.debug(f"Sankey: Total X positions: {len(node_x)}, Total Y positions: {len(node_y)}")

    # DIAGNOSTIC: Log all link data
    all_sources = [link[0] for link in links]
    all_targets = [link[1] for link in links]
    logging.debug(f"Sankey: ALL sources: {all_sources}")
    logging.debug(f"Sankey: ALL targets: {all_targets}")
    logging.debug(f"Sankey: ALL values: {values}")

    # Build custom data for hover: [reads, percentage, rank_name, full_name]
    # Scale padding nodes get empty labels and are hidden from hover
    rank_names = {"D": "Domain", "K": "Kingdom", "P": "Phylum", "C": "Class",
                  "O": "Order", "F": "Family", "G": "Genus", "S": "Species"}
    node_customdata = []
    node_labels = []  # Display labels (empty for scale nodes)

    MAX_LABEL_LEN = 30  # Truncate long names to reduce label overlap
    for node_key in nodes:
        # Extract plain display name from composite key (e.g., "P_Pseudomonadota" -> "Pseudomonadota")
        display_name = node_key.split("_", 1)[1] if "_" in node_key else node_key
        # Truncate long labels; full name is in hover tooltip via customdata[3]
        if len(display_name) > MAX_LABEL_LEN:
            node_labels.append(display_name[:MAX_LABEL_LEN - 1] + "...")
        else:
            node_labels.append(display_name)
        reads = node_values.get(node_key, 0)
        pct = node_pcts.get(node_key, 0)
        rank = node_ranks.get(node_key, "")
        rank_name = rank_names.get(rank, rank)
        node_customdata.append([reads, pct, rank_name, display_name])

    # Enforce minimum node visibility: nodes with < 0.5% of reads can be
    # nearly invisible, so set a floor on link values used for rendering
    max_value = max(values) if values else 1
    min_visible = max_value * 0.005  # 0.5% of largest link
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
                source=all_sources,
                target=all_targets,
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

    logging.debug(f"Sankey: Figure created successfully")

    # Calculate adaptive height based on number of nodes
    # Find the maximum number of nodes at any single level
    max_nodes_at_level = max(nodes_per_level.values()) if nodes_per_level else 5
    total_nodes = len(nodes)

    # Adaptive height calculation:
    # - Minimum 50px per node at the most crowded level
    # - Plus padding for title and margins
    # - Constrained between 600 and 2500 pixels
    MIN_HEIGHT = 600
    MAX_HEIGHT = 2500
    PIXELS_PER_NODE = 60  # Generous spacing per node

    adaptive_height = max(MIN_HEIGHT, min(MAX_HEIGHT, max_nodes_at_level * PIXELS_PER_NODE + 100))

    # Determine final height
    if chart_height == "auto" or chart_height is None:
        final_height = adaptive_height
        logging.debug(f"Sankey: Using adaptive height={final_height}px (max_nodes_at_level={max_nodes_at_level})")
    else:
        try:
            final_height = int(chart_height)
            logging.debug(f"Sankey: Using user-specified height={final_height}px")
        except (ValueError, TypeError):
            final_height = adaptive_height
            logging.debug(f"Sankey: Invalid height '{chart_height}', falling back to adaptive={final_height}px")

    # Build level legend for Sankey subtitle
    sankey_legend_items = []
    for level in tax_levels:
        color = colors.get(level, "#94A3B8")
        name = rank_names.get(level, level)
        sankey_legend_items.append(f"<span style='color:{color}'>&#9632;</span> {name}")
    sankey_legend_text = " (broad) " + "  ".join(sankey_legend_items) + " (specific)"

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


def create_sunburst_data(kraken_df, domains, tax_levels, min_reads, config, color_palette=None):
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

    Returns:
        A go.Figure with the styled Sunburst chart
    """
    # Ensure clean integer index to prevent duplicate-index issues with .loc[]
    kraken_df = kraken_df.reset_index(drop=True)

    # Sub-ranks (S1, S2, F3, etc.) are excluded by the tax_levels filter below.
    # No rank normalization needed — their cumulative reads are already counted
    # in the parent rank, so normalizing would double-count.

    # Use provided color palette or default
    palette = color_palette or TAXONOMY_COLORS
    # Use provided tax_levels or fallback to config
    if not tax_levels:
        tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "K", "P", "C", "O", "F", "G", "S"]
        )
        logging.debug(f"Sunburst: No tax_levels provided, using config: {tax_levels}")
    else:
        logging.debug(f"Sunburst: Using provided tax_levels: {tax_levels}")

    # Check available ranks BEFORE min_reads filtering
    available_ranks = kraken_df["rank"].unique().tolist()
    tax_levels = [level for level in tax_levels if level in available_ranks]

    logging.debug(f"Sunburst: Available ranks: {available_ranks}")
    logging.debug(f"Sunburst: Selected levels: {tax_levels}")

    # Filter by tax_levels, apply min_reads only to Species
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

    # CRITICAL FIX: Recalculate cumulative reads bottom-up to ensure parent >= children
    # This fixes issues when aggregating across multiple samples
    recalc_cumul = recalculate_cumulative_reads(kraken_df)

    # Add recalculated cumulative reads to filtered_df
    # Uses composite key f"{rank}_{name}" to match recalculate_cumulative_reads output
    filtered_df["recalc_cumul"] = (
        filtered_df["rank"] + "_" + filtered_df["name"].str.strip()
    ).map(recalc_cumul).fillna(0).astype(int)

    # Calculate total reads for percentage calculations (use recalculated root value)
    # Find the domain-level totals for proper percentage base
    first_level_df = filtered_df[filtered_df["rank"] == tax_levels[0]]
    total_reads = sum(
        recalc_cumul.get(f"{row['rank']}_{row['name'].strip()}", 0)
        for _, row in first_level_df.iterrows()
    ) if tax_levels else 1
    if total_reads == 0:
        total_reads = 1  # Avoid division by zero

    # Build sunburst data with proper hierarchy
    ids = []
    labels = []
    parents = []
    values = []
    colors = []
    ranks = []
    custom_data = []  # For enhanced hover

    # Track counts per level for color variation
    level_counts = {}
    level_positions = {}

    # First pass: count items per level
    for level in tax_levels:
        count = len(filtered_df[filtered_df["rank"] == level])
        level_counts[level] = count
        level_positions[level] = 0

    # Calculate sum of first-level reads for root value (use recalculated values)
    first_level = tax_levels[0] if tax_levels else "D"
    first_level_reads = filtered_df[filtered_df["rank"] == first_level]["recalc_cumul"].sum()

    logging.debug(f"Sunburst: First level '{first_level}' has {level_counts.get(first_level, 0)} items with total reads {first_level_reads}")

    # Add root node - don't add a value since we'll use branchvalues="remainder"
    # This avoids the parent >= sum(children) constraint issues
    ids.append("root")
    labels.append("All Taxa")
    parents.append("")
    values.append(0)  # With remainder mode, root doesn't need a value
    colors.append("#E5E7EB")  # Light gray for root
    ranks.append("Root")
    custom_data.append(["Root", first_level_reads, 100.0])

    # Track which IDs we've added to detect orphan parents
    added_ids = set(["root"])

    # Process each taxonomy level
    for level_idx, level in enumerate(tax_levels):
        # Sort by recalculated cumulative reads for proper hierarchy representation
        level_df = filtered_df[filtered_df["rank"] == level].sort_values(
            "recalc_cumul", ascending=False
        )

        logging.debug(f"Sunburst: Processing level {level} with {len(level_df)} items")

        # Pre-extract data for faster iteration (avoid iterrows overhead)
        taxon_names_full = level_df["name"].tolist()
        taxon_names_stripped = level_df["name"].str.strip().tolist()
        taxon_reads = level_df["recalc_cumul"].tolist()
        taxon_indices = level_df.index.tolist()

        for taxon_name_full, taxon, reads, row_idx in zip(
            taxon_names_full, taxon_names_stripped, taxon_reads, taxon_indices
        ):
            # Create unique ID to handle duplicate names across levels
            taxon_id = f"{level}_{taxon}"

            # Find parent using indentation-based hierarchy from Kraken format
            parent_id = "root"

            if level_idx > 0:
                # Get position in original dataframe
                row_indent = len(taxon_name_full) - len(taxon_name_full.lstrip())

                # Search backwards for parent
                for check_idx in range(row_idx - 1, -1, -1):
                    if check_idx not in filtered_df.index:
                        continue

                    check_row = filtered_df.loc[check_idx]
                    check_indent = len(check_row["name"]) - len(check_row["name"].lstrip())
                    check_rank = check_row["rank"]

                    # Parent has less indentation and is in our level list
                    if check_indent < row_indent and check_rank in tax_levels[:level_idx]:
                        check_name = check_row["name"].strip()
                        candidate_parent_id = f"{check_rank}_{check_name}"
                        # CRITICAL: Only use this parent if it's in our added_ids
                        if candidate_parent_id in added_ids:
                            parent_id = candidate_parent_id
                        break

            # Calculate percentage
            pct_of_total = (reads / total_reads * 100) if total_reads > 0 else 0

            # Get color with variation
            position = level_positions[level]
            color = get_level_color(level, position, level_counts[level], palette)
            level_positions[level] += 1

            # Add to lists
            ids.append(taxon_id)
            added_ids.add(taxon_id)
            labels.append(taxon)
            parents.append(parent_id)
            values.append(reads)
            colors.append(color)
            ranks.append(level)
            custom_data.append([RANK_NAMES.get(level, level), reads, pct_of_total])

    # Debug: Check for orphan parents (parents that don't exist in ids)
    all_parents = set(parents) - {""}  # Exclude root's empty parent
    orphan_parents = all_parents - added_ids
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


