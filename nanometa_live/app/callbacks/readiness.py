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


# Skip window for an idle update-interval tick, so it does not re-run
# ReadinessChecker's subprocess probes (docker info ~5 s, nextflow -version
# ~10 s) when the readiness-relevant config is unchanged.
#
# The state MUST live in a Store, not in this module. This callback is
# background=True, and DiskcacheManager starts a NEW OS process per invocation
# (app.py forces the "spawn" start method), so a module-level dict is
# re-initialised on every single call and the TTL never once fired -- the
# probes ran on every tick for the life of the session. The Store is written
# by the worker and read back as State on the next call, which is the only
# channel that survives the process boundary.
_READINESS_TTL = 60.0


def _probe_window_is_fresh(stamp: Optional[Dict[str, Any]],
                           fingerprint: str,
                           now: float) -> bool:
    """True when the last probe run covers *fingerprint* and is within the TTL.

    ``stamp`` is the ``readiness-probe-stamp`` Store value, written on every
    recompute (unlike ``readiness-state``, which is deliberately left alone
    when the result is unchanged so the checklist does not re-open under the
    operator). Keeping the timestamp on its own Store means an unchanged result
    still refreshes the TTL window; folding it into readiness-state would have
    made the window unrenewable, and the probes would resume every tick after
    the first expiry.
    """
    if not isinstance(stamp, dict):
        return False
    if stamp.get("fingerprint") != fingerprint:
        return False
    try:
        ts = float(stamp.get("ts") or 0.0)
    except (TypeError, ValueError):
        return False
    return (now - ts) < _READINESS_TTL


def _readiness_fingerprint(
    config: Optional[Dict[str, Any]],
    watchlist_entries: Optional[list] = None,
) -> str:
    """Hash only the inputs the readiness checks actually read.

    Includes the enabled-watchlist signature so toggling pathogens in the
    Watchlist & Preparation tab recomputes the watchlist checks instead of
    being skipped by the TTL/dedup short-circuit.
    """
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
    relevant["_watchlist"] = sorted(
        e.get("taxid") for e in (watchlist_entries or [])
        if e.get("enabled", True) and e.get("taxid")
    )
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
        Output("readiness-probe-stamp", "data"),
        Input("update-interval", "n_intervals"),
        Input("app-config", "data"),
        Input("check-readiness-btn", "n_clicks"),
        Input("genome-download-complete", "data"),
        State("readiness-state", "data"),
        State("watchlist-entries-snapshot", "data"),
        State("readiness-probe-stamp", "data"),
        background=True,
        manager=background_callback_manager,
    )
    def update_readiness_state(n_intervals, config, n_clicks, genome_change,
                               prev_state, watchlist_entries, probe_stamp):
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

        # A genome import/download/delete changes neither config nor watchlist,
        # so the fingerprint/TTL gate below would skip the recompute and the
        # Watchlist-Genomes / BLAST-Databases checks would stay stale. Treat
        # genome-download-complete as a forcing trigger, and reload the (stale)
        # worker-process genome singleton before the checks read it.
        try:
            trig = dash.ctx.triggered_id
        except Exception:
            trig = None
        genome_set_changed = (trig == "genome-download-complete")
        forced = trig in ("check-readiness-btn", "genome-download-complete")

        if not config:
            new = _empty_readiness_state("No configuration loaded")
            return (
                no_update if _readiness_unchanged(prev_state, new) else new,
                no_update,
            )

        fingerprint = _readiness_fingerprint(config, watchlist_entries)
        now = time.time()
        if not forced and _probe_window_is_fresh(probe_stamp, fingerprint, now):
            # Same readiness-relevant config, probed recently: skip the whole
            # recompute, including the docker/nextflow subprocess probes.
            return no_update, no_update

        try:
            # Pass the watchlist snapshot: this callback runs in a background
            # worker where the WatchlistManager singleton is empty, so the
            # watchlist checks would otherwise always report "not enabled".
            report = ReadinessChecker().check_readiness(
                config, watchlist_entries=watchlist_entries,
                reload_genomes=genome_set_changed,
            )
            new = _serialize_report(report)
        except Exception as e:
            logging.error(f"Readiness check failed: {e}")
            new = _empty_readiness_state(str(e))

        # Always refresh the probe window, even when the report itself is
        # unchanged and readiness-state is left alone below. No renderer reads
        # this Store, so writing it cannot disturb the operator's checklist.
        stamp = {"fingerprint": fingerprint, "ts": now}

        if forced:
            return new, stamp
        return (
            no_update if _readiness_unchanged(prev_state, new) else new,
            stamp,
        )

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
