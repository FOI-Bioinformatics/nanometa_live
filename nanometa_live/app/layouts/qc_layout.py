"""
Quality Control (QC) tab layout for Nanometa Live v2.0.

This module defines the layout for the QC tab, which displays quality metrics
and processing statistics with multi-sample/barcode support.

MODERNIZED: Uses visual quality indicators, plain language, and operator-friendly design.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px

from nanometa_live.app.components.modern_components import (
    EmptyStateMessage,
    TABLE_STYLE_CELL,
    TABLE_STYLE_HEADER,
    status_conditional_style,
)
from nanometa_live.app.utils.plotly_theme import CHART_CONFIG
from nanometa_live.app.components.organism_components import (
    FilteringBreakdownVisual,
    KeyMetricsSummaryCard,
    BaseQualityCard,
    ReadStatisticsCard,
)


def create_qc_layout():
    """
    Create the layout for the QC tab.

    MODERNIZED: Visual quality indicators, plain language, operator-friendly design.
    Follows visual hierarchy: score → breakdown → per-sample → detailed plots.

    Returns:
        A dash component representing the QC tab layout
    """
    # Create empty placeholder plots
    cumul_reads_fig = px.line(title="Cumulative DNA Sequences")
    cumul_bp_fig = px.line(title="Cumulative Base Pairs")
    reads_fig = px.bar(title="DNA Sequences per Batch")
    bp_fig = px.bar(title="Base Pairs per Batch")

    return html.Div([
        # Centralized QC data cache - loaded once per interval cycle
        dcc.Store(id="qc-data-cache", data={}),

        # KEY METRICS SUMMARY CARD
        # Provides at-a-glance overview of key QC metrics (non-sticky, matching QualityScoreIndicator style)
        dcc.Loading(
            id="loading-qc-metrics",
            type="circle",
            color="#198754",
            children=[
                html.Div(
                    id="qc-metrics-summary-container",
                    children=[
                        EmptyStateMessage(
                            title="No QC Metrics",
                            message="Key metrics will appear here once data is loaded",
                            icon="bi-speedometer2"
                        )
                    ],
                    className="d-flex justify-content-center mb-4"
                )
            ]
        ),

        html.Hr(className="my-3"),

        # LEVEL 1: Base Quality and Read Statistics Cards (NEW)
        html.H4("Sequencing Quality", className="mb-3"),
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id="loading-base-quality",
                    type="circle",
                    color="#198754",
                    children=[
                        html.Div(id="base-quality-card-container", children=[
                            EmptyStateMessage(
                                title="No Base Quality Data",
                                message="Base quality metrics will appear here once data is loaded",
                                icon="bi-bar-chart"
                            )
                        ])
                    ]
                )
            ], md=6),
            dbc.Col([
                dcc.Loading(
                    id="loading-read-statistics",
                    type="circle",
                    color="#198754",
                    children=[
                        html.Div(id="read-statistics-card-container", children=[
                            EmptyStateMessage(
                                title="No Read Statistics",
                                message="Read statistics will appear here once data is loaded",
                                icon="bi-file-earmark-text"
                            )
                        ])
                    ]
                )
            ], md=6)
        ], className="mb-3"),
        # Export button row
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    [html.I(className="bi bi-download me-2"), "Export QC Report"],
                    id="export-qc-report",
                    color="secondary",
                    outline=True,
                    size="sm"
                )
            ], className="d-flex justify-content-end")
        ], className="mb-3"),

        html.Hr(className="my-3"),

        # LEVEL 2: Filtering Breakdown (Visual Bar Chart)
        html.H4("Quality Filtering Breakdown", className="mb-3"),
        dcc.Loading(
            id="loading-filtering-breakdown",
            type="circle",
            color="#0d6efd",
            children=[
                html.Div(id="filtering-breakdown-container", children=[
                    EmptyStateMessage(
                        title="No Filtering Data",
                        message="Filtering statistics will appear here once analysis is complete",
                        icon="bi-funnel"
                    )
                ], className="mb-4")
            ]
        ),

        html.Hr(className="my-3"),

        # LEVEL 3: Per-Sample Quality Table
        html.H4("Per-Sample Quality", className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("Sample Breakdown", className="mb-0"),
                        html.Small("Quality metrics for each sample/barcode", className="text-muted ms-2")
                    ]),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="per-sample-table",
                            columns=[
                                {"name": "Sample", "id": "sample"},
                                {"name": "Reads", "id": "reads", "type": "numeric", "format": {"specifier": ","}},
                                {"name": "Quality", "id": "mean_quality"},
                                {"name": "Classified", "id": "classified_rate"},
                                {"name": "Status", "id": "status"},
                                # Hidden numeric column for proper filtering
                                {"name": "", "id": "classified_rate_num", "type": "numeric", "hideable": True},
                            ],
                            hidden_columns=["classified_rate_num"],
                            data=[],
                            style_cell={**TABLE_STYLE_CELL, "minWidth": "100px"},
                            style_header=TABLE_STYLE_HEADER,
                            style_data_conditional=[
                                # Classification rate highlights (80%+ is good)
                                # Uses classified_rate_num (hidden numeric column) for filtering
                                {
                                    "if": {
                                        "filter_query": "{classified_rate_num} >= 80",
                                        "column_id": "classified_rate"
                                    },
                                    "backgroundColor": "#d4edda",
                                    "color": "#155724",
                                    "fontWeight": "bold"
                                },
                                # Quality score thresholds
                                {
                                    "if": {"filter_query": "{mean_quality} >= 15", "column_id": "mean_quality"},
                                    "backgroundColor": "#d4edda", "color": "#155724"
                                },
                                {
                                    "if": {"filter_query": "{mean_quality} >= 10 && {mean_quality} < 15", "column_id": "mean_quality"},
                                    "backgroundColor": "#fff3cd", "color": "#856404"
                                },
                                {
                                    "if": {"filter_query": "{mean_quality} < 10", "column_id": "mean_quality"},
                                    "backgroundColor": "#f8d7da", "color": "#721c24"
                                },
                            ] + status_conditional_style("status"),
                            tooltip_header={
                                "mean_quality": "Average quality score (Q15+ is good)",
                                "classified_rate": "Percentage of reads successfully classified",
                                "status": "Overall sample quality assessment"
                            },
                            tooltip_delay=500,
                            tooltip_duration=3000,
                            page_size=10,
                            sort_action="native"
                        ),
                        html.Small(
                            "Detailed metrics available in Technical Statistics section below",
                            className="text-muted d-block mt-2"
                        )
                    ])
                ])
            ])
        ], className="mb-4"),

        # LEVEL 4: Detailed Plots (Advanced - Collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5("Processing Metrics Over Time", className="mb-0"),
                                dbc.Button(
                                    "Export Plots",
                                    id="export-qc-plots",
                                    color="secondary",
                                    size="sm",
                                    className="float-end"
                                )
                            ]),
                            dbc.CardBody([
                                html.P(
                                    "These charts show how data accumulated during the sequencing run. "
                                    "Useful for troubleshooting if you suspect issues during specific time periods.",
                                    className="text-muted mb-3"
                                ),
                                # Top row of plots
                                dcc.Loading(
                                    id="loading-cumulative-charts",
                                    type="circle",
                                    color="#0d6efd",
                                    children=[
                                        dbc.Row([
                                            dbc.Col(
                                                dcc.Graph(
                                                    id="cumul-reads-graph",
                                                    figure=cumul_reads_fig,
                                                    config=CHART_CONFIG
                                                ),
                                                width=6
                                            ),
                                            dbc.Col(
                                                dcc.Graph(
                                                    id="cumul-bp-graph",
                                                    figure=cumul_bp_fig,
                                                    config=CHART_CONFIG
                                                ),
                                                width=6
                                            )
                                        ], className="mb-4"),
                                    ]
                                ),

                                # Bottom row of plots
                                dcc.Loading(
                                    id="loading-batch-charts",
                                    type="circle",
                                    color="#0d6efd",
                                    children=[
                                        dbc.Row([
                                            dbc.Col(
                                                dcc.Graph(
                                                    id="reads-graph",
                                                    figure=reads_fig,
                                                    config=CHART_CONFIG
                                                ),
                                                width=6
                                            ),
                                            dbc.Col(
                                                dcc.Graph(
                                                    id="bp-graph",
                                                    figure=bp_fig,
                                                    config=CHART_CONFIG
                                                ),
                                                width=6
                                            )
                                        ])
                                    ]
                                )
                            ])
                        ])
                    ])
                ])
            ], title="Detailed Processing Charts (Advanced)")
        ], start_collapsed=True, className="mb-4"),

        # Technical Statistics (Hidden by default - for power users)
        dbc.Accordion([
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([
                        html.P(
                            "These are technical statistics from the analysis pipeline. "
                            "Most operators won't need these - use the visual indicators above.",
                            className="text-muted mb-3"
                        ),
                        html.Div([
                            # Filtering stats
                            html.H5("Quality Filtering", className="fw-bold mb-3"),
                            html.Div(id="qc-reads-pre-filtering", children="Total DNA sequences before filtering: 0"),
                            html.Div(id="qc-reads-passed", children="Sequences that passed quality control: 0"),
                            html.Div(id="qc-reads-removed", children="Total sequences removed: 0"),

                            html.Hr(),

                            # Reasons for removal
                            html.H5("Removal Reasons (Technical)", className="fw-bold mb-3"),
                            html.Div(id="qc-proportions-info", children="(percentages of total removed sequences)"),
                            html.Div(id="qc-low-quality", children="Too low quality: 0 (0%)"),
                            html.Div(id="qc-too-short", children="Too short: 0 (0%)"),
                            html.Div(id="qc-low-complexity", children="Too low complexity: 0 (0%)"),

                            html.Hr(),

                            # Classification stats
                            html.H5("Organism Classification", className="fw-bold mb-3"),
                            html.Div(id="qc-classified-reads", children="Successfully classified: 0 (0%)"),
                            html.Div(id="qc-unclassified-reads", children="Unclassified: 0 (0%)"),

                            html.Hr(),

                            # Processing stats
                            html.H5("File Processing", className="fw-bold mb-3"),
                            html.Div(id="qc-processed-files", children="Files processed: 0"),
                            html.Div(id="qc-waiting-files", children="Files awaiting processing: 0"),
                        ])
                    ])
                ])
            ], title="Technical Statistics (Advanced)")
        ], start_collapsed=True, className="mb-4"),

        # Help Section
        dbc.Card([
            dbc.CardHeader(html.H5("Need Help?", className="mb-0")),
            dbc.CardBody([
                html.P("Common Quality Issues:", className="fw-bold mb-2"),
                html.Ul([
                    html.Li([
                        html.Strong("Low Quality Sequences: "),
                        "Contains too many uncertain bases (poor signal from sequencer)"
                    ]),
                    html.Li([
                        html.Strong("Too Short: "),
                        "DNA fragments below minimum length (< 15 base pairs)"
                    ]),
                    html.Li([
                        html.Strong("Low Complexity: "),
                        "Repetitive sequences that may be artifacts (e.g., AAAAAAA...)"
                    ])
                ], className="mb-3"),
                html.P([
                    html.Strong("What to do if quality is low: "),
                    "Check sequencing conditions, flow cell health, and sample quality. "
                    "Consider re-running critical samples if pass rate is below 60%."
                ], className="mb-3"),
                dbc.Button(
                    "View Detailed Help",
                    id="qc-help-button",
                    color="info",
                    outline=True
                )
            ])
        ], className="mb-4", style={"backgroundColor": "#f8f9fa"}),

        # Help modal (updated with plain language)
        dbc.Modal([
            dbc.ModalHeader("QC Help"),
            dbc.ModalBody([
                html.P([
                    "The two upper graphs show the cumulative reads and base pairs produced by the sequencer ",
                    "over time, using the pre-filtered data, i.e. the raw data from the sequencer."
                ]),
                html.P([
                    "The lower two plots show the number of reads and base pairs produced in each batch, also ",
                    "using the unfiltered sequencer data."
                ]),
                html.P([
                    "The FILTERING info displays the total number of sequences produced, the number of passed ",
                    "and removed sequences, and the reasons for removal."
                ]),
                html.P("The filter parameters are the following:"),
                html.Ul([
                    html.Li([
                        html.Strong("Too low quality: "),
                        "removes sequences with too many unqualified bases. Bases with phred quality <15 are unqualified. ",
                        "Sequences with more than 40% unqualified bases are discarded."
                    ]),
                    html.Li([
                        html.Strong("Too short: "),
                        "removes sequences that are shorter than 15 bp."
                    ]),
                    html.Li([
                        html.Strong("Too low complexity: "),
                        "filters by the percentage of bases that are different from its next base. ",
                        "This way, sequences with long stretches of the same nucleotide are filtered out. ",
                        "At least 30% complexity is required."
                    ])
                ]),
                html.P("The filtering also automatically removes adapters."),
                html.P([
                    "CLASSIFICATION shows the number of reads that were successfully classified."
                ]),
                html.P([
                    "FILE PROCESSING shows the number of batch files that have been processed ",
                    "and the number that still remain."
                ])
            ]),
            dbc.ModalFooter(
                dbc.Button("Close", id="close-qc-help", className="ms-auto")
            )
        ], id="qc-help-modal", size="lg"),

        # Export modal
        dbc.Modal([
            dbc.ModalHeader("Export QC Plots"),
            dbc.ModalBody([
                html.Div([
                    dbc.Label("Export Directory:"),
                    dbc.Input(id="qc-export-dir", placeholder="Leave empty to use default reports directory")
                ], className="mb-3"),
                html.Div([
                    dbc.Label("Base Filename:"),
                    dbc.Input(id="qc-export-filename", placeholder="e.g., qc_plots")
                ], className="mb-3")
            ]),
            dbc.ModalFooter([
                dbc.Button("Export", id="confirm-qc-export", color="primary"),
                dbc.Button("Cancel", id="cancel-qc-export", color="secondary")
            ])
        ], id="qc-export-modal")
    ], className="p-4")