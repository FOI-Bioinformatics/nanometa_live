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
from nanometa_live.app.app import background_callback_manager

# Readiness single source of truth. ONE callback runs ReadinessChecker and
# writes the ``readiness-state`` Store; the header pill and the
# Preparation-tab checklist are both pure renderers of that Store, so they
# cannot drift out of sync. (The previous header-only TTL cache keyed on a
# partial config fingerprint was the cause of the reported mismatch.)

# Severity-string -> icon class for the header popover/pill (the Store carries
# severity as the enum's string value, not the enum object).
_SEVERITY_ICON = {
    "critical": "bi bi-x-circle-fill text-danger",
    "warning": "bi bi-exclamation-triangle-fill text-warning",
    "info": "bi bi-info-circle-fill text-info",
}


def _serialize_report(report) -> Dict[str, Any]:
    """Serialize a ReadinessReport into the readiness-state Store schema.

    The schema is a superset of the legacy ``{ready, checks}`` shape so
    existing consumers (e.g. the Start button gate in status.py) keep working
    while the renderers gain ``summary`` and per-check ``severity``/``message``.
    """
    return {
        "ready": report.ready,
        "summary": report.summary(),
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "severity": c.severity.value,
                "message": c.message,
            }
            for c in report.checks
        ],
        "computed_at": time.time(),
        "error": None,
    }


def _empty_readiness_state(message: str) -> Dict[str, Any]:
    """Readiness-state value when there is no config or the check errored."""
    return {
        "ready": False,
        "summary": {"total": 0, "passed": 0, "failed": 0,
                    "critical_failures": 0, "warnings": 0},
        "checks": [],
        "computed_at": time.time(),
        "error": message,
    }


# Best-effort per-process skip so an idle update-interval tick does not re-run
# ReadinessChecker's subprocess probes (docker info, nextflow -version) when the
# readiness-relevant config is unchanged. Belt-and-braces with the prev-state
# equality compare below, which robustly suppresses Store rewrites even across
# DiskcacheManager worker processes (it reads the published Store as State).
_READINESS_TTL = 60.0
_readiness_lock = threading.Lock()
_readiness_last: Dict[str, Any] = {"fingerprint": None, "ts": 0.0}


def _readiness_fingerprint(config: Optional[Dict[str, Any]]) -> str:
    """Hash only the config fields the readiness checks actually read."""
    if not config:
        return "no-config"
    relevant = {
        k: config.get(k) for k in (
            "kraken_db", "main_dir", "results_output_directory",
            "nanopore_output_directory", "pipeline_source", "pipeline_profile",
            "pipeline_cache_dir", "blast_validation", "network_check_enabled",
            "offline_mode",
        )
    }
    return hashlib.md5(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def _readiness_unchanged(prev: Optional[Dict[str, Any]],
                         new: Dict[str, Any]) -> bool:
    """True when two readiness states are equivalent ignoring ``computed_at``.

    Used to skip rewriting the Store (and thus re-firing the renderers, which
    would re-open the checklist every interval tick) when nothing meaningful
    changed.
    """
    if not prev:
        return False
    return (
        prev.get("ready") == new.get("ready")
        and prev.get("error") == new.get("error")
        and prev.get("summary") == new.get("summary")
        and prev.get("checks") == new.get("checks")
    )


def register_readiness(app, backend_manager):
    # Recompute callback: the ONLY place that runs ReadinessChecker. It writes
    # the shared readiness-state Store; both the header pill (below) and the
    # Preparation-tab checklist render from that Store, so they stay in sync.
    #
    # Backgrounded because the cold path shells out to ``docker info`` (5 s) and
    # ``nextflow -version`` (10 s) plus other probes -- up to ~15-20 s on the
    # first run after a config change. A DiskcacheManager worker keeps the
    # Werkzeug request thread responsive. ``check-readiness-btn`` is a direct
    # Input so the operator's "Check Everything" forces an immediate recompute.
    @app.callback(
        Output("readiness-state", "data"),
        Input("update-interval", "n_intervals"),
        Input("app-config", "data"),
        Input("check-readiness-btn", "n_clicks"),
        State("readiness-state", "data"),
        background=True,
        manager=background_callback_manager,
    )
    def update_readiness_state(n_intervals, config, n_clicks, prev_state):
        """Compute readiness and publish it to the shared Store, deduplicated.

        Idle update-interval ticks must not re-run the checker's subprocess
        probes or rewrite the Store -- a Store rewrite re-fires the renderers and
        would re-open the checklist every 30 s, fighting the operator's manual
        collapse. So: a manual "Check Everything" click always recomputes; an
        unchanged config within the TTL skips the recompute entirely; and even
        when we do recompute, an unchanged result returns no_update so the Store
        (and the renderers) stay put.
        """
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

        try:
            forced = (dash.ctx.triggered_id == "check-readiness-btn")
        except Exception:
            forced = False

        if not config:
            new = _empty_readiness_state("No configuration loaded")
            return no_update if _readiness_unchanged(prev_state, new) else new

        fingerprint = _readiness_fingerprint(config)
        now = time.time()
        if not forced:
            with _readiness_lock:
                fresh = (_readiness_last["fingerprint"] == fingerprint
                         and (now - _readiness_last["ts"]) < _READINESS_TTL)
            if fresh:
                return no_update

        try:
            report = ReadinessChecker().check_readiness(config)
            new = _serialize_report(report)
        except Exception as e:
            logging.error(f"Readiness check failed: {e}")
            new = _empty_readiness_state(str(e))

        with _readiness_lock:
            _readiness_last["fingerprint"] = fingerprint
            _readiness_last["ts"] = now

        if forced:
            return new
        return no_update if _readiness_unchanged(prev_state, new) else new

    @app.callback(
        Output("readiness-badge", "children"),
        Output("readiness-badge", "color"),
        Output("readiness-popover-body", "children"),
        Input("readiness-state", "data"),
    )
    def render_readiness_badge(state):
        """Render the header readiness pill from the shared Store (no I/O)."""
        state = state or {}
        checks = state.get("checks") or []
        error = state.get("error")

        if not checks:
            if error and error != "No configuration loaded":
                return (
                    [html.I(className="bi bi-dash-circle me-1"), "Unknown"],
                    "secondary",
                    html.Div(f"Error: {error}", className="text-danger small"),
                )
            if error == "No configuration loaded":
                return (
                    [html.I(className="bi bi-dash-circle me-1"), "Not configured"],
                    "secondary",
                    html.Div("Load a configuration to see readiness checks.",
                             className="text-muted small"),
                )
            # Initial Store value, before the first recompute lands.
            return (
                [html.I(className="bi bi-hourglass-split me-1"), "Checking..."],
                "secondary",
                html.Div("Running readiness checks...", className="text-muted small"),
            )

        summary = state.get("summary", {})
        ready = state.get("ready", False)
        if ready:
            badge_children = [html.I(className="bi bi-check-circle-fill me-1"), "Ready"]
            badge_color = "success"
        else:
            badge_children = [
                html.I(className="bi bi-exclamation-triangle-fill me-1"),
                f"{summary.get('passed', 0)}/{summary.get('total', 0)} checks",
            ]
            badge_color = "danger" if summary.get("critical_failures", 0) > 0 else "warning"

        popover_items = []
        for c in checks:
            if c.get("passed"):
                icon_cls = "bi bi-check-circle-fill text-success"
            else:
                icon_cls = _SEVERITY_ICON.get(c.get("severity"), "bi bi-dash-circle text-muted")
            popover_items.append(
                html.Div([
                    html.I(className=f"{icon_cls} me-2"),
                    html.Span(c.get("name", ""), className="small"),
                ], className="mb-1", title=c.get("message", ""))
            )
        popover_content = html.Div(popover_items, style={"maxHeight": "300px", "overflowY": "auto"})
        if not ready:
            popover_content = html.Div([
                popover_content,
                html.Hr(className="my-2"),
                html.Div("Click badge to go to Watchlist & Preparation",
                         className="text-muted small fst-italic"),
            ])
        return badge_children, badge_color, popover_content

    app.clientside_callback(
        """
        function(n_clicks, readiness) {
            if (!n_clicks || !readiness) return dash_clientside.no_update;
            if (readiness.ready) return dash_clientside.no_update;
            return "watchlist-tab";
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
