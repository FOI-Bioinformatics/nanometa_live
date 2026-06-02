"""
Main results tab layout for Nanometa Live v2.0.

This module defines the layout for the main results tab, which displays the
species of interest and top matches from the analysis with multi-sample support.

MODERNIZED: Uses visual organism cards, watched species section, alert banners,
and operator-friendly design with progressive disclosure.

The layout is assembled from per-section builder functions (``_main_*``) so each
zone can be read and edited in isolation; ``create_main_layout`` composes them in
visual order. The builders return components only -- no callbacks or data access
-- and every component id is preserved exactly as the callbacks expect.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from nanometa_live.app.components.organism_components import (
    OrganismCard,
    OrganismSummaryCard,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage


def _main_export_actions():
    """Organism-results header with the compact export dropdown."""
    return dbc.Row([
        dbc.Col([
            html.Div([
                html.H4("Organism Results", className="mb-0 d-inline"),
                dbc.Badge(id="organism-results-count", children="0", color="primary", className="ms-2")
            ], className="d-flex align-items-center")
        ], md=8),
        dbc.Col([
            dbc.DropdownMenu(
                [
                    dbc.DropdownMenuItem([
                        html.I(className="bi bi-file-earmark-text me-2"),
                        "Export Report (TXT)"
                    ], id="export-all-txt"),
                    dbc.DropdownMenuItem([
                        html.I(className="bi bi-file-earmark-spreadsheet me-2"),
                        "Export Data (CSV)"
                    ], id="export-all-csv"),
                    dbc.DropdownMenuItem(divider=True),
                    dbc.DropdownMenuItem([
                        html.I(className="bi bi-file-earmark-excel me-2"),
                        "Export Excel (XLSX)"
                    ], id="export-all-xlsx"),
                ],
                label="Export",
                color="secondary",
                size="sm",
                className="float-end"
            )
        ], md=4, className="text-end")
    ], className="mb-3 align-items-center")


def _main_watched_species_section():
    """Watched-organisms card with BLAST tooltip and empty state."""
    return html.Div(id="watched-organisms-section", children=[
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.I(className="bi bi-star-fill text-warning me-2"),
                    html.H5("Watched Organisms", className="mb-0 d-inline"),
                    dbc.Badge(
                        "0",
                        id="watched-organisms-count",
                        color="secondary",
                        className="ms-2"
                    ),
                    # BLAST info tooltip (condensed)
                    html.Span([
                        html.I(
                            className="bi bi-info-circle text-muted ms-3",
                            id="blast-info-icon",
                            style={"cursor": "pointer"},
                            **{"aria-label": "BLAST validation information", "role": "img"}
                        ),
                        dbc.Tooltip(
                            "When BLAST validation is enabled, watched species are verified "
                            "against reference genomes. Green = 80%+ verified, Amber = 50-80%, Red = <50%",
                            target="blast-info-icon",
                            placement="right"
                        )
                    ])
                ], className="d-flex align-items-center")
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(
                    id="loading-watched-organisms",
                    type="circle",
                    color="#ffc107",
                    children=[
                        html.Div(
                            id="watched-organisms-cards",
                            children=[
                                EmptyStateMessage(
                                    title="No Watched Organisms",
                                    message="Add species to your watchlist in the Watchlist tab to monitor specific organisms.",
                                    icon="bi-star"
                                )
                            ]
                        )
                    ]
                )
            ])
        ], className="mb-4")
    ])


def _main_all_organisms_section():
    """All-organisms cards view (charts live in the Taxonomy tab)."""
    return html.Div([
        html.Div([
            html.H4("Top Organisms Found", className="mb-0 d-inline"),
            dbc.Badge(
                id="total-organisms-count",
                children="0",
                color="primary",
                className="ms-2"
            ),
            html.Small(
                "See Taxonomy tab for charts",
                className="ms-3 text-muted"
            ),
        ], className="d-flex align-items-center mb-3"),

        # Organism Cards
        dcc.Loading(
            id="loading-organism-cards",
            type="circle",
            color="#6f42c1",
            children=[
                html.Div(
                    id="organism-cards-container",
                    children=[
                        EmptyStateMessage(
                            title="Awaiting Results",
                            message="Organism cards will appear here once analysis is complete",
                            icon="bi-hourglass"
                        )
                    ],
                )
            ]
        )
    ], className="mb-4")


def _main_advanced_filters():
    """Collapsible advanced-filter controls accordion."""
    return dbc.Accordion([
        dbc.AccordionItem([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Show Top:", html_for="top-organisms-count"),
                    dbc.Input(
                        id="top-organisms-count",
                        type="number",
                        min=5,
                        max=100,
                        value=10,
                        placeholder="Number of organisms"
                    ),
                    dbc.FormText("Display top N organisms by abundance")
                ], md=3),
                dbc.Col([
                    dbc.Label("Minimum Abundance (%):", html_for="min-abundance"),
                    dbc.Input(
                        id="min-abundance",
                        type="number",
                        min=0,
                        max=100,
                        step=0.1,
                        value=0.1,
                        placeholder="Minimum %"
                    ),
                    dbc.FormText("Hide organisms below this abundance")
                ], md=3),
                dbc.Col([
                    dbc.Label("Taxonomic Rank:", html_for="tax-rank-filter"),
                    dbc.Checklist(
                        id="tax-rank-filter",
                        options=[
                            {"label": "Species", "value": "S"},
                            {"label": "Genus", "value": "G"},
                            {"label": "Family", "value": "F"}
                        ],
                        value=["S", "G"],
                        inline=True
                    )
                ], md=4),
                dbc.Col([
                    dbc.Button(
                        "Apply Filters",
                        id="apply-organism-filters",
                        color="primary",
                        className="mt-4"
                    )
                ], md=2, className="d-flex align-items-end")
            ])
        ], title="Advanced Filters (Optional)")
    ], start_collapsed=True, className="mb-4")


def _main_detailed_table():
    """Collapsible detailed organism data table for power users."""
    return dbc.Accordion([
        dbc.AccordionItem([
            html.Div([
                html.P(
                    "This table shows all technical details from the analysis. "
                    "Most operators can use the visual cards above for easier interpretation.",
                    className="text-muted mb-3"
                ),
                dag.AgGrid(
                    id="detailed-organism-table",
                    columnDefs=[
                        {"headerName": "Organism Name", "field": "name"},
                        {
                            "headerName": "Classification Level",
                            "field": "rank",
                            "valueFormatter": {
                                "function": (
                                    "function(params) {"
                                    "  var m = {D:'Domain',K:'Kingdom',P:'Phylum',C:'Class',"
                                    "           O:'Order',F:'Family',G:'Genus',S:'Species',U:'Unclassified'};"
                                    "  return m[params.value] || params.value;"
                                    "}"
                                )
                            },
                        },
                        {
                            "headerName": "DNA Sequences",
                            "field": "reads",
                            "type": "numericColumn",
                            "valueFormatter": {"function": "d3.format(',')(params.value)"},
                        },
                        {
                            "headerName": "Abundance (%)",
                            "field": "abundance",
                            "cellStyle": {"fontWeight": "bold"},
                        },
                        {
                            "headerName": "Database ID",
                            "field": "taxid",
                            "hide": True,
                        },
                    ],
                    rowData=[],
                    defaultColDef={"sortable": True, "filter": True, "resizable": True},
                    # ``getRowId`` keys each row by its taxid so AgGrid
                    # can match rows across rowData updates on the 30s
                    # interval tick. Without it, every tick rebuilds
                    # all DOM rows from scratch and clobbers the
                    # operator's sort, filter, and row selection. With
                    # it, AgGrid updates only the cells whose values
                    # changed and preserves interaction state.
                    dashGridOptions={
                        "pagination": True,
                        "paginationPageSize": 25,
                        "getRowId": {"function": "params.data.taxid"},
                    },
                )
            ])
        ], title="Detailed Data Table (Advanced)")
    ], start_collapsed=True, className="mb-4")


def _main_help_card():
    """Static 'Need Help?' results-interpretation card."""
    return dbc.Card([
        dbc.CardHeader(html.H5("Need Help?", className="mb-0")),
        dbc.CardBody([
            html.P("Understanding Your Results:", className="fw-bold mb-2"),
            html.Ul([
                html.Li([
                    html.Strong("Watched Organisms: "),
                    "Species you've added to your watchlist appear in the highlighted section"
                ]),
                html.Li([
                    html.Strong("Abundance bar: "),
                    "Shows what % of total DNA sequences belong to this organism"
                ]),
                html.Li([
                    html.Strong("DNA Sequences: "),
                    "Higher numbers indicate more confident identification"
                ]),
                html.Li([
                    html.Strong("Confidence: "),
                    "HIGH, MEDIUM, or LOW based on read count thresholds (configurable in settings)"
                ]),
                html.Li([
                    html.Strong("BLAST Validation: "),
                    "When enabled, verifies watched species against reference genomes. ",
                    "Green = 80%+ verified, amber = 50-80%, red = <50%"
                ])
            ], className="mb-3"),
            dbc.Button(
                "View Full Operator Guide",
                id="view-operator-guide",
                color="info",
                outline=True
            )
        ])
    ], className="mb-4", style={"backgroundColor": "#f8f9fa"})


def _main_export_modal():
    """Organism-data export format/filename modal."""
    return dbc.Modal([
        dbc.ModalHeader("Export Organism Data"),
        dbc.ModalBody([
            dbc.Label("Select Format:"),
            dbc.RadioItems(
                id="export-format-select",
                options=[
                    {"label": "Text Report (.txt) - Human-readable summary", "value": "txt"},
                    {"label": "CSV Spreadsheet - For data analysis", "value": "csv"},
                    {"label": "Excel Workbook - Complete data", "value": "xlsx"}
                ],
                value="txt"
            ),
            html.Hr(),
            dbc.Label("Filename:", html_for="export-filename"),
            dbc.Input(
                id="export-filename",
                placeholder="organism_results",
                type="text"
            )
        ]),
        dbc.ModalFooter([
            dbc.Button("Export", id="confirm-export", color="primary"),
            dbc.Button("Cancel", id="cancel-export", color="secondary")
        ])
    ], id="export-modal", is_open=False)


def _main_operator_guide_modal():
    """Operator quick-reference guide modal."""
    return dbc.Modal([
        dbc.ModalHeader(
            dbc.ModalTitle([
                html.I(className="bi bi-book me-2"),
                "Operator Quick Reference Guide"
            ]),
            close_button=True
        ),
        dbc.ModalBody([
            # Status Indicators Section
            html.H5("Status Indicators", className="text-primary mb-3"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-circle-fill text-success me-2"),
                        html.Strong("Green: "),
                        "System running normally, data current"
                    ], className="mb-2"),
                    html.Div([
                        html.I(className="bi bi-circle-fill text-warning me-2"),
                        html.Strong("Yellow: "),
                        "Attention needed, check alerts"
                    ], className="mb-2"),
                    html.Div([
                        html.I(className="bi bi-circle-fill text-danger me-2"),
                        html.Strong("Red: "),
                        "Critical - immediate action required"
                    ], className="mb-2"),
                ], md=6),
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-circle-fill text-secondary me-2"),
                        html.Strong("Gray: "),
                        "Pipeline paused or no data"
                    ], className="mb-2"),
                    html.Div([
                        html.I(className="bi bi-circle-fill text-info me-2"),
                        html.Strong("Blue: "),
                        "Information or processing"
                    ], className="mb-2"),
                ], md=6),
            ], className="mb-4"),

            html.Hr(),

            # Workflow Section
            html.H5("Basic Workflow", className="text-primary mb-3"),
            dbc.ListGroup([
                dbc.ListGroupItem([
                    html.Strong("1. Configure: "),
                    "Set input directory and Kraken2 database in Configuration tab"
                ]),
                dbc.ListGroupItem([
                    html.Strong("2. Start: "),
                    "Click 'Start Analysis' to begin processing"
                ]),
                dbc.ListGroupItem([
                    html.Strong("3. Monitor: "),
                    "Watch Dashboard for pathogen alerts and status"
                ]),
                dbc.ListGroupItem([
                    html.Strong("4. Review: "),
                    "Check Organisms tab for detailed results"
                ]),
                dbc.ListGroupItem([
                    html.Strong("5. Export: "),
                    "Download reports using Export menu"
                ]),
            ], flush=True, className="mb-4"),

            html.Hr(),

            # Keyboard Shortcuts
            html.H5("Keyboard Shortcuts", className="text-primary mb-3"),
            dbc.Row([
                dbc.Col([
                    html.Kbd("Esc", className="me-2"),
                    "Dismiss notifications"
                ], className="mb-2"),
            ]),

            html.Hr(),

            # Tips
            html.H5("Tips", className="text-primary mb-3"),
            html.Ul([
                html.Li("Use the sample selector dropdown to filter by barcode"),
                html.Li("Click column headers in tables to sort data"),
                html.Li("Hover over elements for additional information"),
                html.Li("Enable BLAST validation for high-confidence pathogen detection"),
            ], className="mb-0"),
        ], className="p-3"),
        dbc.ModalFooter([
            dbc.Button(
                "Close",
                id="close-operator-guide",
                color="secondary",
                outline=True
            )
        ])
    ], id="operator-guide-modal", is_open=False, size="lg", scrollable=True)


def _main_on_demand_validation_modal():
    """On-demand BLAST/minimap2 validation modal."""
    return dbc.Modal([
        dbc.ModalHeader([
            html.I(className="bi bi-check2-square me-2 text-info"),
            dbc.ModalTitle("On-Demand BLAST Validation")
        ]),
        dbc.ModalBody([
            # Target organism info
            html.Div(id="validation-target-info", children=[
                dbc.Alert([
                    html.I(className="bi bi-info-circle me-2"),
                    "Select an organism to validate"
                ], color="info")
            ]),

            # Validation method selector
            dbc.Row([
                dbc.Col([
                    dbc.Label("Validation Method:", html_for="on-demand-method-select"),
                    dbc.Select(
                        id="on-demand-method-select",
                        options=[
                            {"label": "BLAST", "value": "blast"},
                            {"label": "minimap2", "value": "minimap2"},
                            {"label": "Both (BLAST + minimap2)", "value": "both"},
                        ],
                        value="blast",
                    ),
                    dbc.FormText("Select the alignment method for sequence validation"),
                ], md=6)
            ], className="mt-3 mb-2"),

            html.Hr(),

            # Progress section
            html.Div(id="validation-progress-section", children=[
                html.P(
                    id="validation-status-text",
                    children="Ready to start validation",
                    className="text-muted"
                ),
                dbc.Progress(
                    id="validation-progress-bar",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-3"
                ),
                # Progress log
                html.Div(
                    id="validation-progress-log",
                    className="border rounded p-2 bg-light",
                    style={
                        "maxHeight": "150px",
                        "overflowY": "auto",
                        "fontSize": "12px",
                        "fontFamily": "monospace"
                    },
                    children=[]
                )
            ]),

            html.Hr(),

            # Results section (shown after completion)
            html.Div(id="validation-results-section", children=[], style={"display": "none"})
        ]),
        dbc.ModalFooter([
            html.Div(id="validation-status-badge"),
            dbc.Button(
                "Start Validation",
                id="start-on-demand-validation",
                color="primary",
                className="me-2"
            ),
            dbc.Button(
                "Cancel",
                id="cancel-on-demand-validation",
                color="secondary",
                outline=True
            ),
            dbc.Button(
                "Close",
                id="close-on-demand-validation",
                color="secondary",
                style={"display": "none"}
            )
        ])
    ], id="on-demand-validation-modal", is_open=False, size="lg", backdrop="static")


def create_main_layout():
    """
    Create the layout for the main results tab.

    MODERNIZED: Visual organism cards, watched species section with alerts,
    plain language, operator-friendly design.
    Follows progressive disclosure: alert banner -> summary -> watched species
    -> other organisms -> detailed table (optional).

    Returns:
        A dash component representing the main results tab layout
    """
    return html.Div([
        # Hidden store for species watchlist (synced with config)
        dcc.Store(id="main-watchlist-store", data=[], storage_type="session"),

        # On-demand validation stores
        dcc.Store(id="on-demand-validation-target", data=None),  # {taxid, name} of organism being validated
        dcc.Store(id="on-demand-validation-results", data={}),  # {taxid: validation_result}

        # Alert Banner for watched species (dynamic - populated by callback)
        html.Div(id="watched-species-alert-container", className="mb-3"),

        # Per-barcode freshness pills (U2). Populated by
        # update_organisms_freshness_row in app/tabs/main_tab.py.
        html.Div(
            id="organisms-freshness-row",
            className="d-flex flex-wrap gap-2 mb-3",
            role="status",
            **{"aria-live": "polite"},
        ),

        html.Hr(className="my-3"),

        # Summary Card (Top of page - most important info)
        html.Div(id="organism-summary-container", children=[
            EmptyStateMessage(
                title="No Organism Data",
                message="Select a sample or start an analysis to view organism results",
                icon="bi-bug"
            )
        ]),

        # Compact Export Actions (Dropdown menu - less visual clutter)
        _main_export_actions(),

        # Watched Species Section (Always visible with empty state)
        _main_watched_species_section(),

        # All Organisms Section (Cards view only - charts available in Taxonomy tab)
        _main_all_organisms_section(),

        # Advanced Filters (Collapsible - progressive disclosure)
        _main_advanced_filters(),

        # Detailed Data Table (Optional - for power users)
        _main_detailed_table(),

        # Help Section
        _main_help_card(),

        # Export modals
        _main_export_modal(),

        # Download component for file export
        dcc.Download(id="download-organism-data"),

        # Operator Guide Modal
        _main_operator_guide_modal(),

        # On-demand BLAST Validation Modal
        _main_on_demand_validation_modal(),

    ], className="p-4")
