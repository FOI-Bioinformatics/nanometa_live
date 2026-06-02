"""Readiness-checklist indicator callback (with its cached ReadinessReport)."""

import hashlib
import json
import os
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import dash
from dash import ALL, Dash, Input, Output, State, callback, dcc, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.sample_detector import get_available_samples, get_sample_file_mapping
from nanometa_live.core.utils.loader_utils import check_data_freshness
from nanometa_live.app.utils.callback_helpers import log_callback_error
from nanometa_live.app.utils.outdir_resolution import resolve_outdir_for_fingerprint
from nanometa_live.app.utils.debounce import (
    should_skip_update, get_trigger_type,
    interval_render_is_redundant, mark_rendered,
)
from nanometa_live.app.app import background_callback_manager

# update_readiness_indicator runs the full ReadinessChecker every
# update-interval tick. Each invocation does ~7 shutil.which calls plus
# os.stat / glob over the configured Kraken2 DB and BLAST DB directories,
# i.e. 10+ syscalls every 30 s for a state that almost never changes.
# This module-level cache reuses a recent ReadinessReport when the
# relevant config has not changed AND less than _READINESS_TTL seconds
# have elapsed. The TTL guarantees that "operator just installed
# bowtie / dropped a Kraken2 DB into place" surfaces within 60 s.
_READINESS_TTL = 60.0
_readiness_cache: Dict[str, Tuple[float, Any]] = {}
_readiness_cache_lock = threading.Lock()


def _readiness_cache_key(config: Optional[Dict[str, Any]]) -> str:
    """Build a stable cache key from the config fields that affect readiness.

    The full config dict is not used because the dashboard mutates
    unrelated keys (UI flags, last-selected sample) on every save, which
    would invalidate the cache for no reason. Only the fields the
    readiness checks actually read are included.
    """
    if not config:
        return "no-config"
    relevant = {
        k: config.get(k) for k in (
            "kraken_db",
            "main_dir",
            "results_output_directory",
            "nanopore_output_directory",
            "pipeline_source",
            "pipeline_profile",
            "pipeline_cache_dir",
            "blast_validation",
            "network_check_enabled",
            "offline_mode",
        )
    }
    return hashlib.md5(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def register_readiness(app, backend_manager):
    @app.callback(
        [
            Output("readiness-badge", "children"),
            Output("readiness-badge", "color"),
            Output("readiness-state", "data"),
            Output("readiness-popover-body", "children"),
        ],
        Input("update-interval", "n_intervals"),
        Input("app-config", "data"),
        # Audit item #6 (docs/audit/threading-2026-05-10.md): the cold path
        # of this callback shells out to ``docker info`` (5 s timeout) and
        # ``nextflow -version`` (10 s timeout) plus a couple of other
        # readiness probes, blocking the Werkzeug request thread for up to
        # ~15-20 s on first run after a configuration change. The 60 s
        # process-local TTL cache covers the warm path, but cold runs hung
        # every other Dash callback in flight. Running in a DiskcacheManager
        # worker isolates the subprocess wait from the main process.
        # Cache state does not cross the worker boundary, so the worst-case
        # latency is ~15 s of *worker* time per cold tick; the request
        # thread stays responsive.
        background=True,
        manager=background_callback_manager,
    )
    def update_readiness_indicator(n_intervals, config):
        """Update the readiness badge, popover details, and cached readiness state."""
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

        if not config:
            return (
                [html.I(className="bi bi-dash-circle me-1"), "Not configured"],
                "secondary",
                {"ready": False, "checks": [], "message": "No configuration loaded"},
                html.Div("Load a configuration to see readiness checks.", className="text-muted small"),
            )

        try:
            cache_key = _readiness_cache_key(config)
            now = time.time()
            with _readiness_cache_lock:
                cached = _readiness_cache.get(cache_key)
            if cached is not None and (now - cached[0]) < _READINESS_TTL:
                report = cached[1]
            else:
                checker = ReadinessChecker()
                report = checker.check_readiness(config)
                with _readiness_cache_lock:
                    _readiness_cache[cache_key] = (now, report)
            summary = report.summary()

            if report.ready:
                badge_children = [html.I(className="bi bi-check-circle-fill me-1"), "Ready"]
                badge_color = "success"
            else:
                badge_children = [
                    html.I(className="bi bi-exclamation-triangle-fill me-1"),
                    f"{summary['passed']}/{summary['total']} checks",
                ]
                badge_color = "danger" if summary["critical_failures"] > 0 else "warning"

            checks_data = []
            popover_items = []
            for c in report.checks:
                checks_data.append({
                    "name": c.name,
                    "passed": c.passed,
                    "severity": c.severity.value,
                    "message": c.message,
                })
                if c.passed:
                    icon_cls = "bi bi-check-circle-fill text-success"
                elif c.severity.value == "critical":
                    icon_cls = "bi bi-x-circle-fill text-danger"
                else:
                    icon_cls = "bi bi-exclamation-triangle-fill text-warning"
                popover_items.append(
                    html.Div([
                        html.I(className=f"{icon_cls} me-2"),
                        html.Span(c.name, className="small"),
                    ], className="mb-1", title=c.message)
                )

            popover_content = html.Div(popover_items, style={"maxHeight": "300px", "overflowY": "auto"})
            if not report.ready:
                popover_content = html.Div([
                    popover_content,
                    html.Hr(className="my-2"),
                    html.Div("Click badge to go to Preparation tab", className="text-muted small fst-italic"),
                ])

            return (
                badge_children,
                badge_color,
                {"ready": report.ready, "checks": checks_data, "message": ""},
                popover_content,
            )
        except Exception as e:
            logging.error(f"Readiness check failed: {e}")
            return (
                [html.I(className="bi bi-dash-circle me-1"), "Unknown"],
                "secondary",
                {"ready": False, "checks": [], "message": str(e)},
                html.Div(f"Error: {str(e)}", className="text-danger small"),
            )

    app.clientside_callback(
        """
        function(n_clicks, readiness) {
            if (!n_clicks || !readiness) return dash_clientside.no_update;
            if (readiness.ready) return dash_clientside.no_update;
            return "preparation-tab";
        }
        """,
        Output("tabs", "active_tab", allow_duplicate=True),
        Input("readiness-badge", "n_clicks"),
        State("readiness-state", "data"),
        prevent_initial_call=True,
    )

    # ========================================================================
    # Config Status Badge (Auto-save indicator)
    # ========================================================================

    @app.callback(
        [
            Output("config-status-badge", "children"),
            Output("config-status-badge", "color"),
            Output("config-status-badge", "style"),
        ],
        Input("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_config_badge(config):
        """Show config save status in header badge."""
        from nanometa_live.core.utils.paths import NanometaPaths
        paths = NanometaPaths.from_config(config or {})
        last_session = str(paths.last_session_yaml)
        badge_style = {"fontSize": "0.75rem", "display": "inline-block"}
        if os.path.exists(last_session):
            return "Auto-saved", "success", badge_style
        return "Not saved", "secondary", badge_style

    # ========================================================================
    # Sample Management Callbacks (Multi-sample/Barcode Support)
    # ========================================================================
