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
        dcc.Store(id="wizard-step-state", data={
            "current_step": 0,
            "steps": {
                "0": "pending", "1": "pending", "2": "pending", "3": "pending",
                "4": "pending", "5": "pending", "6": "pending", "7": "pending",
            },
        }),
        dcc.Store(id="prep-job-state", data=None),
        dcc.Store(id="genome-download-progress", data={"current": 0, "total": 0, "status": "idle"}),
        dcc.Store(id="download-cancel-flag", data=False),
        dcc.Store(id="blast-cancel-flag", data=False),
        dcc.Store(id="genome-import-unrecognized", data=[]),

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

        # Import Genomes (manual / archive)
        html.Div(_create_import_genomes_card(), id="import-genomes-card"),

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

        # Deploy Offline Wizard
        _create_deploy_wizard_card(),

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
            # Inline progress bar (hidden by default)
            html.Div(id="taxmap-rescan-progress-container", style={"display": "none"}, children=[
                dbc.Progress(id="taxmap-rescan-progress", value=0, striped=True, animated=True, className="mt-2", style={"height": "6px"}),
                html.Small(id="taxmap-rescan-progress-label", children="", className="text-muted mt-1 d-block"),
            ]),
            # Current status display
            html.Div(id="taxmap-rescan-info", className="mt-3", children=[
                html.Div([html.I(className="bi bi-database me-2"), html.Span(id="taxmap-current-db-type", children="No database scanned", className="small text-muted")], className="mb-1"),
                html.Div([html.I(className="bi bi-check2-circle me-2"), html.Span(id="taxmap-current-mapping-count", children="0 species mapped", className="small text-muted")], className="mb-1"),
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
                "Import reference genome FASTA files from a local directory or archive. "
                "Files named {taxid}.fasta are recognized automatically.",
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
                    dcc.Upload(
                        id="genome-import-archive-upload",
                        children=html.Div([
                            html.I(className="bi bi-cloud-upload me-2"),
                            "Drag and drop or ",
                            html.A("select archive", className="text-primary"),
                            html.Br(),
                            html.Small("(.tar.gz or .zip)", className="text-muted"),
                        ]),
                        style={
                            "width": "100%",
                            "height": "80px",
                            "lineHeight": "40px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "5px",
                            "textAlign": "center",
                            "paddingTop": "10px",
                        },
                        className="mt-3 mb-2",
                        multiple=False,
                        max_size=500_000_000,  # 500 MB
                    ),
                    dbc.InputGroup([
                        dbc.InputGroupText("Or path"),
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
                        "The following files could not be matched to a taxid. "
                        "Enter the NCBI taxonomy ID for each file to import it.",
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


# =============================================================================
# DEPLOY OFFLINE WIZARD
# =============================================================================

_WIZARD_STEPS = [
    {
        "index": 0,
        "icon": "bi-list-check",
        "title": "Select Watchlists",
        "desc": "Choose which pathogen watchlists to include in the deployment.",
    },
    {
        "index": 1,
        "icon": "bi-database-check",
        "title": "Verify Kraken2 DB",
        "desc": "Confirm the Kraken2 database path is valid and contains required files.",
    },
    {
        "index": 2,
        "icon": "bi-diagram-3",
        "title": "Build Taxonomy Index",
        "desc": "Build the taxonomy index and generate taxid mappings from the database.",
    },
    {
        "index": 3,
        "icon": "bi-cloud-download",
        "title": "Download Genomes",
        "desc": "Download reference genomes for all watchlist entries.",
    },
    {
        "index": 4,
        "icon": "bi-database-fill-gear",
        "title": "Build BLAST DBs",
        "desc": "Build BLAST databases from downloaded reference genomes.",
    },
    {
        "index": 5,
        "icon": "bi-archive",
        "title": "Cache Taxonomy",
        "desc": "Export taxonomy lookup data for offline name resolution.",
    },
    {
        "index": 6,
        "icon": "bi-clipboard2-check",
        "title": "Readiness Check",
        "desc": "Verify that all prerequisites are in place for offline operation.",
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
            html.Span(
                id={"type": "wizard-step-badge", "index": idx},
                className="ms-2",
            ),
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
