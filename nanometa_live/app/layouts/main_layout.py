"""
Main results tab layout for Nanometa Live.

This module defines the layout for the main results tab, which displays the
species of interest and top matches from the analysis.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px


def create_main_layout():
    """
    Create the layout for the main results tab.

    Returns:
        A dash component representing the main results tab layout
    """
    # Create empty placeholder plots
    pathogen_fig = px.bar(title="Species of Interest")

    return html.Div([
        dbc.Row([
            # Species of Interest section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H4("Species of Interest", className="mb-0"),
                        dbc.Button(
                            "Export Data",
                            id="export-species-button",
                            color="secondary",
                            size="sm",
                            className="ms-2"
                        )
                    ], className="d-flex justify-content-between align-items-center"),
                    dbc.CardBody([
                        # Plot of species counts
                        dcc.Graph(
                            id="species-plot",
                            figure=pathogen_fig,
                            style={"height": "400px"}
                        ),

                        # Settings for display
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Alert Threshold:", html_for="species-threshold-input"),
                                dbc.Input(
                                    id="species-threshold-input",
                                    type="number",
                                    min=1,
                                    value=100
                                ),
                                dbc.FormText("Species with reads above this threshold will be highlighted")
                            ], width=4),
                            dbc.Col([
                                dbc.Label("Display Validation:", html_for="show-validation-input"),
                                dbc.Checklist(
                                    id="show-validation-input",
                                    options=[{"label": "Show BLAST validation", "value": "true"}],
                                    value=["true"],
                                    switch=True
                                )
                            ], width=4),
                            dbc.Col([
                                dbc.Button(
                                    "Apply",
                                    id="apply-species-settings",
                                    color="primary",
                                    className="mt-4"
                                )
                            ], width=4, className="d-flex align-items-end")
                        ], className="mt-3"),

                        # Species table
                        html.Div([
                            dash_table.DataTable(
                                id="species-table",
                                columns=[
                                    {"name": "Name", "id": "Name"},
                                    {"name": "Tax ID", "id": "Tax ID"},
                                    {"name": "Reads", "id": "Reads"}
                                ],
                                data=[],
                                style_cell={
                                    "textAlign": "left",
                                    "padding": "10px"
                                },
                                style_header={
                                    "fontWeight": "bold",
                                    "backgroundColor": "#f8f9fa"
                                },
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{Reads} > 100"},
                                        "backgroundColor": "#ffcccc"
                                    }
                                ]
                            )
                        ], className="mt-3")
                    ])
                ], className="h-100")
            ], width=6),

            # Top Matches section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H4("Top Matches", className="mb-0"),
                        dbc.Button(
                            "Export Data",
                            id="export-top-button",
                            color="secondary",
                            size="sm",
                            className="ms-2"
                        )
                    ], className="d-flex justify-content-between align-items-center"),
                    dbc.CardBody([
                        # Settings for top matches
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Number of entries:", html_for="top-entries-input"),
                                dbc.Input(
                                    id="top-entries-input",
                                    type="number",
                                    min=1,
                                    max=100,
                                    value=20
                                )
                            ], width=4),
                            dbc.Col([
                                dbc.Label("Taxonomy levels:", html_for="tax-level-input"),
                                dbc.Checklist(
                                    id="tax-level-input",
                                    options=[
                                        {"label": "Species", "value": "S"},
                                        {"label": "Genus", "value": "G"},
                                        {"label": "Family", "value": "F"},
                                        {"label": "Order", "value": "O"},
                                        {"label": "Class", "value": "C"},
                                        {"label": "Phylum", "value": "P"},
                                        {"label": "Domain", "value": "D"}
                                    ],
                                    value=["S"],
                                    inline=True
                                )
                            ], width=8)
                        ]),

                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Domains:", html_for="domains-input"),
                                dbc.Checklist(
                                    id="domains-input",
                                    options=[
                                        {"label": "Bacteria", "value": "Bacteria"},
                                        {"label": "Archaea", "value": "Archaea"},
                                        {"label": "Eukaryota", "value": "Eukaryota"},
                                        {"label": "Viruses", "value": "Viruses"}
                                    ],
                                    value=["Bacteria", "Archaea", "Eukaryota", "Viruses"],
                                    inline=True
                                )
                            ], width=9),
                            dbc.Col([
                                dbc.Button(
                                    "Apply",
                                    id="apply-top-settings",
                                    color="primary",
                                    className="mt-3"
                                )
                            ], width=3, className="d-flex align-items-end")
                        ], className="mb-3"),

                        # Top matches table
                        dash_table.DataTable(
                            id="top-table",
                            columns=[
                                {"name": "Index", "id": "Index"},
                                {"name": "Name", "id": "Name"},
                                {"name": "Tax ID", "id": "Tax ID"},
                                {"name": "Tax Rank", "id": "Tax Rank"},
                                {"name": "Reads", "id": "Reads"}
                            ],
                            data=[],
                            style_cell={
                                "textAlign": "left",
                                "padding": "10px"
                            },
                            style_header={
                                "fontWeight": "bold",
                                "backgroundColor": "#f8f9fa"
                            },
                            page_size=20
                        )
                    ])
                ], className="h-100")
            ], width=6)
        ]),

        # Export modals
        dbc.Modal([
            dbc.ModalHeader("Export Species Data"),
            dbc.ModalBody([
                dbc.Label("Filename:", html_for="species-export-filename"),
                dbc.Input(id="species-export-filename", placeholder="Enter filename", type="text")
            ]),
            dbc.ModalFooter([
                dbc.Button("Export", id="confirm-species-export", color="primary"),
                dbc.Button("Cancel", id="cancel-species-export", color="secondary")
            ])
        ], id="species-export-modal", is_open=False),

        dbc.Modal([
            dbc.ModalHeader("Export Top Matches Data"),
            dbc.ModalBody([
                dbc.Label("Filename:", html_for="top-export-filename"),
                dbc.Input(id="top-export-filename", placeholder="Enter filename", type="text")
            ]),
            dbc.ModalFooter([
                dbc.Button("Export", id="confirm-top-export", color="primary"),
                dbc.Button("Cancel", id="cancel-top-export", color="secondary")
            ])
        ], id="top-export-modal", is_open=False)
    ], className="p-4")