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
