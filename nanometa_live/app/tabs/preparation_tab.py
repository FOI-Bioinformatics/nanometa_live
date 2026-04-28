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
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dash_bootstrap_components as dbc
from dash import html, Input, Output, State, callback, no_update, ctx, ALL, MATCH, set_props
from dash.exceptions import PreventUpdate

from nanometa_live.app.app import background_callback_manager

logger = logging.getLogger(__name__)


def register_preparation_callbacks(app):
    """Register all preparation tab callbacks."""

    # --- Readiness check ---
    @app.callback(
        Output("readiness-results", "children"),
        Output("readiness-collapse", "is_open"),
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

            # Map check names to section IDs for scroll links
            _section_links = {
                "Kraken2 Database": "kraken2-db-card",
                "DB Taxonomy Index": "taxid-mapping-card",
                "Taxid Mappings": "taxid-mapping-card",
                "Watchlist Genomes": "genome-downloads-card",
                "BLAST Databases": "genome-downloads-card",
            }

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

                row_children = [
                    icon,
                    dbc.Badge(check.severity.value.upper(), color=badge_color,
                              className="me-2", style={"width": "70px"}),
                    html.Span(check.name, className="fw-semibold me-2"),
                    html.Span(check.message, className="text-muted"),
                ]

                # Add "Fix" link for failed checks that map to a section
                section_id = _section_links.get(check.name)
                if not check.passed and section_id:
                    row_children.append(
                        html.A(
                            html.Small("Fix"),
                            href=f"#{section_id}",
                            className="ms-2 text-decoration-none",
                            title=f"Scroll to {check.name} section",
                        )
                    )

                rows.append(
                    html.Div(row_children, className="mb-2 d-flex align-items-center")
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

            # Collapse the checklist if all checks pass (no issues to review)
            has_issues = not report.ready
            return html.Div([header] + rows), has_issues

        except Exception as e:
            logger.error(f"Readiness check failed: {e}", exc_info=True)
            return dbc.Alert(f"Error: {e}", color="danger"), True

    # --- Toggle readiness checklist collapse ---
    app.clientside_callback(
        """
        function(n_clicks, is_open) {
            if (!n_clicks) { return [window.dash_clientside.no_update, window.dash_clientside.no_update]; }
            var new_state = !is_open;
            var icon_class = new_state ? "bi bi-chevron-down ms-2" : "bi bi-chevron-right ms-2";
            return [new_state, icon_class];
        }
        """,
        Output("readiness-collapse", "is_open", allow_duplicate=True),
        Output("readiness-collapse-icon", "className"),
        Input("readiness-header-toggle", "n_clicks"),
        State("readiness-collapse", "is_open"),
        prevent_initial_call=True,
    )

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
        manager=background_callback_manager,
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
        Output("bundle-export-directory", "value"),
        Input("bundle-export-browse-btn", "n_clicks"),
        State("bundle-export-directory", "value"),
        prevent_initial_call=True,
    )
    def browse_export_directory(n_clicks, current_dir):
        """Open a native folder picker dialog."""
        if not n_clicks:
            raise PreventUpdate
        import platform
        import subprocess as _sp
        initial = current_dir if current_dir and Path(current_dir).exists() else str(Path.home())
        try:
            if platform.system() == "Darwin":
                script = (
                    f'set theFolder to POSIX path of '
                    f'(choose folder with prompt "Select export directory" '
                    f'default location POSIX file "{initial}")\n'
                    f'return theFolder'
                )
                result = _sp.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().rstrip("/")
            elif platform.system() == "Linux":
                result = _sp.run(
                    ["zenity", "--file-selection", "--directory",
                     "--title=Select export directory",
                     f"--filename={initial}/"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            else:
                # Windows
                script = (
                    'Add-Type -AssemblyName System.Windows.Forms; '
                    '$d = New-Object System.Windows.Forms.FolderBrowserDialog; '
                    f'$d.SelectedPath = "{initial}"; '
                    'if ($d.ShowDialog() -eq "OK") { $d.SelectedPath }'
                )
                result = _sp.run(
                    ["powershell", "-Command", script],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Folder picker unavailable: {e}")
        raise PreventUpdate

    @app.callback(
        Output("export-readiness-issues", "children"),
        Output("export-force-area", "style"),
        Output("export-result", "children"),
        Output("export-force-check", "value"),
        Input("export-bundle-btn", "n_clicks"),
        State("bundle-export-directory", "value"),
        State("bundle-export-filename", "value"),
        State("bundle-export-prewarm", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def export_bundle(n_clicks, directory, filename, pre_warm, config):
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
            result = _run_export(config, filename, directory, pre_warm=pre_warm)
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
        State("bundle-export-directory", "value"),
        State("bundle-export-filename", "value"),
        State("bundle-export-prewarm", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def force_export_bundle(n_clicks, directory, filename, pre_warm, config):
        """Export bundle after user acknowledged warnings."""
        if not n_clicks:
            raise PreventUpdate
        return _run_export(config, filename, directory, pre_warm=pre_warm)

    def _run_export(config, filename=None, directory=None, pre_warm=True):
        """Perform the actual bundle export. Returns an Alert component."""
        try:
            from nanometa_live.core.workflow.bundle_manager import BundleManager
            export_dir = Path(directory) if directory else Path.home() / "Downloads"
            if not export_dir.exists():
                return dbc.Alert(
                    f"Directory does not exist: {export_dir}",
                    color="danger",
                )
            output_path = export_dir / (filename or "mobile_lab_bundle.tar.gz")

            manager = BundleManager()
            pipeline_path = config.get("pipeline_source") if isinstance(
                config.get("pipeline_source"), str
            ) and not str(config.get("pipeline_source", "")).startswith("remote:") else None
            path = manager.export_bundle(
                str(output_path),
                config,
                pipeline_path=pipeline_path,
                pre_warm_conda_envs=bool(pre_warm),
            )
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
                # Bundle import enables offline_mode — propagate to singletons
                from nanometa_live.app.app import _init_offline_mode
                _init_offline_mode(True)

                children = [
                    html.I(className="bi bi-check-circle me-2"),
                    "Bundle imported. Offline mode activated.",
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
    # Import Genomes (manual directory / archive)
    # =========================================================================

    @app.callback(
        Output("genome-import-result", "children"),
        Output("genome-import-unrecognized", "data"),
        Output("genome-import-mapping-area", "style"),
        Output("genome-import-mapping-table", "children"),
        Input("genome-import-dir-btn", "n_clicks"),
        State("genome-import-dir-path", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def import_genomes_from_dir(n_clicks, dir_path, config):
        """Import genome FASTA files from a directory."""
        if not n_clicks:
            raise PreventUpdate

        if not dir_path:
            return (
                dbc.Alert("Please provide a directory path.", color="warning"),
                [], {"display": "none"}, [],
            )

        if not Path(dir_path).is_dir():
            return (
                dbc.Alert(f"Directory not found: {dir_path}", color="danger"),
                [], {"display": "none"}, [],
            )

        try:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            cache_dir = config.get("genome_cache_dir") if config else None
            mgr = get_genome_manager(cache_dir=cache_dir)
            imported, unrecognized = mgr.import_genomes_from_directory(dir_path)

            alert = dbc.Alert(
                f"Imported {imported} genome(s). "
                + (f"{len(unrecognized)} file(s) need manual taxid mapping."
                   if unrecognized else "All files recognized."),
                color="success" if not unrecognized else "info",
            )

            if unrecognized:
                mapping_rows = _build_mapping_table(unrecognized)
                return alert, unrecognized, {"display": "block"}, mapping_rows

            return alert, [], {"display": "none"}, []

        except Exception as e:
            logger.error(f"Genome import failed: {e}", exc_info=True)
            return (
                dbc.Alert(f"Import failed: {e}", color="danger"),
                [], {"display": "none"}, [],
            )

    @app.callback(
        Output("genome-import-result", "children", allow_duplicate=True),
        Output("genome-import-unrecognized", "data", allow_duplicate=True),
        Output("genome-import-mapping-area", "style", allow_duplicate=True),
        Output("genome-import-mapping-table", "children", allow_duplicate=True),
        Input("genome-import-archive-btn", "n_clicks"),
        State("genome-import-archive-path", "value"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def import_genomes_from_archive(n_clicks, archive_path, config):
        """Import genome FASTA files from an archive."""
        if not n_clicks:
            raise PreventUpdate

        if not archive_path:
            return (
                dbc.Alert("Please provide an archive path.", color="warning"),
                [], {"display": "none"}, [],
            )

        if not Path(archive_path).exists():
            return (
                dbc.Alert(f"Archive not found: {archive_path}", color="danger"),
                [], {"display": "none"}, [],
            )

        try:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            cache_dir = config.get("genome_cache_dir") if config else None
            mgr = get_genome_manager(cache_dir=cache_dir)
            imported, unrecognized = mgr.import_genomes_from_archive(archive_path)

            alert = dbc.Alert(
                f"Imported {imported} genome(s). "
                + (f"{len(unrecognized)} file(s) need manual taxid mapping."
                   if unrecognized else "All files recognized."),
                color="success" if not unrecognized else "info",
            )

            if unrecognized:
                mapping_rows = _build_mapping_table(unrecognized)
                return alert, unrecognized, {"display": "block"}, mapping_rows

            return alert, [], {"display": "none"}, []

        except Exception as e:
            logger.error(f"Genome archive import failed: {e}", exc_info=True)
            return (
                dbc.Alert(f"Import failed: {e}", color="danger"),
                [], {"display": "none"}, [],
            )

    @app.callback(
        Output("genome-import-result", "children", allow_duplicate=True),
        Output("genome-import-mapping-area", "style", allow_duplicate=True),
        Input("genome-import-mapped-btn", "n_clicks"),
        State("genome-import-unrecognized", "data"),
        State({"type": "genome-taxid-input", "index": ALL}, "value"),
        State({"type": "genome-taxid-input", "index": ALL}, "id"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def import_mapped_genomes(n_clicks, unrecognized, taxid_values, taxid_ids, config):
        """Import unrecognized genome files with user-provided taxid mappings."""
        if not n_clicks or not unrecognized:
            raise PreventUpdate

        from nanometa_live.core.utils.genome_manager import get_genome_manager
        cache_dir = config.get("genome_cache_dir") if config else None
        mgr = get_genome_manager(cache_dir=cache_dir)

        imported = 0
        skipped = 0
        for i, entry in enumerate(unrecognized):
            if i >= len(taxid_values):
                break
            val = taxid_values[i]
            if not val:
                skipped += 1
                continue
            try:
                taxid = int(val)
            except (ValueError, TypeError):
                skipped += 1
                continue

            if mgr.import_genome_with_taxid(entry["path"], taxid):
                imported += 1
            else:
                skipped += 1

        alert = dbc.Alert(
            f"Imported {imported} mapped genome(s). {skipped} skipped.",
            color="success" if imported > 0 else "warning",
        )
        return alert, {"display": "none"}

    def _build_mapping_table(unrecognized):
        """Build a table of unrecognized files for manual taxid mapping."""
        rows = []
        for i, entry in enumerate(unrecognized):
            rows.append(
                dbc.Row([
                    dbc.Col(
                        html.Small(entry["filename"], className="text-truncate"),
                        md=7,
                        className="d-flex align-items-center",
                    ),
                    dbc.Col(
                        dbc.Input(
                            id={"type": "genome-taxid-input", "index": i},
                            type="number",
                            placeholder="Database ID",
                            size="sm",
                        ),
                        md=5,
                    ),
                ], className="mb-1 g-2")
            )
        return rows

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
        Output("taxmap-database-info", "data", allow_duplicate=True),
        Output("taxmap-rescan-complete", "data", allow_duplicate=True),
        Output("watchlist-table-refresh", "data", allow_duplicate=True),
        Output("taxmap-rescan-status", "children"),
        Output("taxmap-rescan-progress-container", "style"),
        Output("taxmap-rescan-progress", "value"),
        Output("taxmap-rescan-progress-label", "children"),
        Input("taxmap-rescan-btn", "n_clicks"),
        State("app-config", "data"),
        State("watchlist-table-refresh", "data"),
        prevent_initial_call=True,
    )
    def run_rescan(n_clicks, config, current_refresh):
        """Callback for Kraken2 database rescan."""
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

        logger.info(f"[RESCAN] run_rescan called: n_clicks={n_clicks}")
        hide_progress = {"display": "none"}
        show_progress = {"display": "block"}

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
                {"name": e.get("name", ""), "taxid": e.get("taxid", 0), "rank": e.get("api_rank", "species"),
                 "names_alt": e.get("names_alt", [])}
                for e in entries
            ]

            if not watchlist_entries:
                logger.info("No watchlist entries to map")
                return (None, None, datetime.now().isoformat(), (current_refresh or 0) + 1, "No entries to map",
                        hide_progress, 0, "")

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
                    if ncbi_tid is not None:
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

            stats = mapper.get_statistics()
            mapped_count = (stats.get("mapped_exact", 0) + stats.get("mapped_fuzzy", 0)
                            + stats.get("mapped_manual", 0) + stats.get("mapped_partial", 0))
            unmapped_count = stats.get("unmapped", 0)
            total_count = stats.get("total_entries", 0)
            if unmapped_count > 0:
                status = f"Mapped {mapped_count}/{total_count} entries ({unmapped_count} not in database)"
                progress_label = f"Completed: {mapped_count} mapped, {unmapped_count} not in database"
            else:
                status = f"Mapped {mapped_count} entries"
                progress_label = f"Completed: {mapped_count} mappings"
            logger.info(f"Rescan returning: mapped={mapped_count}, unmapped={unmapped_count}, refresh={new_refresh}")
            return (collection_data, db_info, now, new_refresh, status,
                    hide_progress, 100, progress_label)

        except Exception as e:
            logger.error(f"Rescan failed: {e}")
            traceback.print_exc()
            return (no_update, no_update, no_update, no_update, f"Error: {str(e)}",
                    hide_progress, 0, "")

    # --- Taxid mapping status info display ---
    @app.callback(
        Output("taxmap-current-db-type", "children"),
        Output("taxmap-current-mapping-count", "children"),
        Output("taxmap-last-scan-time", "children"),
        Input("taxmap-rescan-complete", "data"),
        Input("taxmap-database-info", "data"),
        State("taxmap-collection", "data"),
    )
    def update_taxmap_status_info(rescan_time, db_info, collection):
        """Update the inline status display after rescan or on page load."""
        # Database type
        if db_info and db_info.get("type"):
            db_type = db_info["type"].replace("_", " ").title()
            db_type_text = f"Database type: {db_type}"
        else:
            db_type_text = "No database scanned"

        # Mapping count (with unmapped info)
        if collection and isinstance(collection.get("mappings"), dict):
            mappings = collection["mappings"]
            total = len(mappings)
            unmapped = sum(
                1 for m in mappings.values()
                if isinstance(m, dict) and m.get("confidence") == "unmapped"
            )
            mapped = total - unmapped
            if unmapped > 0:
                count_text = f"{mapped}/{total} mapped ({unmapped} not in database)"
            else:
                count_text = f"{mapped} species mapped"
        else:
            count_text = "0 species mapped"

        # Last scan time
        if rescan_time:
            try:
                dt = datetime.fromisoformat(rescan_time)
                scan_text = f"Last scan: {dt.strftime('%Y-%m-%d %H:%M:%S')}"
            except (ValueError, TypeError):
                scan_text = f"Last scan: {rescan_time}"
        else:
            scan_text = "Last scan: Never"

        return db_type_text, count_text, scan_text

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
        set_progress((5, f"Downloading {total} genome(s)...", "Preparing batch downloads", log_entries[-20:], []))

        # Use batch download for concurrent fetching
        def progress_cb(completed, total_count, name):
            nonlocal downloaded, failed
            pct = 5 + int((completed / max(total_count, 1)) * 80)
            set_progress((
                pct,
                f"Downloading {completed} of {total_count}",
                f"Fetched {name}",
                log_entries[-20:],
                dbc.Badge(f"{completed}/{total_count}", color="primary", className="me-2"),
            ))

        try:
            results = genome_mgr.download_genomes_batch(
                missing, max_workers=3, progress_callback=progress_cb
            )

            # Log results and count successes/failures
            successful_taxids = []
            for entry in missing:
                taxid = entry.get("taxid", 0)
                name = entry.get("name", "Unknown")
                path = results.get(taxid)
                if path:
                    downloaded += 1
                    successful_taxids.append(taxid)
                    add_log(f"Downloaded: {name}", "success")
                else:
                    failed += 1
                    failed_names.append(name)
                    reason = genome_mgr.get_last_error(taxid) or "Unknown error"
                    add_log(f"Download failed: {name} -- {reason}", "error")

            # Batch build BLAST databases for all downloaded genomes
            if successful_taxids:
                set_progress((
                    90,
                    f"Building {len(successful_taxids)} BLAST database(s)...",
                    "Building BLAST databases",
                    add_log(f"Building BLAST databases for {len(successful_taxids)} genome(s)"),
                    dbc.Badge("BLAST", color="info", className="me-2"),
                ))
                built = genome_mgr.build_blast_dbs_batch(successful_taxids, max_workers=2)
                add_log(f"Built {built} BLAST database(s)", "success" if built > 0 else "warning")

        except Exception as e:
            failed = total
            add_log(f"Batch download error: {str(e)}", "error")
            logger.error(f"Batch download error: {e}")

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

        if not ctx.triggered_id:
            raise PreventUpdate

        # Check that a button was actually clicked
        trigger_value = ctx.triggered[0].get("value")
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        # ctx.triggered_id is the dict ID for pattern-matching callbacks
        taxid = ctx.triggered_id.get("index") if isinstance(ctx.triggered_id, dict) else None
        if not taxid:
            raise PreventUpdate

        if taxid:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            genome_mgr = get_genome_manager()
            genome_mgr.delete_genome(taxid)
            logger.info(f"Deleted genome for taxid {taxid}")
            return datetime.now().isoformat()

        raise PreventUpdate

    # -----------------------------------------------------------------
    # Remove All Genomes (confirmation modal + action)
    # -----------------------------------------------------------------

    @app.callback(
        [
            Output("genome-remove-all-modal", "is_open"),
            Output("genome-remove-all-count", "children"),
        ],
        Input("genome-remove-all-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_remove_all_modal(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        genome_mgr = get_genome_manager()
        count = len(genome_mgr.get_all_genomes())
        return True, f"{count} genome(s) and associated BLAST databases will be deleted."

    @app.callback(
        [
            Output("genome-remove-all-modal", "is_open", allow_duplicate=True),
            Output("genome-download-complete", "data", allow_duplicate=True),
        ],
        [
            Input("genome-remove-all-confirm-btn", "n_clicks"),
            Input("genome-remove-all-cancel-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def handle_remove_all(confirm_clicks, cancel_clicks):
        if not ctx.triggered_id:
            raise PreventUpdate
        if ctx.triggered_id == "genome-remove-all-cancel-btn":
            return False, no_update
        # Confirmed — delete all
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        genome_mgr = get_genome_manager()
        deleted = genome_mgr.delete_all_genomes()
        logger.info(f"Removed all genomes ({deleted} deleted)")
        return False, datetime.now().isoformat()

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
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

        if not ctx.triggered_id:
            raise PreventUpdate

        # Check that a button was actually clicked
        trigger_value = ctx.triggered[0].get("value")
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        # ctx.triggered_id is the dict ID for pattern-matching callbacks
        taxid = ctx.triggered_id.get("index") if isinstance(ctx.triggered_id, dict) else None
        if not taxid:
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

    # =========================================================================
    # Deploy Offline Wizard Callbacks
    # =========================================================================

    from nanometa_live.core.workflow.mobile_lab_preparer import (
        MobileLabPreparer, PrepStage,
    )

    _WIZARD_STAGE_MAP = {
        0: [PrepStage.VERIFY_DB],           # Select watchlists (no engine stage, handled locally)
        1: [PrepStage.VERIFY_DB],           # Verify Kraken2 DB
        2: [PrepStage.BUILD_INDEX, PrepStage.GENERATE_MAPPINGS],  # Build index + mappings
        3: [PrepStage.DOWNLOAD_GENOMES],    # Download genomes
        4: [PrepStage.BUILD_BLAST_DBS],     # Build BLAST DBs
        5: [PrepStage.CACHE_TAXONOMY],      # Cache taxonomy
        6: [PrepStage.READINESS_CHECK, PrepStage.CHECK_TOOLS],  # Readiness check
        7: [],                              # Export bundle (handled separately)
    }

    @app.callback(
        Output({"type": "wizard-step-status", "index": ALL}, "children"),
        Output("wizard-overall-progress", "value"),
        Output("wizard-overall-label", "children"),
        Input("wizard-step-state", "data"),
    )
    def update_wizard_display(state):
        """Update wizard step badges and overall progress based on state."""
        if not state:
            from dash import no_update
            return no_update, no_update, no_update

        steps = state.get("steps", {})
        statuses = []
        completed = 0
        total = 8

        for i in range(total):
            step_status = steps.get(str(i), "pending")
            if step_status == "done":
                completed += 1
                statuses.append(dbc.Badge(
                    [html.I(className="bi bi-check-circle me-1"), "Done"],
                    color="success",
                    className="ms-1",
                ))
            elif step_status == "running":
                statuses.append(dbc.Spinner(
                    size="sm",
                    spinner_class_name="ms-1",
                ))
            elif step_status == "failed":
                statuses.append(dbc.Badge(
                    [html.I(className="bi bi-x-circle me-1"), "Failed"],
                    color="danger",
                    className="ms-1",
                ))
            else:
                statuses.append(html.Span())

        pct = (completed / total) * 100
        label = f"{completed}/{total} steps"
        return statuses, pct, label

    @app.callback(
        Output({"type": "wizard-step-progress", "index": MATCH}, "children"),
        Input({"type": "wizard-step-run", "index": MATCH}, "n_clicks"),
        State("wizard-step-state", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def run_wizard_step(n_clicks, wizard_state, config):
        """Run a single wizard step."""
        if not n_clicks:
            raise PreventUpdate

        triggered = ctx.triggered_id
        if not triggered:
            raise PreventUpdate

        step_idx = triggered["index"]
        wizard_state = wizard_state or {
            "current_step": 0,
            "steps": {str(i): "pending" for i in range(8)},
        }
        config = config or {}

        # Mark running
        wizard_state["steps"][str(step_idx)] = "running"

        try:
            result_children = _execute_wizard_step(step_idx, config)
            wizard_state["steps"][str(step_idx)] = "done"
            set_props("wizard-step-state-relay", {"data": wizard_state})
            return result_children
        except Exception as e:
            wizard_state["steps"][str(step_idx)] = "failed"
            set_props("wizard-step-state-relay", {"data": wizard_state})
            return dbc.Alert(
                [html.I(className="bi bi-x-circle me-2"), str(e)],
                color="danger",
                className="mt-2 py-2",
            )

    @app.callback(
        Output("wizard-step-state", "data", allow_duplicate=True),
        Input("wizard-step-state-relay", "data"),
        prevent_initial_call=True,
    )
    def relay_wizard_step_state(relayed_state):
        """Forward wizard state from the relay store to the main store.

        This is needed because Dash does not allow mixing pattern-matching
        (MATCH) outputs with plain-ID outputs in the same callback.
        """
        if relayed_state is None:
            raise PreventUpdate
        return relayed_state

    def _execute_wizard_step(step_idx, config):
        """Execute a wizard step and return result component."""
        from nanometa_live.core.workflow.mobile_lab_preparer import MobileLabPreparer
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, Severity
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        # Step 0: Watchlist selection (informational)
        if step_idx == 0:
            try:
                from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
                wm = get_watchlist_manager()
                active = wm.get_active_entries()
                count = len(active) if active else 0
                if count == 0:
                    return dbc.Alert(
                        [html.I(className="bi bi-exclamation-triangle me-2"),
                         "No watchlist entries enabled. Enable pathogens in the Watchlist tab first."],
                        color="warning", className="mt-2 py-2",
                    )
                return dbc.Alert(
                    [html.I(className="bi bi-check-circle me-2"),
                     f"{count} watchlist entries active and ready for deployment."],
                    color="success", className="mt-2 py-2",
                )
            except Exception as e:
                return dbc.Alert(
                    [html.I(className="bi bi-info-circle me-2"),
                     f"Could not load watchlist manager: {e}"],
                    color="info", className="mt-2 py-2",
                )

        # Step 1: Verify Kraken2 DB
        if step_idx == 1:
            db_path = config.get("kraken_db", "")
            if not db_path:
                raise ValueError("No kraken_db path configured")
            from nanometa_live.core.utils.kraken_utils import verify_kraken_db
            if not verify_kraken_db(db_path):
                raise ValueError(f"Invalid Kraken2 database at {db_path}")
            return dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"),
                 f"Kraken2 database verified at: {db_path}"],
                color="success", className="mt-2 py-2",
            )

        # Step 2: Build taxonomy index + mappings
        if step_idx == 2:
            preparer = MobileLabPreparer(config=config)
            result = preparer.prepare.__wrapped__ if hasattr(preparer.prepare, '__wrapped__') else None
            # Run the two stages directly
            from nanometa_live.core.workflow.mobile_lab_preparer import PreparationResult
            pr = PreparationResult(success=True)
            preparer._run_build_index(0, pr, skip_existing=True)
            preparer._run_generate_mappings(1, pr, skip_existing=True)
            msgs = []
            if "build_index" not in pr.stages_failed:
                msgs.append("Taxonomy index built")
            if "generate_mappings" not in pr.stages_failed:
                msgs.append("Taxid mappings generated")
            if pr.warnings:
                msgs.extend(pr.warnings)
            return dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"),
                 ". ".join(msgs) + "."],
                color="success", className="mt-2 py-2",
            )

        # Step 3: Download genomes
        if step_idx == 3:
            preparer = MobileLabPreparer(config=config)
            from nanometa_live.core.workflow.mobile_lab_preparer import PreparationResult
            pr = PreparationResult(success=True)
            preparer._run_download_genomes(0, pr, skip_existing=True)
            msg = f"Genome download complete. {pr.genomes_downloaded} new genome(s) downloaded."
            return dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"), msg],
                color="success", className="mt-2 py-2",
            )

        # Step 4: Build BLAST DBs
        if step_idx == 4:
            preparer = MobileLabPreparer(config=config)
            from nanometa_live.core.workflow.mobile_lab_preparer import PreparationResult
            pr = PreparationResult(success=True)
            preparer._run_build_blast_dbs(0, pr, skip_existing=True)
            msg = f"BLAST database build complete. {pr.blast_dbs_built} database(s) built."
            return dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"), msg],
                color="success", className="mt-2 py-2",
            )

        # Step 5: Cache taxonomy
        if step_idx == 5:
            preparer = MobileLabPreparer(config=config)
            from nanometa_live.core.workflow.mobile_lab_preparer import PreparationResult
            pr = PreparationResult(success=True)
            preparer._run_cache_taxonomy(0, pr, skip_existing=False)
            if pr.warnings:
                return dbc.Alert(
                    [html.I(className="bi bi-exclamation-triangle me-2"),
                     "Taxonomy cache: " + "; ".join(pr.warnings)],
                    color="warning", className="mt-2 py-2",
                )
            return dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"),
                 "Taxonomy data cached for offline name resolution."],
                color="success", className="mt-2 py-2",
            )

        # Step 6: Readiness check
        if step_idx == 6:
            checker = ReadinessChecker()
            report = checker.check_readiness(config)
            summary = report.summary()
            items = []
            for c in report.checks:
                if c.passed:
                    icon_cls = "bi bi-check-circle-fill text-success"
                elif c.severity == Severity.CRITICAL:
                    icon_cls = "bi bi-x-octagon-fill text-danger"
                else:
                    icon_cls = "bi bi-exclamation-triangle-fill text-warning"
                items.append(html.Div([
                    html.I(className=f"{icon_cls} me-2"),
                    html.Span(c.name, className="fw-semibold me-2"),
                    html.Span(c.message, className="text-muted small"),
                ], className="mb-1"))

            color = "success" if report.ready else "danger"
            header = "System ready for offline operation." if report.ready else "System is NOT ready."
            return html.Div([
                dbc.Alert(
                    [html.I(className="bi bi-clipboard2-check me-2"), header],
                    color=color, className="mt-2 py-2",
                ),
                html.Div(items, className="ms-2 mt-2",
                         style={"maxHeight": "200px", "overflowY": "auto"}),
            ])

        # Step 7: Export bundle (uses ~/Downloads as default)
        if step_idx == 7:
            return _run_export(config)

        raise ValueError(f"Unknown wizard step: {step_idx}")

    # Run All Steps
    @app.callback(
        Output("wizard-run-all-result", "children"),
        Output("wizard-step-state", "data", allow_duplicate=True),
        Output("wizard-run-all-btn", "disabled"),
        Input("wizard-run-all-btn", "n_clicks"),
        State("wizard-step-state", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def run_all_wizard_steps(n_clicks, wizard_state, config):
        """Run all wizard steps sequentially."""
        if not n_clicks:
            raise PreventUpdate

        config = config or {}
        wizard_state = wizard_state or {
            "current_step": 0,
            "steps": {str(i): "pending" for i in range(8)},
        }

        results = []
        all_ok = True

        for step_idx in range(8):
            wizard_state["steps"][str(step_idx)] = "running"
            try:
                _execute_wizard_step(step_idx, config)
                wizard_state["steps"][str(step_idx)] = "done"
            except Exception as e:
                wizard_state["steps"][str(step_idx)] = "failed"
                results.append(f"Step {step_idx + 1} failed: {e}")
                all_ok = False
                # Steps 1-2 are critical, abort on failure
                if step_idx in (1, 2):
                    results.append("Aborting: critical step failed.")
                    break

        if all_ok:
            alert = dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"),
                 "All 8 steps completed. System is ready for offline deployment."],
                color="success",
            )
        else:
            alert = dbc.Alert([
                html.I(className="bi bi-exclamation-triangle me-2"),
                html.Strong("Some steps failed:"),
                html.Ul([html.Li(r) for r in results]),
            ], color="warning")

        return alert, wizard_state, False

    # =========================================================================
    # Kraken2 Database Download button
    # =========================================================================

    @app.callback(
        Output("download-kraken-db-btn", "disabled"),
        Input("external-kraken-input", "value"),
        prevent_initial_call=False,
    )
    def toggle_kraken_download_btn(selected):
        """Enable the download button only when a database is selected."""
        return not bool(selected)

    @app.callback(
        Output("kraken-download-status", "children"),
        Input("download-kraken-db-btn", "n_clicks"),
        State("external-kraken-input", "value"),
        State("kraken-databases", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
        background=True,
        manager=background_callback_manager,
        running=[
            (Output("download-kraken-db-btn", "disabled"), True, False),
        ],
    )
    def download_kraken_database(set_progress, n_clicks, selected_db, databases, config):
        """Download the selected Kraken2 database."""
        if not n_clicks or not selected_db:
            raise PreventUpdate

        db_info = (databases or {}).get(selected_db)
        if not db_info:
            return dbc.Alert(f"Database '{selected_db}' not found.", color="danger")

        dest_dir = (config or {}).get("kraken_db", "") or str(Path.home() / ".nanometa" / "kraken2_databases")

        try:
            from nanometa_live.core.utils.kraken_utils import download_kraken_database as _download
            success, message = _download(db_info, dest_dir)
            if success:
                return dbc.Alert(
                    [html.I(className="bi bi-check-circle me-2"), message],
                    color="success",
                )
            return dbc.Alert(
                [html.I(className="bi bi-x-circle me-2"), message],
                color="danger",
            )
        except Exception as e:
            logger.error(f"Kraken2 database download failed: {e}", exc_info=True)
            return dbc.Alert(f"Download failed: {e}", color="danger")

    # =========================================================================
    # Wizard Cancel button
    # =========================================================================

    @app.callback(
        Output("wizard-run-all-btn", "disabled", allow_duplicate=True),
        Input("wizard-cancel-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def cancel_wizard(n_clicks):
        """Re-enable the run-all button when cancel is clicked.

        The wizard-run-all-btn background callback does not expose a cancel
        input, so this callback simply re-enables the button so the user can
        restart after clicking Cancel.
        """
        if not n_clicks:
            raise PreventUpdate
        return False

    logger.info("Preparation tab callbacks registered")
