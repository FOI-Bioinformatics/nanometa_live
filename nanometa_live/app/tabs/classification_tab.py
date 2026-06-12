"""
Classification tab callbacks for Nanometa Live v2.0.

This module combines Sankey and Sunburst visualizations into a single tab
with toggleable views, supporting both per-sample and aggregated analysis.
"""

import os
import logging

from dash import Dash, Input, Output, State, no_update, html, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.app.utils.callback_helpers import (
    validate_config_and_get_main_dir,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.app.utils.debounce import (
    interval_tick_is_redundant,
    mark_rendered,
)
from nanometa_live.app.tabs.kraken2_helpers import (
    COLORS_TABLEAU,
    COLOR_SCHEMES,
    load_kraken2_taxonomy,
    apply_authoritative_taxonomy,
)
from nanometa_live.app.tabs.classification_helpers import (
    create_placeholder_sankey,
    create_sankey_data,
    create_empty_sunburst,
    create_sunburst_data,
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
            Input("update-interval", "n_intervals"),  # Polling backstop
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
        _n_intervals,     # Polling backstop
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
        if interval_tick_is_redundant(ctx, "classification_plot", _fingerprint):
            raise PreventUpdate
        mark_rendered("classification_plot", _fingerprint)

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
                figure = create_sunburst_data(kraken_df, domains, tax_levels, filter_value, config, color_palette, max_taxa_per_level=max_taxa)
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
            logging.warning(f"Failed to export classification plot: {e}", exc_info=True)
            return {
                "title": "Export Failed",
                "message": f"Failed to export plot: {str(e)}",
                "color": "danger",
            }

    # Note: Sankey label repositioning is handled by a MutationObserver
    # in assets/custom.js (workaround for plotly.js#7445).

