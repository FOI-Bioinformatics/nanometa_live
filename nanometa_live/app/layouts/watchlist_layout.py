"""
Watchlist Tab Layout for Nanometa Live.

Provides a dedicated tab for managing species watchlists with:
- Statistics overview and taxonomy mode selector
- Watchlist file management (enable/disable builtin/user/project)
- Pathogens table with inline editing
- API validation controls (manual button)
- Add custom species with API lookup
"""

from typing import Any, Dict, List, Optional

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.taxid_mapping_ui import (
    create_mapping_section,
)
from nanometa_live.app.components.modern_components import WorkflowStepper


def create_watchlist_layout() -> html.Div:
    """
    Create the Watchlist tab layout.

    Simplified 4-section layout:
    1. Stats bar - Quick overview of watchlist status
    2. Pathogens table - Main interaction area with Kraken2 Match status
    3. Watchlist files (collapsible) - Enable/disable watchlist files
    4. Add species (collapsible) - Add custom species with API lookup

    Returns:
        html.Div containing the complete Watchlist management interface
    """
    return html.Div([
        # Workflow step indicator
        WorkflowStepper(active_step=2),

        # Stores for state management
        dcc.Store(id="watchlist-tab-state", data={}),
        dcc.Store(id="watchlist-table-refresh", data=0),  # Counter to force table refresh
        dcc.Store(id="api-validation-progress", data={"current": 0, "total": 0}),
        dcc.Store(id="api-lookup-result", data=None),
        # Watchlist-local stores
        dcc.Store(id="taxmap-selected-entry", data=None),
        # Note: taxmap-collection, taxmap-database-info, taxmap-rescan-complete,
        # taxmap-export-download, genome-status-data, genome-download-complete,
        # blast-build-complete are shared stores defined in app.py

        # Main content - Simplified 4-section layout
        dbc.Container([
            # Section 1: Stats Bar (compact overview)
            _create_stats_bar(),

            # Brief intro text
            html.P(
                "Organisms listed below will be monitored during analysis. "
                "A default watchlist is pre-enabled. Enable additional watchlists "
                "or add custom species below.",
                className="text-muted small mb-2",
            ),

            # Section 2: Pathogens Table (main focus area)
            _create_pathogens_table_section(),

            # Section 3: Watchlist Files (collapsible)
            _create_collapsible_watchlist_files(),

            # Section 4: Add Custom Species (collapsible)
            _create_collapsible_add_species(),

        ], fluid=True, className="p-3"),

        # Modals
        _create_entry_edit_modal(),
        _create_api_details_modal(),
        _create_validation_progress_modal(),
        # Taxid mapping modal (for Kraken2 Match badge clicks)
        _create_taxid_mapping_modal_only(),

        # Next step navigation
        html.Div([
            html.Hr(className="my-4"),
            html.Div([
                dbc.Button([
                    "Next: Prepare Databases ",
                    html.I(className="bi bi-arrow-right ms-1"),
                ],
                    id="watchlist-next-preparation-btn",
                    color="primary",
                    outline=True,
                    size="lg",
                ),
            ], className="text-end"),
        ]),

    ], id="watchlist-tab-content", className="watchlist-tab p-4")


# =============================================================================
# NEW SIMPLIFIED LAYOUT FUNCTIONS
# =============================================================================

def _create_stats_bar() -> dbc.Card:
    """
    Create a compact statistics bar.

    Shows: Total | Active | Validated | Critical/High counts
    Taxonomy mode moved to Configuration tab.
    """
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                # Total count
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-list-ul me-2 text-primary",
                               style={"fontSize": "1.1rem"}),
                        html.Span(
                            "0",
                            id="watchlist-stat-total",
                            className="h4 mb-0 text-primary"
                        ),
                        html.Small(" total", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-4"),

                # Active count
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-check-circle me-2 text-success",
                               style={"fontSize": "1.1rem"}),
                        html.Span(
                            "0",
                            id="watchlist-stat-active",
                            className="h4 mb-0 text-success"
                        ),
                        html.Small(" active", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-4"),

                # Validated count
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-patch-check me-2 text-info",
                               style={"fontSize": "1.1rem"}),
                        html.Span(
                            "0",
                            id="watchlist-stat-validated",
                            className="h4 mb-0 text-info"
                        ),
                        html.Small(" validated", className="text-muted ms-1"),
                    ], className="d-flex align-items-baseline"),
                ], width="auto", className="me-4"),

                # Threat level badges
                dbc.Col([
                    dbc.Badge(
                        "Critical: 0",
                        id="watchlist-stat-critical",
                        color="danger",
                        className="me-2"
                    ),
                    dbc.Badge(
                        "High: 0",
                        id="watchlist-stat-high",
                        color="warning",
                    ),
                ], width="auto", className="me-4"),

                # Spacer
                dbc.Col([], className="flex-grow-1"),

                # API options for validation lookups
                dbc.Col([
                    html.Span([
                        html.Small("Databases: ", className="text-muted me-1"),
                        dbc.Checklist(
                            id="watchlist-api-options",
                            options=[
                                {"label": "NCBI", "value": "ncbi"},
                                {"label": "GTDB", "value": "gtdb"},
                            ],
                            value=["ncbi", "gtdb"],
                            inline=True,
                            className="small d-inline-flex",
                            inputClassName="me-1",
                            labelClassName="me-2 small",
                            persistence=True,
                            persistence_type="session",
                        ),
                    ], title="Select which taxonomy databases to query when validating species names",
                       className="d-flex align-items-center"),
                ], width="auto", className="me-2 d-flex align-items-center"),

                # Validation controls
                dbc.Col([
                    html.Div([
                        dbc.Button(
                            [html.I(className="bi bi-check2-all me-1"), "Verify Taxonomy IDs"],
                            id="watchlist-validate-all-btn",
                            color="primary",
                            size="sm",
                            n_clicks=0,
                        ),
                        dbc.Tooltip(
                            "Verify that species names and taxonomy IDs are valid "
                            "in NCBI/GTDB databases",
                            target="watchlist-validate-all-btn",
                            placement="bottom",
                        ),
                    ]),
                ], width="auto", className="d-flex align-items-center"),
            ], align="center", className="g-0"),
        ], className="py-2"),
    ], className="mb-3 watchlist-stats-bar")


def _create_pathogens_table_section() -> dbc.Card:
    """
    Create the pathogens table section.

    This is the main interaction area showing all pathogens from enabled
    watchlists with search, bulk actions, and status indicators.
    """
    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-shield-exclamation me-2",
                               style={"fontSize": "1.1rem"}),
                        html.H6("Monitored Pathogens", className="mb-0 d-inline"),
                        dbc.Badge(
                            id="watchlist-pathogen-count",
                            color="primary",
                            className="ms-2",
                            style={"display": "none"},
                        ),
                    ], className="d-flex align-items-center"),
                ], width=4),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(html.I(className="bi bi-search")),
                        dbc.Input(
                            id="watchlist-search-input",
                            type="text",
                            placeholder="Search by name, taxid, or category...",
                            debounce=True,
                        ),
                    ], size="sm"),
                ], width=4),
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button(
                            [html.I(className="bi bi-toggle-on me-1"), "Enable All"],
                            id="watchlist-enable-all-btn",
                            size="sm",
                            color="success",
                            outline=True,
                            n_clicks=0,
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-toggle-off me-1"), "Disable All"],
                            id="watchlist-disable-all-btn",
                            size="sm",
                            color="secondary",
                            outline=True,
                            n_clicks=0,
                        ),
                    ], size="sm"),
                ], width=4, className="text-end"),
            ], align="center"),
        ]),
        dbc.CardBody([
            # Table header with tooltip explanations
            html.Div([
                dbc.Row([
                    dbc.Col(html.Small("Organism", className="fw-bold"), width=3),
                    dbc.Col(html.Small("Threat", className="fw-bold"), width=1),
                    dbc.Col([
                        html.Small("BSL", className="fw-bold"),
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="bsl-header-info",
                               style={"fontSize": "0.7rem", "cursor": "help"}),
                        dbc.Tooltip(
                            "Biosafety level required for handling this organism",
                            target="bsl-header-info",
                            placement="top",
                        ),
                    ], width=1),
                    dbc.Col(html.Small("Validated", className="fw-bold"), width=1),
                    dbc.Col([
                        html.Small("DB Match", className="fw-bold"),
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="dbmatch-header-info",
                               style={"fontSize": "0.7rem", "cursor": "help"}),
                        dbc.Tooltip(
                            "Whether this organism's taxid was found in the "
                            "Kraken2 database. Run 'Rescan DB' in the Preparation "
                            "tab to populate this column.",
                            target="dbmatch-header-info",
                            placement="top",
                        ),
                    ], width=2),
                    dbc.Col([
                        html.Small("Ref.", className="fw-bold"),
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="genome-header-info",
                               style={"fontSize": "0.7rem", "cursor": "help"}),
                        dbc.Tooltip(
                            "Reference genome and BLAST database status for "
                            "validation. Download genomes in the Preparation tab.",
                            target="genome-header-info",
                            placement="top",
                        ),
                    ], width=1),
                    dbc.Col(html.Small("Actions", className="fw-bold"), width=3),
                ], className="py-2 bg-light border-bottom watchlist-table-header"),
            ]),

            # Table body (populated by callback)
            html.Div(
                id="watchlist-pathogens-table",
                style={"maxHeight": "400px", "overflowY": "auto"}
            ),
        ]),
    ], className="mb-3")


def _create_collapsible_watchlist_files() -> dbc.Accordion:
    """
    Create collapsible watchlist files section with quick-start presets.

    Combines watchlist file management with quick-start buttons.
    """
    return dbc.Accordion([
        dbc.AccordionItem([
            # Quick-start buttons row
            html.Div([
                html.Div([
                    html.I(className="bi bi-lightning me-1"),
                    html.Small("Quick enable: ", className="text-muted"),
                ], className="d-flex align-items-center me-2"),
                dbc.ButtonGroup([
                    dbc.Button(
                        [html.I(className="bi bi-hospital me-1"), "Clinical"],
                        id="quick-start-clinical",
                        size="sm",
                        color="primary",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-cup-straw me-1"), "Food Safety"],
                        id="quick-start-foodborne",
                        size="sm",
                        color="warning",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-droplet me-1"), "Water"],
                        id="quick-start-water",
                        size="sm",
                        color="info",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-lungs me-1"), "Respiratory"],
                        id="quick-start-respiratory",
                        size="sm",
                        color="secondary",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-shield-shaded me-1"), "Select Agents"],
                        id="quick-start-cdc",
                        size="sm",
                        color="danger",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-globe me-1"), "WHO Priority"],
                        id="quick-start-who",
                        size="sm",
                        color="dark",
                        outline=True,
                        n_clicks=0,
                    ),
                ], size="sm"),
                html.Span(" ", className="mx-1"),
                dbc.ButtonGroup([
                    dbc.Button(
                        [html.I(className="bi bi-building me-1"), "Nosocomial"],
                        id="quick-start-nosocomial",
                        size="sm",
                        color="danger",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-moisture me-1"), "Wastewater"],
                        id="quick-start-wastewater",
                        size="sm",
                        color="info",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-bug me-1"), "Zoonotic"],
                        id="quick-start-zoonotic",
                        size="sm",
                        color="success",
                        outline=True,
                        n_clicks=0,
                    ),
                ], size="sm"),
                html.Div(id="quick-start-feedback", className="ms-2 small d-inline"),
            ], className="mb-3 d-flex align-items-center flex-wrap"),

            html.Hr(className="my-2"),

            # Watchlist files
            dbc.Row([
                dbc.Col([
                    html.H6("Built-in", className="text-muted mb-2"),
                    html.Div(id="watchlist-builtin-list"),
                ], md=6),
                dbc.Col([
                    html.H6("Custom", className="text-muted mb-2"),
                    html.Div(id="watchlist-custom-list"),
                    dcc.Upload(
                        id="watchlist-upload",
                        children=html.Div([
                            html.I(className="bi bi-upload me-1"),
                            "Import YAML Watchlist"
                        ]),
                        style={
                            "border": "1px dashed var(--bs-secondary)",
                            "borderRadius": "4px",
                            "padding": "6px 12px",
                            "textAlign": "center",
                            "cursor": "pointer",
                            "marginTop": "8px",
                            "fontSize": "0.85rem",
                        },
                        multiple=False,
                        accept=".yaml,.yml",
                    ),
                    html.Div(id="watchlist-upload-feedback", className="mt-1 small"),
                    # Help text for custom watchlists
                    html.Details([
                        html.Summary(
                            html.Small("How to create a custom watchlist", className="text-muted"),
                            className="mt-2",
                            style={"cursor": "pointer"},
                        ),
                        html.Div([
                            html.P([
                                "Uploaded watchlists appear here alongside built-in lists "
                                "and can be enabled, expanded, and toggled in the same way."
                            ], className="small text-muted mb-2"),
                            html.P([
                                "Custom YAML files are saved to ",
                                html.Code("~/.nanometa/watchlists/"),
                                " and persist across sessions.",
                            ], className="small text-muted mb-2"),
                            html.P("Expected YAML format:", className="small fw-bold mb-1"),
                            html.Pre(
                                'version: "2.0"\n'
                                'taxonomy_support: ["ncbi", "gtdb"]\n'
                                "metadata:\n"
                                '  name: "My Watchlist"\n'
                                '  description: "Custom pathogens"\n'
                                "pathogens:\n"
                                '  - name: "Listeria monocytogenes"\n'
                                "    taxid_ncbi: 1639\n"
                                '    threat_level: "critical"\n'
                                "    bsl_level: 2\n"
                                "    alert_threshold: 5\n"
                                '  - name: "Salmonella enterica"\n'
                                "    taxid_ncbi: 28901\n"
                                '    threat_level: "high"\n'
                                "    alert_threshold: 10",
                                className="small bg-light p-2 rounded",
                                style={"fontSize": "0.75rem", "whiteSpace": "pre-wrap"},
                            ),
                            html.P([
                                "Optional fields per pathogen: ",
                                html.Code("names_alt"), ", ",
                                html.Code("common_name"), ", ",
                                html.Code("category"), ", ",
                                html.Code("action_required"), ", ",
                                html.Code("notes"), ".",
                            ], className="small text-muted mb-0"),
                        ], className="mt-1"),
                    ]),
                ], md=6),
            ]),
        ], title="Watchlist Files", item_id="watchlist-files"),
    ], id="watchlist-files-accordion", start_collapsed=False, className="mb-3")


def _create_collapsible_add_species() -> dbc.Accordion:
    """
    Create collapsible add custom species section.

    Provides API lookup and manual entry for adding species to watchlist.
    """
    return dbc.Accordion([
        dbc.AccordionItem([
            html.P([
                "Add individual species to the active watchlist. Use ",
                html.Strong("Lookup"),
                " to verify the name against NCBI/GTDB before adding. ",
                "To import many species at once, use ",
                html.Strong("Import YAML Watchlist"),
                " in the Watchlist Files section above.",
            ], className="small text-muted mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Species Name", className="small"),
                    dbc.Input(
                        id="watchlist-add-name",
                        type="text",
                        placeholder="e.g., Bacillus anthracis",
                        size="sm",
                    ),
                ], md=4),
                dbc.Col([
                    dbc.Label("Taxid (optional)", className="small"),
                    dbc.Input(
                        id="watchlist-add-taxid",
                        type="number",
                        placeholder="NCBI taxid",
                        size="sm",
                    ),
                ], md=2),
                dbc.Col([
                    dbc.Label("Threat Level", className="small"),
                    dbc.Select(
                        id="watchlist-add-threat",
                        options=[
                            {"label": "Critical", "value": "critical"},
                            {"label": "High", "value": "high"},
                            {"label": "Moderate", "value": "moderate"},
                            {"label": "Low", "value": "low"},
                        ],
                        value="moderate",
                        size="sm",
                    ),
                ], md=2),
                dbc.Col([
                    dbc.Label("Threshold", className="small"),
                    dbc.Input(
                        id="watchlist-add-threshold",
                        type="number",
                        value=10,
                        min=1,
                        size="sm",
                    ),
                ], md=2),
                dbc.Col([
                    dbc.Label(" ", className="small d-block"),
                    dbc.ButtonGroup([
                        dbc.Button(
                            [html.I(className="bi bi-search me-1"), "Lookup"],
                            id="watchlist-lookup-btn",
                            color="info",
                            outline=True,
                            size="sm",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-plus-lg me-1"), "Add"],
                            id="watchlist-add-btn",
                            color="success",
                            size="sm",
                        ),
                    ], size="sm"),
                ], md=2),
            ]),

            # API lookup results
            html.Div([
                html.Hr(className="my-2"),
                html.Div(id="watchlist-lookup-results"),
            ], id="watchlist-lookup-section", style={"display": "none"}),

            # Feedback
            html.Div(id="watchlist-add-feedback", className="mt-2 small"),
        ], title="Add Custom Species", item_id="add-species"),
    ], id="add-species-accordion", start_collapsed=True, className="mb-3")



# NOTE: Genome download section, genome/BLAST modals, and rescan progress modal
# have been moved to preparation_layout.py as part of the Setup tab reorganization.


def _create_taxid_mapping_modal_only() -> dbc.Modal:
    """
    Create only the taxid mapping modal (without the full section).

    The modal is opened when clicking Kraken2 Match badges in the Pathogens table.
    Uses the same component from taxid_mapping_ui but standalone.
    """
    from nanometa_live.app.components.taxid_mapping_ui import create_manual_mapping_modal
    return create_manual_mapping_modal("taxmap")


# =============================================================================
# MODALS AND HELPER FUNCTIONS
# =============================================================================

def _create_entry_edit_modal() -> dbc.Modal:
    """Create the entry edit modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle("Edit Pathogen Entry", id="watchlist-edit-modal-title"),
        ]),
        dbc.ModalBody([
            dcc.Store(id="watchlist-edit-taxid", data=None),

            # Taxonomy IDs section (read-only info)
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Small("NCBI Taxid", className="text-muted d-block"),
                            html.Code(id="watchlist-edit-ncbi-taxid", children="-"),
                        ], width=4),
                        dbc.Col([
                            html.Small("Kraken2 Taxid", className="text-muted d-block"),
                            html.Code(id="watchlist-edit-kraken-taxid", children="-"),
                        ], width=4),
                        dbc.Col([
                            html.Small("Kraken2 Name", className="text-muted d-block"),
                            html.Span(
                                id="watchlist-edit-kraken-name",
                                children="-",
                                className="small fst-italic",
                            ),
                        ], width=4),
                    ]),
                ], className="py-2"),
            ], className="mb-3 bg-light"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Scientific Name"),
                    dbc.Input(
                        id="watchlist-edit-name",
                        type="text",
                        disabled=True,
                    ),
                ], width=6),
                dbc.Col([
                    dbc.Label("Common Name"),
                    dbc.Input(
                        id="watchlist-edit-common",
                        type="text",
                    ),
                ], width=6),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Threat Level"),
                    dbc.Select(
                        id="watchlist-edit-threat",
                        options=[
                            {"label": "Critical", "value": "critical"},
                            {"label": "High", "value": "high"},
                            {"label": "Moderate", "value": "moderate"},
                            {"label": "Low", "value": "low"},
                        ],
                    ),
                ], width=3),
                dbc.Col([
                    dbc.Label("BSL Level"),
                    dbc.Select(
                        id="watchlist-edit-bsl",
                        options=[
                            {"label": "N/A", "value": ""},
                            {"label": "BSL-1", "value": "1"},
                            {"label": "BSL-2", "value": "2"},
                            {"label": "BSL-3", "value": "3"},
                            {"label": "BSL-4", "value": "4"},
                        ],
                    ),
                ], width=3),
                dbc.Col([
                    dbc.Label("Alert Threshold"),
                    dbc.Input(
                        id="watchlist-edit-threshold",
                        type="number",
                        min=1,
                    ),
                ], width=3),
                dbc.Col([
                    dbc.Label("Enabled"),
                    dbc.Switch(
                        id="watchlist-edit-enabled",
                        value=True,
                        className="mt-2",
                    ),
                ], width=3),
            ], className="mb-3"),

            dbc.Row([
                dbc.Col([
                    dbc.Label("Notes"),
                    dbc.Textarea(
                        id="watchlist-edit-notes",
                        rows=2,
                    ),
                ]),
            ]),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Save",
                id="watchlist-edit-save-btn",
                color="primary",
                n_clicks=0,
            ),
            dbc.Button(
                "Cancel",
                id="watchlist-edit-cancel-btn",
                color="secondary",
                n_clicks=0,
            ),
        ]),
    ], id="watchlist-edit-modal", size="lg")


def _create_api_details_modal() -> dbc.Modal:
    """Create the API details modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle("Validation Details", id="watchlist-api-modal-title"),
        ]),
        dbc.ModalBody([
            html.Div(id="watchlist-api-modal-content"),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Close",
                id="watchlist-api-modal-close-btn",
                color="secondary",
            ),
        ]),
    ], id="watchlist-api-modal", size="lg")


def _create_validation_progress_modal() -> dbc.Modal:
    """Create the validation progress modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle("Validating Entries"),
        ]),
        dbc.ModalBody([
            html.Div([
                html.P(id="watchlist-progress-text", children="Validating..."),
                dbc.Progress(
                    id="watchlist-progress-bar",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-3",
                ),
                html.Small(
                    id="watchlist-progress-detail",
                    className="text-muted",
                ),
            ]),
        ]),
    ], id="watchlist-progress-modal", centered=True, backdrop="static")




# Helper functions for creating table rows (used by callbacks)

def create_pathogen_row(
    entry: Dict[str, Any],
    index: int,
    mapping_info: Optional[Dict[str, Any]] = None,
    genome_info: Optional[Dict[str, Any]] = None
) -> html.Div:
    """
    Create a single pathogen row for the table.

    Args:
        entry: Entry dict from WatchlistManager.get_entries_with_toggle_state()
        index: Row index for styling
        mapping_info: Optional dict with Kraken2 mapping status
            - confidence: "exact", "fuzzy", "manual", "unmapped", or "unknown"
            - db_taxid: Mapped database taxid (if available)
            - match_score: Similarity score 0.0-1.0
        genome_info: Optional dict with genome status
            - has_genome: True if genome is downloaded
            - has_blast_db: True if BLAST database exists

    Returns:
        html.Div containing the row
    """
    taxid = entry.get("taxid", 0) or 0
    name = entry.get("name") or "Unknown"
    common_name = entry.get("common_name") or ""
    threat_level = entry.get("threat_level") or "moderate"
    bsl = entry.get("bsl_level")
    enabled = entry.get("enabled", True)
    validated = entry.get("validated", False)

    # Threat level colors
    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary",
    }

    # Kraken2 mapping status badge
    mapping_config = {
        "exact": {"color": "success", "icon": "bi-check-circle-fill", "label": "Exact"},
        "fuzzy": {"color": "info", "icon": "bi-dash-circle-fill", "label": "Fuzzy"},
        "manual": {"color": "warning", "icon": "bi-pencil-fill", "label": "Manual"},
        "partial": {"color": "warning", "icon": "bi-question-circle-fill", "label": "Partial"},
        "unmapped": {"color": "danger", "icon": "bi-x-circle-fill", "label": "Not Found"},
        "unknown": {"color": "light", "icon": "bi-dash-lg", "label": "Not Scanned"},
    }

    # Get mapping status and Kraken taxid
    confidence = "unknown"
    db_taxid = None
    db_name = ""
    if mapping_info:
        confidence = mapping_info.get("confidence", "unknown")
        db_taxid = mapping_info.get("db_taxid")
        db_name = mapping_info.get("db_name", "")
    config = mapping_config.get(confidence, mapping_config["unknown"])

    # Row styling
    row_class = "py-2 border-bottom"
    if not enabled:
        row_class += " text-muted"

    # Genome status
    has_genome = False
    has_blast_db = False
    if genome_info:
        has_genome = genome_info.get("has_genome", False)
        has_blast_db = genome_info.get("has_blast_db", False)

    return html.Div([
        dbc.Row([
            # Name
            dbc.Col([
                html.Div([
                    html.Span(
                        name,
                        className="fw-bold" + (" text-decoration-line-through" if not enabled else ""),
                    ),
                    html.Small(
                        f" ({common_name})" if common_name else "",
                        className="text-muted",
                    ),
                ]),
                html.Small(f"Taxid: {taxid}", className="text-muted"),
            ], width=3),

            # Threat level
            dbc.Col([
                dbc.Badge(
                    threat_level.title(),
                    color=threat_colors.get(threat_level, "secondary"),
                ),
            ], width=1),

            # BSL
            dbc.Col([
                dbc.Badge(
                    f"BSL-{bsl}" if bsl else "N/A",
                    color="dark",
                    className="border",
                ),
            ], width=1),

            # Validated
            dbc.Col([
                html.I(
                    className="bi bi-check-circle-fill text-success" if validated else "bi bi-x-circle text-muted",
                    id={"type": "watchlist-row-validated", "index": taxid},
                    style={"cursor": "pointer"} if validated else {},
                ),
            ], width=1),

            # Kraken2 Match status with DB info
            dbc.Col([
                html.Div([
                    dbc.Button(
                        [
                            html.I(className=f"bi {config['icon']} me-1"),
                            config["label"],
                        ],
                        id={"type": "watchlist-row-mapping", "index": taxid},
                        color=config["color"],
                        size="sm",
                        className="kraken2-match-badge",
                        title="Click to edit mapping",
                        n_clicks=0,
                    ),
                    # Show Kraken2 DB name and taxid below the badge
                    html.Div([
                        html.Small(
                            db_name[:30] + "..." if db_name and len(db_name) > 30 else db_name or "",
                            className="text-muted d-block",
                            style={"fontSize": "0.7rem", "lineHeight": "1.1"},
                            title=db_name if db_name else "",
                        ),
                        html.Small(
                            f"(taxid: {db_taxid})" if db_taxid else "",
                            className="text-muted d-block",
                            style={"fontSize": "0.65rem", "opacity": "0.8"},
                        ),
                    ]) if db_taxid or db_name else None,
                ]),
            ], width=2),

            # Genome status
            dbc.Col([
                html.Div([
                    # Genome download indicator
                    html.I(
                        className="bi bi-file-earmark-text-fill text-success" if has_genome else "bi bi-file-earmark text-muted",
                        title="Genome: Downloaded" if has_genome else "Genome: Not downloaded",
                        style={"fontSize": "1rem"},
                    ),
                    # BLAST DB indicator
                    html.I(
                        className="bi bi-database-fill text-info ms-1" if has_blast_db else "bi bi-database text-muted ms-1",
                        title="BLAST DB: Ready" if has_blast_db else "BLAST DB: Not built",
                        style={"fontSize": "0.9rem"},
                    ) if has_genome else None,
                ]),
            ], width=1),

            # Actions
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button(
                        [html.I(className="bi bi-pencil me-1"), "Edit"],
                        id={"type": "watchlist-row-edit", "index": taxid},
                        size="sm",
                        color="secondary",
                        outline=True,
                        title=f"Edit {name}",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-check2-circle me-1"), "Verify"],
                        id={"type": "watchlist-row-validate", "index": taxid},
                        size="sm",
                        color="info",
                        outline=True,
                        title=f"Validate {name} against NCBI/GTDB taxonomy",
                    ),
                    dbc.Button(
                        [
                            html.I(className="bi bi-toggle-on" if enabled else "bi bi-toggle-off"),
                        ],
                        id={"type": "watchlist-row-toggle", "index": taxid},
                        size="sm",
                        color="success" if enabled else "secondary",
                        outline=not enabled,
                        title=f"{'Disable' if enabled else 'Enable'} {name}",
                    ),
                ], size="sm"),
            ], width=3),
        ], align="center", className=row_class),
    ], className="pathogen-row")


def _create_nested_pathogen_row(entry: Dict[str, Any], watchlist_id: str) -> html.Div:
    """
    Create a single pathogen row for the nested watchlist view.

    Args:
        entry: Entry dict from WatchlistManager
        watchlist_id: ID of the parent watchlist

    Returns:
        html.Div containing the pathogen row
    """
    taxid = entry.get("taxid", 0)
    name = entry.get("name", "Unknown")
    threat_level = entry.get("threat_level", "moderate")
    threshold = entry.get("alert_threshold", 10)
    enabled = entry.get("enabled", True)

    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary",
    }

    row_class = "py-1 border-bottom"
    if not enabled:
        row_class += " opacity-50"

    return html.Div([
        dbc.Row([
            # Checkbox for individual selection
            dbc.Col([
                dbc.Checkbox(
                    id={"type": "watchlist-nested-pathogen-toggle", "index": taxid, "watchlist": watchlist_id},
                    value=enabled,
                ),
            ], width=1),

            # Name
            dbc.Col([
                html.Span(
                    name,
                    className="small" + (" text-decoration-line-through" if not enabled else ""),
                    title=f"TaxID: {taxid}"
                ),
            ], width=5),

            # Threat level badge
            dbc.Col([
                dbc.Badge(
                    threat_level.title() if threat_level else "N/A",
                    color=threat_colors.get(threat_level, "secondary"),
                    className="small",
                ),
            ], width=2),

            # Threshold
            dbc.Col([
                html.Small(str(threshold)),
            ], width=2),

            # Actions
            dbc.Col([
                dbc.Button(
                    html.I(className="bi bi-pencil"),
                    id={"type": "watchlist-nested-edit", "index": taxid, "watchlist": watchlist_id},
                    size="sm",
                    color="link",
                    className="p-0",
                    title="Edit",
                ),
            ], width=2, className="text-end"),
        ], align="center", className=row_class),
    ], className="nested-pathogen-row")


def _create_watchlist_pathogen_list(pathogens: List[Dict[str, Any]], watchlist_id: str) -> html.Div:
    """
    Create the nested pathogen list for an expandable watchlist.

    Args:
        pathogens: List of pathogen entry dicts
        watchlist_id: ID of the parent watchlist

    Returns:
        html.Div containing the pathogen list with individual toggles
    """
    if not pathogens:
        return html.Div(
            "No pathogens in this watchlist.",
            className="text-muted fst-italic py-2"
        )

    # Header row
    header = dbc.Row([
        dbc.Col(html.Small("", className="fw-bold"), width=1),
        dbc.Col(html.Small("Name", className="fw-bold"), width=5),
        dbc.Col(html.Small("Threat", className="fw-bold"), width=2),
        dbc.Col(html.Small("Threshold", className="fw-bold"), width=2),
        dbc.Col(html.Small("Actions", className="fw-bold text-end"), width=2),
    ], className="py-1 border-bottom bg-white sticky-top")

    # Pathogen rows
    rows = [header]
    for entry in pathogens:
        rows.append(_create_nested_pathogen_row(entry, watchlist_id))

    return html.Div(rows, style={"maxHeight": "250px", "overflowY": "auto"})


def create_watchlist_file_item(wl: Dict[str, Any], pathogens: List[Dict[str, Any]] = None) -> html.Div:
    """
    Create an expandable watchlist file item for the files section.

    Args:
        wl: Watchlist metadata dict
        pathogens: Optional list of pathogen entries for this watchlist

    Returns:
        html.Div containing the expandable watchlist item
    """
    wl_id = wl.get("id", "")
    name = wl.get("name", "Unknown")
    description = wl.get("description", "")
    pathogen_count = wl.get("pathogen_count", 0)
    enabled = wl.get("enabled", False)
    source = wl.get("source", "builtin")

    source_colors = {
        "builtin": "primary",
        "user": "success",
        "project": "warning",
    }

    # Create collapsed pathogen list content
    if pathogens:
        pathogen_list_content = _create_watchlist_pathogen_list(pathogens, wl_id)
    else:
        pathogen_list_content = html.Div(
            "No pathogens loaded.",
            className="text-muted py-2"
        )

    return html.Div([
        # Main row with expand trigger
        dbc.Row([
            # Checkbox (separate from expand trigger)
            dbc.Col([
                dbc.Checkbox(
                    id={"type": "watchlist-file-toggle", "index": wl_id},
                    value=enabled,
                    className="d-inline-block",
                ),
            ], width=1, className="pe-0"),

            # Clickable expand area
            dbc.Col([
                html.Div([
                    html.I(
                        className="bi bi-chevron-right me-2",
                        id={"type": "watchlist-expand-icon", "index": wl_id},
                        style={"transition": "transform 0.2s", "fontSize": "16px"}
                    ),
                    html.Span(name, className="fw-bold"),
                    dbc.Badge(
                        source.title(),
                        color=source_colors.get(source, "secondary"),
                        pill=True,
                        className="ms-2 small",
                    ),
                    # Enabled/disabled status badge
                    dbc.Badge(
                        "Active" if enabled else "Off",
                        color="success" if enabled else "secondary",
                        pill=True,
                        className="ms-2 small",
                    ),
                ], style={"cursor": "pointer"},
                   className="watchlist-expand-trigger",
                   id={"type": "watchlist-expand-trigger", "index": wl_id},
                   n_clicks=0),
            ], width=5),

            # Pathogen count
            dbc.Col([
                html.Small(
                    f"{pathogen_count} pathogens",
                    className="text-muted",
                ),
            ], width=3),

            # Actions
            dbc.Col([
                dbc.Button(
                    html.I(className="bi bi-eye"),
                    id={"type": "watchlist-file-view", "index": wl_id},
                    size="sm",
                    color="secondary",
                    outline=True,
                    title="View in main table",
                    className="me-1",
                ),
                dbc.Button(
                    html.I(className="bi bi-trash"),
                    id={"type": "watchlist-file-delete", "index": wl_id},
                    size="sm",
                    color="danger",
                    outline=True,
                    title="Remove custom watchlist",
                    style={"display": "inline-block" if source == "user" else "none"},
                ),
            ], width=3, className="text-end"),
        ], align="center", className="py-2 border-bottom"),

        # Description (if any)
        html.Small(description, className="text-muted d-block ms-4 mb-1") if description else None,

        # Collapsible pathogen list
        dbc.Collapse(
            html.Div([
                pathogen_list_content
            ], className="ps-4 py-2 bg-light border-start border-3 border-primary ms-3 rounded-bottom"),
            id={"type": "watchlist-pathogen-collapse", "index": wl_id},
            is_open=False,
        ),

    ], className=f"watchlist-file-item {'watchlist-enabled' if enabled else 'watchlist-disabled'}")


def create_api_lookup_result(
    ncbi_result: Optional[Dict[str, Any]] = None,
    gtdb_result: Optional[Dict[str, Any]] = None,
) -> html.Div:
    """
    Create the API lookup results display.

    Args:
        ncbi_result: NCBI lookup result dict
        gtdb_result: GTDB lookup result dict

    Returns:
        html.Div containing the results
    """
    items = []

    if ncbi_result:
        items.append(
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Badge("NCBI", color="primary", className="me-2"),
                            html.Strong(ncbi_result.get("sciname", "")),
                            html.Small(f" (taxid: {ncbi_result.get('taxid', '')})", className="text-muted"),
                        ], width=8),
                        dbc.Col([
                            dbc.Button(
                                "Use This",
                                id="watchlist-use-ncbi-btn",
                                size="sm",
                                color="primary",
                                outline=True,
                            ),
                        ], width=4, className="text-end"),
                    ]),
                    html.Small([
                        html.Strong("Common name: "),
                        ncbi_result.get("commonname", "N/A"),
                    ], className="text-muted d-block"),
                    html.Small([
                        html.Strong("Rank: "),
                        ncbi_result.get("rank", "N/A"),
                    ], className="text-muted d-block"),
                ]),
            ], className="mb-2"),
        )

    if gtdb_result:
        items.append(
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Badge("GTDB", color="success", className="me-2"),
                            html.Strong(gtdb_result.get("species", "")),
                        ], width=8),
                        dbc.Col([
                            dbc.Button(
                                "Use This",
                                id="watchlist-use-gtdb-btn",
                                size="sm",
                                color="success",
                                outline=True,
                            ),
                        ], width=4, className="text-end"),
                    ]),
                    html.Small([
                        html.Strong("Taxonomy: "),
                        gtdb_result.get("gtdb_taxonomy", "N/A"),
                    ], className="text-muted d-block"),
                ]),
            ], className="mb-2"),
        )

    if not items:
        return html.Div(
            "No results found in NCBI or GTDB.",
            className="text-muted text-center py-3",
        )

    return html.Div(items)


def create_missing_genome_item(entry: Dict[str, Any]) -> html.Div:
    """
    Create a single item for the missing genomes list.

    Args:
        entry: Watchlist entry dict with taxid, name, threat_level, etc.

    Returns:
        html.Div containing the missing genome item
    """
    taxid = entry.get("taxid", 0)
    name = entry.get("name", "Unknown")
    threat_level = entry.get("threat_level", "moderate")

    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary",
    }

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Span(name, className="fw-bold"),
                html.Small(f" (taxid: {taxid})", className="text-muted"),
            ], width=6),
            dbc.Col([
                dbc.Badge(
                    threat_level.title() if threat_level else "Unknown",
                    color=threat_colors.get(threat_level, "secondary"),
                    className="me-1",
                ),
            ], width=2),
            dbc.Col([
                html.I(
                    className="bi bi-exclamation-triangle text-warning me-1",
                    title="Genome not downloaded",
                ),
                html.Small("Not downloaded", className="text-muted"),
            ], width=3),
            dbc.Col([
                dbc.Button(
                    html.I(className="bi bi-download"),
                    id={"type": "genome-download-single-btn", "index": taxid},
                    color="primary",
                    size="sm",
                    outline=True,
                    className="p-1",
                    title="Download genome",
                    n_clicks=0,
                ),
            ], width=1, className="text-end"),
        ], align="center", className="py-1 border-bottom"),
    ], className="missing-genome-item")


def create_genome_item(genome_meta: Dict[str, Any]) -> html.Div:
    """
    Create a single genome item for the downloaded genomes list.

    Args:
        genome_meta: GenomeMetadata dict with taxid, species_name, accession, etc.

    Returns:
        html.Div containing the genome item
    """
    taxid = genome_meta.get("taxid", 0)
    species = genome_meta.get("species_name", "Unknown")

    # Fall back to watchlist name if stored name is unresolved
    if species.startswith("Unknown") and taxid:
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
        try:
            wm = get_watchlist_manager()
            entry = wm.get_entry_by_taxid(taxid)
            if entry and entry.name:
                species = entry.name
        except Exception:
            pass
    accession = genome_meta.get("accession", "")
    source = genome_meta.get("source", "ncbi")
    kingdom = genome_meta.get("kingdom", "Unknown")
    has_blast = genome_meta.get("blast_db_path") is not None
    # Also check filesystem if metadata lacks blast_db_path
    if not has_blast and taxid:
        try:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            has_blast = get_genome_manager().has_blast_db(taxid)
        except Exception:
            pass
    file_size = genome_meta.get("file_size", 0)
    size_mb = round(file_size / (1024 * 1024), 2) if file_size else 0

    source_labels = {
        "gtdb": "GTDB", "ncbi": "NCBI", "ncbi_virus": "NCBI Virus",
        "ncbi_cli": "NCBI", "discovered": "Local",
    }
    source_label = source_labels.get(source, source.upper())
    source_color = "success" if source == "gtdb" else "primary"

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Span(species, className="fw-bold"),
                html.Small(f" (taxid: {taxid})", className="text-muted"),
            ], width=5),
            dbc.Col([
                dbc.Badge(source_label, color=source_color, className="me-1"),
                dbc.Badge(kingdom, color="secondary", className="me-1"),
                dbc.Badge(
                    "BLAST DB",
                    color="info" if has_blast else "light",
                    className="me-1",
                    style={"opacity": "1" if has_blast else "0.5"},
                ),
            ], width=3),
            dbc.Col([
                html.Small(accession, className="text-muted font-monospace"),
            ], width=2),
            dbc.Col([
                html.Small(f"{size_mb} MB", className="text-muted"),
                dbc.Button(
                    html.I(className="bi bi-trash"),
                    id={"type": "genome-delete-btn", "index": taxid},
                    color="danger",
                    size="sm",
                    outline=True,
                    className="ms-2 p-1",
                    title="Delete genome",
                    n_clicks=0,
                ),
            ], width=2, className="text-end"),
        ], align="center", className="py-1 border-bottom"),
    ], className="genome-item")


def create_api_details_content(entry: Dict[str, Any]) -> html.Div:
    """
    Create the API validation details content for the modal.

    Args:
        entry: Entry dict with validation data

    Returns:
        html.Div containing the details
    """
    name = entry.get("name", "Unknown")
    api_sciname = entry.get("api_sciname")
    api_commonname = entry.get("api_commonname")
    api_rank = entry.get("api_rank")
    lineage = entry.get("lineage", [])
    validation_date = entry.get("validation_date")
    ncbi_link = entry.get("ncbi_link")
    gtdb_link = entry.get("gtdb_link")
    gtdb_taxonomy = entry.get("gtdb_taxonomy")

    return html.Div([
        # Header
        html.H5(name, className="mb-3"),

        # API-verified name
        html.Div([
            html.Strong("API Verified Name: "),
            html.Span(api_sciname or "N/A"),
        ], className="mb-2") if api_sciname else None,

        # Common name
        html.Div([
            html.Strong("Common Name: "),
            html.Span(api_commonname or "N/A"),
        ], className="mb-2") if api_commonname else None,

        # Rank
        html.Div([
            html.Strong("Taxonomic Rank: "),
            html.Span(api_rank or "N/A"),
        ], className="mb-2") if api_rank else None,

        # Lineage
        html.Div([
            html.Strong("Lineage: "),
            html.Div([
                dbc.Badge(taxon, color="secondary", className="me-1 mb-1")
                for taxon in lineage
            ] if lineage else [html.Span("N/A", className="text-muted")]),
        ], className="mb-3"),

        # GTDB taxonomy
        html.Div([
            html.Strong("GTDB Taxonomy: "),
            html.Code(gtdb_taxonomy, className="small"),
        ], className="mb-3") if gtdb_taxonomy else None,

        # Links
        html.Div([
            html.Strong("External Links: "),
            html.Div([
                html.A(
                    [html.I(className="bi bi-box-arrow-up-right me-1"), "NCBI Taxonomy"],
                    href=ncbi_link,
                    target="_blank",
                    className="btn btn-outline-primary btn-sm me-2",
                ) if ncbi_link else None,
                html.A(
                    [html.I(className="bi bi-box-arrow-up-right me-1"), "GTDB"],
                    href=gtdb_link,
                    target="_blank",
                    className="btn btn-outline-success btn-sm",
                ) if gtdb_link else None,
            ]),
        ], className="mb-3"),

        # Validation date
        html.Div([
            html.Small([
                html.Strong("Validated: "),
                html.Span(validation_date or "Unknown"),
            ], className="text-muted"),
        ]),
    ])
