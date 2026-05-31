"""
Layout for the Preparation tab.

Provides UI for:
- Readiness checking
- Kraken2 database download (moved from Configuration tab)
- Taxid mapping / DB rescan (moved from Watchlist tab)
- Genome downloads and BLAST DB building (moved from Watchlist tab)
- Preparation execution
- Exporting/importing portable bundles for offline field operation
"""

import platform
import shutil
from pathlib import Path
from typing import Tuple

import dash_bootstrap_components as dbc
from dash import html, dcc

from nanometa_live.app.components.modern_components import WorkflowStepper


def _detect_engine_availability() -> Tuple[bool, bool, bool]:
    """Return ``(conda_ok, docker_ok, apptainer_ok)`` for the build host.

    Conda is always available because nanometa_live itself runs in a
    conda env. Docker and Apptainer are detected by their CLI presence
    on PATH; the radio for an unavailable engine is rendered disabled.
    """
    conda_ok = True
    docker_ok = shutil.which("docker") is not None
    apptainer_ok = (
        shutil.which("apptainer") is not None
        or shutil.which("singularity") is not None
    )
    return conda_ok, docker_ok, apptainer_ok


def _build_platform_banner() -> dbc.Alert:
    """Banner that adapts to the selected containerization engine.

    The body text is updated client-side via the
    ``platform-banner-body`` callback in preparation_tab.py; the
    initial render shows the conda mode message because conda is the
    default radio selection.
    """
    system = platform.system()
    machine = platform.machine()
    return dbc.Alert(
        [
            html.I(className="bi bi-info-circle me-2"),
            html.Span(id="platform-banner-body", children=[
                html.Strong(f"Build platform: {system} {machine}. "),
                "Pre-warmed conda environments only run on a field machine "
                "with the same OS and CPU architecture.",
            ]),
        ],
        color="info",
        className="small py-2 mb-3",
        id="platform-banner",
    )


def _build_containerization_radio() -> dbc.RadioItems:
    """Three-engine radio for offline-deployment containerization.

    Closes W7-C from
    ``docs/plan-2026-04-28-throughput-fixes.md``. Docker and
    Apptainer options are radio-disabled when their CLI is not on the
    build host's PATH; the platform banner above the radio adapts
    its text based on the selected engine.
    """
    _, docker_ok, apptainer_ok = _detect_engine_availability()

    options = [
        {
            "label": " Conda environments  (this OS+arch only; ~5 GB bundle)",
            "value": "conda",
        },
        {
            "label": (
                " Docker images  (cross-platform; ~2 GB bundle)"
                if docker_ok
                else " Docker images  (Docker not detected on build host)"
            ),
            "value": "docker",
            "disabled": not docker_ok,
        },
        {
            "label": (
                " Apptainer/Singularity  (Linux field hosts only; ~1.5 GB bundle)"
                if apptainer_ok
                else " Apptainer/Singularity  (apptainer not detected on build host)"
            ),
            "value": "singularity",
            "disabled": not apptainer_ok,
        },
    ]

    return dbc.RadioItems(
        id="bundle-containerization-radio",
        options=options,
        value="conda",
        className="mb-2",
    )


def create_preparation_layout():
    """Create the Preparation tab layout."""
    return dbc.Container([
        # Preparation-local stores
        dcc.Store(id="wizard-step-state", data={
            "current_step": 0,
            "steps": {
                "0": "pending", "1": "pending", "2": "pending", "3": "pending",
                "4": "pending", "5": "pending", "6": "pending", "7": "pending",
            },
        }),
        # Intermediate store: relays wizard-step-state updates from MATCH callbacks
        # to the plain wizard-step-state store (MATCH and plain IDs cannot be mixed
        # in a single callback's outputs).
        dcc.Store(id="wizard-step-state-relay", data=None),
        dcc.Store(id="genome-import-unrecognized", data=[]),

        # Workflow step indicator
        WorkflowStepper(active_step=3),

        # Header
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-box-seam me-2",
                           style={"fontSize": "1.3rem"}),
                    html.H4("Preparation", className="mb-0 d-inline"),
                ], className="d-flex align-items-center mb-1"),
                html.P(
                    "Verify that everything is ready before you start analysis. "
                    "1. Run the readiness checklist. 2. Click Start Preparation "
                    "for automated setup, or expand Advanced: Individual Stages "
                    "to run a single step. 3. Use Offline deployment to build a "
                    "portable bundle for field machines.",
                    className="text-muted mb-0 small"
                ),
            ]),
        ], className="mb-3"),

        # Readiness checklist
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.I(className="bi bi-clipboard-check me-2",
                           style={"fontSize": "1.1rem"}),
                    html.H5("Readiness Checklist", className="mb-0 d-inline"),
                    html.I(
                        id="readiness-collapse-icon",
                        className="bi bi-chevron-down ms-2",
                        style={"fontSize": "0.9rem", "cursor": "pointer"},
                    ),
                ], className="d-inline-flex align-items-center",
                   id="readiness-header-toggle",
                   role="button",
                   style={"cursor": "pointer"}),
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-1"), "Check Everything"],
                    id="check-readiness-btn",
                    color="primary",
                    size="sm",
                    className="float-end",
                ),
            ]),
            dbc.Collapse(
                dbc.CardBody([
                    dbc.Spinner(
                        html.Div(id="readiness-results",
                                 children=html.Div([
                                     html.I(className="bi bi-info-circle text-muted me-2"),
                                     html.Span(
                                         "Click 'Check Everything' above to verify your setup. "
                                         "This will check directories, databases, and required software.",
                                         className="text-muted",
                                     ),
                                 ], className="d-flex align-items-center")),
                        size="sm",
                        type="border",
                    ),
                ]),
                id="readiness-collapse",
                is_open=True,
            ),
        ], className="mb-4"),

        # Recommended order guidance (rewritten to describe primary vs manual split)
        dbc.Alert([
            html.I(className="bi bi-signpost-2 me-2"),
            html.Strong("Recommended order: "),
            html.Span(
                "Run the readiness checklist, then click Start Preparation for "
                "one-shot setup. The Manual stages and Offline deployment "
                "sections below are collapsed by default; expand them only "
                "to inspect or re-run individual stages."
            ),
        ], color="light", className="small py-2 mb-3 border"),

        # PRIMARY PATH: Run Preparation (full width)
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="bi bi-gear-wide-connected me-2"),
                    "Run Preparation"
                ], className="mb-0"),
            ]),
            dbc.CardBody([
                html.P(
                    "Run all preparation steps automatically: verify the database, "
                    "check organism mappings, download reference genomes, and build "
                    "search indexes.",
                    className="text-muted"
                ),
                dbc.Checklist(
                    id="prep-options",
                    options=[
                        {"label": " Skip already-completed steps", "value": "skip_existing"},
                    ],
                    value=["skip_existing"],
                    className="mb-3",
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            [html.I(className="bi bi-play-circle me-2"), "Start Preparation"],
                            id="start-prep-btn",
                            color="primary",
                            size="lg",
                            className="me-2",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-x-circle me-2"), "Cancel"],
                            id="cancel-prep-btn",
                            color="outline-danger",
                            size="lg",
                            style={"display": "none"},
                        ),
                    ]),
                ]),
                # Progress area
                html.Div(id="prep-progress-area", children=[], className="mt-3"),
                # Result area
                html.Div(id="prep-result-area", children=[], className="mt-3"),
            ]),
        ], className="mb-4 border-primary shadow-sm"),

        # SECONDARY: Manual stages (collapsed accordion)
        dbc.Accordion([
            dbc.AccordionItem([
                html.P(
                    "Run individual preparation stages. Use these only to "
                    "inspect, debug, or re-run a single step; the primary "
                    "Run Preparation flow above covers all of them.",
                    className="text-muted small mb-3",
                ),
                # Kraken2 Database Download
                html.Div(_create_kraken_db_download_card(), id="kraken2-db-card"),
                # Taxid Mapping / Rescan DB
                html.Div(_create_rescan_db_card(), id="taxid-mapping-card"),
                # Genome Downloads
                html.Div(_create_genome_downloads_card(), id="genome-downloads-card"),
                # Import Genomes
                html.Div(_create_import_genomes_card(), id="import-genomes-card"),
            ], title=html.Span([
                html.I(className="bi bi-tools me-2"),
                "Advanced: Individual Stages",
                html.Small(
                    "  -  most users should use Run Preparation above",
                    className="text-muted ms-2",
                ),
            ])),
        ], start_collapsed=True, className="mb-4"),

        # OFFLINE DEPLOYMENT: wizard + export + import (collapsed accordion)
        dbc.Accordion([
            dbc.AccordionItem([
                html.P(
                    "Tools for preparing a portable bundle for field "
                    "deployment. Use the wizard to step through each "
                    "stage, or the Export / Import controls if you "
                    "already have a prepared bundle.",
                    className="text-muted small mb-3",
                ),
                # Deploy Offline Wizard
                _create_deploy_wizard_card(),
                # Export / Import side by side
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5([
                                    html.I(className="bi bi-box-arrow-up me-2"),
                                    "Export Bundle"
                                ], className="mb-0"),
                            ]),
                            dbc.CardBody([
                                html.P(
                                    "Package all prepared data into a portable archive for "
                                    "transfer to a field computer. The species database is not "
                                    "included due to size -- transfer it separately.",
                                    className="text-muted small"
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText("Save to"),
                                    dbc.Input(
                                        id="bundle-export-directory",
                                        value=str(Path.home() / "Downloads"),
                                        type="text",
                                        placeholder="/path/to/save/directory",
                                    ),
                                    dbc.Button(
                                        html.I(className="bi bi-folder2-open"),
                                        id="bundle-export-browse-btn",
                                        color="secondary",
                                        outline=True,
                                        n_clicks=0,
                                        title="Browse for directory",
                                    ),
                                ], className="mb-2"),
                                dbc.InputGroup([
                                    dbc.InputGroupText("Filename"),
                                    dbc.Input(
                                        id="bundle-export-filename",
                                        value="mobile_lab_bundle.tar.gz",
                                        type="text",
                                    ),
                                ], className="mb-3"),
                                # Containerization engine + adaptive
                                # platform banner. Conda mode keeps the
                                # legacy pre-warm checkbox visible so
                                # operators can opt out for very large
                                # bundles or cross-platform builds.
                                html.Label(
                                    "Containerization:",
                                    className="fw-bold mb-1",
                                    htmlFor="bundle-containerization-radio",
                                ),
                                _build_containerization_radio(),
                                # Conda-mode-only sub-control: pre-warm
                                # toggle. The export callback ignores
                                # this flag when docker / singularity
                                # is selected.
                                dbc.Checkbox(
                                    id="bundle-export-prewarm",
                                    label=(
                                        "Pre-warm conda environments "
                                        "(adds roughly 30 min and ~5 GB; "
                                        "applies only to Conda mode)"
                                    ),
                                    value=True,
                                    className="mb-2 ms-3",
                                ),
                                _build_platform_banner(),
                                dbc.Button(
                                    [html.I(className="bi bi-download me-2"), "Export Bundle"],
                                    id="export-bundle-btn",
                                    color="success",
                                ),
                                # Readiness issues area (populated by callback)
                                html.Div(id="export-readiness-issues", className="mt-3"),
                                # Force-export controls (hidden by default)
                                html.Div(
                                    id="export-force-area",
                                    style={"display": "none"},
                                    children=[
                                        dbc.Checkbox(
                                            id="export-force-check",
                                            label="I understand the bundle is incomplete",
                                            value=False,
                                            className="mb-2",
                                        ),
                                        dbc.Button(
                                            [html.I(className="bi bi-exclamation-triangle me-2"),
                                             "Export Incomplete Bundle"],
                                            id="export-force-btn",
                                            color="warning",
                                            disabled=True,
                                        ),
                                    ],
                                ),
                                html.Div(id="export-result", className="mt-2"),
                            ]),
                        ]),
                    ], md=6),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5([
                                    html.I(className="bi bi-box-arrow-in-down me-2"),
                                    "Import Bundle"
                                ], className="mb-0"),
                            ]),
                            dbc.CardBody([
                                html.P(
                                    "Import a bundle from another machine. "
                                    "You must also provide the path to the species database "
                                    "on this computer.",
                                    className="text-muted small"
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText("Bundle Path"),
                                    dbc.Input(
                                        id="import-bundle-path",
                                        placeholder="/path/to/bundle.tar.gz",
                                        type="text",
                                    ),
                                ], className="mb-2"),
                                dbc.InputGroup([
                                    dbc.InputGroupText("Species DB"),
                                    dbc.Input(
                                        id="import-kraken-db-path",
                                        placeholder="/path/to/species/database",
                                        type="text",
                                    ),
                                ], className="mb-3"),
                                dbc.Button(
                                    [html.I(className="bi bi-upload me-2"), "Import Bundle"],
                                    id="import-bundle-btn",
                                    color="info",
                                ),
                                html.Div(id="import-result", className="mt-2"),
                            ]),
                        ]),
                    ], md=6),
                ]),
            ], title=html.Span([
                html.I(className="bi bi-rocket-takeoff me-2"),
                "Offline deployment (wizard, export, import)",
            ])),
        ], start_collapsed=True, className="mb-4"),

        # Modals
        _create_genome_download_modal(),
        _create_blast_build_modal(),
        _create_remove_all_confirm_modal(),

        # Page-bottom Start Analysis CTA. Mirrors the "Next" button
        # placement on the Configuration and Watchlist tabs so the
        # operator's left-to-right step flow ends with a Start
        # Analysis button in the same screen position they expect a
        # Next button. Proxies to the header start-stop-button via
        # the callback in callbacks.py so the existing
        # start_or_prompt_stop logic (collision modal, readiness
        # gate, backend launch) runs unchanged.
        html.Div([
            html.Hr(className="my-4"),
            html.Div([
                dbc.Button(
                    [
                        html.I(className="bi bi-play-fill me-2"),
                        "Start Analysis",
                    ],
                    id="preparation-start-analysis-btn",
                    color="primary",
                    size="lg",
                    n_clicks=0,
                ),
            ], className="text-end"),
        ], className="mt-3 mb-4"),
    ], fluid=True, className="py-3")


# =============================================================================
# SECTION CARDS
# =============================================================================

def _create_kraken_db_download_card() -> dbc.Card:
    """Create the Kraken2 database download card (moved from Configuration tab)."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-database-down me-2"),
            html.H5("Download Species Identification Database", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            html.P(
                "Download a pre-built species database. This is the reference library "
                "used to identify organisms in your samples. The file path will be "
                "set automatically after download completes.",
                className="text-muted small mb-3"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Select Database", html_for="external-kraken-input"),
                    dbc.Select(
                        id="external-kraken-input",
                        options=[
                            {"label": "-- Select to download --", "value": ""},
                        ],
                        value=""
                    ),
                    dbc.FormText("Select a pre-built database to download"),
                ], md=8),
                dbc.Col([
                    dbc.Label(" ", className="d-block"),
                    dbc.Button(
                        [html.I(className="bi bi-download me-1"), "Download"],
                        id="download-kraken-db-btn",
                        color="primary",
                        disabled=True,
                        className="w-100",
                    ),
                ], md=4),
            ]),
            html.Div(id="kraken-download-status", className="mt-2"),
        ]),
    ], className="mb-4")


def _create_rescan_db_card() -> dbc.Card:
    """Create the Rescan DB / Taxid Mapping card (moved from Watchlist tab)."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-arrow-repeat me-2"),
            html.H5("Verify Watchlist Against Database", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            html.P(
                "Check that each organism on your watchlist can be found in the species "
                "database. This step ensures accurate detection, especially when using "
                "specialised databases.",
                className="text-muted small mb-3"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        [
                            html.I(id="taxmap-rescan-icon", className="bi bi-arrow-repeat me-1"),
                            html.Span(id="taxmap-rescan-text", children="Scan Database"),
                        ],
                        id="taxmap-rescan-btn",
                        color="primary",
                        n_clicks=0,
                        title="Scan the species database to verify watchlist organisms are present",
                    ),
                    html.Small(id="taxmap-rescan-status", className="ms-2 text-muted"),
                ], width="auto"),
            ]),
            # Inline progress bar (hidden by default)
            html.Div(id="taxmap-rescan-progress-container", style={"display": "none"}, children=[
                dbc.Progress(id="taxmap-rescan-progress", value=0, striped=True, animated=True, className="mt-2", style={"height": "6px"}),
                html.Small(id="taxmap-rescan-progress-label", children="", className="text-muted mt-1 d-block"),
            ]),
            # Current status display
            html.Div(id="taxmap-rescan-info", className="mt-3", children=[
                html.Div([html.I(className="bi bi-database me-2"), html.Span(id="taxmap-current-db-type", children="No database scanned yet", className="small text-muted")], className="mb-1"),
                html.Div([html.I(className="bi bi-check2-circle me-2"), html.Span(id="taxmap-current-mapping-count", children="0 organisms matched", className="small text-muted")], className="mb-1"),
                html.Div([html.I(className="bi bi-clock-history me-2"), html.Span(id="taxmap-last-scan-time", children="Last scan: Never", className="small text-muted")]),
            ]),
        ]),
    ], className="mb-4")


def _create_genome_downloads_card() -> dbc.Card:
    """
    Create the genome downloads card (moved from Watchlist tab).

    Provides controls for downloading reference genomes for BLAST validation.
    Shows statistics on downloaded genomes and allows bulk downloads.
    """
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-file-earmark-medical me-2"),
            html.H5("Reference Genomes for Confirmation Testing", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            # Status overview row
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span(
                            "0",
                            id="genome-stat-downloaded",
                            className="h5 mb-0 text-success"
                        ),
                        html.Small(" downloaded", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-3"),
                dbc.Col([
                    html.Div([
                        html.Span(
                            "0",
                            id="genome-stat-missing",
                            className="h5 mb-0 text-warning"
                        ),
                        html.Small(" missing", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-3"),
                dbc.Col([
                    html.Div([
                        html.Span(
                            "0",
                            id="genome-stat-blast",
                            className="h5 mb-0 text-info"
                        ),
                        html.Small(" with search index", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-3"),
                dbc.Col([
                    html.Small(
                        id="genome-stat-size",
                        children="0 MB",
                        className="text-muted",
                    ),
                ], width="auto"),

                # Spacer
                dbc.Col([], className="flex-grow-1"),

                # Action buttons
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button(
                            [html.I(className="bi bi-arrow-repeat me-1"), "Refresh"],
                            id="genome-refresh-btn",
                            color="secondary",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-download me-1"), "Download Missing"],
                            id="genome-download-all-btn",
                            color="primary",
                            size="sm",
                            n_clicks=0,
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-database me-1"), "Build Search Index"],
                            id="genome-build-blast-btn",
                            color="success",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            title="Build search indexes from downloaded reference genomes for confirmation testing",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-trash me-1"), "Remove All"],
                            id="genome-remove-all-btn",
                            color="danger",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            title="Delete all downloaded genomes and BLAST databases",
                        ),
                    ], size="sm"),
                ], width="auto"),
            ], align="center", className="mb-3"),

            html.Hr(className="my-2"),

            # Info text
            html.Div([
                html.Small([
                    html.I(className="bi bi-info-circle me-1"),
                    "Reference genomes are used to double-check species identifications. "
                    "Bacterial genomes are downloaded from GTDB, other organisms from NCBI.",
                ], className="text-muted"),
            ], className="mb-3"),

            # Missing genomes list
            html.Div([
                html.H6("Missing Genomes", className="text-muted mb-2"),
                html.Div(
                    id="genome-missing-list",
                    children=[
                        html.P("No missing genomes.", className="text-muted fst-italic")
                    ],
                    style={"maxHeight": "420px", "overflowY": "auto"},
                ),
            ], className="mb-3"),

            # Downloaded genomes list
            html.Div([
                html.H6("Downloaded Genomes", className="text-muted mb-2"),
                html.Div(
                    id="genome-downloaded-list",
                    children=[
                        html.P("No genomes downloaded yet.", className="text-muted fst-italic")
                    ],
                    style={"maxHeight": "420px", "overflowY": "auto"},
                ),
            ]),

            # Dependency status and test download
            html.Div([
                html.Hr(className="my-2"),
                html.H6("System Requirements", className="text-muted mb-2"),
                html.Div(
                    id="genome-dependency-status",
                    children=[
                        html.Div([
                            html.I(className="bi bi-hourglass-split text-muted me-2"),
                            html.Span("Checking dependencies...", className="text-muted"),
                        ]),
                    ],
                    className="mb-2",
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            [html.I(className="bi bi-cloud-download me-2"), "Test Download (E. coli)"],
                            id="test-genome-download-btn",
                            color="info",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            disabled=False,
                        ),
                        html.Small(
                            " Verify genome download works with E. coli (taxid 562)",
                            className="text-muted ms-2",
                        ),
                    ], width="auto"),
                ], className="mb-2"),
                html.Div(
                    id="genome-test-result",
                    children=[],
                    className="mt-2",
                ),
            ], className="mt-2"),
        ]),
    ], className="mb-4")


def _create_import_genomes_card() -> dbc.Card:
    """
    Create the manual genome import card.

    Allows importing genome FASTA files from a local directory or archive,
    with automatic taxid recognition for files named ``{taxid}.fasta``.
    """
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-folder-plus me-2"),
            html.H5("Import Genomes", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            html.P(
                "Import reference genome files from a local folder or archive. "
                "Files named with their taxonomy ID (e.g. 562.fasta) are recognised automatically.",
                className="text-muted small mb-3"
            ),
            dbc.Tabs([
                dbc.Tab([
                    dbc.InputGroup([
                        dbc.InputGroupText("Directory"),
                        dbc.Input(
                            id="genome-import-dir-path",
                            placeholder="/path/to/genomes/",
                            type="text",
                        ),
                    ], className="mt-3 mb-2"),
                    dbc.Button(
                        [html.I(className="bi bi-folder2-open me-1"), "Import from Directory"],
                        id="genome-import-dir-btn",
                        color="primary",
                        size="sm",
                        n_clicks=0,
                    ),
                ], label="Directory", tab_id="import-dir"),
                dbc.Tab([
                    dbc.InputGroup([
                        dbc.InputGroupText("Archive path"),
                        dbc.Input(
                            id="genome-import-archive-path",
                            placeholder="/path/to/genomes.tar.gz",
                            type="text",
                        ),
                    ], className="mb-2"),
                    dbc.Button(
                        [html.I(className="bi bi-file-earmark-zip me-1"), "Import from Archive"],
                        id="genome-import-archive-btn",
                        color="primary",
                        size="sm",
                        n_clicks=0,
                    ),
                ], label="Archive", tab_id="import-archive"),
            ], id="genome-import-tabs", active_tab="import-dir"),

            # Import result area
            html.Div(id="genome-import-result", className="mt-3"),

            # Unrecognized files mapping area (shown when needed)
            html.Div(
                id="genome-import-mapping-area",
                style={"display": "none"},
                className="mt-3",
                children=[
                    html.H6("Unrecognized Files", className="text-warning mb-2"),
                    html.P(
                        "The following files could not be matched to a known organism. "
                        "Enter the NCBI taxonomy ID for each file to import it "
                        "(find IDs at ncbi.nlm.nih.gov/taxonomy).",
                        className="text-muted small",
                    ),
                    html.Div(id="genome-import-mapping-table"),
                    dbc.Button(
                        [html.I(className="bi bi-check-circle me-1"), "Import Mapped"],
                        id="genome-import-mapped-btn",
                        color="success",
                        size="sm",
                        className="mt-2",
                        n_clicks=0,
                    ),
                ],
            ),
        ]),
    ], className="mb-4")


# =============================================================================
# MODALS
# =============================================================================

def _create_genome_download_modal() -> dbc.Modal:
    """Create the genome download progress modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle([
                html.I(className="bi bi-download me-2"),
                "Downloading Genomes",
            ]),
        ]),
        dbc.ModalBody([
            html.Div([
                html.P(
                    id="genome-download-progress-text",
                    children="Preparing downloads...",
                    className="mb-2 fw-semibold",
                ),
                dbc.Progress(
                    id="genome-download-progress-bar",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-3",
                    style={"height": "24px"},
                ),
                html.Div([
                    html.Small("Current operation:", className="text-muted"),
                    html.P(
                        id="genome-download-progress-detail",
                        className="mb-2 small fst-italic",
                        children="Initializing...",
                    ),
                ]),
                html.Div([
                    html.Small("Download log:", className="text-muted d-block mb-1"),
                    html.Div(
                        id="genome-download-log",
                        className="border rounded p-2 bg-light",
                        style={
                            "maxHeight": "150px",
                            "overflowY": "auto",
                            "fontFamily": "monospace",
                            "fontSize": "0.8rem",
                        },
                        children=[],
                    ),
                ], className="mt-2"),
            ]),
        ]),
        dbc.ModalFooter([
            html.Div(
                id="genome-download-status-badge",
                className="me-auto",
                children=[],
            ),
            dbc.Button(
                "Cancel",
                id="genome-download-cancel-btn",
                color="secondary",
                n_clicks=0,
            ),
            dbc.Button(
                "Close",
                id="genome-download-close-btn",
                color="primary",
                n_clicks=0,
                style={"display": "none"},
            ),
        ]),
    ], id="genome-download-modal", centered=True, backdrop="static", is_open=False, size="lg")


def _create_blast_build_modal() -> dbc.Modal:
    """Create the BLAST database build progress modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle([
                html.I(className="bi bi-database-fill-gear me-2"),
                "Building BLAST Databases",
            ]),
        ]),
        dbc.ModalBody([
            html.Div([
                html.P(
                    id="blast-build-progress-text",
                    children="Preparing to build databases...",
                    className="mb-2 fw-semibold",
                ),
                dbc.Progress(
                    id="blast-build-progress-bar",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-3",
                    style={"height": "24px"},
                ),
                html.Div([
                    html.Small("Current operation:", className="text-muted"),
                    html.P(
                        id="blast-build-progress-detail",
                        className="mb-2 small fst-italic",
                        children="Initializing...",
                    ),
                ]),
                html.Div([
                    html.Small("Build log:", className="text-muted d-block mb-1"),
                    html.Div(
                        id="blast-build-log",
                        className="border rounded p-2 bg-light",
                        style={
                            "maxHeight": "150px",
                            "overflowY": "auto",
                            "fontFamily": "monospace",
                            "fontSize": "0.8rem",
                        },
                        children=[],
                    ),
                ], className="mt-2"),
            ]),
        ]),
        dbc.ModalFooter([
            html.Div(
                id="blast-build-status-badge",
                className="me-auto",
                children=[],
            ),
            dbc.Button(
                "Cancel",
                id="blast-build-cancel-btn",
                color="secondary",
                n_clicks=0,
            ),
            dbc.Button(
                "Close",
                id="blast-build-close-btn",
                color="primary",
                n_clicks=0,
                style={"display": "none"},
            ),
        ]),
    ], id="blast-build-modal", centered=True, backdrop="static", is_open=False, size="lg")


def _create_remove_all_confirm_modal() -> dbc.Modal:
    """Confirmation dialog for removing all downloaded genomes."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle([
                html.I(className="bi bi-exclamation-triangle-fill text-danger me-2"),
                "Remove All Genomes",
            ]),
        ]),
        dbc.ModalBody([
            html.P(
                "This will permanently delete all downloaded genome FASTA files "
                "and their BLAST databases.",
                className="mb-2",
            ),
            html.P(
                "Taxid mappings and watchlist configuration will not be affected.",
                className="text-muted mb-0",
            ),
            html.Div(id="genome-remove-all-count", className="mt-2 fw-bold"),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Cancel",
                id="genome-remove-all-cancel-btn",
                color="secondary",
                n_clicks=0,
            ),
            dbc.Button(
                [html.I(className="bi bi-trash me-1"), "Remove All"],
                id="genome-remove-all-confirm-btn",
                color="danger",
                n_clicks=0,
            ),
        ]),
    ], id="genome-remove-all-modal", centered=True, is_open=False)


# =============================================================================
# DEPLOY OFFLINE WIZARD
# =============================================================================

_WIZARD_STEPS = [
    {
        "index": 0,
        "icon": "bi-list-check",
        "title": "Select Watchlists",
        "desc": "Choose which organism watchlists to include in the field deployment.",
    },
    {
        "index": 1,
        "icon": "bi-database-check",
        "title": "Verify Species Database",
        "desc": "Confirm the species identification database is valid and accessible.",
    },
    {
        "index": 2,
        "icon": "bi-diagram-3",
        "title": "Build Organism Index",
        "desc": "Build the organism lookup index so watchlist species can be matched.",
    },
    {
        "index": 3,
        "icon": "bi-cloud-download",
        "title": "Download Reference Genomes",
        "desc": "Download reference genomes for confirmation testing of detected organisms.",
    },
    {
        "index": 4,
        "icon": "bi-database-fill-gear",
        "title": "Build Search Indexes",
        "desc": "Build search indexes from reference genomes for confirmation testing.",
    },
    {
        "index": 5,
        "icon": "bi-archive",
        "title": "Cache Organism Names",
        "desc": "Save organism name lookup data so names resolve without internet access.",
    },
    {
        "index": 6,
        "icon": "bi-clipboard2-check",
        "title": "Readiness Check",
        "desc": "Verify that everything is in place for offline operation.",
    },
    {
        "index": 7,
        "icon": "bi-box-seam",
        "title": "Export Bundle",
        "desc": "Package all prepared data into a portable archive for field deployment.",
    },
]


def _wizard_step_item(step):
    """Create a single wizard step accordion item."""
    idx = step["index"]
    return dbc.AccordionItem(
        [
            html.P(step["desc"], className="text-muted small mb-3"),
            # Step-specific content placeholder
            html.Div(id=f"wizard-step-{idx}-content"),
            # Run button and status
            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        [html.I(className=f"bi bi-play-circle me-2"), "Run"],
                        id={"type": "wizard-step-run", "index": idx},
                        color="primary",
                        size="sm",
                        n_clicks=0,
                    ),
                ], width="auto"),
                dbc.Col([
                    html.Div(
                        id={"type": "wizard-step-status", "index": idx},
                        className="d-flex align-items-center",
                    ),
                ]),
            ], align="center", className="mt-2"),
            # Progress area
            html.Div(
                id={"type": "wizard-step-progress", "index": idx},
                className="mt-2",
            ),
        ],
        title=html.Span([
            html.I(className=f"bi {step['icon']} me-2"),
            f"Step {idx + 1}: {step['title']}",
        ]),
        item_id=f"wizard-step-{idx}",
    )


def _create_deploy_wizard_card() -> dbc.Card:
    """Create the Deploy Offline wizard card with stepper UI."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-rocket-takeoff me-2",
                       style={"fontSize": "1.1rem"}),
                html.H5("Deploy Offline", className="mb-0 d-inline"),
            ], className="d-inline-flex align-items-center"),
        ]),
        dbc.CardBody([
            html.P(
                "Step-by-step wizard to prepare a complete offline deployment. "
                "Each step can be run individually or use 'Run All' to execute "
                "the full pipeline sequentially.",
                className="text-muted small mb-3",
            ),
            # Overall progress
            html.Div([
                html.Div([
                    html.Small("Overall progress", className="text-muted"),
                    html.Span(
                        id="wizard-overall-label",
                        children="0/8 steps",
                        className="text-muted small float-end",
                    ),
                ]),
                dbc.Progress(
                    id="wizard-overall-progress",
                    value=0,
                    className="mb-3",
                    style={"height": "8px"},
                ),
            ]),
            # Run All / Cancel controls
            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        [html.I(className="bi bi-fast-forward me-2"), "Run All Steps"],
                        id="wizard-run-all-btn",
                        color="success",
                        size="sm",
                        className="me-2",
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-x-circle me-2"), "Cancel"],
                        id="wizard-cancel-btn",
                        color="outline-danger",
                        size="sm",
                        style={"display": "none"},
                        n_clicks=0,
                    ),
                ]),
            ], className="mb-3"),
            # Result area for Run All
            html.Div(id="wizard-run-all-result", className="mb-3"),
            # Step accordion
            dbc.Accordion(
                [_wizard_step_item(step) for step in _WIZARD_STEPS],
                id="wizard-steps-accordion",
                start_collapsed=True,
                always_open=True,
            ),
        ]),
    ], className="mb-4")
