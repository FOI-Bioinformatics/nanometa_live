"""
Callbacks for the Preparation tab.

Handles:
- Readiness checking
- Kraken2 database download options (moved from config_tab)
- Taxid mapping / DB rescan (moved from watchlist_tab)
- Genome downloads with progress tracking (moved from watchlist_tab)
- BLAST database building with progress tracking (moved from watchlist_tab)
- Preparation execution
- Bundle export/import
"""

import logging
import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dash_bootstrap_components as dbc
from dash import html, Input, Output, State, callback, no_update, ctx, ALL
from dash.exceptions import PreventUpdate

from nanometa_live.app.app import background_callback_manager

logger = logging.getLogger(__name__)


def register_preparation_callbacks(app):
    """Register all preparation tab callbacks."""

    # --- Readiness check ---
    @app.callback(
        Output("readiness-results", "children"),
        Input("check-readiness-btn", "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def check_readiness(n_clicks, config):
        if not n_clicks:
            raise PreventUpdate

        try:
            from nanometa_live.core.workflow.readiness_checker import (
                ReadinessChecker, Severity,
            )
            checker = ReadinessChecker()
            report = checker.check_readiness(config)

            rows = []
            for check in report.checks:
                if check.passed:
                    icon = html.I(className="bi bi-check-circle-fill text-success me-2")
                elif check.severity == Severity.CRITICAL:
                    icon = html.I(className="bi bi-x-circle-fill text-danger me-2")
                elif check.severity == Severity.WARNING:
                    icon = html.I(className="bi bi-exclamation-triangle-fill text-warning me-2")
                else:
                    icon = html.I(className="bi bi-info-circle-fill text-info me-2")

                badge_color = {
                    Severity.CRITICAL: "danger",
                    Severity.WARNING: "warning",
                    Severity.INFO: "info",
                }.get(check.severity, "secondary")

                rows.append(
                    html.Div([
                        icon,
                        dbc.Badge(check.severity.value.upper(), color=badge_color,
                                  className="me-2", style={"width": "70px"}),
                        html.Span(check.name, className="fw-semibold me-2"),
                        html.Span(check.message, className="text-muted"),
                    ], className="mb-2 d-flex align-items-center")
                )

            summary = report.summary()
            status_color = "success" if report.ready else "danger"
            header = dbc.Alert(
                [
                    html.Strong("Ready" if report.ready else "Not Ready"),
                    f" - {summary['passed']}/{summary['total']} checks passed",
                ],
                color=status_color,
                className="mb-3",
            )

            return html.Div([header] + rows)

        except Exception as e:
            logger.error(f"Readiness check failed: {e}", exc_info=True)
            return dbc.Alert(f"Error: {e}", color="danger")

    # --- Start Preparation ---
    @app.callback(
        Output("prep-progress-area", "children"),
        Output("prep-result-area", "children"),
        Output("start-prep-btn", "disabled"),
        Input("start-prep-btn", "n_clicks"),
        State("app-config", "data"),
        State("prep-options", "value"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("start-prep-btn", "disabled"), True, False),
            (Output("cancel-prep-btn", "style"), {"display": "inline-block"}, {"display": "none"}),
        ],
        progress=[
            Output("prep-progress-area", "children"),
        ],
    )
    def run_preparation(set_progress, n_clicks, config, options):
        if not n_clicks:
            raise PreventUpdate

        skip_existing = "skip_existing" in (options or [])

        def progress_callback(progress):
            set_progress(
                html.Div([
                    html.Div([
                        html.Strong(progress.stage_label),
                        html.Span(
                            f" ({progress.stage_index + 1}/{progress.total_stages})",
                            className="text-muted ms-1"
                        ),
                    ]),
                    html.Div(progress.stage_detail, className="text-muted small"),
                    dbc.Progress(
                        value=progress.stage_progress,
                        className="mb-1",
                        striped=True, animated=True,
                        style={"height": "8px"},
                    ),
                    html.Div("Overall", className="small text-muted mt-2"),
                    dbc.Progress(
                        value=progress.overall_progress,
                        className="mb-1",
                        striped=True, animated=True,
                    ),
                ])
            )

        try:
            from nanometa_live.core.workflow.mobile_lab_preparer import MobileLabPreparer
            preparer = MobileLabPreparer(
                config=config,
                progress_callback=progress_callback,
            )
            result = preparer.prepare(skip_existing=skip_existing)

            if result.success:
                alert = dbc.Alert([
                    html.I(className="bi bi-check-circle me-2"),
                    html.Strong("Preparation complete. "),
                    f"{len(result.stages_completed)} stages completed. ",
                    f"{result.genomes_downloaded} genomes downloaded, "
                    f"{result.blast_dbs_built} BLAST DBs built.",
                ], color="success")
            else:
                alert = dbc.Alert([
                    html.I(className="bi bi-x-circle me-2"),
                    html.Strong("Preparation failed. "),
                    html.Br(),
                    html.Ul([html.Li(e) for e in result.errors]),
                    html.Hr(),
                    dbc.Button(
                        [html.I(className="bi bi-arrow-clockwise me-2"), "Retry Preparation"],
                        id="retry-preparation-btn",
                        color="warning",
                        size="sm"
                    )
                ], color="danger")

            warnings_div = html.Div()
            if result.warnings:
                warnings_div = dbc.Alert([
                    html.Strong("Warnings:"),
                    html.Ul([html.Li(w) for w in result.warnings]),
                ], color="warning", className="mt-2")

            return (
                html.Div(),
                html.Div([alert, warnings_div]),
                False,
            )

        except Exception as e:
            logger.error(f"Preparation failed: {e}", exc_info=True)
            return (
                html.Div(),
                dbc.Alert([
                    html.I(className="bi bi-x-circle me-2"),
                    html.Strong("Preparation error: "),
                    str(e),
                    html.Hr(),
                    dbc.Button(
                        [html.I(className="bi bi-arrow-clockwise me-2"), "Retry Preparation"],
                        id="retry-preparation-btn",
                        color="warning",
                        size="sm"
                    )
                ], color="danger"),
                False,
            )

    # --- Export Bundle ---

    @app.callback(
        Output("export-readiness-issues", "children"),
        Output("export-force-area", "style"),
        Output("export-result", "children"),
        Output("export-force-check", "value"),
        Input("export-bundle-btn", "n_clicks"),
        State("bundle-export-filename", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def export_bundle(n_clicks, filename, config):
        """Check readiness, then export or show issues."""
        if not n_clicks:
            raise PreventUpdate

        # Run readiness check
        try:
            from nanometa_live.core.workflow.readiness_checker import (
                ReadinessChecker, Severity,
            )
            checker = ReadinessChecker()
            report = checker.check_readiness(config or {})
        except Exception as e:
            logger.error(f"Readiness check failed: {e}", exc_info=True)
            return (
                dbc.Alert(f"Readiness check error: {e}", color="danger"),
                {"display": "none"},
                html.Div(),
                False,
            )

        critical = report.critical_failures
        warnings = report.warnings

        # All checks pass — export immediately
        if not critical and not warnings:
            result = _run_export(config, filename)
            return html.Div(), {"display": "none"}, result, False

        # Build issue list
        items = []
        for c in critical:
            items.append(html.Div([
                html.I(className="bi bi-x-octagon-fill text-danger me-2"),
                html.Strong(c.name), html.Span(f": {c.message}"),
            ], className="mb-1"))
        for w in warnings:
            items.append(html.Div([
                html.I(className="bi bi-exclamation-triangle-fill text-warning me-2"),
                html.Strong(w.name), html.Span(f": {w.message}"),
            ], className="mb-1"))

        if critical:
            # Critical failures — block export entirely
            issues = html.Div([
                dbc.Alert([
                    html.I(className="bi bi-x-octagon me-2"),
                    html.Strong("Cannot export. "),
                    "Critical issues must be resolved first:",
                ], color="danger", className="mb-2"),
                html.Div(items, className="ms-2"),
            ])
            return issues, {"display": "none"}, html.Div(), False

        # Warnings only — allow force-export after acknowledgement
        issues = html.Div([
            dbc.Alert([
                html.I(className="bi bi-exclamation-triangle me-2"),
                html.Strong("Setup is incomplete. "),
                "The following items are not fully prepared:",
            ], color="warning", className="mb-2"),
            html.Div(items, className="ms-2"),
        ])
        return issues, {"display": "block"}, html.Div(), False

    @app.callback(
        Output("export-force-btn", "disabled"),
        Input("export-force-check", "value"),
        prevent_initial_call=True,
    )
    def toggle_force_export_btn(checked):
        """Enable force-export button only when checkbox is ticked."""
        return not checked

    @app.callback(
        Output("export-result", "children", allow_duplicate=True),
        Input("export-force-btn", "n_clicks"),
        State("bundle-export-filename", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def force_export_bundle(n_clicks, filename, config):
        """Export bundle after user acknowledged warnings."""
        if not n_clicks:
            raise PreventUpdate
        return _run_export(config, filename)

    def _run_export(config, filename=None):
        """Perform the actual bundle export. Returns an Alert component."""
        try:
            from nanometa_live.core.workflow.bundle_manager import BundleManager
            downloads = Path.home() / "Downloads"
            downloads.mkdir(exist_ok=True)
            output_path = downloads / (filename or "mobile_lab_bundle.tar.gz")

            manager = BundleManager()
            path = manager.export_bundle(str(output_path), config)
            size_mb = path.stat().st_size / (1024 * 1024)

            return dbc.Alert([
                html.I(className="bi bi-check-circle me-2"),
                f"Bundle exported: {path} ({size_mb:.1f} MB)",
            ], color="success")

        except Exception as e:
            logger.error(f"Export failed: {e}", exc_info=True)
            return dbc.Alert(f"Export failed: {e}", color="danger")

    # --- Import Bundle ---
    @app.callback(
        Output("import-result", "children"),
        Input("import-bundle-btn", "n_clicks"),
        State("import-bundle-path", "value"),
        State("import-kraken-db-path", "value"),
        prevent_initial_call=True,
    )
    def import_bundle(n_clicks, bundle_path, kraken_db_path):
        if not n_clicks:
            raise PreventUpdate

        if not bundle_path:
            return dbc.Alert("Please provide a bundle path.", color="warning")
        if not kraken_db_path:
            return dbc.Alert("Please provide the Kraken2 database path.", color="warning")

        if not Path(bundle_path).exists():
            return dbc.Alert(f"Bundle not found: {bundle_path}", color="danger")

        try:
            from nanometa_live.core.workflow.bundle_manager import BundleManager
            manager = BundleManager()
            result = manager.import_bundle(bundle_path, kraken_db_path)

            if result["success"]:
                children = [
                    html.I(className="bi bi-check-circle me-2"),
                    "Bundle imported.",
                ]
                if result["warnings"]:
                    children.append(html.Br())
                    children.append(html.Strong("Warnings: "))
                    children.extend([
                        html.Span(w + "; ") for w in result["warnings"]
                    ])
                return dbc.Alert(children, color="success")
            else:
                return dbc.Alert("Import failed.", color="danger")

        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            return dbc.Alert(f"Import failed: {e}", color="danger")

    # =========================================================================
    # Kraken2 Database Download (moved from config_tab.py)
    # =========================================================================

    @app.callback(
        Output("external-kraken-input", "options"),
        Input("kraken-databases", "data")
    )
    def populate_kraken_database_options(databases):
        options = [{"label": "None (use local)", "value": ""}]
        if databases:
            for db_id, db_info in databases.items():
                label = f"{db_id} ({db_info.get('description', '')})"
                options.append({"label": label, "value": db_id})
        return options

    # =========================================================================
    # Rescan DB / Taxid Mapping (moved from watchlist_tab.py)
    # =========================================================================

    @app.callback(
        Output("taxmap-collection", "data", allow_duplicate=True),
        Output("taxmap-database-info", "data"),
        Output("taxmap-rescan-complete", "data"),
        Output("watchlist-table-refresh", "data", allow_duplicate=True),
        Output("taxmap-rescan-status", "children"),
        Input("taxmap-rescan-btn", "n_clicks"),
        State("app-config", "data"),
        State("watchlist-table-refresh", "data"),
        prevent_initial_call=True,
    )
    def run_rescan(n_clicks, config, current_refresh):
        """Callback for Kraken2 database rescan."""
        import sys
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

        logger.info(f"[RESCAN] run_rescan called: n_clicks={n_clicks}")

        if not n_clicks:
            raise PreventUpdate

        kraken_db = config.get("kraken_db", "") if config else ""
        logger.info(f"[RESCAN] Kraken DB path: {kraken_db}")
        if not kraken_db:
            logger.warning("No Kraken2 database configured")
            raise PreventUpdate

        try:
            from nanometa_live.core.taxonomy import get_taxid_mapper

            mapper = get_taxid_mapper()
            success = mapper.load_database(kraken_db)

            if not success:
                logger.error("Failed to load database")
                raise PreventUpdate

            manager = get_watchlist_manager()
            entries = manager.get_entries_with_toggle_state()
            watchlist_entries = [
                {"name": e.get("name", ""), "taxid": e.get("taxid", 0), "rank": e.get("api_rank", "species")}
                for e in entries
            ]

            if not watchlist_entries:
                logger.info("No watchlist entries to map")
                return (None, None, datetime.now().isoformat(), (current_refresh or 0) + 1, "No entries to map")

            total = len(watchlist_entries)
            logger.info(f"Processing {total} watchlist entries")

            collection = mapper.generate_mappings(
                watchlist_entries,
                preserve_manual=False,
            )

            if collection:
                collection_data = collection.to_dict()
                mappings_list = collection_data.get("mappings", [])
                mappings_dict = {}
                for mapping in mappings_list:
                    ncbi_tid = mapping.get("ncbi_taxid")
                    if ncbi_tid:
                        mappings_dict[str(ncbi_tid)] = mapping
                collection_data["mappings"] = mappings_dict
                logger.info(f"Rescan complete: {len(mappings_dict)} mappings prepared")
            else:
                collection_data = None
                logger.warning("Rescan produced no collection data")

            db_info = {
                "path": kraken_db,
                "type": collection.database_type.value if collection else "unknown",
                "hash": collection.database_hash if collection else "",
                "stats": mapper.get_statistics(),
            }

            now = datetime.now().isoformat()
            new_refresh = (current_refresh or 0) + 1

            status = f"Mapped {len(mappings_dict)} entries" if collection_data else "Complete"
            logger.info(f"Rescan returning: mappings={len(mappings_dict) if collection_data else 0}, refresh={new_refresh}")
            return (collection_data, db_info, now, new_refresh, status)

        except Exception as e:
            logger.error(f"Rescan failed: {e}")
            traceback.print_exc()
            return (no_update, no_update, no_update, no_update, f"Error: {str(e)}")

    # =========================================================================
    # Genome Downloads (moved from watchlist_tab.py)
    # =========================================================================

    @app.callback(
        [
            Output("genome-stat-downloaded", "children"),
            Output("genome-stat-missing", "children"),
            Output("genome-stat-blast", "children"),
            Output("genome-stat-size", "children"),
            Output("genome-missing-list", "children"),
            Output("genome-downloaded-list", "children"),
            Output("genome-status-data", "data"),
        ],
        [
            Input("genome-refresh-btn", "n_clicks"),
            Input("genome-download-complete", "data"),
            Input("tabs", "active_tab"),
        ],
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_genome_stats(
        refresh_clicks: int,
        download_complete: Any,
        active_tab: str,
        config: Dict,
    ) -> Tuple:
        """Update genome download statistics and list."""
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
        from nanometa_live.app.layouts.watchlist_layout import (
            create_missing_genome_item,
            create_genome_item,
        )

        manager = get_watchlist_manager()

        cache_dir = None
        if config:
            cache_dir = config.get("genome_cache_dir")
        genome_mgr = get_genome_manager(cache_dir=cache_dir)

        if not manager._loaded and config:
            manager.load_config(config)

        entries = manager.get_entries_with_toggle_state()

        # Collect enabled taxids and count stats scoped to enabled entries
        downloaded = 0
        missing = 0
        with_blast = 0
        total_size = 0
        missing_entries = []
        downloaded_taxids = []
        for entry in entries:
            if not entry.get("enabled"):
                continue
            taxid = entry.get("taxid", 0)
            if not taxid:
                continue
            if genome_mgr.has_genome(taxid):
                downloaded += 1
                downloaded_taxids.append(taxid)
                if genome_mgr.has_blast_db(taxid):
                    with_blast += 1
                meta = genome_mgr._metadata.get(taxid)
                if meta:
                    total_size += meta.file_size
            else:
                missing += 1
                missing_entries.append(entry)

        total_size_mb = round(total_size / (1024 * 1024), 2) if total_size else 0

        if missing_entries:
            missing_list = [
                create_missing_genome_item(entry)
                for entry in missing_entries
            ]
        else:
            missing_list = [
                html.P("All genomes downloaded.", className="text-muted fst-italic")
            ]

        # Show only genomes for enabled entries
        all_genomes = [
            g for g in genome_mgr.get_all_genomes()
            if g.taxid in downloaded_taxids
        ]
        if all_genomes:
            genome_list = [
                create_genome_item(g.to_dict())
                for g in all_genomes
            ]
        else:
            genome_list = [
                html.P("No genomes downloaded yet.", className="text-muted fst-italic")
            ]

        # Store missing entries for background download callback
        missing_data = [
            {"taxid": e.get("taxid", 0), "name": e.get("name", "")}
            for e in missing_entries
        ]

        return (
            str(downloaded),
            str(missing),
            str(with_blast),
            f"{total_size_mb} MB",
            missing_list,
            genome_list,
            missing_data,
        )

    @app.callback(
        output=[
            Output("genome-download-complete", "data", allow_duplicate=True),
        ],
        inputs=[
            Input("genome-download-all-btn", "n_clicks"),
        ],
        state=[
            State("app-config", "data"),
            State("genome-status-data", "data"),
        ],
        background=True,
        manager=background_callback_manager,
        running=[
            (Output("genome-download-modal", "is_open"), True, True),
            (Output("genome-download-all-btn", "disabled"), True, False),
            (Output("genome-download-cancel-btn", "style"), {"display": "inline-block"}, {"display": "none"}),
            (Output("genome-download-close-btn", "style"), {"display": "none"}, {"display": "inline-block"}),
        ],
        cancel=[Input("genome-download-cancel-btn", "n_clicks")],
        progress=[
            Output("genome-download-progress-bar", "value"),
            Output("genome-download-progress-text", "children"),
            Output("genome-download-progress-detail", "children"),
            Output("genome-download-log", "children"),
            Output("genome-download-status-badge", "children"),
        ],
        prevent_initial_call=True,
    )
    def download_missing_genomes(
        set_progress,
        download_clicks: int,
        config: Dict,
        missing_store: List,
    ) -> Tuple:
        """Handle genome download requests with real-time progress tracking.

        Uses missing_store (from genome-status-data) populated by
        update_genome_stats in the main process, since this background
        callback runs in a separate process and cannot access the
        in-memory WatchlistManager state.
        """
        if not download_clicks:
            raise PreventUpdate

        from nanometa_live.core.utils.genome_manager import get_genome_manager

        log_entries = []

        def add_log(message: str, level: str = "info"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            color_class = {
                "info": "text-info",
                "success": "text-success",
                "warning": "text-warning",
                "error": "text-danger",
            }.get(level, "")
            log_entries.append(
                html.Div([
                    html.Span(f"[{timestamp}] ", className="text-muted"),
                    html.Span(message, className=color_class),
                ])
            )
            return log_entries[-20:]

        cache_dir = None
        if config:
            cache_dir = config.get("genome_cache_dir")
        genome_mgr = get_genome_manager(cache_dir=cache_dir)

        set_progress((0, "Scanning for missing genomes...", "Checking watchlist entries", add_log("Starting genome download process"), []))

        # Use pre-computed missing list from the main process store
        missing = missing_store if missing_store else []

        if not missing:
            set_progress((
                100,
                "All genomes already downloaded",
                "Nothing to download",
                add_log("All genomes are already present", "success"),
                dbc.Badge("Complete", color="success", className="me-2"),
            ))
            return [datetime.now().isoformat()]

        total = len(missing)
        downloaded = 0
        failed = 0
        failed_names = []

        add_log(f"Found {total} missing genome(s) to download", "info")
        set_progress((5, f"Downloading {total} genome(s)...", "Preparing downloads", log_entries[-20:], []))

        for i, entry in enumerate(missing):
            taxid = entry.get("taxid", 0)
            name = entry.get("name", "Unknown")
            progress_pct = 5 + int((i / total) * 85)

            set_progress((
                progress_pct,
                f"Downloading {i+1} of {total}",
                f"Fetching genome for {name}...",
                add_log(f"Downloading: {name} (taxid: {taxid})"),
                dbc.Badge(f"{i+1}/{total}", color="primary", className="me-2"),
            ))

            try:
                path = genome_mgr.download_genome(taxid, name)
                if path:
                    downloaded += 1
                    add_log(f"Downloaded: {name}", "success")

                    set_progress((
                        progress_pct + 2,
                        f"Downloading {i+1} of {total}",
                        f"Building BLAST DB for {name}...",
                        add_log(f"Building BLAST DB for {name}"),
                        dbc.Badge(f"{i+1}/{total}", color="primary", className="me-2"),
                    ))

                    if genome_mgr.build_blast_db(taxid):
                        add_log(f"BLAST DB built: {name}", "success")
                    else:
                        add_log(f"BLAST DB build failed: {name}", "warning")
                else:
                    failed += 1
                    failed_names.append(name)
                    reason = genome_mgr.get_last_error(taxid) or "Unknown error"
                    add_log(f"Download failed: {name} — {reason}", "error")
            except Exception as e:
                failed += 1
                failed_names.append(name)
                add_log(f"Error downloading {name}: {str(e)}", "error")
                logger.error(f"Download error for {name}: {e}")

            time.sleep(0.1)

        if failed == 0:
            result_text = f"Successfully downloaded {downloaded} genome(s)"
            status_badge = dbc.Badge("Complete", color="success", className="me-2")
            add_log(result_text, "success")
        else:
            result_text = f"Downloaded {downloaded} of {total} ({failed} failed)"
            status_badge = dbc.Badge(f"{failed} failed", color="warning", className="me-2")
            add_log(result_text, "warning")
            if failed_names:
                add_log(f"Failed: {', '.join(failed_names[:5])}" + ("..." if len(failed_names) > 5 else ""), "error")

        set_progress((100, result_text, "Download complete", log_entries[-20:], status_badge))

        return [datetime.now().isoformat()]

    @app.callback(
        Output("genome-download-modal", "is_open", allow_duplicate=True),
        Input("genome-download-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_genome_download_modal(n_clicks):
        if n_clicks:
            return False
        raise PreventUpdate

    @app.callback(
        Output("genome-download-complete", "data", allow_duplicate=True),
        Input({"type": "genome-delete-btn", "index": ALL}, "n_clicks"),
        State({"type": "genome-delete-btn", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def delete_genome(
        delete_clicks: List[int],
        delete_ids: List[Dict],
    ) -> Any:
        """Handle genome deletion."""
        import json
        from dash import callback_context

        ctx_cb = callback_context
        if not ctx_cb.triggered:
            raise PreventUpdate

        trigger = ctx_cb.triggered[0]
        trigger_value = trigger.get("value")
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        trigger_prop_id = trigger.get("prop_id", "")
        try:
            prop_id_json = trigger_prop_id.rsplit(".", 1)[0]
            trigger_id = json.loads(prop_id_json)
            taxid = trigger_id.get("index")
        except (json.JSONDecodeError, IndexError, AttributeError):
            raise PreventUpdate

        if taxid:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            genome_mgr = get_genome_manager()
            genome_mgr.delete_genome(taxid)
            logger.info(f"Deleted genome for taxid {taxid}")
            return datetime.now().isoformat()

        raise PreventUpdate

    @app.callback(
        Output("genome-download-complete", "data", allow_duplicate=True),
        Input({"type": "genome-download-single-btn", "index": ALL}, "n_clicks"),
        [
            State({"type": "genome-download-single-btn", "index": ALL}, "id"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def download_single_genome(
        download_clicks: List[int],
        download_ids: List[Dict],
        config: Dict,
    ) -> Any:
        """Handle individual genome download from missing list."""
        import json
        from dash import callback_context
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

        ctx_cb = callback_context
        if not ctx_cb.triggered:
            raise PreventUpdate

        trigger = ctx_cb.triggered[0]
        trigger_value = trigger.get("value")
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        trigger_prop_id = trigger.get("prop_id", "")
        try:
            prop_id_json = trigger_prop_id.rsplit(".", 1)[0]
            trigger_id = json.loads(prop_id_json)
            taxid = trigger_id.get("index")
        except (json.JSONDecodeError, IndexError, AttributeError):
            raise PreventUpdate

        if taxid:
            from nanometa_live.core.utils.genome_manager import get_genome_manager

            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(taxid)
            species_name = entry.name if entry else "Unknown"

            cache_dir = None
            if config:
                cache_dir = config.get("genome_cache_dir")
            genome_mgr = get_genome_manager(cache_dir=cache_dir)
            logger.info(f"Downloading genome for {species_name} (taxid: {taxid})")

            path = genome_mgr.download_genome(taxid, species_name)
            if path:
                genome_mgr.build_blast_db(taxid)
                logger.info(f"Downloaded genome for taxid {taxid} to {path}")
            else:
                logger.warning(f"Failed to download genome for taxid {taxid}")

            return datetime.now().isoformat()

        raise PreventUpdate

    # =========================================================================
    # BLAST Database Building (moved from watchlist_tab.py)
    # =========================================================================

    @app.callback(
        output=[
            Output("blast-build-complete", "data", allow_duplicate=True),
        ],
        inputs=[
            Input("genome-build-blast-btn", "n_clicks"),
        ],
        state=[
            State("app-config", "data"),
        ],
        background=True,
        manager=background_callback_manager,
        running=[
            (Output("blast-build-modal", "is_open"), True, True),
            (Output("genome-build-blast-btn", "disabled"), True, False),
            (Output("blast-build-cancel-btn", "style"), {"display": "inline-block"}, {"display": "none"}),
            (Output("blast-build-close-btn", "style"), {"display": "none"}, {"display": "inline-block"}),
        ],
        cancel=[Input("blast-build-cancel-btn", "n_clicks")],
        progress=[
            Output("blast-build-progress-bar", "value"),
            Output("blast-build-progress-text", "children"),
            Output("blast-build-progress-detail", "children"),
            Output("blast-build-log", "children"),
            Output("blast-build-status-badge", "children"),
        ],
        prevent_initial_call=True,
    )
    def build_missing_blast_dbs(
        set_progress,
        n_clicks: int,
        config: Dict,
    ) -> Any:
        """Build BLAST databases for all genomes that don't have them."""
        if not n_clicks:
            raise PreventUpdate

        from nanometa_live.core.utils.genome_manager import get_genome_manager
        import shutil

        log_entries = []

        def add_log(message: str, level: str = "info"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            color_class = {
                "info": "text-info",
                "success": "text-success",
                "warning": "text-warning",
                "error": "text-danger",
            }.get(level, "")
            log_entries.append(
                html.Div([
                    html.Span(f"[{timestamp}] ", className="text-muted"),
                    html.Span(message, className=color_class),
                ])
            )
            return log_entries[-20:]

        if not shutil.which("makeblastdb"):
            set_progress((
                100,
                "Error: makeblastdb not found",
                "Install BLAST+ toolkit to build databases",
                add_log("makeblastdb not found in PATH. Install BLAST+ toolkit.", "error"),
                dbc.Badge("Error", color="danger", className="me-2"),
            ))
            return [datetime.now().isoformat()]

        cache_dir = None
        if config:
            cache_dir = config.get("genome_cache_dir")
        genome_mgr = get_genome_manager(cache_dir=cache_dir)

        set_progress((0, "Scanning for missing BLAST databases...", "Checking downloaded genomes", add_log("Starting BLAST database build process"), []))

        all_genomes = genome_mgr.get_all_genomes()
        missing_blast = []
        for meta in all_genomes:
            if not genome_mgr.has_blast_db(meta.taxid):
                missing_blast.append(meta)

        if not missing_blast:
            set_progress((
                100,
                "All BLAST databases already built",
                "Nothing to build",
                add_log("All genomes already have BLAST databases", "success"),
                dbc.Badge("Complete", color="success", className="me-2"),
            ))
            return [datetime.now().isoformat()]

        total = len(missing_blast)
        built = 0
        failed = 0

        add_log(f"Found {total} genome(s) without BLAST databases", "info")
        set_progress((5, f"Building {total} BLAST database(s)...", "Preparing builds", log_entries[-20:], []))

        for i, meta in enumerate(missing_blast):
            taxid = meta.taxid
            name = meta.species_name or f"taxid:{taxid}"
            progress_pct = 5 + int((i / total) * 90)

            set_progress((
                progress_pct,
                f"Building {i+1} of {total}",
                f"Running makeblastdb for {name}...",
                add_log(f"Building BLAST DB: {name} (taxid: {taxid})"),
                dbc.Badge(f"{i+1}/{total}", color="primary", className="me-2"),
            ))

            try:
                if genome_mgr.build_blast_db(taxid):
                    built += 1
                    add_log(f"Built BLAST DB: {name}", "success")
                else:
                    failed += 1
                    add_log(f"Build failed: {name}", "error")
            except Exception as e:
                failed += 1
                add_log(f"Error building {name}: {str(e)}", "error")
                logger.error(f"BLAST build error for {name}: {e}")

            time.sleep(0.1)

        if failed == 0:
            result_text = f"Successfully built {built} BLAST database(s)"
            status_badge = dbc.Badge("Complete", color="success", className="me-2")
            add_log(result_text, "success")
        else:
            result_text = f"Built {built} of {total} ({failed} failed)"
            status_badge = dbc.Badge(f"{failed} failed", color="warning", className="me-2")
            add_log(result_text, "warning")

        set_progress((100, result_text, "Build complete", log_entries[-20:], status_badge))
        logger.info(f"Built {built} BLAST databases ({failed} failed)")

        return [datetime.now().isoformat()]

    @app.callback(
        Output("blast-build-modal", "is_open", allow_duplicate=True),
        Input("blast-build-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_blast_build_modal(n_clicks):
        if n_clicks:
            return False
        raise PreventUpdate

    @app.callback(
        Output("genome-download-complete", "data", allow_duplicate=True),
        Input("blast-build-complete", "data"),
        prevent_initial_call=True,
    )
    def trigger_refresh_on_blast_complete(blast_complete):
        if blast_complete:
            return datetime.now().isoformat()
        raise PreventUpdate

    @app.callback(
        Output("genome-dependency-status", "children"),
        Input("tabs", "active_tab"),
        prevent_initial_call=False,
    )
    def check_genome_dependencies(active_tab):
        """Check if NCBI datasets CLI and BLAST+ toolkit are installed."""
        import shutil

        has_datasets = shutil.which("datasets") is not None
        has_makeblastdb = shutil.which("makeblastdb") is not None

        status_items = []

        if has_datasets:
            datasets_path = shutil.which("datasets")
            status_items.append(
                html.Div([
                    html.I(className="bi bi-check-circle-fill text-success me-2"),
                    html.Span("NCBI datasets CLI: "),
                    html.Code("datasets", className="text-success"),
                    html.Small(f" ({datasets_path})", className="text-muted ms-1"),
                ])
            )
        else:
            status_items.append(
                html.Div([
                    html.I(className="bi bi-x-circle-fill text-danger me-2"),
                    html.Span("NCBI datasets CLI: "),
                    html.Strong("NOT FOUND", className="text-danger"),
                    html.Small(
                        " - Install from https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/",
                        className="text-muted ms-1",
                    ),
                ])
            )

        if has_makeblastdb:
            makeblastdb_path = shutil.which("makeblastdb")
            status_items.append(
                html.Div([
                    html.I(className="bi bi-check-circle-fill text-success me-2"),
                    html.Span("BLAST+ toolkit: "),
                    html.Code("makeblastdb", className="text-success"),
                    html.Small(f" ({makeblastdb_path})", className="text-muted ms-1"),
                ])
            )
        else:
            status_items.append(
                html.Div([
                    html.I(className="bi bi-exclamation-triangle-fill text-warning me-2"),
                    html.Span("BLAST+ toolkit: "),
                    html.Strong("Not found", className="text-warning"),
                    html.Small(
                        " (optional - pipeline uses containerized version)",
                        className="text-muted ms-1",
                    ),
                ])
            )

        return html.Div(status_items)

    @app.callback(
        Output("genome-test-result", "children"),
        Input("test-genome-download-btn", "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def test_genome_download(n_clicks, config):
        """Test genome download with E. coli (taxid 562)."""
        if not n_clicks:
            raise PreventUpdate

        import shutil
        from nanometa_live.core.utils.genome_manager import get_genome_manager

        if not shutil.which("datasets"):
            return dbc.Alert(
                [
                    html.I(className="bi bi-x-circle me-2"),
                    "Cannot test download: NCBI datasets CLI not found. ",
                    "Please install it first.",
                ],
                color="danger",
                className="py-2 mb-0",
            )

        cache_dir = None
        if config:
            cache_dir = config.get("genome_cache_dir", "~/.nanometa")

        try:
            genome_mgr = get_genome_manager(cache_dir=cache_dir)
            logger.info(f"Testing genome download with cache_dir: {genome_mgr.cache_dir}")

            result = genome_mgr.download_genome(
                taxid=562,
                species_name="Escherichia coli",
                force=False
            )

            if result:
                return dbc.Alert(
                    [
                        html.I(className="bi bi-check-circle me-2"),
                        html.Strong("Success! "),
                        f"E. coli genome downloaded to: ",
                        html.Code(str(result), style={"fontSize": "0.8em"}),
                    ],
                    color="success",
                    className="py-2 mb-0",
                )
            else:
                return dbc.Alert(
                    [
                        html.I(className="bi bi-x-circle me-2"),
                        "Download failed. Check the logs for details.",
                    ],
                    color="danger",
                    className="py-2 mb-0",
                )

        except Exception as e:
            logger.error(f"Test genome download failed: {e}")
            return dbc.Alert(
                [
                    html.I(className="bi bi-x-circle me-2"),
                    html.Strong("Error: "),
                    str(e),
                ],
                color="danger",
                className="py-2 mb-0",
            )

    # Retry button wires to clicking the start button
    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks) {
                var btn = document.getElementById('start-prep-btn');
                if (btn) { btn.click(); }
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("start-prep-btn", "className", allow_duplicate=True),
        Input("retry-preparation-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    logger.info("Preparation tab callbacks registered")
