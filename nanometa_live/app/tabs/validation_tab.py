"""
Validation tab callbacks for Nanometa Live v2.1.

Split into BLAST (read validation) and minimap2 (coverage validation)
sub-tab callbacks matching the two-panel layout.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from dash import Dash, Input, Output, State, ctx, no_update, html, ALL
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

from nanometa_live.core.parsers.blast_validation_parser import BlastValidationParser
from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage, aggregate_contig_coverage, CoverageData
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


# Initial visible-card cap for the BLAST and minimap2 result-card
# containers. Closes P1-T07 from
# docs/audit-2026-04-28-throughput-ux.md: a 24-barcode x 5-species run
# produces ~120 cards, which is heavy DOM and pushes initial render
# past the 30-second-scan budget. The first page renders 30 cards;
# operators who want the full list click "Show all".
_CARD_LIST_INITIAL_LIMIT = 30


def _build_coverage_selector_options(
    data: Optional[Dict[str, Any]],
    current_value: Optional[str],
):
    """Group minimap2 validation results into per-sample sections.

    Closes P1-T06 from docs/audit-2026-04-28-throughput-ux.md: a
    24-barcode x 5-species run produces ~120 flat entries; grouping
    by sample turns the dropdown into 24 small sections separated by
    disabled header rows that the dcc.Dropdown's type-to-filter still
    matches against. ``__header__:`` sentinel values guard the
    selection logic from accidentally picking a header row.

    Returns:
        Tuple of (options list, default value or None).
    """
    if not data or not data.get("results"):
        return [], None

    per_sample: Dict[str, List[Dict[str, Any]]] = {}
    sample_order: List[str] = []
    seen = set()
    for r in data["results"]:
        method = r.get("validation_method", "blast")
        if method not in ("minimap2", "both"):
            continue
        sample_id = r.get("sample_id", "")
        taxid = r.get("taxid", "")
        key = f"{sample_id}_{taxid}"
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "label": f"{r.get('species', 'Unknown')} (taxid {taxid})",
            "value": key,
        }
        if sample_id not in per_sample:
            per_sample[sample_id] = []
            sample_order.append(sample_id)
        per_sample[sample_id].append(entry)

    options: List[Dict[str, Any]] = []
    for sample_id in sample_order:
        options.append({
            "label": f"-- {sample_id} ({len(per_sample[sample_id])} species) --",
            "value": f"__header__:{sample_id}",
            "disabled": True,
        })
        options.extend(per_sample[sample_id])

    valid_values = {o["value"] for o in options if not o.get("disabled")}
    if current_value and current_value in valid_values:
        return options, current_value

    first_value = next(
        (o["value"] for o in options if not o.get("disabled")),
        None,
    )
    return options, first_value


def _build_paginated_card_list(
    cards: List[Any],
    show_all: bool,
    show_all_button_id: str,
) -> html.Div:
    """Wrap a list of result cards with a "showing N of M" footer + button.

    When ``show_all`` is False, only the first ``_CARD_LIST_INITIAL_LIMIT``
    cards are rendered with a button below offering to expand. When True
    (or when the list fits under the cap), every card is rendered with
    just the count footer. Empty lists return an empty Div.
    """
    total = len(cards)
    if total == 0:
        return html.Div([])

    visible_cards = cards if show_all or total <= _CARD_LIST_INITIAL_LIMIT \
        else cards[:_CARD_LIST_INITIAL_LIMIT]
    truncated = total - len(visible_cards)

    footer = []
    if truncated > 0:
        footer.append(
            html.Div(
                [
                    html.Span(
                        f"Showing {len(visible_cards)} of {total} results.",
                        className="text-muted me-2",
                    ),
                    dbc.Button(
                        f"Show all {total}",
                        id=show_all_button_id,
                        color="link",
                        size="sm",
                        n_clicks=0,
                        className="p-0",
                    ),
                ],
                className="text-center small mt-3 pt-2 border-top",
            )
        )
    elif total > _CARD_LIST_INITIAL_LIMIT:
        footer.append(
            html.Div(
                f"Showing all {total} results.",
                className="text-center small text-muted mt-3 pt-2 border-top",
            )
        )

    return html.Div(visible_cards + footer)


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


def _filter_results_by_sample(results, selected_sample):
    """Filter validation results to a single sample.

    Treats ``"All Samples"`` and any falsy value as "no filter applied"
    -- matches the convention used by ``load_kraken_data`` on the
    Dashboard and Organism tabs.

    Args:
        results: List of result dicts (each with ``sample_id``).
        selected_sample: The current value of the ``selected-sample``
            store, or None / ``"All Samples"``.

    Returns:
        Filtered list of result dicts.
    """
    if not selected_sample or selected_sample == "All Samples":
        return list(results)
    return [r for r in results if r.get("sample_id") == selected_sample]


def _format_scope_text(selected_sample):
    """Build the scope line for the validation tab's intro banner."""
    if selected_sample and selected_sample != "All Samples":
        return f"Currently showing: {selected_sample}"
    return (
        "Currently showing: all samples (use the sample selector at "
        "the top of the dashboard to narrow to one)."
    )


def _format_criteria_text(config):
    """Build the criteria line for the validation tab's intro banner.

    Pulls the active thresholds from config so the operator always
    sees the live cutoffs, not the documented defaults.
    """
    cfg = config or {}
    identity = cfg.get("validation_identity_threshold", 90)
    hit_rate = cfg.get("validation_hit_rate_threshold", 0.5)
    mapq = cfg.get("minimap2_min_mapq", 10)
    try:
        identity_str = f"{float(identity):.0f}%"
    except (TypeError, ValueError):
        identity_str = "90%"
    try:
        hit_rate_str = f"{float(hit_rate):.0%}"
    except (TypeError, ValueError):
        hit_rate_str = "50%"
    try:
        mapq_str = str(int(mapq))
    except (TypeError, ValueError):
        mapq_str = "10"
    return (
        f"Confirmed: hit rate >= {hit_rate_str} of classified reads "
        f"AND mean identity >= {identity_str}. "
        f"Partial: at least half the hit-rate threshold OR within 90% "
        f"of the identity floor. "
        f"Low Confidence: below both. "
        f"Minimap2 also requires alignment MAPQ >= {mapq_str}."
    )


def _compute_summary(results):
    """Compute summary stats from a validation result list.

    Returns the four per-status species counts AND the aggregate
    read totals across all results so the Validation Summary card
    can show "X of Y reads validated" in addition to the species
    bucket counts.

    Returns:
        ``{
            "confirmed": int,
            "partial": int,
            "low_confidence": int,
            "no_data": int,
            "reads_validated": int,
            "reads_total": int,
        }``
    """
    counts = {
        "confirmed": 0,
        "partial": 0,
        "low_confidence": 0,
        "no_data": 0,
        "reads_validated": 0,
        "reads_total": 0,
    }
    for r in results:
        status = r.get("status", "no_data")
        if status == "confirmed":
            counts["confirmed"] += 1
        elif status == "partial":
            counts["partial"] += 1
        elif status in ("low", "uncertain", "rejected"):
            counts["low_confidence"] += 1
        else:
            counts["no_data"] += 1
        try:
            counts["reads_validated"] += int(r.get("validated_reads", 0) or 0)
            counts["reads_total"] += int(r.get("total_reads", 0) or 0)
        except (TypeError, ValueError):
            continue
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
        [
            Output("validation-sample-scope-note", "children"),
            Output("validation-criteria-note", "children"),
        ],
        [
            Input("selected-sample", "data"),
            Input("app-config", "data"),
        ],
    )
    def update_validation_scope_note(selected_sample, config):
        """Live-update the scope-and-criteria banner so operators always
        see which sample is in view + the active cutoffs.

        Pulls thresholds from the config: ``validation_identity_threshold``
        (post-aggregation identity gate, default 90%),
        ``validation_hit_rate_threshold`` (fraction of reads that must
        hit, default 0.5), and ``minimap2_min_mapq`` (mapq floor,
        default 10). Falls back to the documented defaults when the
        config does not supply a value.
        """
        return _format_scope_text(selected_sample), _format_criteria_text(config)

    @app.callback(
        Output("validation-data-store", "data"),
        [
            Input("results-fingerprint", "data"),
            Input("selected-sample", "data"),
        ],
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def load_validation_data(_fingerprint, selected_sample, config):
        """Load validation data filtered by the selected sample.

        The Validation tab honours the same sample selector as the
        Dashboard and Organism tabs: when the operator chooses a
        specific barcode, the validation results, summary card, cards,
        and stats table all narrow to that sample. ``All Samples`` (or
        an empty value) returns the full result set so cross-sample
        aggregates still work.
        """

        try:
            if not config:
                return {"results": [], "summary": {}, "message": "No configuration loaded",
                        "selected_sample": selected_sample}

            if not config.get("blast_validation", True):
                return {
                    "results": [],
                    "summary": {},
                    "message": "Validation is disabled. Enable it in Configuration tab.",
                    "selected_sample": selected_sample,
                }

            results_dir = config.get("results_output_directory") or config.get("main_dir", "")
            if not results_dir or not os.path.isdir(results_dir):
                return {"results": [], "summary": {}, "message": "Results directory not found",
                        "selected_sample": selected_sample}

            parser = BlastValidationParser(results_dir)
            if not parser.has_validation_data():
                return {
                    "results": [],
                    "summary": {},
                    "message": "Waiting for validation results from pipeline...",
                    "selected_sample": selected_sample,
                }

            results = parser.get_validation_results()
            summary = parser.get_validation_summary()

            # Apply sample filter via the pure helper. ``All Samples`` and
            # empty sentinel values mean "no filter" -- matches the
            # convention used by the Dashboard and Organism tabs.
            results_dicts = [r.to_dict() for r in results]
            filtered = _filter_results_by_sample(results_dicts, selected_sample)
            if selected_sample and selected_sample != "All Samples":
                logger.info(
                    "Validation: %d/%d results match selected sample %s",
                    len(filtered), len(results_dicts), selected_sample,
                )
            results_dicts = filtered

            logger.info("Loaded %d validation results from %s", len(results_dicts), results_dir)

            return {
                "results": results_dicts,
                "summary": summary,
                "message": None,
                "selected_sample": selected_sample,
            }

        except Exception as e:
            log_callback_error("load_validation_data", e)
            return {"results": [], "summary": {}, "message": f"Error loading data: {e}",
                    "selected_sample": selected_sample}

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
            message = data.get("message") if data else None
            if not message:
                return ""
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
            reads_validated=counts["reads_validated"],
            reads_total=counts["reads_total"],
        )

    @app.callback(
        [
            Output("blast-empty-message", "style"),
            Output("blast-empty-message", "children"),
            Output("blast-results-section", "style"),
        ],
        Input("validation-data-store", "data"),
    )
    def update_blast_empty_state(data):
        """Show or hide the BLAST empty-state message, with context-appropriate text."""
        from nanometa_live.app.components.modern_components import EmptyStateMessage

        hidden = {"display": "none"}
        visible = {"display": "block"}

        if not data:
            return visible, EmptyStateMessage(
                title="No Validation Results",
                message="Waiting for validation data...",
                icon="bi-shield-check",
            ), hidden

        if not data.get("results"):
            message = data.get("message") or "No BLAST validation results available."
            # Distinguish disabled vs waiting vs no data
            if "disabled" in message.lower():
                title = "Validation Disabled"
                icon = "bi-shield-x"
            elif "waiting" in message.lower():
                title = "Awaiting Results"
                icon = "bi-hourglass-split"
            else:
                title = "No Validation Results"
                icon = "bi-shield-check"
            return visible, EmptyStateMessage(
                title=title,
                message=message,
                icon=icon,
            ), hidden

        blast_results = _filter_by_method(data["results"], "blast")
        if blast_results:
            return hidden, [], visible
        return visible, EmptyStateMessage(
            title="No BLAST Results",
            message="No BLAST read validation results found for the current sample.",
            icon="bi-shield-check",
        ), hidden

    @app.callback(
        Output("blast-results-container", "children"),
        [
            Input("validation-data-store", "data"),
            Input("blast-status-filter", "value"),
            Input("blast-sort-select", "value"),
            Input("blast-show-all", "data"),
        ],
    )
    def update_blast_cards(data, status_filter, sort_by, show_all):
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

        return _build_paginated_card_list(
            cards, show_all=bool(show_all),
            show_all_button_id="blast-show-all-btn",
        )

    @app.callback(
        Output("blast-show-all", "data"),
        Input("blast-show-all-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def expand_blast_card_list(n_clicks):
        """Flip blast-show-all to True when the operator clicks Show all."""
        return bool(n_clicks)

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

        # Color bars by identity level: green >= 95, amber 90-95, red < 90
        bar_colors = []
        for v in identity_means:
            if v >= 95:
                bar_colors.append("#28a745")
            elif v >= 90:
                bar_colors.append("#fd7e14")
            else:
                bar_colors.append("#dc3545")

        # Only include error bars when min/max data is available.
        # The aggregate JSON path only provides mean identity; min/max
        # stay at 0 and would produce negative error bar values.
        has_range = any(mx > 0 for mx in identity_maxs)
        error_y_cfg = dict(
            type="data",
            symmetric=False,
            array=[max(0, mx - mn) for mn, mx in zip(identity_means, identity_maxs)],
            arrayminus=[max(0, mn - mi) for mn, mi in zip(identity_means, identity_mins)],
            color="#6c757d",
            thickness=1.5,
            visible=has_range,
        )

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=species_names,
            y=identity_means,
            error_y=error_y_cfg,
            marker_color=bar_colors,
            marker_line_width=0,
            text=[f"{v:.1f}%" for v in identity_means],
            textposition="outside",
            textfont=dict(size=11, color="#374151"),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Mean identity: %{y:.1f}%<br>"
                + ("Range: %{customdata[0]:.1f}% - %{customdata[1]:.1f}%" if has_range
                   else "Min/max range not available")
                + "<extra></extra>"
            ),
            customdata=list(zip(identity_mins, identity_maxs)),
        ))

        fig.update_layout(
            title=dict(
                text="Match Quality by Species",
                font=dict(size=14, color="#374151"),
            ),
            xaxis_title="Species",
            yaxis_title="Match Quality (%)",
            yaxis_range=[0, 108],
            showlegend=False,
            template="nanometa",
            margin=dict(l=50, r=30, t=50, b=100),
            font=dict(family="Arial, sans-serif", size=12),
            bargap=0.3,
        )
        fig.add_hline(
            y=90,
            line_dash="dash",
            line_color="#6c757d",
            line_width=1,
            annotation_text="90% minimum for confidence",
            annotation_position="top right",
            annotation_font_size=10,
            annotation_font_color="#6c757d",
        )
        return fig

    @app.callback(
        Output("blast-stats-table", "rowData"),
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
        State("validation-data-store", "data"),
        State("app-config", "data"),
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
            if "coverage_breadth" in df.columns:
                df["coverage_breadth"] = (df["coverage_breadth"] * 100).round(1)
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
            message = data.get("message") if data else None
            if not message:
                return ""
            return dbc.Alert([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(message),
            ], color="info", className="text-center")

        cov_results = _filter_by_method(data["results"], "minimap2")
        if not cov_results:
            return ""

        counts = _compute_summary(cov_results)
        return create_validation_status_card(
            confirmed=counts["confirmed"],
            partial=counts["partial"],
            low_confidence=counts["low_confidence"],
            no_data=counts["no_data"],
            total=len(cov_results),
            reads_validated=counts["reads_validated"],
            reads_total=counts["reads_total"],
        )

    @app.callback(
        [
            Output("coverage-empty-message", "style"),
            Output("coverage-empty-message", "children"),
            Output("coverage-controls-section", "style"),
        ],
        Input("validation-data-store", "data"),
    )
    def update_coverage_empty_state(data):
        """Show or hide the coverage empty-state message and controls, with context-appropriate text."""
        from nanometa_live.app.components.modern_components import EmptyStateMessage

        hidden = {"display": "none"}
        visible = {"display": "block"}

        if not data:
            return visible, EmptyStateMessage(
                title="No Coverage Data",
                message="Waiting for validation data...",
                icon="bi-bar-chart-line",
            ), hidden

        if not data.get("results"):
            message = data.get("message") or "No minimap2 coverage data available."
            if "disabled" in message.lower():
                title = "Validation Disabled"
                icon = "bi-shield-x"
            elif "waiting" in message.lower():
                title = "Awaiting Results"
                icon = "bi-hourglass-split"
            else:
                title = "No Coverage Data"
                icon = "bi-bar-chart-line"
            return visible, EmptyStateMessage(
                title=title,
                message=message,
                icon=icon,
            ), hidden

        cov_results = _filter_by_method(data["results"], "minimap2")
        if cov_results:
            return hidden, [], visible
        return visible, EmptyStateMessage(
            title="No Coverage Data",
            message="No minimap2 coverage results found. Run the pipeline with minimap2 validation enabled.",
            icon="bi-bar-chart-line",
        ), hidden

    @app.callback(
        Output("coverage-results-container", "children"),
        Input("validation-data-store", "data"),
        Input("coverage-show-all", "data"),
    )
    def update_coverage_cards(data, show_all):
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

        return _build_paginated_card_list(
            cards, show_all=bool(show_all),
            show_all_button_id="coverage-show-all-btn",
        )

    @app.callback(
        Output("coverage-show-all", "data"),
        Input("coverage-show-all-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def expand_coverage_card_list(n_clicks):
        """Flip coverage-show-all to True when the operator clicks Show all."""
        return bool(n_clicks)

    @app.callback(
        [
            Output("coverage-species-selector", "options"),
            Output("coverage-species-selector", "value"),
        ],
        Input("validation-data-store", "data"),
        State("coverage-species-selector", "value"),
    )
    def populate_coverage_selector(data, current_value):
        """Populate species selector from minimap2 validation results.

        Preserves the current selection across auto-refresh intervals
        if the selected key is still present in the updated options.
        Grouping logic lives in ``_build_coverage_selector_options``
        so it stays unit-testable without spinning up a Dash app.
        """
        return _build_coverage_selector_options(data, current_value)

    @app.callback(
        [
            Output("coverage-species-selector", "value", allow_duplicate=True),
            Output("validation-sub-tabs", "active_tab", allow_duplicate=True),
        ],
        Input({"type": "view-coverage-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_view_coverage_click(n_clicks_list):
        """Set coverage selector and switch to coverage sub-tab when a View Coverage button is clicked."""
        if not n_clicks_list or not any(n_clicks_list):
            return no_update, no_update
        triggered = ctx.triggered_id
        if triggered and isinstance(triggered, dict):
            return triggered.get("index", no_update), "coverage-tab"
        return no_update, no_update

    @app.callback(
        [
            Output("coverage-depth-plot", "figure"),
            Output("coverage-cumulative-plot", "figure"),
            Output("coverage-histogram-plot", "figure"),
            Output("coverage-stats-container", "children"),
            Output("coverage-plots-section", "style"),
        ],
        [
            Input("coverage-species-selector", "value"),
            Input("coverage-mapq-filter", "value"),
            Input("coverage-depth-threshold", "value"),
        ],
        State("app-config", "data"),
    )
    def update_coverage_plots(selected_key, min_mapq, depth_threshold, config):
        """Load PAF data and render coverage plots."""
        empty = create_empty_coverage_figure
        hidden = {"display": "none"}
        visible = {"display": "block"}

        if not selected_key:
            return empty(), empty(), empty(), "", hidden

        try:
            min_mapq = int(min_mapq or 0)
        except (ValueError, TypeError):
            min_mapq = 0

        try:
            threshold = int(depth_threshold) if depth_threshold is not None else 10
            if threshold < 1:
                threshold = 1
        except (ValueError, TypeError):
            threshold = 10

        coverage = _load_real_coverage(selected_key, config, min_mapq)

        if coverage is None:
            no_paf_msg = "No PAF file found for this species/sample. Ensure minimap2 validation ran and results are in validation/minimap2/."
            no_paf = lambda: create_empty_coverage_figure(
                title="No coverage data",
                message=no_paf_msg,
            )
            return no_paf(), no_paf(), no_paf(), dbc.Alert(
                no_paf_msg,
                color="warning",
                className="text-center",
            ), hidden

        depth_fig = create_coverage_depth_figure(coverage, threshold=threshold)
        cum_fig = create_cumulative_coverage_figure(coverage)
        hist_fig = create_depth_histogram_figure(coverage)
        stats = create_coverage_stats_summary(coverage)

        return depth_fig, cum_fig, hist_fig, stats, visible

    @app.callback(
        Output("download-coverage-report", "data"),
        Input("export-coverage-button", "n_clicks"),
        State("validation-data-store", "data"),
        State("app-config", "data"),
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
    """Load coverage from a real PAF file.

    Returns None if no PAF file exists or if the file has no alignments
    passing the min_mapq filter.
    """
    if not config:
        return None

    results_dir = config.get("results_output_directory") or config.get("main_dir", "")
    if not results_dir:
        return None

    # selected_key format: "{sample_id}_{taxid}" where taxid is numeric
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
                return aggregate_contig_coverage(cov_dict)
            logger.info(
                "PAF file found but has no alignments passing min_mapq=%d: %s",
                min_mapq, paf_path,
            )
            return None

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
        font=dict(size=14, color="#9CA3AF"),
    )
    fig.update_layout(
        title=dict(
            text="Match Quality by Species",
            font=dict(size=14, color="#374151"),
        ),
        xaxis_title="Species",
        yaxis_title="Match Quality (%)",
        template="plotly_white",
        height=350,
        margin=dict(l=50, r=30, t=50, b=60),
        font=dict(family="Arial, sans-serif", size=12),
    )
    return fig
