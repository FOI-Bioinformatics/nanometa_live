"""
Validation results layout for Nanometa Live v2.1.

This layout displays BLAST/minimap2 validation results for watched pathogens,
showing confirmation status, identity statistics, and coverage metrics.

The layout is designed to work in three states:
1. No validation data available (placeholder)
2. Mock/demo mode (generated test data)
3. Real validation results from nanometanf
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from nanometa_live.app.components.modern_components import (
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


def create_validation_layout() -> dbc.Container:
    """
    Create the validation results tab layout.

    Returns:
        dbc.Container with validation visualization components
    """
    return dbc.Container([
        # Page title and description
        html.H4("Pathogen Validation Results", className="mb-3"),
        html.P([
            "This tab shows the results of sequence validation for detected pathogens. ",
            "Validation compares classified reads against reference genomes to confirm ",
            "identification accuracy."
        ], className="text-muted mb-4"),

        # Status alert for when validation is not available
        html.Div(id="validation-status-alert", children=[
            dbc.Alert([
                html.H5([
                    html.I(className="bi bi-info-circle me-2"),
                    "Validation Not Available"
                ], className="alert-heading"),
                html.P([
                    "BLAST/minimap2 validation has not been configured or no results are available yet. ",
                    "To enable validation:"
                ]),
                html.Ol([
                    html.Li("Add pathogens to your watchlist in the Watchlist tab"),
                    html.Li("Download reference genomes for watched pathogens"),
                    html.Li("Enable 'BLAST Validation' in the Configuration tab"),
                    html.Li("Run or restart the analysis pipeline")
                ]),
            ], color="info", className="mb-4")
        ]),

        # Validation Summary Card (populated by callback)
        html.Div(id="validation-summary-container"),

        # Controls row
        dbc.Row([
            dbc.Col([
                dbc.Label("Filter by Status:", className="fw-bold"),
                dcc.Dropdown(
                    id="validation-status-filter",
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
                dbc.Label("Filter by Method:", className="fw-bold"),
                dcc.Dropdown(
                    id="validation-method-filter",
                    options=[
                        {"label": "All Methods", "value": "all"},
                        {"label": "BLAST", "value": "blast"},
                        {"label": "minimap2", "value": "minimap2"},
                    ],
                    value="all",
                    clearable=False,
                )
            ], md=2),
            dbc.Col([
                dbc.Label("Sort By:", className="fw-bold"),
                dcc.Dropdown(
                    id="validation-sort-by",
                    options=[
                        {"label": "Validation %", "value": "percent_validated"},
                        {"label": "Read Count", "value": "validated_reads"},
                        {"label": "Identity %", "value": "percent_identity_mean"},
                        {"label": "Species Name", "value": "species"},
                    ],
                    value="percent_validated",
                    clearable=False,
                )
            ], md=2),
            dbc.Col([
                dbc.Button(
                    [html.I(className="bi bi-download me-2"), "Export Report"],
                    id="export-validation-report",
                    color="secondary",
                    outline=True,
                    className="float-end mt-4"
                )
            ], md=5, className="d-flex justify-content-end align-items-end")
        ], className="mb-4"),

        html.Hr(),

        # Validation Results Cards Container
        html.Div(id="validation-results-container", children=[
            # This will be populated by callback with ValidationResultCard components
            dbc.Alert(
                "Validation results will appear here when available",
                color="light",
                className="text-center"
            )
        ], className="mb-4"),

        # --- Coverage Visualization Section ---
        html.Hr(className="my-4"),
        html.H5([
            html.I(className="bi bi-bar-chart-line me-2"),
            "Genome Coverage"
        ], className="mb-3"),
        html.P(
            "Per-position read depth across the reference genome. "
            "Select a species from the dropdown or click 'View Coverage' on a result card.",
            className="text-muted mb-3",
        ),

        # Species selector for coverage
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
                    id="coverage-min-mapq",
                    type="number",
                    value=0,
                    min=0,
                    max=60,
                    step=1,
                    className="form-control",
                    style={"maxWidth": "120px"},
                ),
            ], md=3),
        ], className="mb-3"),

        # Coverage stats row
        html.Div(id="coverage-stats-container"),

        # Main coverage depth plot (full width)
        dcc.Loading(
            id="loading-coverage-depth",
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
                    id="loading-cumulative-plot",
                    type="circle",
                    children=[
                        dcc.Graph(
                            id="cumulative-coverage-plot",
                            config={"displayModeBar": True, "displaylogo": False},
                            style={"height": "280px"},
                        )
                    ],
                ),
            ], md=6),
            dbc.Col([
                dcc.Loading(
                    id="loading-depth-histogram",
                    type="circle",
                    children=[
                        dcc.Graph(
                            id="depth-histogram-plot",
                            config={"displayModeBar": True, "displaylogo": False},
                            style={"height": "280px"},
                        )
                    ],
                ),
            ], md=6),
        ], className="mb-4"),

        html.Hr(),

        # Detailed Statistics Table (collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Detailed validation metrics for each pathogen. ",
                    "These statistics show per-read alignment quality."
                ], className="text-muted mb-3"),
                dcc.Loading(
                    id="loading-validation-table",
                    type="default",
                    children=[
                        dash_table.DataTable(
                            id="validation-details-table",
                            columns=[
                                {"name": "Species", "id": "species"},
                                {"name": "Sample", "id": "sample_id"},
                                {"name": "Total Reads", "id": "total_reads", "type": "numeric"},
                                {"name": "Validated", "id": "validated_reads", "type": "numeric"},
                                {"name": "Validated %", "id": "percent_validated", "type": "numeric"},
                                {"name": "Identity %", "id": "percent_identity_mean", "type": "numeric"},
                                {"name": "Coverage", "id": "coverage_breadth", "type": "numeric"},
                                {"name": "Method", "id": "validation_method"},
                                {"name": "MapQ", "id": "avg_mapq", "type": "numeric"},
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
                            page_size=15,
                            sort_action="native",
                            filter_action="native",
                        )
                    ]
                )
            ], title="Detailed Validation Statistics")
        ], start_collapsed=True, className="mb-4"),

        # Identity Distribution Plot (collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                html.P([
                    "Distribution of sequence identity scores for validated reads. ",
                    "Higher identity indicates more confident matches to reference genomes."
                ], className="text-muted mb-3"),
                dcc.Loading(
                    id="loading-identity-plot",
                    type="circle",
                    children=[
                        dcc.Graph(
                            id="validation-identity-plot",
                            config={
                                "displayModeBar": True,
                                "displaylogo": False
                            },
                            style={"height": "400px"}
                        )
                    ]
                )
            ], title="Identity Distribution")
        ], start_collapsed=True, className="mb-4"),

        # Help Section
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

        # Hidden stores for validation data
        dcc.Store(id="validation-data-store", data={}),
        # Download component
        dcc.Download(id="download-validation-report"),

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
    avg_mapq: float = 0.0
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

    Returns:
        dbc.Card component
    """
    # Determine status icon and colors
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
            # Progress bar showing validation %
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
            ) if validation_method in ("minimap2", "both") else html.Span(),
        ], className="py-1")
    ], className=f"mb-3 {config['border']}", style={"borderLeftWidth": "4px"})
