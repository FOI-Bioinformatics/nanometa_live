"""Welcome modal, wizard navigation, open-results modal and storage-location callbacks."""

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


def register_navigation(app, backend_manager):
    @app.callback(
        [
            Output("welcome-modal", "is_open"),
            Output("tabs", "active_tab", allow_duplicate=True),
        ],
        [
            Input("welcome-shown", "data"),
            Input("close-welcome-modal", "n_clicks"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def manage_welcome_modal(already_shown, close_clicks):
        """Show the welcome modal on first visit, dismiss on button click."""
        triggered = dash.ctx.triggered_id
        if triggered == "close-welcome-modal":
            return False, "config-tab"
        # Show on first visit only
        if not already_shown:
            return True, no_update
        return False, no_update

    @app.callback(
        Output("welcome-shown", "data"),
        Input("close-welcome-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def mark_welcome_shown(_):
        """Persist that the welcome modal has been shown."""
        return True

    # ========================================================================
    # Step Navigation Buttons
    # ========================================================================

    @app.callback(
        Output("tabs", "active_tab", allow_duplicate=True),
        Output("apply-config-button", "n_clicks", allow_duplicate=True),
        Input("config-next-watchlist-btn", "n_clicks"),
        State("apply-config-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_config_to_watchlist(_n_next, n_apply):
        """Advance the wizard from Configuration to Watchlist & Preparation.

        Also auto-fires Apply Settings so any unsaved edits in the
        Configuration form are persisted before navigation. The
        existing apply_config_changes callback runs validation and
        emits a toast on failure -- the toast is visible on every
        tab via the global notification container, so the operator
        still sees errors after the tab has switched. Bumping
        apply-config-button.n_clicks via allow_duplicate keeps the
        apply logic single-sourced (no duplicated validate-and-save
        path here).
        """
        return "watchlist-tab", (n_apply or 0) + 1

    @app.callback(
        Output("tabs", "active_tab", allow_duplicate=True),
        Input("merged-next-deployment-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_preparation_to_deployment(_):
        """Navigate from the merged Watchlist & Preparation tab to Deployment."""
        return "deployment-tab"

    # ========================================================================
    # Session restore is explicit, not automatic
    # ========================================================================
    # Boot is always fresh: nanometa_live.py main() starts from a default
    # config and never auto-loads ~/.nanometa/configs/last-session.yaml.
    # The autosave still happens on Apply Settings, so a prior session can
    # be restored deliberately from Configuration > Load ("Last Session").
    # To view a finished run's data, use the "Open Results" control in the
    # secondary bar (see open_results_* callbacks) -- viewing a results
    # folder is kept separate from restoring a pipeline configuration.

    @app.callback(
        Output("open-results-modal", "is_open", allow_duplicate=True),
        Output("open-results-list", "children"),
        Input("open-results-btn", "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def open_results_modal(n_clicks, config):
        """Open the run picker and list the run folders under the project's
        results/ directory. Each run is a clickable item; a folder is treated
        as a run when it holds nanometanf output (detect_existing_results)."""
        if not n_clicks:
            raise PreventUpdate

        from nanometa_live.core.utils.paths import NanometaPaths
        results_root = NanometaPaths.from_config(config or {}).results
        items = []
        try:
            entries = sorted(
                (e for e in os.scandir(str(results_root)) if e.is_dir()),
                key=lambda e: e.name,
            )
        except OSError:
            entries = []

        for entry in entries:
            found = backend_manager.detect_existing_results(entry.path)
            if not found:
                continue  # not a run folder (no nanometanf output)
            meta = backend_manager.read_run_metadata(entry.path)
            subtitle = f"{', '.join(found[:4])}{'...' if len(found) > 4 else ''}"
            when = (meta or {}).get("written_at")
            detail = f"produced {when}" if when else "no run record"
            items.append(
                dbc.ListGroupItem(
                    [
                        html.Div([
                            html.I(className="bi bi-folder-fill text-warning me-2"),
                            html.Strong(entry.name),
                            html.Span(f"  -  {detail}", className="text-muted small ms-1"),
                        ]),
                        html.Div(subtitle, className="text-muted small"),
                    ],
                    id={"type": "open-results-run", "path": entry.path},
                    action=True,
                    n_clicks=0,
                )
            )

        if items:
            body = [
                html.P(
                    [
                        "Runs in this project (",
                        html.Code(str(results_root)),
                        "):",
                    ],
                    className="small text-muted",
                ),
                dbc.ListGroup(items),
            ]
        else:
            body = html.Div([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(
                    "No runs found in this project yet. Start an analysis to "
                    "create one, or use 'Browse another folder' to open results "
                    "from elsewhere.",
                    className="text-muted",
                ),
            ])
        return True, body

    @app.callback(
        Output("open-results-modal", "is_open", allow_duplicate=True),
        Input("open-results-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_open_results_modal(n_clicks):
        """Close the run picker."""
        if not n_clicks:
            raise PreventUpdate
        return False

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Output("open-results-modal", "is_open", allow_duplicate=True),
        Output("toast-message", "data", allow_duplicate=True),
        Output("selected-sample", "data", allow_duplicate=True),
        Input({"type": "open-results-run", "path": ALL}, "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def select_run_to_view(clicks, config):
        """Point the dashboard at a run picked from the project list. Transient
        view action: in-memory app-config only (never persisted)."""
        if not clicks or not any(clicks) or not dash.ctx.triggered_id:
            raise PreventUpdate
        path = dash.ctx.triggered_id.get("path") if isinstance(dash.ctx.triggered_id, dict) else None
        if not path or not os.path.isdir(path):
            return no_update, False, {
                "type": "error", "title": "Could not open run",
                "message": "That run folder no longer exists.",
            }, no_update
        new_config = dict(config or {})
        new_config["results_output_directory"] = path
        new_config["main_dir"] = path
        new_config["visualization_only"] = True
        return new_config, False, {
            "type": "success", "title": "Viewing run",
            "message": f"Now displaying results from {path}.",
        }, "All Samples"

    @app.callback(
        Output("open-results-modal", "is_open", allow_duplicate=True),
        Output("folder-browser-modal", "is_open", allow_duplicate=True),
        Output("browse-target-field", "data", allow_duplicate=True),
        Output("current-browse-path", "data", allow_duplicate=True),
        Input("open-results-browse-btn", "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def open_results_browse_elsewhere(n_clicks, config):
        """Escape hatch: open the generic folder browser (target 'open-results')
        for results outside the project. Closes the run picker first."""
        if not n_clicks:
            raise PreventUpdate
        start = resolve_outdir_for_fingerprint(config or {})
        if not start or not os.path.isdir(start):
            start = os.path.expanduser("~")
        return False, True, "open-results", start

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Output("folder-browser-modal", "is_open", allow_duplicate=True),
        Output("toast-message", "data", allow_duplicate=True),
        Output("selected-sample", "data", allow_duplicate=True),
        Input("confirm-directory-select", "n_clicks"),
        State("current-browse-path", "data"),
        State("browse-target-field", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def apply_open_results(confirm_clicks, selected_path, target_field, config):
        """When the folder browser was opened for 'open-results', point the
        dashboard at the chosen folder. This is a transient view action: it
        updates the in-memory app-config only (results dir + view-only mode)
        and never writes last-session.yaml, keeping viewing separate from
        restoring a configuration. The fingerprint/sample callbacks refresh
        the dashboard off the app-config change."""
        if not confirm_clicks or target_field != "open-results":
            raise PreventUpdate
        if not selected_path or not os.path.isdir(selected_path):
            return (
                no_update,
                False,
                {
                    "type": "error",
                    "title": "Could not open results",
                    "message": "The selected folder does not exist.",
                },
                no_update,
            )
        new_config = dict(config or {})
        new_config["results_output_directory"] = selected_path
        new_config["main_dir"] = selected_path
        # View past data read-only; the operator must reconfigure inputs to run.
        new_config["visualization_only"] = True
        return (
            new_config,
            False,
            {
                "type": "success",
                "title": "Viewing results",
                "message": f"Now displaying results from {selected_path}.",
            },
            "All Samples",
        )

    @app.callback(
        Output("current-results-display", "children"),
        Input("app-config", "data"),
    )
    def update_current_results_display(config):
        """Show the results folder currently driving the dashboard, or a
        clear empty state on a fresh boot."""
        path = resolve_outdir_for_fingerprint(config or {})
        if path:
            return path
        return html.Span(
            "(no results loaded) - Open Results... to view a finished run, "
            "or configure inputs and Start Analysis.",
            className="fst-italic",
        )

    # ========================================================================
    # Storage Locations panel
    # ========================================================================
    # The 8 storage zones below are surfaced read-only in the
    # Configuration tab so the operator can see exactly where their
    # genomes, configs, BLAST DBs, mappings, watchlists, caches,
    # logs, and DB registry live -- without having to `cd` into a
    # hidden dot-directory. The Open button shells out to the OS
    # file manager via app/utils/file_manager_open.py.

    @app.callback(
        Output("storage-locations-table", "children"),
        Input("app-data-dir", "data"),
        Input("app-config", "data"),
    )
    def render_storage_locations_table(data_dir, config):
        """Render the Storage Locations accordion body.

        The body has two parts:

        1. A header row showing the active data_dir with a Copy button
           and a one-line note that the value is set via the
           ``--data-dir`` CLI flag (a restart is required to change
           it; runtime mutation of data_dir would require re-init of
           BackendManager, DiskcacheManager, and several singleton
           directory layouts that are wired at app start).
        2. A per-zone table with absolute paths and Open buttons.
           The genome / BLAST rows honour ``genome_cache_dir`` (the
           one zone that is operator-configurable today); the other
           rows are rooted at data_dir.
        """
        if not data_dir:
            return html.Div("Data directory not configured.", className="text-muted")

        genome_root_raw = (config or {}).get("genome_cache_dir") or data_dir
        genome_root = os.path.expanduser(genome_root_raw)
        data_root = os.path.expanduser(data_dir)

        zones = [
            ("Configurations", os.path.join(data_root, "configs"),
             "Saved YAML configs incl. last-session.yaml"),
            ("Genomes (FASTA)", os.path.join(genome_root, "genomes"),
             "Downloaded reference genomes for watchlist species"),
            ("BLAST databases", os.path.join(genome_root, "blast"),
             "Per-taxid BLAST indices built from downloaded genomes"),
            ("Taxid mappings", os.path.join(data_root, "mappings"),
             "Cached Kraken2 taxid -> species mappings"),
            ("Watchlists", os.path.join(data_root, "watchlists"),
             "Operator-uploaded custom watchlist YAMLs"),
            ("Application cache", os.path.join(data_root, "cache"),
             "Background-callback (Dash) cache; safe to delete"),
            ("Logs", os.path.join(data_root, "logs"),
             "App and Nextflow trace logs"),
            ("Custom DB registry",
             os.path.join(data_root, "kraken2_databases.local.yaml"),
             "Operator-managed Kraken2 DB list (merges with bundled)"),
        ]

        rows = []
        for name, path, hint in zones:
            exists = os.path.exists(path)
            badge = (
                dbc.Badge("present", color="success", className="ms-2")
                if exists
                else dbc.Badge("not yet created", color="secondary", className="ms-2")
            )
            rows.append(
                html.Tr([
                    html.Td([
                        html.Strong(name),
                        badge,
                        html.Br(),
                        html.Small(hint, className="text-muted"),
                    ], style={"verticalAlign": "middle"}),
                    html.Td(
                        html.Code(path, style={"wordBreak": "break-all"}),
                        style={"verticalAlign": "middle"},
                    ),
                    html.Td(
                        dbc.Button(
                            [html.I(className="bi bi-folder2-open me-1"), "Open"],
                            id={"type": "storage-open-btn", "path": path},
                            color="outline-primary",
                            size="sm",
                            disabled=not exists,
                            n_clicks=0,
                        ),
                        style={"verticalAlign": "middle", "whiteSpace": "nowrap"},
                    ),
                ])
            )

        # data_dir header row. A small alert with the absolute path,
        # a one-click clipboard copy, and a one-line restart-required
        # note. dcc.Clipboard avoids hand-rolled JS and is a
        # first-class Dash 4 component.
        header = dbc.Alert(
            [
                html.Div([
                    html.Strong("Data root: "),
                    html.Code(data_root, id="storage-data-root-code",
                              style={"wordBreak": "break-all"}),
                    dcc.Clipboard(
                        target_id="storage-data-root-code",
                        title="Copy path",
                        style={
                            "marginLeft": "8px",
                            "cursor": "pointer",
                            "color": "#0d6efd",
                        },
                    ),
                ], className="mb-1"),
                html.Small(
                    [
                        html.I(className="bi bi-info-circle me-1"),
                        "Set with ",
                        html.Code("--data-dir /path"),
                        " on the command line. Restart required to ",
                        "take effect.",
                    ],
                    className="text-muted",
                ),
            ],
            color="light",
            className="mb-3",
        )

        table = dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Zone", style={"width": "30%"}),
                    html.Th("Absolute path"),
                    html.Th("", style={"width": "1%"}),
                ])),
                html.Tbody(rows),
            ],
            hover=True,
            responsive=True,
            className="mb-0",
        )

        return [header, table]

    @app.callback(
        Output("toast-message", "data", allow_duplicate=True),
        Input({"type": "storage-open-btn", "path": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def open_storage_location(n_clicks_list):
        """Launch the OS file manager at the path encoded in the
        clicked button's pattern-matching id.

        ``prevent_initial_call=True`` already gates against the
        startup dispatch where every n_clicks is None / 0, so the
        only check needed here is that dash.ctx.triggered_id is a real
        pattern-match dict (it is when a click fires; it is None for
        the rare degenerate case). The previous ``any()`` guard was
        redundant and -- because every button rendered with
        n_clicks=0 -- could be misread as the source of the
        no-op-on-click bug.

        The INFO log line provides a single point to confirm whether
        the callback actually fires when the operator clicks Open.
        Errors come back as a toast rather than an exception so a
        failing helper does not propagate up the Dash callback
        chain.
        """
        triggered = dash.ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            raise PreventUpdate
        # Pattern-matching ALL inputs fire when buttons first render
        # (n_clicks goes from non-existent to 0), even with
        # prevent_initial_call=True. Require a real click to avoid
        # the file manager opening at app startup.
        if not n_clicks_list or not any(n_clicks_list):
            raise PreventUpdate
        path = triggered.get("path")
        logging.info("Storage Locations: opening %s", path)
        from nanometa_live.app.utils.file_manager_open import open_in_file_manager
        err = open_in_file_manager(path)
        if err:
            return {
                "type": "error",
                "title": "Could not open location",
                "message": err,
            }
        return {
            "type": "info",
            "title": "Opened in file manager",
            "message": path,
        }

    @app.callback(
        Output("start-stop-button", "n_clicks", allow_duplicate=True),
        Input("preparation-start-analysis-btn", "n_clicks"),
        State("start-stop-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def proxy_preparation_start_to_header(n_prep, n_header):
        """Proxy the Preparation-tab Start Analysis button into the
        header's start-stop-button.

        The existing start_or_prompt_stop callback gates on
        start-stop-button.n_clicks: bumping that count from here
        triggers exactly the same readiness check, collision-modal,
        and backend-launch flow as if the operator had clicked the
        header button. Keeping the launch logic single-sourced
        avoids accidental drift between the two CTAs.
        """
        if not n_prep:
            raise PreventUpdate
        return (n_header or 0) + 1
