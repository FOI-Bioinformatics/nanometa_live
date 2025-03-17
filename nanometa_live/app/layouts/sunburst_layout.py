"""
Sunburst chart tab layout for Nanometa Live.

This module defines the layout for the Sunburst chart tab, which displays
taxonomic hierarchy in a radial visualization.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd


def create_sunburst_layout():
    """
    Create the layout for the Sunburst chart tab.

    Returns:
        A dash component representing the Sunburst chart tab layout
    """
    # Create empty sunburst chart
    empty_df = pd.DataFrame({
        "Taxon": ["root", "No Data"],
        "Parent": ["", "root"],
        "Reads": [0, 0]
    })
    empty_fig = px.sunburst(
        empty_df,
        names="Taxon",
        parents="Parent",
        values="Reads",
        title="Taxonomic Hierarchy - No Data"
    )

    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H4("Sunburst Chart Controls", className="mb-0"),
                dbc.Button(
                    "Export Chart",
                    id="export-sunburst-button",
                    color="secondary",
                    size="sm",
                    className="ms-2"
                )
            ], className="d-flex justify-content-between align-items-center"),
            dbc.CardBody([
                dbc.Row([
                    # First column of controls
                    dbc.Col([
                        dbc.Label("Filter by minimum reads:", html_for="sunburst-filter-input"),
                        dbc.Input(
                            id="sunburst-filter-input",
                            type="number",
                            min=1,
                            value=10,
                            className="mb-3"
                        ),
                        dbc.FormText("Only include taxa with at least this many reads")
                    ], width=6),

                    # Second column of controls
                    dbc.Col([
                        dbc.Label("Domains:", html_for="sunburst-domains-input"),
                        dbc.Checklist(
                            id="sunburst-domains-input",
                            options=[
                                {"label": "Bacteria", "value": "Bacteria"},
                                {"label": "Archaea", "value": "Archaea"},
                                {"label": "Eukaryota", "value": "Eukaryota"},
                                {"label": "Viruses", "value": "Viruses"}
                            ],
                            value=["Bacteria", "Archaea", "Eukaryota", "Viruses"],
                            className="mb-3"
                        ),

                        dbc.Button(
                            "Apply",
                            id="apply-sunburst-settings",
                            color="primary",
                            className="mt-2"
                        )
                    ], width=6)
                ])
            ])
        ], className="mb-4"),

        # Sunburst chart
        dbc.Card([
            dbc.CardHeader(html.H4("Taxonomic Hierarchy")),
            dbc.CardBody([
                dcc.Loading(
                    id="sunburst-loading",
                    type="circle",
                    children=dcc.Graph(
                        id="sunburst-chart",
                        figure=empty_fig,
                        style={"height": "700px"},
                        config={
                            "displayModeBar": True,
                            "scrollZoom": True
                        }
                    )
                )
            ])
        ]),

        # Export modal
        dbc.Modal([
            dbc.ModalHeader("Export Sunburst Chart"),
            dbc.ModalBody([
                dbc.Label("Filename:", html_for="sunburst-export-filename"),
                dbc.Input(id="sunburst-export-filename", placeholder="Enter filename", type="text")
            ]),
            dbc.ModalFooter([
                dbc.Button("Export", id="confirm-sunburst-export", color="primary"),
                dbc.Button("Cancel", id="cancel-sunburst-export", color="secondary")
            ])
        ], id="sunburst-export-modal", is_open=False),

        # Help modal
        dbc.Modal([
            dbc.ModalHeader("Sunburst Chart Help"),
            dbc.ModalBody([
                html.P([
                    "The sunburst chart shows a hierarchical view of the taxonomic data, with the ",
                    "highest taxonomic levels (domains) at the center and more specific levels ",
                    "radiating outward."
                ]),
                html.P([
                    "Click on any segment to zoom in on that taxonomic level. Click the center ",
                    "to zoom back out."
                ]),
                html.P([
                    "The colors represent the number of reads, with darker colors indicating ",
                    "higher read counts."
                ]),
                html.P([
                    "Hover over segments to see details about the taxonomy and read counts."
                ])
            ]),
            dbc.ModalFooter(
                dbc.Button("Close", id="close-sunburst-help", className="ms-auto")
            )
        ], id="sunburst-help-modal", size="lg")
    ], className="p-4")