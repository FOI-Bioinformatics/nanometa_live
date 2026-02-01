"""
Validation results layout for Nanometa Live v2.1.

Split into two sub-tabs:
1. Read Validation (BLAST) - sequence identity and read-level confirmation
2. Coverage Validation (minimap2) - genome coverage depth and breadth
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from nanometa_live.app.components.modern_components import (
    EmptyStateMessage,
    TABLE_STYLE_CELL,
    TABLE_STYLE_HEADER,
)


def create_validation_status_card(
    confirmed: int = 0,
    partial: int = 0,
    low_confidence: int = 0,
    no_data: int = 0,
    total: int = 0
) -> dbc.Card:
    """
    Create a summary card showing validation status counts.

    Args:
        confirmed: Number of confirmed detections (>80% validated)
        partial: Number of partial confirmations (50-80%)
        low_confidence: Low confidence detections (<50%)
        no_data: Species with no validation data
        total: Total species checked

    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-shield-check me-2"),
            html.H5("Validation Summary", className="mb-0 d-inline")
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.H2(str(confirmed), className="text-success mb-0"),
                        html.Small("Confirmed", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(partial), className="text-warning mb-0"),
                        html.Small("Partial", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(low_confidence), className="text-danger mb-0"),
                        html.Small("Low Confidence", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(no_data), className="text-secondary mb-0"),
                        html.Small("No Data", className="text-muted")
                    ], className="text-center")
                ], md=3),
            ]),
            html.Hr(className="my-3"),
            html.Div([
                html.Small([
                    html.Strong("Total species checked: "),
                    str(total)
                ], className="text-muted")
            ], className="text-center")
        ])
    ], className="mb-4")


def _create_blast_tab() -> dbc.Tab:
    """Create the Read Validation (BLAST) sub-tab."""
    return dbc.Tab(
        label="Read Validation (BLAST)",
        tab_id="blast-tab",
        children=html.Div([
            # Summary container
            html.Div(id="blast-summary-container", className="mb-4"),

            # Controls row
            dbc.Row([
                dbc.Col([
                    dbc.Label("Filter by Status:", className="fw-bold"),
                    dcc.Dropdown(
                        id="blast-status-filter",
                        options=[
                            {"label": "All", "value": "all"},
                            {"label": "Confirmed (>80%)", "value": "confirmed"},
                            {"label": "Partial (50-80%)", "value": "partial"},
                            {"label": "Low Confidence (<50%)", "value": "low"},
                            {"label": "No Data", "value": "no_data"},
                        ],
                        value="all",
                        clearable=False,
                    )
                ], md=3),
                dbc.Col([
                    dbc.Label("Sort By:", className="fw-bold"),
                    dcc.Dropdown(
                        id="blast-sort-select",
                        options=[
                            {"label": "Validation %", "value": "percent_validated"},
                            {"label": "Read Count", "value": "validated_reads"},
                            {"label": "Identity %", "value": "percent_identity_mean"},
                            {"label": "Species Name", "value": "species"},
                        ],
                        value="percent_validated",
                        clearable=False,
                    )
                ], md=3),
                dbc.Col([
                    dbc.Button(
                        [html.I(className="bi bi-download me-2"), "Export Report"],
                        id="export-blast-button",
                        color="secondary",
                        outline=True,
                        className="float-end mt-4"
                    )
                ], md=6, className="d-flex justify-content-end align-items-end")
            ], className="mb-4"),

            html.Hr(),

            # Empty state
            html.Div(
                id="blast-empty-message",
                children=[
                    EmptyStateMessage(
                        title="No Validation Results",
                        message="No BLAST validation results available. Run the pipeline with BLAST validation enabled to see results here.",
                        icon="bi-shield-check"
                    )
                ]
            ),

            # Results cards container
            html.Div(id="blast-results-container", className="mb-4"),

            # Identity distribution plot (collapsible)
            dbc.Accordion([
                dbc.AccordionItem([
                    html.P(
                        "Distribution of sequence identity scores for validated reads. "
                        "Higher identity indicates more confident matches to reference genomes.",
                        className="text-muted mb-3",
                    ),
                    dcc.Loading(
                        type="circle",
                        children=[
                            dcc.Graph(
                                id="blast-identity-plot",
                                config={"displayModeBar": True, "displaylogo": False},
                                style={"height": "400px"},
                            )
                        ]
                    )
                ], title="Identity Distribution")
            ], start_collapsed=True, className="mb-4"),

            # Stats table (collapsible)
            dbc.Accordion([
                dbc.AccordionItem([
                    html.P(
                        "Detailed BLAST validation metrics for each pathogen.",
                        className="text-muted mb-3",
                    ),
                    dcc.Loading(
                        type="default",
                        children=[
                            dash_table.DataTable(
                                id="blast-stats-table",
                                columns=[
                                    {"name": "Species", "id": "species"},
                                    {"name": "Sample", "id": "sample_id"},
                                    {"name": "Total Reads", "id": "total_reads", "type": "numeric"},
                                    {"name": "Validated", "id": "validated_reads", "type": "numeric"},
                                    {"name": "Validated %", "id": "percent_validated", "type": "numeric"},
                                    {"name": "Identity %", "id": "percent_identity_mean", "type": "numeric"},
                                    {"name": "Coverage", "id": "coverage_breadth", "type": "numeric"},
                                    {"name": "Status", "id": "status"},
                                ],
                                data=[],
                                style_cell=TABLE_STYLE_CELL,
                                style_header=TABLE_STYLE_HEADER,
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{status} = 'confirmed'"},
                                        "backgroundColor": "#d4edda",
                                        "color": "#155724"
                                    },
                                    {
                                        "if": {"filter_query": "{status} = 'partial'"},
                                        "backgroundColor": "#fff3cd",
                                        "color": "#856404"
                                    },
                                    {
                                        "if": {"filter_query": "{status} = 'low'"},
                                        "backgroundColor": "#f8d7da",
                                        "color": "#721c24"
                                    },
                                ],
                                page_size=25,
                                page_action="native",
                                sort_action="native",
                                filter_action="native",
                            )
                        ]
                    )
                ], title="Detailed Validation Statistics")
            ], start_collapsed=True, className="mb-4"),

            # Download component
            dcc.Download(id="download-blast-report"),
        ], className="pt-3")
    )


def _create_coverage_tab() -> dbc.Tab:
    """Create the Coverage Validation (minimap2) sub-tab."""
    return dbc.Tab(
        label="Coverage Validation (minimap2)",
        tab_id="coverage-tab",
        children=html.Div([
            # Summary container
            html.Div(id="coverage-summary-container", className="mb-4"),

            # Controls row
            dbc.Row([
                dbc.Col([
                    dbc.Label("Species / Sample:", className="fw-bold"),
                    dcc.Dropdown(
                        id="coverage-species-selector",
                        placeholder="Select a species to view coverage...",
                        clearable=True,
                    ),
                ], md=6),
                dbc.Col([
                    dbc.Label("Min MapQ filter:", className="fw-bold"),
                    dcc.Input(
                        id="coverage-mapq-filter",
                        type="number",
                        value=0,
                        min=0,
                        max=60,
                        step=1,
                        className="form-control",
                        style={"maxWidth": "120px"},
                    ),
                ], md=3),
                dbc.Col([
                    dbc.Button(
                        [html.I(className="bi bi-download me-2"), "Export Report"],
                        id="export-coverage-button",
                        color="secondary",
                        outline=True,
                        className="float-end mt-4"
                    )
                ], md=3, className="d-flex justify-content-end align-items-end")
            ], className="mb-3"),

            # Empty state
            html.Div(
                id="coverage-empty-message",
                children=[
                    EmptyStateMessage(
                        title="No Coverage Data",
                        message="No minimap2 coverage data available. Run minimap2 validation or select a validated species.",
                        icon="bi-bar-chart-line"
                    )
                ]
            ),

            # Coverage stats badges
            html.Div(id="coverage-stats-container", className="mb-3"),

            # Main coverage depth plot (full width)
            dcc.Loading(
                type="circle",
                children=[
                    dcc.Graph(
                        id="coverage-depth-plot",
                        config={"displayModeBar": True, "displaylogo": False},
                        style={"height": "450px"},
                    )
                ],
            ),

            # Cumulative + Histogram side by side
            dbc.Row([
                dbc.Col([
                    dcc.Loading(
                        type="circle",
                        children=[
                            dcc.Graph(
                                id="coverage-cumulative-plot",
                                config={"displayModeBar": True, "displaylogo": False},
                                style={"height": "280px"},
                            )
                        ],
                    ),
                ], md=6),
                dbc.Col([
                    dcc.Loading(
                        type="circle",
                        children=[
                            dcc.Graph(
                                id="coverage-histogram-plot",
                                config={"displayModeBar": True, "displaylogo": False},
                                style={"height": "280px"},
                            )
                        ],
                    ),
                ], md=6),
            ], className="mb-4"),

            html.Hr(),

            # Results cards container (minimap2 cards)
            html.Div(id="coverage-results-container", className="mb-4"),

            # Download component
            dcc.Download(id="download-coverage-report"),
        ], className="pt-3")
    )


def create_validation_layout() -> dbc.Container:
    """
    Create the validation results tab layout with BLAST and coverage sub-tabs.

    Returns:
        dbc.Container with validation visualization components
    """
    return dbc.Container([
        # Page title
        html.H4("Pathogen Validation Results", className="mb-3"),
        html.P(
            "Validation compares classified reads against reference genomes to confirm "
            "identification accuracy. Use the tabs below to view BLAST read-level results "
            "or minimap2 coverage analysis.",
            className="text-muted mb-4",
        ),

        # Shared data store
        dcc.Store(id="validation-data-store", data={}),

        # Sub-tabs
        dbc.Tabs(
            id="validation-sub-tabs",
            active_tab="blast-tab",
            children=[
                _create_blast_tab(),
                _create_coverage_tab(),
            ],
            className="mb-4",
        ),

        # Help Section (outside tabs)
        dbc.Card([
            dbc.CardHeader(html.H5("Understanding Validation Results", className="mb-0")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.H6("Status Indicators", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-check-circle-fill text-success me-2"),
                                ),
                                html.Strong("Confirmed: "),
                                "80%+ reads validated with 90%+ identity"
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-exclamation-circle-fill text-warning me-2"),
                                ),
                                html.Strong("Partial: "),
                                "50-80% reads validated"
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-x-circle-fill text-danger me-2"),
                                ),
                                html.Strong("Low Confidence: "),
                                "Less than 50% reads validated"
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-question-circle-fill text-secondary me-2"),
                                ),
                                html.Strong("No Data: "),
                                "Validation not performed or failed"
                            ])
                        ])
                    ], md=6),
                    dbc.Col([
                        html.H6("Key Metrics", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Strong("Validated %: "),
                                "Percentage of Kraken2 reads confirmed by BLAST"
                            ]),
                            html.Li([
                                html.Strong("Identity %: "),
                                "Average sequence similarity to reference genome"
                            ]),
                            html.Li([
                                html.Strong("Coverage: "),
                                "Fraction of reference genome covered by reads"
                            ]),
                            html.Li([
                                html.Strong("Depth: "),
                                "Average number of reads per genome position"
                            ])
                        ])
                    ], md=6)
                ]),
                html.Hr(),
                html.P([
                    html.Strong("Note: "),
                    "Validation results help distinguish true pathogen presence from ",
                    "potential misclassification. Even confirmed results should be ",
                    "interpreted in clinical context."
                ], className="text-muted mb-0")
            ])
        ], className="mb-4", style={"backgroundColor": "#f8f9fa"}),

    ], fluid=True)


def create_validation_result_card(
    species: str,
    taxid: int,
    status: str,
    percent_validated: float,
    percent_identity: float,
    total_reads: int,
    validated_reads: int,
    coverage: float = 0.0,
    sample_id: str = "",
    validation_method: str = "blast",
    avg_mapq: float = 0.0,
    show_coverage_button: bool = False
) -> dbc.Card:
    """
    Create a card displaying validation results for a single species.

    Args:
        species: Species name
        taxid: Taxonomy ID
        status: Validation status (confirmed, partial, low, no_data)
        percent_validated: Percentage of reads validated
        percent_identity: Mean identity percentage
        total_reads: Total reads from Kraken2
        validated_reads: Reads validated by BLAST
        coverage: Reference genome coverage (0-1)
        sample_id: Sample identifier
        validation_method: Validation method used (blast or minimap2)
        avg_mapq: Average mapping quality (minimap2)
        show_coverage_button: Whether to show the View Coverage button

    Returns:
        dbc.Card component
    """
    status_config = {
        "confirmed": {
            "icon": "bi-check-circle-fill",
            "color": "success",
            "badge": "Confirmed",
            "border": "border-success"
        },
        "partial": {
            "icon": "bi-exclamation-circle-fill",
            "color": "warning",
            "badge": "Partial",
            "border": "border-warning"
        },
        "low": {
            "icon": "bi-x-circle-fill",
            "color": "danger",
            "badge": "Low Confidence",
            "border": "border-danger"
        },
        "no_data": {
            "icon": "bi-question-circle-fill",
            "color": "secondary",
            "badge": "No Data",
            "border": "border-secondary"
        },
        "failed": {
            "icon": "bi-exclamation-triangle-fill",
            "color": "dark",
            "badge": "Failed",
            "border": "border-dark"
        }
    }

    config = status_config.get(status, status_config["no_data"])

    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.I(className=f"bi {config['icon']} text-{config['color']} me-2"),
                    html.Strong(species, style={"fontSize": "1.1rem"}),
                ], md=8),
                dbc.Col([
                    dbc.Badge(
                        config["badge"],
                        color=config["color"],
                        className="float-end"
                    ),
                    dbc.Badge(
                        validation_method.upper() if validation_method != "blast" else "BLAST",
                        color="info" if validation_method == "minimap2" else "warning",
                        className="float-end me-1",
                        style={"fontSize": "0.7rem"}
                    )
                ], md=4, className="text-end")
            ])
        ], className=f"py-2 {config['border']}"),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Small("Validated", className="text-muted d-block"),
                        html.Strong(f"{percent_validated:.1f}%", style={"fontSize": "1.2rem"})
                    ])
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.Small("Identity", className="text-muted d-block"),
                        html.Strong(f"{percent_identity:.1f}%", style={"fontSize": "1.2rem"})
                    ])
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.Small("Reads", className="text-muted d-block"),
                        html.Strong(f"{validated_reads:,}/{total_reads:,}", style={"fontSize": "1.1rem"})
                    ])
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.Small(
                            "MapQ" if validation_method == "minimap2" else "Coverage",
                            className="text-muted d-block"
                        ),
                        html.Strong(
                            f"{avg_mapq:.1f}" if validation_method == "minimap2" else f"{coverage*100:.1f}%",
                            style={"fontSize": "1.2rem"}
                        )
                    ])
                ], md=3),
            ]),
            html.Div([
                dbc.Progress(
                    value=percent_validated,
                    color=config["color"],
                    className="mt-3",
                    style={"height": "8px"}
                )
            ])
        ]),
        dbc.CardFooter([
            html.Small([
                html.Span(f"TaxID: {taxid}", className="me-3"),
                html.Span(f"Sample: {sample_id}", className="me-3") if sample_id else "",
            ], className="text-muted d-inline"),
            dbc.Button(
                [html.I(className="bi bi-bar-chart-line me-1"), "View Coverage"],
                id={"type": "view-coverage-btn", "index": f"{sample_id}_{taxid}"},
                color="info",
                size="sm",
                outline=True,
                className="float-end",
            ) if show_coverage_button else html.Span(),
        ], className="py-1")
    ], className=f"mb-3 {config['border']}", style={"borderLeftWidth": "4px"})
