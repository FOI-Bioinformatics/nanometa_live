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

import dash_bootstrap_components as dbc
from dash import html, dcc

from nanometa_live.app.components.modern_components import WorkflowStepper


def create_preparation_layout():
    """Create the Preparation tab layout."""
    return dbc.Container([
        # Preparation-local stores
        dcc.Store(id="prep-job-state", data=None),
        dcc.Store(id="genome-download-progress", data={"current": 0, "total": 0, "status": "idle"}),
        dcc.Store(id="download-cancel-flag", data=False),
        dcc.Store(id="blast-cancel-flag", data=False),

        # Workflow step indicator
        WorkflowStepper(active_step=3),

        # Recommended order guidance
        html.P(
            "Follow the steps below in order. Start with the Readiness Checklist "
            "to identify any issues, then address them using the sections below.",
            className="text-muted small mb-3",
        ),

        # Header
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-box-seam me-2",
                           style={"fontSize": "1.3rem"}),
                    html.H4("Preparation", className="mb-0 d-inline"),
                ], className="d-flex align-items-center mb-1"),
                html.P(
                    "Download databases, scan taxid mappings, download genomes, "
                    "build BLAST databases, and export portable bundles. "
                    "Complete these steps before starting analysis.",
                    className="text-muted mb-0 small"
                ),
            ]),
        ], className="mb-4"),

        # Readiness checklist
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.I(className="bi bi-clipboard-check me-2",
                           style={"fontSize": "1.1rem"}),
                    html.H5("Readiness Checklist", className="mb-0 d-inline"),
                ], className="d-inline-flex align-items-center"),
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-1"), "Run Checks"],
                    id="check-readiness-btn",
                    color="outline-primary",
                    size="sm",
                    className="float-end",
                ),
            ]),
            dbc.CardBody([
                dbc.Spinner(
                    html.Div(id="readiness-results",
                             children=html.Div([
                                 html.I(className="bi bi-info-circle text-muted me-2"),
                                 html.Span(
                                     "Click 'Run Checks' to verify that all required "
                                     "components are configured.",
                                     className="text-muted",
                                 ),
                             ], className="d-flex align-items-center")),
                    size="sm",
                    type="border",
                ),
            ]),
        ], className="mb-4"),

        # Kraken2 Database Download (moved from Configuration tab)
        html.Div(_create_kraken_db_download_card(), id="kraken2-db-card"),

        # Taxid Mapping / Rescan DB (moved from Watchlist tab)
        html.Div(_create_rescan_db_card(), id="taxid-mapping-card"),

        # Genome Downloads (moved from Watchlist tab)
        html.Div(_create_genome_downloads_card(), id="genome-downloads-card"),

        # Run Preparation
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="bi bi-gear-wide-connected me-2"),
                    "Run Preparation"
                ], className="mb-0"),
            ]),
            dbc.CardBody([
                html.P(
                    "Build taxonomy index, generate taxid mappings, download "
                    "reference genomes, and build BLAST databases.",
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
                            className="me-2",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-x-circle me-2"), "Cancel"],
                            id="cancel-prep-btn",
                            color="outline-danger",
                            style={"display": "none"},
                        ),
                    ]),
                ]),
                # Progress area
                html.Div(id="prep-progress-area", children=[], className="mt-3"),
                # Result area
                html.Div(id="prep-result-area", children=[], className="mt-3"),
            ]),
        ], className="mb-4"),

        # Export / Import (collapsed by default)
        dbc.Accordion([
            dbc.AccordionItem([
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
                                    "Package all prepared data into a portable archive. "
                                    "The Kraken2 database is not included (transfer separately).",
                                    className="text-muted small"
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText("Filename"),
                                    dbc.Input(
                                        id="bundle-export-filename",
                                        value="mobile_lab_bundle.tar.gz",
                                        type="text",
                                    ),
                                ], className="mb-3"),
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
                                    "You must also provide the local Kraken2 database path.",
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
                                    dbc.InputGroupText("Kraken2 DB"),
                                    dbc.Input(
                                        id="import-kraken-db-path",
                                        placeholder="/path/to/kraken2/db",
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
            ], title="Export / Import Bundle (Advanced)"),
        ], start_collapsed=True, className="mb-4"),

        # Modals
        _create_genome_download_modal(),
        _create_blast_build_modal(),
        _create_rescan_progress_modal(),

    ], fluid=True, className="py-3")


# =============================================================================
# SECTION CARDS
# =============================================================================

def _create_kraken_db_download_card() -> dbc.Card:
    """Create the Kraken2 database download card (moved from Configuration tab)."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-database-down me-2"),
            html.H5("Download External Kraken2 Database", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            html.P(
                "Download a pre-built Kraken2 database. The database path will be "
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
            html.H5("Taxid Mapping (Rescan Database)", className="mb-0 d-inline"),
        ]),
        dbc.CardBody([
            html.P(
                "Scan the Kraken2 database to map watchlist pathogen taxids to database entries. "
                "This is needed for accurate detection when using GTDB or custom databases.",
                className="text-muted small mb-3"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Button(
                        [
                            html.I(id="taxmap-rescan-icon", className="bi bi-arrow-repeat me-1"),
                            html.Span(id="taxmap-rescan-text", children="Rescan DB"),
                        ],
                        id="taxmap-rescan-btn",
                        color="primary",
                        n_clicks=0,
                        title="Re-scan Kraken2 database for taxid mappings",
                    ),
                    html.Small(id="taxmap-rescan-status", className="ms-2 text-muted"),
                ], width="auto"),
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
            html.H5("Genome Downloads for BLAST Validation", className="mb-0 d-inline"),
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
                        html.Small(" with BLAST DB", className="text-muted ms-1"),
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
                            [html.I(className="bi bi-database me-1"), "Build BLAST DBs"],
                            id="genome-build-blast-btn",
                            color="success",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            title="Build BLAST databases for downloaded genomes",
                        ),
                    ], size="sm"),
                ], width="auto"),
            ], align="center", className="mb-3"),

            html.Hr(className="my-2"),

            # Info text
            html.Div([
                html.Small([
                    html.I(className="bi bi-info-circle me-1"),
                    "Reference genomes are used for BLAST validation of detected pathogens. "
                    "Bacteria/Archaea genomes are downloaded from GTDB, other organisms from NCBI RefSeq.",
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
                    style={"maxHeight": "200px", "overflowY": "auto"},
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
                    style={"maxHeight": "200px", "overflowY": "auto"},
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


def _create_rescan_progress_modal() -> dbc.Modal:
    """Create the rescan progress modal for taxmap scanning."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle([
                html.I(className="bi bi-arrow-repeat me-2"),
                "Scanning Database",
            ]),
        ]),
        dbc.ModalBody([
            html.Div([
                html.P(
                    id="taxmap-rescan-progress-text",
                    children="Initializing...",
                    className="mb-2",
                ),
                dbc.Progress(
                    id="taxmap-rescan-progress-bar",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-2",
                    style={"height": "20px"},
                ),
                html.Small(
                    id="taxmap-rescan-progress-detail",
                    className="text-muted",
                ),
            ]),
        ]),
    ], id="taxmap-rescan-modal", centered=True, backdrop="static", is_open=False)
