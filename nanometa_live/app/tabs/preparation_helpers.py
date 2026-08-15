"""
Helper functions for the Preparation tab.

Extracted from preparation_tab.py so the registration function stays
focused on Dash callback declarations. These helpers are pure logic
(bundle export, taxid-mapping table builder, wizard-step dispatcher)
that do not capture the Dash ``app`` instance.
"""

import logging
from pathlib import Path

import dash_bootstrap_components as dbc
from dash import html

logger = logging.getLogger(__name__)


def _build_export_opts(directory, filename, pre_warm, containerization):
    """Bundle the Export-card selections into the dict step 7 forwards to
    ``_run_export``. Shared by the single-step and run-all wizard callbacks so
    the two entry points stay in lock-step.
    """
    return {
        "directory": directory,
        "filename": filename,
        "pre_warm": pre_warm,
        "containerization": containerization,
    }


def _run_export(config, filename=None, directory=None, pre_warm=True,
                containerization="conda"):
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
            containerization=containerization or "conda",
        )
        size_mb = path.stat().st_size / (1024 * 1024)

        return dbc.Alert([
            html.I(className="bi bi-check-circle me-2"),
            f"Bundle exported: {path} ({size_mb:.1f} MB) "
            f"-- engine: {containerization or 'conda'}",
        ], color="success")

    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return dbc.Alert(f"Export failed: {e}", color="danger")

def _render_import_result(result):
    """Render the import outcome from the worker's result dict into an Alert.

    Pure (no I/O, no singleton mutation) so the background-import split can call
    it from the main-process finalize callback and so it is unit-testable. The
    dict is one of:
      - ``{"early_error": msg, "color": ...}``  -- a pre-import validation stop
      - ``{"exception": msg}``                  -- the import raised
      - ``{"success": True, ...manager result}``
      - ``{"success": False, "warnings": [...]}`` -- the manager refused

    Offline-mode activation is NOT done here -- that is a main-process side
    effect handled by the finalize callback, since a background worker cannot
    re-init the live singletons.
    """
    if result.get("early_error"):
        return dbc.Alert(
            result["early_error"], color=result.get("color", "warning")
        )
    if result.get("exception"):
        return dbc.Alert(f"Import failed: {result['exception']}", color="danger")

    if not result.get("success"):
        # The manager's own diagnostics (platform mismatch, checksum failure,
        # unsupported version, ...).
        detail = "; ".join(result.get("warnings", [])) or "see logs"
        return dbc.Alert(f"Import failed: {detail}", color="danger")

    return dbc.Alert(_import_success_children(result), color="success")


def _import_success_children(result):
    """Build the body of the success Alert: header, action-required items, the
    DB-hash regenerate button, warnings, and the next-steps line.
    """
    children = [
        html.I(className="bi bi-check-circle me-2"),
        html.Strong("Bundle imported. Offline mode activated."),
    ]
    # Setup that is not yet complete (action required) -- surface prominently so
    # the operator does not read "activated" as "ready to run".
    action_needed = []
    if result.get("kraken_db_unset"):
        action_needed.append(
            "Set the Kraken2 database path before starting analysis "
            "(it is transferred separately from the bundle)."
        )
    if result.get("plugins_empty"):
        action_needed.append(
            "Bundled Nextflow plugins are missing; re-export from a machine "
            "with the plugins cached, or the offline run will fail when "
            "Nextflow probes the online plugin registry."
        )
    if result.get("db_hash_mismatch"):
        action_needed.append(
            "The bundled taxid mappings were built for a different Kraken2 "
            "database; point the Kraken2 database path at the one the bundle "
            "was built for, or click 'Regenerate mappings for this database' "
            "below to rebuild them here. Otherwise the readiness check and the "
            "run will not find the mappings."
        )
    if action_needed:
        children.append(
            dbc.Alert(
                [html.Strong("Action required: ")]
                + [html.Div(a, className="small") for a in action_needed],
                color="warning",
                className="mt-2 mb-2",
            )
        )
    # One-click recovery for a DB-hash mismatch (background callback
    # `regenerate_mappings`, result rendered in `regenerate-mappings-result`).
    if result.get("db_hash_mismatch"):
        children.append(
            dbc.Button(
                [html.I(className="bi bi-arrow-repeat me-2"),
                 "Regenerate mappings for this database"],
                id="regenerate-mappings-btn",
                color="warning",
                size="sm",
                className="mt-1 mb-2",
            )
        )
    if result.get("warnings"):
        children.append(html.Br())
        children.append(html.Strong("Warnings: "))
        children.extend([html.Span(w + "; ") for w in result["warnings"]])
    children.append(html.Hr(className="my-2"))
    children.append(html.Div([
        html.Strong("Next steps: "),
        "open the Watchlist & Preparation tab, run the Readiness checklist to "
        "confirm everything is green, then click Start Analysis.",
    ], className="small"))
    return children


def _regenerate_mappings(config, watchlist_entries=None):
    """Rebuild the taxonomy index + taxid mappings for the configured Kraken2
    database.

    Recovers from a bundle imported against a different database (db_hash
    mismatch): the bundled mappings are keyed by the *bundle's* DB hash, so
    readiness and the run cannot find them. Rebuilding here writes them under
    ``{local_db_hash}_*`` in ``<home>/mappings`` where those consumers look.

    ``watchlist_entries`` is the ``watchlist-entries-snapshot`` payload; it is
    forwarded to MobileLabPreparer so this works in a background worker where
    the WatchlistManager singleton is empty. Returns a dbc.Alert.
    """
    import shutil

    db_path = (config or {}).get("kraken_db", "")
    if not db_path:
        return dbc.Alert(
            "No Kraken2 database configured; set the database path before "
            "regenerating mappings.",
            color="danger",
        )

    # Building the taxonomy index needs the database's inspect.txt; when it is
    # absent it is generated with kraken2-inspect. On an air-gapped field
    # machine with neither present, regeneration cannot proceed -- fail with
    # clear guidance rather than leaving stale, mis-keyed mappings in place.
    if not (Path(db_path) / "inspect.txt").exists() and not shutil.which(
        "kraken2-inspect"
    ):
        return dbc.Alert(
            [
                html.Strong("Cannot regenerate mappings: "),
                "the database has no inspect.txt and kraken2-inspect is not "
                "installed, so the taxonomy index cannot be built. Install "
                "kraken2 (which provides kraken2-inspect) on this machine, or "
                "ship an inspect.txt alongside the database, then retry.",
            ],
            color="danger",
        )

    try:
        from nanometa_live.core.workflow.mobile_lab_preparer import (
            MobileLabPreparer,
            PreparationResult,
        )

        preparer = MobileLabPreparer(
            config=config, watchlist_entries=watchlist_entries
        )
        pr = PreparationResult(success=True)
        # skip_existing=False: force a rebuild for the local DB hash even if a
        # partial artefact exists. verify_db also ensures inspect.txt.
        preparer._run_verify_db(0, pr, skip_existing=False)
        preparer._run_build_index(1, pr, skip_existing=False)
        preparer._run_generate_mappings(2, pr, skip_existing=False)

        msgs = [
            "Taxonomy index rebuilt",
            "Taxid mappings regenerated for this database",
        ]
        if pr.warnings:
            msgs.extend(pr.warnings)
        return dbc.Alert(
            [
                html.I(className="bi bi-check-circle me-2"),
                ". ".join(msgs)
                + ". Re-run the Readiness checklist to confirm the "
                "'Database index' and 'Taxid mappings' checks now pass.",
            ],
            color="success",
        )
    except Exception as e:
        logger.error(f"Mapping regeneration failed: {e}", exc_info=True)
        return dbc.Alert(f"Regeneration failed: {e}", color="danger")


def _render_genome_import_result(result):
    """Render the four genome-import outputs from a worker result dict.

    Returns ``(result_alert, unrecognized_data, mapping_area_style,
    mapping_table_children)``. Pure (no I/O, no singleton mutation) so the
    background genome-import workers and the main-process finalize share it and
    it stays unit-testable. Shapes handled: ``early`` (a pre-import validation
    stop), ``error`` (the import raised), a ``mapped`` import, and a
    directory/archive import that may leave files needing manual taxid mapping.
    """
    early = result.get("early")
    if early:
        return (
            dbc.Alert(early["message"], color=early.get("color", "warning")),
            [], {"display": "none"}, [],
        )
    if result.get("error"):
        return (
            dbc.Alert(f"Import failed: {result['error']}", color="danger"),
            [], {"display": "none"}, [],
        )

    imported = result.get("imported", 0)
    if result.get("source") == "mapped":
        skipped = result.get("skipped", 0)
        return (
            dbc.Alert(
                f"Imported {imported} mapped genome(s). {skipped} skipped.",
                color="success" if imported > 0 else "warning",
            ),
            [], {"display": "none"}, [],
        )

    unrecognized = result.get("unrecognized") or []
    alert = dbc.Alert(
        f"Imported {imported} genome(s). "
        + (
            f"{len(unrecognized)} file(s) need manual taxid mapping."
            if unrecognized else "All files recognized."
        ),
        color="success" if not unrecognized else "info",
    )
    if unrecognized:
        return (
            alert, unrecognized, {"display": "block"},
            _build_mapping_table(unrecognized),
        )
    return alert, [], {"display": "none"}, []


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

def _alert_text(component) -> str:
    """Flatten an alert's visible text, for summarising a step's outcome."""
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_alert_text(c) for c in component).strip()
    children = getattr(component, "children", None)
    return _alert_text(children).strip() if children is not None else ""


def _execute_wizard_step(step_idx, config, export_opts=None):
    """Execute a wizard step and return result component.

    ``export_opts`` (used only by step 7) carries the operator's Export-card
    selections -- ``directory``, ``filename``, ``pre_warm``,
    ``containerization`` -- so the guided wizard exports with the same engine
    and pre-warm choice as the manual Export button instead of silently
    defaulting to conda + ~/Downloads.
    """
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
                     "No watchlist entries enabled. Enable pathogens in the Watchlist & Preparation tab first."],
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
        # Report total ready (built + already-present), not just this run's
        # builds -- the genome manager auto-builds DBs on scan, so blast_dbs_built
        # alone understates how many are ready. See preparation_tab.render.
        blast_ready = pr.blast_dbs_built + pr.blast_dbs_present
        msg = f"BLAST database build complete. {blast_ready} database(s) ready."
        if pr.blast_dbs_present:
            msg += f" ({pr.blast_dbs_built} built now, {pr.blast_dbs_present} already present.)"
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

    # Step 7: Export bundle, honoring the Export-card selections when the
    # caller wired them (falls back to conda + ~/Downloads + pre-warm off).
    if step_idx == 7:
        opts = export_opts or {}
        return _run_export(
            config,
            filename=opts.get("filename"),
            directory=opts.get("directory"),
            pre_warm=bool(opts.get("pre_warm", False)),
            containerization=opts.get("containerization") or "conda",
        )

    raise ValueError(f"Unknown wizard step: {step_idx}")
