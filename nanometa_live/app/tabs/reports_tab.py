"""Reports tab callbacks.

Builds the Reports-tab content from the operator's current results directory:
links to the MultiQC + Nextflow reports (gap 2), the realtime performance panel
(gap 3), and the assembly summary (gap 4). The render is gated on the
results-fingerprint + interval backstop like the other tabs, and only does work
while the Reports tab is active.
"""

from __future__ import annotations

import logging

import dash
from dash import Input, Output, State, html, ctx
from dash.exceptions import PreventUpdate

from nanometa_live.app.utils.debounce import interval_tick_is_redundant, mark_rendered
from nanometa_live.core.utils.reports_loader import set_reports_dir, detect_reports
from nanometa_live.core.utils.realtime_stats_loader import load_realtime_stats
from nanometa_live.core.utils.assembly_loader import load_assembly_stats
from nanometa_live.core.utils.taxpasta_loader import load_taxpasta_long
from nanometa_live.app.tabs.reports_helpers import (
    build_pipeline_reports_card,
    build_multiqc_embed,
    build_realtime_performance_panel,
    build_assembly_panel,
    build_taxpasta_panel,
)


def _name_by_taxid(results_dir):
    """taxid -> name map from the Kraken2 data, to label taxpasta taxa (which
    carry no names). Best-effort: returns {} on any load problem."""
    try:
        from nanometa_live.core.utils.classification_loaders import load_kraken_data
        df = load_kraken_data(results_dir)
        if df is None or df.empty or "taxid" not in df or "name" not in df:
            return {}
        return {int(t): str(n).strip() for t, n in zip(df["taxid"], df["name"])}
    except Exception:
        logger.debug("name map for taxpasta failed", exc_info=True)
        return {}

logger = logging.getLogger(__name__)


def register_reports_callbacks(app, backend_manager=None):
    @app.callback(
        Output("reports-content", "children"),
        [
            Input("tabs", "active_tab"),
            Input("results-fingerprint", "data"),
            Input("update-interval", "n_intervals"),
        ],
        State("app-config", "data"),
    )
    def render_reports_content(active_tab, _fingerprint, _n_intervals, config):
        # Only do work while the Reports tab is visible.
        if active_tab != "reports-tab":
            raise PreventUpdate
        # Debounce: a tick that found nothing new is a microsecond short-circuit,
        # unless the operator just switched to the tab (then always render).
        if ctx.triggered_id != "tabs" and interval_tick_is_redundant(ctx, "reports_tab", _fingerprint):
            raise PreventUpdate
        mark_rendered("reports_tab", _fingerprint)

        results_dir = ""
        if config:
            results_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
        # Tell the Flask serve route which directory the links point into.
        set_reports_dir(results_dir or None)

        reports = detect_reports(results_dir)
        realtime = load_realtime_stats(results_dir)
        assemblies = load_assembly_stats(results_dir)
        taxpasta_rows = load_taxpasta_long(results_dir)
        taxpasta_names = _name_by_taxid(results_dir) if taxpasta_rows else {}
        return html.Div([
            build_realtime_performance_panel(realtime),
            build_taxpasta_panel(taxpasta_rows, taxpasta_names),
            build_assembly_panel(assemblies),
            build_pipeline_reports_card(reports),
            build_multiqc_embed(reports),
        ])
