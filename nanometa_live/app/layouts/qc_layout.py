"""
Quality Control (QC) tab layout for Nanometa Live v2.0.

This module defines the layout for the QC tab, which displays quality metrics
and processing statistics with multi-sample/barcode support.

MODERNIZED: Uses visual quality indicators, plain language, and operator-friendly design.

The layout is assembled from per-section builder functions (``_qc_*``) so each
zone can be read and edited in isolation; ``create_qc_layout`` composes them in
visual order. The builders return components only -- no callbacks or data
access -- and every component id is preserved exactly as the callbacks expect.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.express as px

from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.app.utils.plotly_theme import CHART_CONFIG


def _qc_after_filtering_cards():
    """Read-quality and read-statistics cards (post-filtering metrics)."""
    return [
        html.H4([
            "Read Quality — After filtering",
            html.Small(
                " (SeqKit · chopped.fastq.gz)",
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
    ]


def _qc_per_sample_table():
    """Per-sample quality breakdown (AgGrid with cumulative/latest horizons)."""
    return dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("Sample Breakdown", className="mb-0"),
                        html.Small(
                            "Two horizons shown side-by-side: "
                            "cumulative since run start, and the latest batch only.",
                            className="text-muted d-block mt-1",
                        ),
                    ])
                ]),
                dbc.CardBody([
                    dag.AgGrid(
                        id="per-sample-table",
                        columnDefs=[
                            {
                                "headerName": "Sample",
                                "field": "sample",
                                "pinned": "left",
                                "minWidth": 130,
                            },
                            {
                                # Group: cumulative horizon (matches Stage Strip, Dashboard, Organism tab)
                                "headerName": "Cumulative (since run start)",
                                "headerClass": "qc-col-group-cumul",
                                "children": [
                                    {
                                        "headerName": "Filtered reads",
                                        "field": "reads_cumul",
                                        "headerTooltip": (
                                            "Reads that passed the quality filter, "
                                            "summed across every batch since the run started. "
                                            "Source: Kraken2 cumulative report."
                                        ),
                                        "type": "numericColumn",
                                        "valueFormatter": {
                                            "function": "params.value == null ? '' : d3.format(',')(params.value)"
                                        },
                                        "minWidth": 130,
                                    },
                                    {
                                        "headerName": "Classification rate",
                                        "field": "classified_rate_cumul",
                                        "headerTooltip": (
                                            "Fraction of filtered reads matched to a known organism, "
                                            "across the whole run. Source: Kraken2 cumulative report."
                                        ),
                                        "cellStyle": {
                                            "styleConditions": [
                                                {
                                                    "condition": "params.data && params.data.classified_rate_cumul_num >= 80",
                                                    "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "600"},
                                                },
                                                {
                                                    "condition": "params.data && params.data.classified_rate_cumul_num >= 50 && params.data.classified_rate_cumul_num < 80",
                                                    "style": {"backgroundColor": "#fff3cd", "color": "#664d03"},
                                                },
                                                {
                                                    "condition": "params.data && params.data.classified_rate_cumul_num < 50",
                                                    "style": {"backgroundColor": "#f8d7da", "color": "#721c24"},
                                                },
                                            ],
                                        },
                                        "minWidth": 140,
                                    },
                                ],
                            },
                            {
                                # Group: latest-batch horizon (what happened in the most recent batch)
                                "headerName": "Latest batch",
                                "headerClass": "qc-col-group-latest",
                                "children": [
                                    {
                                        "headerName": "Filtered reads",
                                        "field": "reads_latest",
                                        "headerTooltip": (
                                            "Reads processed by Kraken2 in the most recent batch only. "
                                            "Equal to the cumulative value in batch-mode runs."
                                        ),
                                        "type": "numericColumn",
                                        "valueFormatter": {
                                            "function": "params.value == null ? '' : d3.format(',')(params.value)"
                                        },
                                        "minWidth": 130,
                                        "cellClass": "qc-col-latest-cell",
                                    },
                                    {
                                        "headerName": "Classification rate",
                                        "field": "classified_rate_latest",
                                        "headerTooltip": (
                                            "Fraction of reads classified in the most recent batch only."
                                        ),
                                        "cellStyle": {
                                            "styleConditions": [
                                                {
                                                    "condition": "params.data && params.data.classified_rate_latest_num >= 80",
                                                    "style": {"color": "var(--text-success-inline)", "fontWeight": "600"},
                                                },
                                                {
                                                    "condition": "params.data && params.data.classified_rate_latest_num >= 50 && params.data.classified_rate_latest_num < 80",
                                                    "style": {"color": "var(--text-warning-inline)"},
                                                },
                                                {
                                                    "condition": "params.data && params.data.classified_rate_latest_num > 0 && params.data.classified_rate_latest_num < 50",
                                                    "style": {"color": "var(--text-danger-inline)"},
                                                },
                                            ],
                                        },
                                        "minWidth": 140,
                                        "cellClass": "qc-col-latest-cell",
                                    },
                                ],
                            },
                            {
                                "headerName": "Avg. Q score",
                                "field": "mean_quality",
                                "headerTooltip": "Mean Phred quality per read. Source: SeqKit",
                                "minWidth": 120,
                                "cellStyle": {
                                    "styleConditions": [
                                        {
                                            "condition": "params.value >= 15",
                                            "style": {"backgroundColor": "#d4edda", "color": "#155724"},
                                        },
                                        {
                                            "condition": "params.value >= 10 && params.value < 15",
                                            "style": {"backgroundColor": "#fff3cd", "color": "#664d03"},
                                        },
                                        {
                                            "condition": "typeof params.value === 'number' && params.value < 10",
                                            "style": {"backgroundColor": "#f8d7da", "color": "#721c24"},
                                        },
                                    ],
                                },
                            },
                            {
                                "headerName": "Status",
                                "field": "status",
                                "headerTooltip": "Overall assessment based on cumulative classification rate.",
                                "minWidth": 130,
                                "cellStyle": {
                                    "styleConditions": [
                                        {
                                            "condition": "params.value && params.value.indexOf('Complete') >= 0",
                                            "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "600"},
                                        },
                                        {
                                            "condition": "params.value && params.value.indexOf('Review') >= 0",
                                            "style": {"backgroundColor": "#fff3cd", "color": "#664d03", "fontWeight": "600"},
                                        },
                                        {
                                            "condition": "params.value && params.value.indexOf('Issue') >= 0",
                                            "style": {"backgroundColor": "#f8d7da", "color": "#721c24", "fontWeight": "600"},
                                        },
                                    ],
                                },
                            },
                            # Hidden numeric companions for styleConditions
                            {"field": "classified_rate_cumul_num", "hide": True},
                            {"field": "classified_rate_latest_num", "hide": True},
                        ],
                        rowData=[],
                        defaultColDef={
                            "sortable": True,
                            "filter": True,
                            "resizable": True,
                            "minWidth": 100,
                        },
                        # Page size 25 (from 10) shows up to 24
                        # barcodes without paginating; selector
                        # lets the operator narrow or widen.
                        # ``domLayout: autoHeight`` replaces the
                        # fixed 420px container so the table grows
                        # to fit visible rows -- the operator's
                        # primary at-a-glance comparison surface
                        # stops being clipped at 12 visible rows on
                        # 1280x800 displays. Closes P1-T03 from
                        # docs/audit-2026-04-28-throughput-ux.md.
                        # ``getRowId`` keys each row by sample id so
                        # AgGrid preserves the operator's sort, filter,
                        # and any selection across the 30s interval
                        # tick that rewrites rowData. Without it the
                        # comparison surface re-renders fully every
                        # tick and the operator loses their place.
                        dashGridOptions={
                            "pagination": True,
                            "paginationPageSize": 25,
                            "paginationPageSizeSelector": [10, 25, 50, 100],
                            "tooltipShowDelay": 500,
                            "suppressMenuHide": False,
                            "domLayout": "autoHeight",
                            # Group header dominant; column header secondary
                            "headerHeight": 32,
                            "groupHeaderHeight": 38,
                            "getRowId": {"function": "params.data.sample"},
                        },
                        className="ag-theme-alpine qc-sample-breakdown-grid",
                        style={"width": "100%"},
                    ),
                    html.Small(
                        "Detailed metrics available in Technical Statistics section below.",
                        className="text-muted d-block mt-2"
                    )
                ])
            ])
        ])
    ], className="mb-4")


def _qc_detailed_plots_accordion():
    """Collapsible accordion of cumulative/per-batch processing charts."""
    # Empty placeholder plots, replaced by callbacks once data is loaded
    cumul_reads_fig = px.line(title="Cumulative DNA Sequences")
    cumul_bp_fig = px.line(title="Cumulative Base Pairs")
    reads_fig = px.bar(title="DNA Sequences per Batch")
    bp_fig = px.bar(title="Base Pairs per Batch")

    return dbc.Accordion([
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
    ], start_collapsed=True, className="mb-4")


def _qc_technical_stats_accordion():
    """Collapsible accordion of raw pipeline statistics for power users."""
    return dbc.Accordion([
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
                        html.Div(id="qc-reads-pre-filtering", children="Raw reads (pre-Chopper): —"),
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
    ], start_collapsed=True, className="mb-4")


def _qc_help_card():
    """Static 'Understanding This Page' help card."""
    return dbc.Card([
        dbc.CardHeader(html.H5("Understanding This Page", className="mb-0")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.P("Sample Breakdown columns:", className="fw-bold mb-2"),
                    html.Ul([
                        html.Li([
                            html.Strong("Cumulative — Filtered reads: "),
                            "Reads that passed quality filtering, summed across every batch since the "
                            "run started. Sourced from the Kraken2 cumulative report."
                        ]),
                        html.Li([
                            html.Strong("Cumulative — Classification rate: "),
                            "Fraction of filtered reads that Kraken2 assigned to a taxon, across the "
                            "whole run. Green ≥ 80%, amber 50–79%, red < 50% — matches the "
                            "Stage Strip thresholds."
                        ]),
                        html.Li([
                            html.Strong("Latest batch — Filtered reads / Classification rate: "),
                            "Same two metrics restricted to the most recent batch report. In batch-mode "
                            "runs these equal the cumulative values."
                        ]),
                        html.Li([
                            html.Strong("Avg. Q score: "),
                            "Mean Phred quality per post-filter read (SeqKit). For nanopore data a mean "
                            "Q ≥ 15 is typical; values below Q10 suggest a degraded flow cell."
                        ]),
                    ], className="mb-0"),
                ], md=6),
                dbc.Col([
                    html.P("Interpreting the values:", className="fw-bold mb-2"),
                    html.Ul([
                        html.Li([
                            html.Strong("Cumulative classification rate below 50%: "),
                            "Most reads did not match the reference database. Confirm the correct Kraken2 "
                            "database is configured and check sample purity."
                        ]),
                        html.Li([
                            html.Strong("Cumulative classification rate 50–79%: "),
                            "Partial coverage of the sample by the database. Results are usable but review "
                            "the unclassified fraction before drawing conclusions."
                        ]),
                        html.Li([
                            html.Strong("Latest batch rate diverges from cumulative: "),
                            "The most recent batch differs from the run so far — useful for spotting "
                            "contamination appearing late in a run."
                        ]),
                        html.Li([
                            html.Strong("Low mean Q score: "),
                            "Consider flow-cell health and library quality. Downstream identification can "
                            "still be informative; cross-check with the Validation tab."
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
    ], className="mb-4", style={"backgroundColor": "#f8f9fa"})


def _qc_help_modal():
    """Detailed QC help modal (opened from the help card)."""
    return dbc.Modal([
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
    ], id="qc-help-modal", size="lg")


def _qc_export_modal():
    """Export-plots modal (directory and filename inputs)."""
    return dbc.Modal([
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


def create_qc_layout():
    """
    Create the layout for the QC tab.

    MODERNIZED: Visual quality indicators, plain language, operator-friendly design.
    Follows visual hierarchy: score -> breakdown -> per-sample -> detailed plots.

    Returns:
        A dash component representing the QC tab layout
    """
    return html.Div([
        # Download component for QC report export
        dcc.Download(id="download-qc-report"),

        # STAGE STRIP - Pipeline overview: Raw -> Quality-filtered -> Classified
        dcc.Loading(
            id="loading-stage-strip",
            type="circle",
            color="#198754",
            children=[
                html.Div(id="qc-stage-strip", className="mb-4")
            ]
        ),

        # ACTION GUIDANCE BANNER - shown dynamically by callback
        html.Div(id="qc-action-guidance-container", className="mb-3"),

        # Read Quality and Read Length Cards (after-filtering metrics)
        *_qc_after_filtering_cards(),

        html.Hr(className="my-3"),

        # Per-Sample Quality Table
        html.H4([
            "Per-Sample Quality",
            html.Small(
                " — individual results for each barcode/sample",
                className="text-muted fw-normal",
                style={"fontSize": "14px"}
            ),
        ], className="mb-3"),
        _qc_per_sample_table(),

        # LEVEL 4: Detailed Plots (Advanced - Collapsible)
        _qc_detailed_plots_accordion(),

        # Technical Statistics (Hidden by default - for power users)
        _qc_technical_stats_accordion(),

        # Help Section
        _qc_help_card(),

        # Help modal (updated with plain language)
        _qc_help_modal(),

        # Export modal
        _qc_export_modal(),
    ], className="p-4")
