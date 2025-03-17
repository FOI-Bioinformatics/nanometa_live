"""
Configuration form component for Nanometa Live.

This module defines a reusable form component for configuring the application.
"""

import os
from typing import Dict, Any

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_config_form():
    """
    Create a form for configuring Nanometa Live.

    Returns:
        A dash component representing the configuration form
    """
    return html.Div([
        dbc.Tabs([
            # Basic Configuration Tab
            dbc.Tab(
                label="Basic Settings",
                tab_id="basic-tab",
                children=dbc.Form([
                    html.H4("Project Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Analysis Name", html_for="analysis-name-input"),
                                dbc.Input(
                                    id="analysis-name-input",
                                    type="text",
                                    placeholder="Enter a name for your analysis"
                                ),
                                dbc.FormText("A descriptive name for your analysis")
                            ], className="mb-3")
                        ], width=12)
                    ]),

                    html.H4("Data Directories", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Nanopore Output Directory", html_for="nanopore-dir-input"),
                                dbc.Input(
                                    id="nanopore-dir-input",
                                    type="text",
                                    placeholder="Enter path to nanopore output directory"
                                ),
                                dbc.FormText("The directory where the sequencer outputs FASTQ files (required)")
                            ], className="mb-3")
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Kraken2 Database", html_for="kraken-db-input"),
                                dbc.Input(
                                    id="kraken-db-input",
                                    type="text",
                                    placeholder="Enter path to Kraken2 database"
                                ),
                                dbc.FormText("Path to Kraken2 database directory (required)")
                            ], className="mb-3")
                        ], width=12)
                    ]),

                    html.H4("Species of Interest", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Species List", html_for="species-file-input"),
                                dcc.Upload(
                                    id="species-file-input",
                                    children=html.Div([
                                        html.A("Drag and Drop or Select a File")
                                    ]),
                                    style={
                                        "width": "100%",
                                        "height": "60px",
                                        "lineHeight": "60px",
                                        "borderWidth": "1px",
                                        "borderStyle": "dashed",
                                        "borderRadius": "5px",
                                        "textAlign": "center",
                                        "margin": "10px 0"
                                    },
                                    multiple=False
                                ),
                                dbc.FormText("A text file with one species per line (optional)")
                            ], className="mb-3")
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div(id="species-list-container")
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Add Species", id="add-species-button", color="secondary", size="sm")
                        ], width=12)
                    ])
                ])
            ),

            # Advanced Configuration Tab
            dbc.Tab(
                label="Advanced Settings",
                tab_id="advanced-tab",
                children=dbc.Form([
                    html.H4("GUI Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Update Interval (seconds)", html_for="update-interval-input"),
                                dbc.Input(
                                    id="update-interval-input",
                                    type="number",
                                    min=1,
                                    max=300,
                                    step=1,
                                    value=30
                                ),
                                dbc.FormText("How often the interface should update (1-300 seconds)")
                            ], className="mb-3")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label("Alert Threshold", html_for="danger-threshold-input"),
                                dbc.Input(
                                    id="danger-threshold-input",
                                    type="number",
                                    min=1,
                                    step=1,
                                    value=100
                                ),
                                dbc.FormText("Species with reads above this threshold will be highlighted")
                            ], className="mb-3")
                        ], width=6)
                    ]),

                    html.H4("Taxonomy Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Taxonomy Database", html_for="kraken-taxonomy-input"),
                                dbc.Select(
                                    id="kraken-taxonomy-input",
                                    options=[
                                        {"label": "GTDB", "value": "gtdb"},
                                        {"label": "NCBI", "value": "ncbi"}
                                    ],
                                    value="gtdb"
                                ),
                                dbc.FormText("Taxonomy database used by Kraken2")
                            ], className="mb-3")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label("External Kraken2 Database", html_for="external-kraken-input"),
                                dbc.Select(
                                    id="external-kraken-input",
                                    options=[
                                        {"label": "None (use local)", "value": ""},
                                        {"label": "Standard", "value": "Standard"},
                                        {"label": "PlusPF (Protozoa & Fungi)", "value": "PlusPF"},
                                        {"label": "PlusPFP (Protozoa, Fungi & Plant)", "value": "PlusPFP"},
                                        {"label": "Viral", "value": "Viral"},
                                        {"label": "MinusB", "value": "MinusB"}
                                    ],
                                    value=""
                                ),
                                dbc.FormText("Optional: download and use a predefined Kraken2 database")
                            ], className="mb-3")
                        ], width=6)
                    ]),

                    html.H4("Processing Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("Check Interval (seconds)", html_for="check-interval-input"),
                                dbc.Input(
                                    id="check-interval-input",
                                    type="number",
                                    min=1,
                                    max=300,
                                    step=1,
                                    value=15
                                ),
                                dbc.FormText("How often to check for new input files (1-300 seconds)")
                            ], className="mb-3")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label("Memory Mapping", html_for="memory-mapping-input"),
                                dbc.Switch(
                                    id="memory-mapping-input",
                                    label="Use memory mapping for Kraken2",
                                    value=True
                                ),
                                dbc.FormText("Use memory mapping to reduce RAM usage (slower)")
                            ], className="mb-3")
                        ], width=6)
                    ]),

                    html.H4("Validation Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("BLAST Validation", html_for="blast-validation-input"),
                                dbc.Switch(
                                    id="blast-validation-input",
                                    label="Enable BLAST validation",
                                    value=True
                                ),
                                dbc.FormText("Validate species hits using BLAST")
                            ], className="mb-3")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label("Validation Threshold", html_for="min-identity-input"),
                                dbc.Input(
                                    id="min-identity-input",
                                    type="number",
                                    min=50,
                                    max=100,
                                    step=1,
                                    value=90
                                ),
                                dbc.FormText("Minimum percent identity for BLAST validation (50-100)")
                            ], className="mb-3")
                        ], width=6)
                    ]),

                    html.H4("Performance Settings", className="mt-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label("CPU Cores", html_for="cores-input"),
                                dbc.Input(
                                    id="cores-input",
                                    type="number",
                                    min=1,
                                    step=1,
                                    value=1
                                ),
                                dbc.FormText("Number of CPU cores to use for processing")
                            ], className="mb-3")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label("Clean Temporary Files", html_for="clean-temp-input"),
                                dbc.Switch(
                                    id="clean-temp-input",
                                    label="Remove temporary files after processing",
                                    value=True
                                ),
                                dbc.FormText("Remove temporary files to save disk space")
                            ], className="mb-3")
                        ], width=6)
                    ])
                ])
            )
        ], id="config-form-tabs")
    ])