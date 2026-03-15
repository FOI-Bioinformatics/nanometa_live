"""
Quality Control (QC) tab layout for Nanometa Live v2.0.

This module defines the layout for the QC tab, which displays quality metrics
and processing statistics with multi-sample/barcode support.

MODERNIZED: Uses visual quality indicators, plain language, and operator-friendly design.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.express as px

from nanometa_live.app.components.modern_components import EmptyStateMessage
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
        # Download component for QC report export
        dcc.Download(id="download-qc-report"),

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

        # ACTION GUIDANCE BANNER - shown dynamically by callback
        html.Div(id="qc-action-guidance-container", className="mb-3"),

        # LEVEL 1: Base Quality and Read Statistics Cards (NEW)
        html.H4([
            "Sequencing Quality",
            html.Small(
                " - How good is the raw data from the sequencer?",
                className="text-muted fw-normal",
                style={"fontSize": "14px"}
            ),
        ], className="mb-3"),
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
        html.H4([
            "Quality Filtering Breakdown",
            html.Small(
                " - How many sequences passed quality checks?",
                className="text-muted fw-normal",
                style={"fontSize": "14px"}
            ),
        ], className="mb-3"),
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
        html.H4([
            "Per-Sample Quality",
            html.Small(
                " - Individual results for each barcode/sample",
                className="text-muted fw-normal",
                style={"fontSize": "14px"}
            ),
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("Sample Breakdown", className="mb-0"),
                        html.Small("Quality metrics for each sample/barcode", className="text-muted ms-2")
                    ]),
                    dbc.CardBody([
                        dag.AgGrid(
                            id="per-sample-table",
                            columnDefs=[
                                {"headerName": "Sample", "field": "sample"},
                                {
                                    "headerName": "Sequences",
                                    "field": "reads",
                                    "headerTooltip": "Number of DNA sequence fragments in this sample",
                                    "type": "numericColumn",
                                    "valueFormatter": {"function": "d3.format(',')(params.value)"},
                                },
                                {
                                    "headerName": "Avg. Quality",
                                    "field": "mean_quality",
                                    "headerTooltip": "Average quality score per read. Green (15+) = Good, Yellow (10-15) = Fair, Red (<10) = Poor. Higher is better.",
                                    "cellStyle": {
                                        "styleConditions": [
                                            {
                                                "condition": "params.value >= 15",
                                                "style": {"backgroundColor": "#d4edda", "color": "#155724"},
                                            },
                                            {
                                                "condition": "params.value >= 10 && params.value < 15",
                                                "style": {"backgroundColor": "#fff3cd", "color": "#856404"},
                                            },
                                            {
                                                "condition": "params.value < 10",
                                                "style": {"backgroundColor": "#f8d7da", "color": "#721c24"},
                                            },
                                        ],
                                    },
                                },
                                {
                                    "headerName": "Identified",
                                    "field": "classified_rate",
                                    "headerTooltip": "Percentage of sequences matched to a known organism. 80%+ is good for environmental samples.",
                                    "cellStyle": {
                                        "styleConditions": [
                                            {
                                                "condition": "params.data && params.data.classified_rate_num >= 80",
                                                "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "bold"},
                                            },
                                        ],
                                    },
                                },
                                {
                                    "headerName": "Status",
                                    "field": "status",
                                    "headerTooltip": "Overall assessment: Good = data is usable, Review = check results carefully, Issue = may need re-sequencing",
                                    "cellStyle": {
                                        "styleConditions": [
                                            {
                                                "condition": "params.value && (params.value.indexOf('Complete') >= 0 || params.value.indexOf('Good') >= 0)",
                                                "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "bold"},
                                            },
                                            {
                                                "condition": "params.value && (params.value.indexOf('Processing') >= 0 || params.value.indexOf('Review') >= 0)",
                                                "style": {"backgroundColor": "#fff3cd", "color": "#856404", "fontWeight": "bold"},
                                            },
                                            {
                                                "condition": "params.value && (params.value.indexOf('Error') >= 0 || params.value.indexOf('Issue') >= 0)",
                                                "style": {"backgroundColor": "#f8d7da", "color": "#721c24", "fontWeight": "bold"},
                                            },
                                        ],
                                    },
                                },
                                # Hidden numeric column still in data for classified_rate styling
                                {"field": "classified_rate_num", "hide": True},
                            ],
                            rowData=[],
                            defaultColDef={"sortable": True, "filter": True, "resizable": True, "minWidth": 100},
                            dashGridOptions={
                                "pagination": True,
                                "paginationPageSize": 10,
                                "tooltipShowDelay": 500,
                            },
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
            dbc.CardHeader(html.H5("Understanding This Page", className="mb-0")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.P("Key Terms:", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Strong("Pass Rate: "),
                                "Percentage of sequences that are high enough quality to analyze. ",
                                "Above 80% is normal."
                            ]),
                            html.Li([
                                html.Strong("Q20 / Q30: "),
                                "Measures of base accuracy. Q20 = 99% accurate, Q30 = 99.9% accurate. ",
                                "For nanopore: Q20 above 65% and Q30 above 45% are good."
                            ]),
                            html.Li([
                                html.Strong("N50: "),
                                "A measure of sequence length. Half of all data is in sequences ",
                                "this long or longer. Higher = better. Above 2,000 bp is good."
                            ]),
                            html.Li([
                                html.Strong("GC Content: "),
                                "The proportion of G and C bases. Should be 40-60% for most samples."
                            ]),
                        ], className="mb-0"),
                    ], md=6),
                    dbc.Col([
                        html.P("What To Do:", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Strong("Pass rate below 60%: "),
                                "Check flow cell health, sample purity, and loading concentration. ",
                                "Consider re-sequencing critical samples."
                            ]),
                            html.Li([
                                html.Strong("Low Q20/Q30: "),
                                "May indicate an old or damaged flow cell, or poor library prep. ",
                                "Results can still be usable - check organism identification confidence."
                            ]),
                            html.Li([
                                html.Strong("Short sequences (low N50): "),
                                "DNA may be degraded. Consider fresh extraction if possible."
                            ]),
                            html.Li([
                                html.Strong("Everything looks good: "),
                                "Proceed to the Organisms or Validation tabs to review findings."
                            ]),
                        ], className="mb-0"),
                    ], md=6),
                ]),
                html.Hr(className="my-3"),
                dbc.Button(
                    "View Full Technical Details",
                    id="qc-help-button",
                    color="info",
                    outline=True,
                    size="sm"
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