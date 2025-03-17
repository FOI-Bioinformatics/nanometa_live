"""
Sankey plot tab layout for Nanometa Live.

This module defines the layout for the Sankey plot tab, which displays
taxonomic hierarchy in a Sankey diagram.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go


def create_sankey_layout():
    """
    Create the layout for the Sankey plot tab.

    Returns:
        A dash component representing the Sankey plot tab layout
    """
    # Create empty Sankey plot
    empty_fig = go.Figure(go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=["No data available"],
            color="blue"
        ),
        link=dict(
            source=[],
            target=[],
            value=[]
        )
    ))
    empty_fig.update_layout(title_text="Taxonomic Hierarchy - No Data", font_size=10)

    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H4("Sankey Plot Controls", className="mb-0"),
                dbc.Button(
                    "Export Plot",
                    id="export-sankey-button",
                    color="secondary",
                    size="sm",
                    className="ms-2"
                )
            ], className="d-flex justify-content-between align-items-center"),
            dbc.CardBody([
                dbc.Row([
                    # First column of controls
                    dbc.Col([
                        dbc.Label("Filter by top reads:", html_for="sankey-filter-input"),
                        dbc.Input(
                            id="sankey-filter-input",
                            type="number",
                            min=1,
                            max=50,
                            value=10,
                            className="mb-3"
                        ),
                        dbc.FormText("Number of taxa to show at each level"),

                        dbc.Label("Domains:", html_for="sankey-domains-input"),
                        dbc.Checklist(
                            id="sankey-domains-input",
                            options=[
                                {"label": "Bacteria", "value": "Bacteria"},
                                {"label": "Archaea", "value": "Archaea"},
                                {"label": "Eukaryota", "value": "Eukaryota"},
                                {"label": "Viruses", "value": "Viruses"}
                            ],
                            value=["Bacteria", "Archaea", "Eukaryota", "Viruses"],
                            className="mb-3"
                        )
                    ], width=6),

                    # Second column of controls
                    dbc.Col([
                        dbc.Label("Taxonomic levels:", html_for="sankey-levels-input"),
                        dbc.Checklist(
                            id="sankey-levels-input",
                            options=[
                                {"label": "Domain", "value": "D"},
                                {"label": "Phylum", "value": "P"},
                                {"label": "Class", "value": "C"},
                                {"label": "Order", "value": "O"},
                                {"label": "Family", "value": "F"},
                                {"label": "Genus", "value": "G"},
                                {"label": "Species", "value": "S"}
                            ],
                            value=["D", "P", "C", "O", "F", "G", "S"],
                            className="mb-3"
                        ),

                        dbc.Button(
                            "Apply",
                            id="apply-sankey-settings",
                            color="primary",
                            className="mt-4"
                        )
                    ], width=6)
                ])
            ])
        ], className="mb-4"),

        # Sankey plot
        dbc.Card([
            dbc.CardHeader(html.H4("Taxonomic Hierarchy")),
            dbc.CardBody([
                dcc.Loading(
                    id="sankey-loading",
                    type="circle",
                    children=dcc.Graph(
                        id="sankey-plot",
                        figure=empty_fig,
                        style={"height": "600px"},
                        config={
                            "displayModeBar": True,
                            "scrollZoom": True,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]
                        }
                    )
                )
            ])
        ]),

        # Export modal
        dbc.Modal([
            dbc.ModalHeader("Export Sankey Plot"),
            dbc.ModalBody([
                dbc.Label("Filename:", html_for="sankey-export-filename"),
                dbc.Input(id="sankey-export-filename", placeholder="Enter filename", type="text")
            ]),
            dbc.ModalFooter([
                dbc.Button("Export", id="confirm-sankey-export", color="primary"),
                dbc.Button("Cancel", id="cancel-sankey-export", color="secondary")
            ])
        ], id="sankey-export-modal", is_open=False)
    ], className="p-4")