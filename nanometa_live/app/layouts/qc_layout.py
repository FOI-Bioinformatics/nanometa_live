"""
Quality Control (QC) tab layout for Nanometa Live.

This module defines the layout for the QC tab, which displays quality metrics
and processing statistics.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go


def create_qc_layout():
    """
    Create the layout for the QC tab.

    Returns:
        A dash component representing the QC tab layout
    """
    # Create empty placeholder plots
    cumul_reads_fig = px.line(title="Cumulative Reads")
    cumul_bp_fig = px.line(title="Cumulative Base Pairs")
    reads_fig = px.bar(title="Reads per Batch")
    bp_fig = px.bar(title="Base Pairs per Batch")

    return html.Div([
        dbc.Row([
            # QC statistics panel
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H4("QC Statistics")),
                    dbc.CardBody([
                        html.Div([
                            # Filtering stats
                            html.H5("FILTERING", className="font-weight-bold"),
                            html.Div(id="qc-reads-pre-filtering", children="Total reads pre-filtering: 0"),
                            html.Div(id="qc-reads-passed", children="Reads that passed filtering: 0"),
                            html.Div(id="qc-reads-removed", children="Total reads removed: 0"),

                            html.Hr(),

                            # Reasons for removal
                            html.H5("REASONS FOR REMOVAL", className="font-weight-bold"),
                            html.Div(id="qc-proportions-info", children="(percentages of total removed reads)"),
                            html.Div(id="qc-low-quality", children="Too low quality: 0 (0%)"),
                            html.Div(id="qc-too-short", children="Too short: 0 (0%)"),
                            html.Div(id="qc-low-complexity", children="Too low complexity: 0 (0%)"),

                            html.Hr(),

                            # Classification stats
                            html.H5("CLASSIFICATION", className="font-weight-bold"),
                            html.Div(id="qc-classified-reads", children="Classified reads: 0 (0%)"),
                            html.Div(id="qc-unclassified-reads", children="Unclassified reads: 0 (0%)"),

                            html.Hr(),

                            # Processing stats
                            html.H5("FILE PROCESSING", className="font-weight-bold"),
                            html.Div(id="qc-processed-files", children="Files processed: 0"),
                            html.Div(id="qc-waiting-files", children="Files awaiting processing: 0"),

                            html.Hr(),

                            # Help button
                            dbc.Button("Help", id="qc-help-button", color="info", size="sm")
                        ])
                    ])
                ], className="h-100")
            ], width=3),

            # QC plots
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H4("QC Metrics", className="d-inline"),
                        dbc.Button(
                            "Export Plots",
                            id="export-qc-button",
                            color="secondary",
                            size="sm",
                            className="float-right"
                        )
                    ]),
                    dbc.CardBody([
                        # Top row of plots
                        dbc.Row([
                            dbc.Col(
                                dcc.Graph(
                                    id="cumul-reads-graph",
                                    figure=cumul_reads_fig,
                                    config={"displayModeBar": True}
                                ),
                                width=6
                            ),
                            dbc.Col(
                                dcc.Graph(
                                    id="cumul-bp-graph",
                                    figure=cumul_bp_fig,
                                    config={"displayModeBar": True}
                                ),
                                width=6
                            )
                        ], className="mb-4"),

                        # Bottom row of plots
                        dbc.Row([
                            dbc.Col(
                                dcc.Graph(
                                    id="reads-graph",
                                    figure=reads_fig,
                                    config={"displayModeBar": True}
                                ),
                                width=6
                            ),
                            dbc.Col(
                                dcc.Graph(
                                    id="bp-graph",
                                    figure=bp_fig,
                                    config={"displayModeBar": True}
                                ),
                                width=6
                            )
                        ])
                    ])
                ], className="h-100")
            ], width=9)
        ]),

        # Help modal
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