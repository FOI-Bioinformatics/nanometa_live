"""
Classification tab callbacks for Nanometa Live v2.0.

This module combines Sankey and Sunburst visualizations into a single tab
with toggleable views, supporting both per-sample and aggregated analysis.
"""

import os
import logging
import pandas as pd
from typing import Optional

from dash import Dash, Input, Output, State, no_update, html
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px

from nanometa_live.core.utils.data_loaders import load_kraken_data
from nanometa_live.core.utils.sample_detector import get_available_samples
from nanometa_live.app.utils.callback_helpers import (
    validate_config_and_get_main_dir,
    log_callback_error,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage


def register_classification_callbacks(app: Dash):
    """
    Register callbacks for the unified Classification tab.

    Args:
        app: Dash application
    """

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
            'all': ['D', 'P', 'C', 'O', 'F', 'G', 'S'],
            'high': ['D', 'P', 'C'],
            'mid': ['P', 'C', 'O', 'F'],
            'detailed': ['F', 'G', 'S'],
            'species': ['O', 'F', 'G', 'S'],
            'custom': ['F', 'G', 'S']  # Default for custom
        }
        return presets.get(preset, ['F', 'G', 'S'])

    @app.callback(
        [
            Output("classification-plot", "figure"),
            Output("classification-info-message", "children"),
            Output("classification-plot", "style"),
        ],
        [
            Input("update-interval", "n_intervals"),
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
        n_intervals,
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
        # Style constants for showing/hiding the graph
        graph_visible = {"width": "100%"}
        graph_hidden = {"width": "100%", "display": "none"}

        # Empty state for when no data is available
        empty_state = EmptyStateMessage(
            title="No Classification Data",
            message="Classification results will appear here once analysis data is available",
            icon="bi-diagram-3"
        )

        # Helper to create a minimal empty figure (used when graph is hidden)
        def _empty_figure():
            fig = go.Figure()
            fig.update_layout(height=50, margin=dict(l=0, r=0, t=0, b=0))
            return fig

        # Validate config and get output directory using centralized helper
        main_dir = validate_config_and_get_main_dir(config)
        if not main_dir:
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
        all_tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "P", "C", "O", "F", "G", "S"]
        )
        if not tax_levels:
            tax_levels = config.get("default_hierarchy_letters", ["D", "C", "G", "S"])

        # Keep only valid taxonomy levels in correct order
        tax_levels = [level for level in all_tax_levels if level in tax_levels]

        try:
            # Load Kraken2 data (per-sample or aggregated)
            logging.debug(f"Loading Kraken data for sample='{selected_sample}' (type={type(selected_sample)})")
            kraken_df = load_kraken_data(main_dir, selected_sample)

            if kraken_df.empty:
                return _empty_figure(), empty_state, graph_hidden

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

    @app.callback(
        Output("classification-levels-container", "style"),
        Input("classification-view-type", "value"),
    )
    def toggle_levels_visibility(view_type):
        """
        Show taxonomy levels selector for both Sankey and Sunburst views.
        Both visualizations now support level filtering.
        """
        # Both views support taxonomy level selection
        return {"display": "block"}

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


def _recalculate_cumulative_reads(df):
    """
    Get cumulative reads from the Kraken2 cumul_reads column.

    The Kraken2 report format provides cumulative reads (column 2) which represents
    the total reads for a clade (this taxon + all descendants). This is the correct
    value to use for visualization.

    For single samples: cumul_reads is already correct from Kraken2.
    For aggregated samples: cumul_reads sum is an approximation.

    Args:
        df: DataFrame with Kraken2 data including 'name', 'cumul_reads' columns

    Returns:
        Dict mapping taxon name (stripped) to cumulative reads
    """
    if df.empty:
        return {}

    result = {}
    for idx in range(len(df)):
        row = df.iloc[idx]
        name = row["name"].strip()
        # Use cumul_reads (column 2) - the cumulative/clade reads
        # NOT reads (column 3) which is only direct assignments
        result[name] = row.get("cumul_reads", row.get("reads", 0))

    return result


def _build_parent_map(tax_df, domain_df, tax_levels, node_ids, top_filter):
    """
    Build a mapping of child node names to their parent node names.

    Uses indentation-based hierarchy from Kraken2 format to determine relationships.
    Only includes parents that are in the visualization (passed top_filter).

    Args:
        tax_df: DataFrame filtered to selected taxonomy levels
        domain_df: Full DataFrame including domain entries for hierarchy traversal
        tax_levels: List of taxonomy levels being displayed
        node_ids: Dict mapping node name -> node index
        top_filter: Number of top entities at each level

    Returns:
        Dict mapping child node name -> parent node name
    """
    parent_map = {}

    # Process from lowest level up to find parents
    for i in range(len(tax_levels) - 1, 0, -1):
        current_level = tax_levels[i]
        parent_level = tax_levels[i - 1]

        level_df = (
            tax_df[tax_df["rank"] == current_level]
            .sort_values("recalc_cumul", ascending=False)
            .head(top_filter)
        )

        # Pre-extract data for faster iteration (avoid iterrows overhead)
        child_names_stripped = level_df["name"].str.strip().tolist()
        child_names_full = level_df["name"].tolist()
        child_indices = level_df.index.tolist()

        for child_name, child_name_full, child_idx in zip(
            child_names_stripped, child_names_full, child_indices
        ):
            if child_name not in node_ids:
                continue

            child_indent = len(child_name_full) - len(child_name_full.lstrip())

            # Search backwards through the dataframe for parent
            for check_idx in range(child_idx - 1, -1, -1):
                if check_idx not in domain_df.index:
                    continue

                check_row = domain_df.loc[check_idx]
                check_rank = check_row["rank"]
                check_name_full = check_row["name"]
                check_indent = len(check_name_full) - len(check_name_full.lstrip())
                check_name = check_name_full.strip()

                # Found a row with less indentation
                if check_indent < child_indent:
                    if check_rank == parent_level and check_name in node_ids:
                        parent_map[child_name] = check_name
                        break
                    elif check_rank in tax_levels and tax_levels.index(check_rank) < tax_levels.index(parent_level):
                        # Hit a higher level without finding parent at expected level
                        break

    return parent_map


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
    MIN_FRACTION = 0.01  # 1% minimum per node

    def calculate_proportional_positions(node_list, start_y, end_y):
        """
        Calculate Y positions for nodes proportional to their values.

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
            text="No taxonomic classification data available for this sample.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # CRITICAL FIX: Find which tax levels actually exist in the data
    available_ranks = kraken_df["rank"].unique().tolist()
    # Filter tax_levels to only those actually present in data
    tax_levels = [level for level in tax_levels if level in available_ranks]

    logging.debug(f"Sankey: Available ranks in data: {available_ranks}")
    logging.debug(f"Sankey: Using tax_levels: {tax_levels}")

    # If no valid tax levels after filtering, return informative message
    if not tax_levels:
        logging.debug("Sankey: No matching tax levels found in data")
        fig = go.Figure()
        fig.add_annotation(
            text=f"No matching taxonomy ranks found in data.<br>Available ranks: {', '.join(available_ranks)}<br>Try adjusting filter settings.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # Sankey requires at least 2 levels to show parent-child relationships
    if len(tax_levels) < 2:
        logging.debug(f"Sankey: Need at least 2 taxonomy levels, only have {len(tax_levels)}: {tax_levels}")
        rank_names = {"D": "Domain", "P": "Phylum", "C": "Class", "O": "Order", "F": "Family", "G": "Genus", "S": "Species"}
        available_names = [rank_names.get(r, r) for r in available_ranks]
        fig = go.Figure()
        fig.add_annotation(
            text=f"Sankey diagram requires at least 2 taxonomy levels.<br>Currently available: {', '.join(available_names)}<br>Try switching to Sunburst view or adjust taxonomy filters.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#6B7280"),
        )
        fig.update_layout(**_info_layout)
        return fig

    # CRITICAL FIX: Recalculate cumulative reads on FULL dataframe BEFORE filtering
    # This ensures the complete taxonomy hierarchy is used for parent-child relationships
    # Must be done before domain filtering to preserve correct hierarchy
    recalc_cumul = _recalculate_cumulative_reads(kraken_df)

    # Calculate total reads for percentage calculation
    total_reads = sum(recalc_cumul.values())
    if total_reads == 0:
        total_reads = 1

    # Filter by domains
    domain_indices = []
    for domain in domains:
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]
        if not domain_rows.empty:
            start_idx = domain_rows.index[0]

            # Find next domain index
            sliced_df = kraken_df.iloc[start_idx + 1:]
            next_domains = sliced_df[sliced_df["name"].str.strip().isin(domains)]
            if not next_domains.empty:
                end_idx = next_domains.index[0]
            else:
                end_idx = len(kraken_df)

            domain_indices.extend(range(start_idx, end_idx))

    # Filter dataframe by domains
    domain_df = kraken_df.iloc[domain_indices].copy()

    # Add recalculated cumulative reads to domain_df for sorting and link values
    domain_df["recalc_cumul"] = domain_df["name"].apply(
        lambda x: recalc_cumul.get(x.strip(), 0)
    )

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
    # Plotly's "freeform" arrangement uses this ordering to position nodes correctly
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
            node_ids[name] = node_id
            nodes.append(name)
            # Store recalculated cumulative value and percentage for this node
            node_values[name] = cumul_val
            node_pcts[name] = pct_val
            node_ranks[name] = level
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

    # CRITICAL FIX: Use indentation to find parent-child relationships
    # Kraken2 reports use leading spaces to indicate hierarchy depth

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
        child_names_full = level_df["name"].tolist()
        child_names_stripped = level_df["name"].str.strip().tolist()
        child_cumuls = level_df["recalc_cumul"].tolist()
        child_indices = level_df.index.tolist()

        for child_name_full, child_name_stripped, child_cumul, child_idx in zip(
            child_names_full, child_names_stripped, child_cumuls, child_indices
        ):
            if child_name_stripped not in node_ids:
                continue

            # Get child's recalculated cumulative value
            child_value = node_values.get(child_name_stripped, child_cumul)

            # Get child's indentation level (number of leading spaces)
            child_indent = len(child_name_full) - len(child_name_full.lstrip())

            # Find parent: nearest entry ABOVE child with less indentation and parent rank
            parent_found = False

            # Search backwards from child's position in original dataframe
            for check_idx in range(child_idx - 1, -1, -1):
                if check_idx not in domain_df.index:
                    continue

                check_row = domain_df.loc[check_idx]
                check_rank = check_row["rank"]
                check_name_full = check_row["name"]
                check_indent = len(check_name_full) - len(check_name_full.lstrip())
                check_name_stripped = check_name_full.strip()

                # Parent must have less indentation (shallower level)
                if check_indent < child_indent:
                    # Is this the parent rank we're looking for?
                    if check_rank == parent_level:
                        # Is this parent in our visualization (passed max_taxa_per_level)?
                        if check_name_stripped in node_ids:
                            link_idx = len(links)
                            links.append((node_ids[check_name_stripped], node_ids[child_name_stripped]))
                            values.append(child_value)  # Use recalculated cumulative reads
                            # Track parent's outgoing and link indices for scaling
                            parent_outgoing_sum[check_name_stripped] = parent_outgoing_sum.get(check_name_stripped, 0) + child_value
                            if check_name_stripped not in parent_link_indices:
                                parent_link_indices[check_name_stripped] = []
                            parent_link_indices[check_name_stripped].append(link_idx)
                            parent_found = True
                            break
                    # Stop if we've gone too far up the hierarchy
                    elif check_rank in tax_levels and tax_levels.index(check_rank) < tax_levels.index(parent_level):
                        break

            # If still no parent found, link to first available parent at that level
            if not parent_found:
                parent_options = tax_df[tax_df["rank"] == parent_level].sort_values("recalc_cumul", ascending=False).head(max_taxa_per_level)
                if not parent_options.empty:
                    fallback_parent = parent_options.iloc[0]["name"].strip()
                    if fallback_parent in node_ids:
                        link_idx = len(links)
                        links.append((node_ids[fallback_parent], node_ids[child_name_stripped]))
                        values.append(child_value)  # Use recalculated cumulative reads
                        # Track parent's outgoing and link indices for scaling
                        parent_outgoing_sum[fallback_parent] = parent_outgoing_sum.get(fallback_parent, 0) + child_value
                        if fallback_parent not in parent_link_indices:
                            parent_link_indices[fallback_parent] = []
                        parent_link_indices[fallback_parent].append(link_idx)

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

    # Create invisible sink nodes to capture unaccounted reads
    # This ensures parent nodes have correct visual height (outgoing = cumulative reads)
    # Without this, filtered children cause parents to appear smaller than they should

    # Step 1: Create one invisible sink node per child level (not first level)
    sink_nodes = {}  # level -> sink_node_name
    for level_idx in range(1, len(tax_levels)):
        level = tax_levels[level_idx]
        sink_name = f"__sink_{level}"
        sink_id = len(nodes)
        nodes.append(sink_name)
        node_ids[sink_name] = sink_id
        node_values[sink_name] = 0  # Will accumulate unaccounted reads
        node_pcts[sink_name] = 0
        node_ranks[sink_name] = level
        sink_nodes[level] = sink_name

    # Step 2: For each parent, add invisible link for unaccounted reads
    sink_links_added = 0
    for parent_name, outgoing_sum in parent_outgoing_sum.items():
        parent_value = node_values.get(parent_name, 0)
        unaccounted = parent_value - outgoing_sum

        if unaccounted > 0:
            # Find the child level for this parent
            parent_level = node_ranks.get(parent_name)
            if parent_level in tax_levels:
                parent_level_idx = tax_levels.index(parent_level)
                if parent_level_idx + 1 < len(tax_levels):
                    child_level = tax_levels[parent_level_idx + 1]
                    sink_name = sink_nodes.get(child_level)

                    if sink_name and sink_name in node_ids:
                        # Add invisible link from parent to sink
                        links.append((node_ids[parent_name], node_ids[sink_name]))
                        values.append(unaccounted)
                        node_values[sink_name] += unaccounted
                        sink_links_added += 1

    logging.debug(f"Sankey: Added {len(sink_nodes)} invisible sink nodes, {sink_links_added} sink links")

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
    # Sink nodes are invisible (capture unaccounted reads from filtered children)
    for name in nodes:
        if name.startswith("__sink_"):
            # Invisible sink node - ensures parent heights are correct
            node_colors.append("rgba(0,0,0,0)")
        else:
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

    # Create link colors with transparency (rgba)
    # Color links based on source node's color
    # Links TO sink nodes are invisible (they carry unaccounted reads)
    link_colors = []
    for link in links:
        source_idx = link[0]
        target_idx = link[1]
        target_name = nodes[target_idx] if target_idx < len(nodes) else ""

        # Links to sink nodes are invisible (carry unaccounted reads)
        if target_name.startswith("__sink_"):
            link_colors.append("rgba(0,0,0,0)")
        elif source_idx < len(node_colors):
            source_color = node_colors[source_idx]
            # Handle both hex and rgba colors
            if source_color.startswith("rgba"):
                link_colors.append(source_color)
            else:
                # Convert hex to rgba with transparency
                hex_color = source_color.lstrip("#")
                r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                link_colors.append(f"rgba({r},{g},{b},0.4)")
        else:
            link_colors.append("rgba(150,150,150,0.3)")

    # Create explicit X positions for nodes based on taxonomy level
    # This ensures proper column positioning in the Sankey diagram
    # Nodes span 0.001-0.85 with 150px right margin for rightmost labels
    # Iterate through nodes list directly to handle "Other" nodes correctly
    node_x = []
    level_to_x = {}
    for level_idx, level in enumerate(tax_levels):
        # Calculate X position for each level
        # Nodes span 0.001-0.85, leaving right space for label text
        # (custom.js repositions rightmost-column labels to the right of nodes)
        x_pos = 0.001 + (level_idx / max(len(tax_levels) - 1, 1)) * 0.849
        level_to_x[level] = x_pos

    for name in nodes:
        if name.startswith("__sink_"):
            # Sink nodes keep same x as their parent level
            level = name.replace("__sink_", "")
            x_pos = level_to_x.get(level, 0.5)
            node_x.append(x_pos)
        else:
            level = node_ranks.get(name, "")
            x_pos = level_to_x.get(level, 0.5)
            node_x.append(x_pos)

    # Build parent map for hierarchical Y positioning
    parent_map = _build_parent_map(tax_df, domain_df, tax_levels, node_ids, max_taxa_per_level)
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

    # Build custom data for hover: [reads, percentage, rank_name]
    # Scale padding nodes get empty labels and are hidden from hover
    rank_names = {"D": "Domain", "P": "Phylum", "C": "Class", "O": "Order",
                  "F": "Family", "G": "Genus", "S": "Species"}
    node_customdata = []
    node_labels = []  # Display labels (empty for scale nodes)

    for name in nodes:
        if name.startswith("__sink_"):
            # Sink nodes: hidden labels, no hover data
            node_labels.append("")
            node_customdata.append([0, 0, ""])
        else:
            node_labels.append(name)
            reads = node_values.get(name, 0)
            pct = node_pcts.get(name, 0)
            rank = node_ranks.get(name, "")
            rank_name = rank_names.get(rank, rank)
            node_customdata.append([reads, pct, rank_name])

    # Position scale padding nodes at the very bottom (Y near 0.999)
    for i, name in enumerate(nodes):
        if name.startswith("__sink_"):
            node_y[i] = 0.999

    # Create the Sankey figure with enhanced hover information
    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            textfont=dict(size=11, color="#1F2937", family="Arial, sans-serif"),
            domain=dict(
                x=[0.0, 1.0],
                y=[0.02, 0.98]
            ),
            node=dict(
                pad=25,
                thickness=20,
                label=node_labels,
                color=node_colors,
                customdata=node_customdata,
                line=dict(color="#E5E7EB", width=0.5),
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "<span style='color:#6B7280'>%{customdata[2]}</span><br>"
                    "Reads: <b>%{customdata[0]:,.0f}</b><br>"
                    "Proportion: <b>%{customdata[1]:.2f}%</b>"
                    "<extra></extra>"
                ),
            ),
            link=dict(
                source=all_sources,
                target=all_targets,
                value=values,
                color=link_colors,
                hovertemplate=(
                    "<b>%{source.label}</b> &rarr; <b>%{target.label}</b><br>"
                    "Reads: %{value:,.0f}"
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
    sankey_legend_text = "  ".join(sankey_legend_items)

    # Layout with dynamic height and balanced margins for labels
    figure.update_layout(
        height=final_height,
        title=dict(
            text="<b>Taxonomic Classification Flow</b>",
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

    return figure


# ============================================================================
# Sunburst Visualization Functions
# ============================================================================

# =============================================================================
# Color Scheme Definitions - Multiple palettes for user selection
# =============================================================================

# Tableau 10 - Scientific publication standard, colorblind-friendly
COLORS_TABLEAU = {
    "D": "#4E79A7",  # Domain - Steel blue
    "P": "#F28E2B",  # Phylum - Warm orange
    "C": "#E15759",  # Class - Soft red
    "O": "#76B7B2",  # Order - Teal
    "F": "#59A14F",  # Family - Forest green
    "G": "#EDC948",  # Genus - Gold/yellow
    "S": "#B07AA1",  # Species - Muted purple
}

# Viridis-inspired - Perceptually uniform, excellent for colorblind users
COLORS_VIRIDIS = {
    "D": "#440154",  # Domain - Deep purple
    "P": "#414487",  # Phylum - Indigo
    "C": "#2A788E",  # Class - Blue-teal
    "O": "#22A884",  # Order - Teal-green
    "F": "#7AD151",  # Family - Yellow-green
    "G": "#BDDF26",  # Genus - Lime
    "S": "#FDE725",  # Species - Yellow
}

# ColorBrewer Set2 - Pastel, softer colors for presentations
COLORS_PASTEL = {
    "D": "#66C2A5",  # Domain - Mint
    "P": "#FC8D62",  # Phylum - Salmon
    "C": "#8DA0CB",  # Class - Periwinkle
    "O": "#E78AC3",  # Order - Pink
    "F": "#A6D854",  # Family - Lime green
    "G": "#FFD92F",  # Genus - Yellow
    "S": "#E5C494",  # Species - Tan
}

# ColorBrewer Dark2 - High contrast for projectors/posters
COLORS_DARK = {
    "D": "#1B9E77",  # Domain - Teal
    "P": "#D95F02",  # Phylum - Orange
    "C": "#7570B3",  # Class - Purple
    "O": "#E7298A",  # Order - Magenta
    "F": "#66A61E",  # Family - Green
    "G": "#E6AB02",  # Genus - Gold
    "S": "#A6761D",  # Species - Brown
}

# Nature-inspired - Earthy tones for ecological studies
COLORS_NATURE = {
    "D": "#2D4739",  # Domain - Dark forest
    "P": "#5A8A5C",  # Phylum - Forest green
    "C": "#8CB369",  # Class - Sage
    "O": "#E9C46A",  # Order - Sandy
    "F": "#F4A261",  # Family - Terracotta
    "G": "#E76F51",  # Genus - Coral
    "S": "#264653",  # Species - Deep teal
}

# Ocean - Cool blues for marine studies
COLORS_OCEAN = {
    "D": "#03045E",  # Domain - Navy
    "P": "#023E8A",  # Phylum - Dark blue
    "C": "#0077B6",  # Class - Medium blue
    "O": "#0096C7",  # Order - Bright blue
    "F": "#00B4D8",  # Family - Light blue
    "G": "#48CAE4",  # Genus - Sky blue
    "S": "#90E0EF",  # Species - Pale blue
}

# Available color schemes (simplified to 3 essential options)
COLOR_SCHEMES = {
    "viridis": COLORS_VIRIDIS,
    "tableau": COLORS_TABLEAU,
    "dark": COLORS_DARK,
}

# Default color scheme
TAXONOMY_COLORS = COLORS_TABLEAU

# Full names for taxonomy levels
RANK_NAMES = {
    "D": "Domain",
    "P": "Phylum",
    "C": "Class",
    "O": "Order",
    "F": "Family",
    "G": "Genus",
    "S": "Species",
    "R": "Root",
    "R1": "Superkingdom",
    "U": "Unclassified",
}


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


def _get_level_color(rank, depth_in_level=0, total_in_level=1, color_palette=None):
    """
    Get color for a taxonomy level with brightness variation.

    Args:
        rank: Taxonomy rank code (D, P, C, O, F, G, S)
        depth_in_level: Position of this item within its level (for variation)
        total_in_level: Total items at this level
        color_palette: Optional color palette dictionary (defaults to TAXONOMY_COLORS)

    Returns:
        RGBA color string
    """
    colors = color_palette or TAXONOMY_COLORS
    base_color = colors.get(rank, "#94A3B8")

    # Convert hex to RGB
    hex_color = base_color.lstrip("#")
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    # Add subtle brightness variation within each level
    if total_in_level > 1:
        variation = 0.15 * (depth_in_level / max(1, total_in_level - 1)) - 0.075
        r = min(255, max(0, int(r * (1 + variation))))
        g = min(255, max(0, int(g * (1 + variation))))
        b = min(255, max(0, int(b * (1 + variation))))

    return f"rgb({r},{g},{b})"


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

    # Use provided color palette or default
    palette = color_palette or TAXONOMY_COLORS
    # Use provided tax_levels or fallback to config
    if not tax_levels:
        tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "P", "C", "O", "F", "G", "S"]
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
    recalc_cumul = _recalculate_cumulative_reads(kraken_df)

    # Add recalculated cumulative reads to filtered_df
    filtered_df["recalc_cumul"] = filtered_df["name"].apply(
        lambda x: recalc_cumul.get(x.strip(), 0)
    )

    # Calculate total reads for percentage calculations (use recalculated root value)
    # Find the domain-level totals for proper percentage base
    total_reads = sum(
        recalc_cumul.get(name.strip(), 0)
        for name in filtered_df[filtered_df["rank"] == tax_levels[0]]["name"]
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
            color = _get_level_color(level, position, level_counts[level], palette)
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
            "<span style='color:#9CA3AF'>%{customdata[0]}</span><br>"
            "Reads: <b>%{customdata[1]:,.0f}</b><br>"
            "Of total: <b>%{customdata[2]:.1f}%</b><br>"
            "Of parent: <b>%{percentParent:.1%}</b>"
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
            text="<b>Taxonomic Classification</b>",
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
                text=f"<b>Taxonomy Levels:</b> {legend_text}",
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
    return fig


def filter_by_domains(kraken_df, domains):
    """
    Filter Kraken report by domains using indentation-based hierarchy.

    CRITICAL: Uses leading spaces (indentation) to determine parent-child relationships.
    Works correctly even when dataframe indices are non-sequential (after aggregation).

    Args:
        kraken_df: DataFrame containing Kraken report with 'name' column
        domains: List of domain names to include (e.g., ['Bacteria', 'Archaea'])

    Returns:
        DataFrame containing selected domains and all their descendants
    """
    import logging

    if kraken_df.empty or not domains:
        return pd.DataFrame()

    selected_indices = []

    for domain in domains:
        # Find domain row (exact match, case-sensitive, stripped)
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]

        if domain_rows.empty:
            logging.debug(f"Domain '{domain}' not found in Kraken data")
            continue

        # Get domain row index (first occurrence)
        domain_idx = domain_rows.index[0]
        domain_name_full = kraken_df.loc[domain_idx, "name"]
        domain_indent = len(domain_name_full) - len(domain_name_full.lstrip())

        # Add domain itself
        selected_indices.append(domain_idx)

        # Find all descendants (rows with greater indentation that come after this domain)
        # Stop when we hit another domain at same indentation level OR end of dataframe
        current_pos = list(kraken_df.index).index(domain_idx)

        for next_pos in range(current_pos + 1, len(kraken_df)):
            next_idx = kraken_df.index[next_pos]
            next_row = kraken_df.loc[next_idx]
            next_name_full = next_row["name"]
            next_indent = len(next_name_full) - len(next_name_full.lstrip())

            # If indentation is less than or equal to domain (same or shallower level),
            # we've left this domain's subtree
            if next_indent <= domain_indent:
                # Check if this is another selected domain
                if next_row["name"].strip() not in domains:
                    # Not a selected domain, and we're back at domain level - stop
                    break
                else:
                    # This is another selected domain - don't include it here
                    # (it will be added in its own iteration)
                    break
            else:
                # This is a descendant (greater indentation) - include it
                selected_indices.append(next_idx)

    # Remove duplicates while preserving order
    seen = set()
    unique_indices = []
    for idx in selected_indices:
        if idx not in seen:
            seen.add(idx)
            unique_indices.append(idx)

    # Return filtered dataframe in original order
    if not unique_indices:
        return pd.DataFrame()

    return kraken_df.loc[unique_indices].copy()
