"""
Validation tab callbacks for Nanometa Live v2.1.

This module contains callbacks for the BLAST/minimap2 validation results tab,
including data loading, filtering, visualization, and export functionality.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from dash import Dash, Input, Output, State, callback, ctx, no_update, html, ALL
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from nanometa_live.core.parsers.blast_validation_parser import (
    BlastValidationParser,
    ValidationResult,
    ValidationStatus,
    generate_mock_validation_data,
)
from nanometa_live.core.parsers.paf_coverage_parser import (
    parse_paf_coverage,
    CoverageData,
)
from nanometa_live.app.layouts.validation_layout import (
    create_validation_status_card,
    create_validation_result_card,
)
from nanometa_live.app.components.coverage_plots import (
    create_coverage_depth_figure,
    create_cumulative_coverage_figure,
    create_depth_histogram_figure,
    create_coverage_stats_summary,
    create_empty_coverage_figure,
)
from nanometa_live.app.utils.callback_helpers import log_callback_error

logger = logging.getLogger(__name__)


def register_validation_callbacks(app: Dash):
    """
    Register callbacks for the validation results tab.

    Args:
        app: Dash application instance
    """

    @app.callback(
        Output("validation-data-store", "data"),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def load_validation_data(n_intervals, config):
        """
        Load validation data from results directory.

        Validation results are produced by nanometanf VALIDATION subworkflow
        and written to {results_dir}/validation/validation_results.json
        """
        try:
            if not config:
                return {"results": [], "summary": {}, "message": "No configuration loaded"}

            # Check if validation is enabled
            if not config.get("blast_validation", False):
                return {
                    "results": [],
                    "summary": {},
                    "message": "Validation is disabled. Enable it in Configuration tab."
                }

            # Get results directory (prefer results_output_directory, fall back to main_dir)
            results_dir = config.get("results_output_directory") or config.get("main_dir", "")
            if not results_dir or not os.path.isdir(results_dir):
                return {
                    "results": [],
                    "summary": {},
                    "message": "Results directory not found"
                }

            # Try to parse real validation results
            parser = BlastValidationParser(results_dir)
            if not parser.has_validation_data():
                return {
                    "results": [],
                    "summary": {},
                    "message": "Waiting for validation results from pipeline..."
                }

            results = parser.get_validation_results()
            summary = parser.get_validation_summary()

            logger.info(f"Loaded {len(results)} validation results from {results_dir}")

            return {
                "results": [r.to_dict() for r in results],
                "summary": summary,
                "message": None
            }

        except Exception as e:
            log_callback_error("load_validation_data", e)
            return {"results": [], "summary": {}, "message": f"Error loading data: {e}"}

    @app.callback(
        [
            Output("validation-status-alert", "style"),
            Output("validation-summary-container", "children"),
        ],
        Input("validation-data-store", "data"),
    )
    def update_validation_summary(data):
        """
        Update the validation summary card based on loaded data.
        """
        if not data or not data.get("results"):
            # Show message explaining why no data is available
            message = data.get("message", "No validation data available") if data else "No data"

            alert_content = dbc.Alert([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(message),
                html.Br(),
                html.Small(
                    "Enable validation in Configuration, download genomes in Watchlist, then run the pipeline.",
                    className="text-muted"
                )
            ], color="info", className="text-center")

            return {"display": "block"}, alert_content

        # Hide default alert, show summary
        summary = data.get("summary", {})
        summary_card = create_validation_status_card(
            confirmed=summary.get("confirmed", 0),
            partial=summary.get("partial", 0),
            low_confidence=summary.get("low_confidence", 0),
            no_data=summary.get("no_data", 0),
            total=summary.get("total_species", 0),
        )

        return {"display": "none"}, summary_card

    @app.callback(
        Output("validation-results-container", "children"),
        [
            Input("validation-data-store", "data"),
            Input("validation-status-filter", "value"),
            Input("validation-method-filter", "value"),
            Input("validation-sort-by", "value"),
        ],
    )
    def update_validation_cards(data, status_filter, method_filter, sort_by):
        """
        Update the validation result cards based on data and filters.
        """
        if not data or not data.get("results"):
            message = data.get("message", "No validation data available") if data else "No data"
            return dbc.Alert([
                html.I(className="bi bi-hourglass-split me-2"),
                html.Span(message)
            ], color="light", className="text-center")

        results = data["results"]

        # Apply status filter
        if status_filter and status_filter != "all":
            results = [r for r in results if r.get("status") == status_filter]

        # Apply method filter
        if method_filter and method_filter != "all":
            results = [r for r in results if r.get("validation_method") == method_filter]

        if not results:
            return dbc.Alert(
                f"No results match the filter: {status_filter}",
                color="info",
                className="text-center"
            )

        # Sort results
        sort_key = sort_by or "percent_validated"
        reverse = sort_key != "species"  # Descending for numeric, ascending for name
        try:
            results = sorted(
                results,
                key=lambda x: x.get(sort_key, 0) if sort_key != "species" else x.get("species", ""),
                reverse=reverse
            )
        except Exception:
            pass

        # Create cards
        cards = []
        for result in results:
            card = create_validation_result_card(
                species=result.get("species", "Unknown"),
                taxid=result.get("taxid", 0),
                status=result.get("status", "no_data"),
                percent_validated=result.get("percent_validated", 0),
                percent_identity=result.get("percent_identity_mean", 0),
                total_reads=result.get("total_reads", 0),
                validated_reads=result.get("validated_reads", 0),
                coverage=result.get("coverage_breadth", 0),
                sample_id=result.get("sample_id", ""),
                validation_method=result.get("validation_method", "blast"),
                avg_mapq=result.get("avg_mapq", 0.0),
            )
            cards.append(card)

        return html.Div(cards)

    @app.callback(
        Output("validation-details-table", "data"),
        Input("validation-data-store", "data"),
    )
    def update_validation_table(data):
        """
        Update the detailed validation table.
        """
        if not data or not data.get("results"):
            return []

        # Convert to table format
        table_data = []
        for result in data["results"]:
            table_data.append({
                "species": result.get("species", "Unknown"),
                "sample_id": result.get("sample_id", ""),
                "total_reads": result.get("total_reads", 0),
                "validated_reads": result.get("validated_reads", 0),
                "percent_validated": round(result.get("percent_validated", 0), 1),
                "percent_identity_mean": round(result.get("percent_identity_mean", 0), 1),
                "coverage_breadth": round(result.get("coverage_breadth", 0) * 100, 1),
                "validation_method": result.get("validation_method", "blast"),
                "avg_mapq": round(result.get("avg_mapq", 0), 1),
                "status": result.get("status", "no_data"),
            })

        return table_data

    @app.callback(
        Output("validation-identity-plot", "figure"),
        Input("validation-data-store", "data"),
    )
    def update_identity_plot(data):
        """
        Create the identity distribution plot.
        """
        if not data or not data.get("results"):
            return _create_empty_identity_plot()

        results = data["results"]

        # Build data for box plot
        species_names = []
        identity_means = []
        identity_mins = []
        identity_maxs = []
        statuses = []
        methods = []

        for result in results:
            if result.get("percent_identity_mean", 0) > 0:
                species_names.append(result.get("species", "Unknown")[:30])
                identity_means.append(result.get("percent_identity_mean", 0))
                identity_mins.append(result.get("percent_identity_min", 0))
                identity_maxs.append(result.get("percent_identity_max", 0))
                statuses.append(result.get("status", "no_data"))
                methods.append(result.get("validation_method", "blast"))

        if not species_names:
            return _create_empty_identity_plot()

        # Create color map based on method
        method_color_map = {
            "blast": "#fd7e14",    # orange
            "minimap2": "#0d6efd", # blue
        }
        colors = [method_color_map.get(m, "#6c757d") for m in methods]

        # Create bar chart with error bars showing identity range
        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=species_names,
            y=identity_means,
            error_y=dict(
                type='data',
                symmetric=False,
                array=[max_val - mean for mean, max_val in zip(identity_means, identity_maxs)],
                arrayminus=[mean - min_val for mean, min_val in zip(identity_means, identity_mins)],
            ),
            marker_color=colors,
            text=[f"{v:.1f}%" for v in identity_means],
            textposition='outside',
            hovertemplate="<b>%{x}</b><br>Mean: %{y:.1f}%<br>Range: %{customdata[0]:.1f}% - %{customdata[1]:.1f}%<extra></extra>",
            customdata=list(zip(identity_mins, identity_maxs)),
        ))

        fig.update_layout(
            title="Sequence Identity by Species",
            xaxis_title="Species",
            yaxis_title="Identity (%)",
            yaxis_range=[0, 105],
            showlegend=False,
            template="plotly_white",
            margin=dict(l=50, r=50, t=60, b=100),
        )

        # Add threshold line at 90%
        fig.add_hline(
            y=90,
            line_dash="dash",
            line_color="green",
            annotation_text="90% threshold",
            annotation_position="top right"
        )

        return fig

    @app.callback(
        Output("download-validation-report", "data"),
        Input("export-validation-report", "n_clicks"),
        [State("validation-data-store", "data"), State("app-config", "data")],
        prevent_initial_call=True,
    )
    def export_validation_report(n_clicks, data, config):
        """
        Export validation results to CSV/JSON.
        """
        if not n_clicks or not data or not data.get("results"):
            return no_update

        try:
            # Create DataFrame from results
            df = pd.DataFrame(data["results"])

            # Generate filename
            analysis_name = config.get("analysis_name", "analysis") if config else "analysis"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"validation_report_{analysis_name}_{timestamp}.csv"

            # Return as download
            return dict(
                content=df.to_csv(index=False),
                filename=filename,
                type="text/csv"
            )

        except Exception as e:
            log_callback_error("export_validation_report", e)
            return no_update

    # --- Coverage callbacks ---

    @app.callback(
        [
            Output("coverage-species-selector", "options"),
            Output("coverage-species-selector", "value"),
        ],
        Input("validation-data-store", "data"),
    )
    def populate_coverage_selector(data):
        """Populate species selector from minimap2 validation results."""
        if not data or not data.get("results"):
            return [], None

        options = []
        seen = set()
        for r in data["results"]:
            method = r.get("validation_method", "blast")
            if method not in ("minimap2", "both"):
                continue
            key = f"{r.get('sample_id', '')}_{r.get('taxid', '')}"
            if key in seen:
                continue
            seen.add(key)
            label = f"{r.get('species', 'Unknown')} ({r.get('sample_id', '')})"
            options.append({"label": label, "value": key})

        first_value = options[0]["value"] if options else None
        return options, first_value

    @app.callback(
        Output("coverage-species-selector", "value", allow_duplicate=True),
        Input({"type": "view-coverage-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_view_coverage_click(n_clicks_list):
        """Set coverage selector when a 'View Coverage' button is clicked."""
        if not n_clicks_list or not any(n_clicks_list):
            return no_update
        triggered = ctx.triggered_id
        if triggered and isinstance(triggered, dict):
            return triggered.get("index", no_update)
        return no_update

    @app.callback(
        [
            Output("coverage-depth-plot", "figure"),
            Output("cumulative-coverage-plot", "figure"),
            Output("depth-histogram-plot", "figure"),
            Output("coverage-stats-container", "children"),
        ],
        [
            Input("coverage-species-selector", "value"),
            Input("coverage-min-mapq", "value"),
        ],
        State("app-config", "data"),
    )
    def update_coverage_plots(selected_key, min_mapq, config):
        """Load PAF data and render coverage plots."""
        empty = create_empty_coverage_figure
        if not selected_key:
            return empty(), empty(), empty(), ""

        try:
            min_mapq = int(min_mapq or 0)
        except (ValueError, TypeError):
            min_mapq = 0

        coverage = _load_real_coverage(selected_key, config, min_mapq)

        if coverage is None:
            return empty(), empty(), empty(), dbc.Alert(
                "No coverage data found for this species/sample.",
                color="warning", className="text-center",
            )

        depth_fig = create_coverage_depth_figure(coverage)
        cum_fig = create_cumulative_coverage_figure(coverage)
        hist_fig = create_depth_histogram_figure(coverage)
        stats = create_coverage_stats_summary(coverage)

        return depth_fig, cum_fig, hist_fig, stats


def _load_real_coverage(
    selected_key: str, config: Optional[dict], min_mapq: int
) -> Optional[CoverageData]:
    """Load coverage from a real PAF file."""
    if not config:
        return None

    results_dir = config.get("results_output_directory") or config.get("main_dir", "")
    if not results_dir:
        return None

    parts = selected_key.rsplit("_", 1)
    if len(parts) != 2:
        return None
    sample_id, taxid_str = parts

    # Try pipeline path first, then on-demand path
    candidates = [
        Path(results_dir) / "validation" / "minimap2" / f"{sample_id}_taxid{taxid_str}.paf",
        Path(results_dir) / "on_demand_validation" / f"{sample_id}_{taxid_str}_ondemand.paf",
    ]

    for paf_path in candidates:
        if paf_path.exists():
            cov_dict = parse_paf_coverage(paf_path, min_mapq=min_mapq)
            if cov_dict:
                # Return the first (usually only) reference
                return next(iter(cov_dict.values()))

    return None


def _create_empty_identity_plot() -> go.Figure:
    """Create an empty placeholder identity plot."""
    fig = go.Figure()
    fig.add_annotation(
        text="No identity data available",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=16, color="gray")
    )
    fig.update_layout(
        title="Sequence Identity by Species",
        xaxis_title="Species",
        yaxis_title="Identity (%)",
        template="plotly_white",
    )
    return fig
