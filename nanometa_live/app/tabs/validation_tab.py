"""
Validation tab callbacks for Nanometa Live v2.1.

Split into BLAST (read validation) and minimap2 (coverage validation)
sub-tab callbacks matching the two-panel layout.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from dash import Dash, Input, Output, State, ctx, no_update, html, ALL
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

from nanometa_live.core.parsers.blast_validation_parser import BlastValidationParser
from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage, CoverageData
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


def _filter_by_method(results, method):
    """Filter validation results by method.

    Args:
        results: List of result dicts from validation-data-store.
        method: 'blast' or 'minimap2'.

    Returns:
        Filtered list of result dicts.
    """
    if method == "blast":
        return [r for r in results if r.get("validation_method", "blast") != "minimap2"]
    else:  # minimap2
        return [r for r in results if r.get("validation_method") in ("minimap2", "both")]


def _compute_summary(results):
    """Compute confirmed/partial/low/no_data counts from a result list."""
    counts = {"confirmed": 0, "partial": 0, "low_confidence": 0, "no_data": 0}
    for r in results:
        status = r.get("status", "no_data")
        if status == "confirmed":
            counts["confirmed"] += 1
        elif status == "partial":
            counts["partial"] += 1
        elif status == "low":
            counts["low_confidence"] += 1
        else:
            counts["no_data"] += 1
    return counts


def register_validation_callbacks(app: Dash):
    """Register callbacks for the validation results tab.

    Args:
        app: Dash application instance.
    """

    # -----------------------------------------------------------------
    # Shared: load validation data
    # -----------------------------------------------------------------

    @app.callback(
        Output("validation-data-store", "data"),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def load_validation_data(n_intervals, config):
        """Load validation data from results directory."""
        try:
            if not config:
                return {"results": [], "summary": {}, "message": "No configuration loaded"}

            if not config.get("blast_validation", False):
                return {
                    "results": [],
                    "summary": {},
                    "message": "Validation is disabled. Enable it in Configuration tab.",
                }

            results_dir = config.get("results_output_directory") or config.get("main_dir", "")
            if not results_dir or not os.path.isdir(results_dir):
                return {"results": [], "summary": {}, "message": "Results directory not found"}

            parser = BlastValidationParser(results_dir)
            if not parser.has_validation_data():
                return {
                    "results": [],
                    "summary": {},
                    "message": "Waiting for validation results from pipeline...",
                }

            results = parser.get_validation_results()
            summary = parser.get_validation_summary()

            logger.info("Loaded %d validation results from %s", len(results), results_dir)

            return {
                "results": [r.to_dict() for r in results],
                "summary": summary,
                "message": None,
            }

        except Exception as e:
            log_callback_error("load_validation_data", e)
            return {"results": [], "summary": {}, "message": f"Error loading data: {e}"}

    # =================================================================
    # BLAST sub-tab callbacks
    # =================================================================

    @app.callback(
        Output("blast-summary-container", "children"),
        Input("validation-data-store", "data"),
    )
    def update_blast_summary(data):
        """Render summary card for BLAST results."""
        if not data or not data.get("results"):
            message = data.get("message", "No validation data available") if data else "No data"
            return dbc.Alert([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(message),
            ], color="info", className="text-center")

        blast_results = _filter_by_method(data["results"], "blast")
        counts = _compute_summary(blast_results)
        return create_validation_status_card(
            confirmed=counts["confirmed"],
            partial=counts["partial"],
            low_confidence=counts["low_confidence"],
            no_data=counts["no_data"],
            total=len(blast_results),
        )

    @app.callback(
        Output("blast-empty-message", "style"),
        Input("validation-data-store", "data"),
    )
    def update_blast_empty_state(data):
        """Show or hide the BLAST empty-state message."""
        if not data or not data.get("results"):
            return {"display": "block"}
        blast_results = _filter_by_method(data["results"], "blast")
        return {"display": "none"} if blast_results else {"display": "block"}

    @app.callback(
        Output("blast-results-container", "children"),
        [
            Input("validation-data-store", "data"),
            Input("blast-status-filter", "value"),
            Input("blast-sort-select", "value"),
        ],
    )
    def update_blast_cards(data, status_filter, sort_by):
        """Render BLAST result cards with filtering and sorting."""
        if not data or not data.get("results"):
            return ""

        results = _filter_by_method(data["results"], "blast")

        if status_filter and status_filter != "all":
            results = [r for r in results if r.get("status") == status_filter]

        if not results:
            return dbc.Alert(
                f"No BLAST results match the filter: {status_filter}",
                color="info",
                className="text-center",
            )

        sort_key = sort_by or "percent_validated"
        reverse = sort_key != "species"
        try:
            results = sorted(
                results,
                key=lambda x: x.get(sort_key, 0) if sort_key != "species" else x.get("species", ""),
                reverse=reverse,
            )
        except Exception:
            pass

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
                show_coverage_button=False,
            )
            cards.append(card)

        return html.Div(cards)

    @app.callback(
        Output("blast-identity-plot", "figure"),
        Input("validation-data-store", "data"),
    )
    def update_blast_identity_plot(data):
        """Create identity distribution plot for BLAST results."""
        if not data or not data.get("results"):
            return _create_empty_identity_plot()

        results = _filter_by_method(data["results"], "blast")

        species_names = []
        identity_means = []
        identity_mins = []
        identity_maxs = []

        for result in results:
            if result.get("percent_identity_mean", 0) > 0:
                species_names.append(result.get("species", "Unknown")[:30])
                identity_means.append(result.get("percent_identity_mean", 0))
                identity_mins.append(result.get("percent_identity_min", 0))
                identity_maxs.append(result.get("percent_identity_max", 0))

        if not species_names:
            return _create_empty_identity_plot()

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=species_names,
            y=identity_means,
            error_y=dict(
                type="data",
                symmetric=False,
                array=[mx - mn for mn, mx in zip(identity_means, identity_maxs)],
                arrayminus=[mn - mi for mn, mi in zip(identity_means, identity_mins)],
            ),
            marker_color="#fd7e14",
            text=[f"{v:.1f}%" for v in identity_means],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>Mean: %{y:.1f}%<br>"
                "Range: %{customdata[0]:.1f}% - %{customdata[1]:.1f}%<extra></extra>"
            ),
            customdata=list(zip(identity_mins, identity_maxs)),
        ))

        fig.update_layout(
            title="Sequence Identity by Species (BLAST)",
            xaxis_title="Species",
            yaxis_title="Identity (%)",
            yaxis_range=[0, 105],
            showlegend=False,
            template="plotly_white",
            margin=dict(l=50, r=50, t=60, b=100),
        )
        fig.add_hline(
            y=90,
            line_dash="dash",
            line_color="green",
            annotation_text="90% threshold",
            annotation_position="top right",
        )
        return fig

    @app.callback(
        Output("blast-stats-table", "data"),
        Input("validation-data-store", "data"),
    )
    def update_blast_table(data):
        """Populate the BLAST statistics table."""
        if not data or not data.get("results"):
            return []

        results = _filter_by_method(data["results"], "blast")
        table_data = []
        for result in results:
            table_data.append({
                "species": result.get("species", "Unknown"),
                "sample_id": result.get("sample_id", ""),
                "total_reads": result.get("total_reads", 0),
                "validated_reads": result.get("validated_reads", 0),
                "percent_validated": round(result.get("percent_validated", 0), 1),
                "percent_identity_mean": round(result.get("percent_identity_mean", 0), 1),
                "coverage_breadth": round(result.get("coverage_breadth", 0) * 100, 1),
                "status": result.get("status", "no_data"),
            })
        return table_data

    @app.callback(
        Output("download-blast-report", "data"),
        Input("export-blast-button", "n_clicks"),
        [State("validation-data-store", "data"), State("app-config", "data")],
        prevent_initial_call=True,
    )
    def export_blast_report(n_clicks, data, config):
        """Export BLAST validation results to CSV."""
        if not n_clicks or not data or not data.get("results"):
            return no_update

        try:
            blast_results = _filter_by_method(data["results"], "blast")
            if not blast_results:
                return no_update

            df = pd.DataFrame(blast_results)
            analysis_name = config.get("analysis_name", "analysis") if config else "analysis"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"blast_validation_{analysis_name}_{timestamp}.csv"

            return dict(content=df.to_csv(index=False), filename=filename, type="text/csv")

        except Exception as e:
            log_callback_error("export_blast_report", e)
            return no_update

    # =================================================================
    # Coverage (minimap2) sub-tab callbacks
    # =================================================================

    @app.callback(
        Output("coverage-summary-container", "children"),
        Input("validation-data-store", "data"),
    )
    def update_coverage_summary(data):
        """Render summary card for minimap2 coverage results."""
        if not data or not data.get("results"):
            message = data.get("message", "No validation data available") if data else "No data"
            return dbc.Alert([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(message),
            ], color="info", className="text-center")

        cov_results = _filter_by_method(data["results"], "minimap2")
        if not cov_results:
            return dbc.Alert(
                "No minimap2 coverage results available.",
                color="light",
                className="text-center",
            )

        counts = _compute_summary(cov_results)
        return create_validation_status_card(
            confirmed=counts["confirmed"],
            partial=counts["partial"],
            low_confidence=counts["low_confidence"],
            no_data=counts["no_data"],
            total=len(cov_results),
        )

    @app.callback(
        Output("coverage-empty-message", "style"),
        Input("validation-data-store", "data"),
    )
    def update_coverage_empty_state(data):
        """Show or hide the coverage empty-state message."""
        if not data or not data.get("results"):
            return {"display": "block"}
        cov_results = _filter_by_method(data["results"], "minimap2")
        return {"display": "none"} if cov_results else {"display": "block"}

    @app.callback(
        Output("coverage-results-container", "children"),
        Input("validation-data-store", "data"),
    )
    def update_coverage_cards(data):
        """Render minimap2 result cards with View Coverage buttons."""
        if not data or not data.get("results"):
            return ""

        results = _filter_by_method(data["results"], "minimap2")
        if not results:
            return ""

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
                validation_method=result.get("validation_method", "minimap2"),
                avg_mapq=result.get("avg_mapq", 0.0),
                show_coverage_button=True,
            )
            cards.append(card)

        return html.Div(cards)

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
        """Set coverage selector when a View Coverage button is clicked."""
        if not n_clicks_list or not any(n_clicks_list):
            return no_update
        triggered = ctx.triggered_id
        if triggered and isinstance(triggered, dict):
            return triggered.get("index", no_update)
        return no_update

    @app.callback(
        [
            Output("coverage-depth-plot", "figure"),
            Output("coverage-cumulative-plot", "figure"),
            Output("coverage-histogram-plot", "figure"),
            Output("coverage-stats-container", "children"),
        ],
        [
            Input("coverage-species-selector", "value"),
            Input("coverage-mapq-filter", "value"),
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
                color="warning",
                className="text-center",
            )

        depth_fig = create_coverage_depth_figure(coverage)
        cum_fig = create_cumulative_coverage_figure(coverage)
        hist_fig = create_depth_histogram_figure(coverage)
        stats = create_coverage_stats_summary(coverage)

        return depth_fig, cum_fig, hist_fig, stats

    @app.callback(
        Output("download-coverage-report", "data"),
        Input("export-coverage-button", "n_clicks"),
        [State("validation-data-store", "data"), State("app-config", "data")],
        prevent_initial_call=True,
    )
    def export_coverage_report(n_clicks, data, config):
        """Export minimap2 coverage results to CSV."""
        if not n_clicks or not data or not data.get("results"):
            return no_update

        try:
            cov_results = _filter_by_method(data["results"], "minimap2")
            if not cov_results:
                return no_update

            df = pd.DataFrame(cov_results)
            analysis_name = config.get("analysis_name", "analysis") if config else "analysis"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"coverage_validation_{analysis_name}_{timestamp}.csv"

            return dict(content=df.to_csv(index=False), filename=filename, type="text/csv")

        except Exception as e:
            log_callback_error("export_coverage_report", e)
            return no_update


# =====================================================================
# Helper functions (module-level)
# =====================================================================

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

    candidates = [
        Path(results_dir) / "validation" / "minimap2" / f"{sample_id}_taxid{taxid_str}.paf",
        Path(results_dir) / "on_demand_validation" / f"{sample_id}_{taxid_str}_ondemand.paf",
    ]

    for paf_path in candidates:
        if paf_path.exists():
            cov_dict = parse_paf_coverage(paf_path, min_mapq=min_mapq)
            if cov_dict:
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
        font=dict(size=16, color="gray"),
    )
    fig.update_layout(
        title="Sequence Identity by Species",
        xaxis_title="Species",
        yaxis_title="Identity (%)",
        template="plotly_white",
    )
    return fig
