"""
Configuration tab layout for Nanometa Live.

This module defines the layout for the configuration tab, which allows
users to configure the application before starting the analysis.
"""

import os
from typing import Dict, Any

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.config_form import create_config_form


def create_config_layout():
    """
    Create the layout for the configuration tab.

    Returns:
        A dash component representing the configuration tab layout
    """
    return html.Div([
        # Introduction section
        dbc.Card(
            dbc.CardBody([
                html.H3("Configuration", className="card-title"),
                html.P(
                    "Configure Nanometa Live before starting your analysis. "
                    "Fill in the required fields, save your configuration, and start the analysis.",
                    className="card-text"
                ),
                html.Hr(),

                # Configuration quick actions
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            "Load Configuration",
                            id="load-config-button",
                            color="primary",
                            className="me-2"
                        ),
                        dbc.Button(
                            "Save Configuration",
                            id="save-config-button",
                            color="success",
                            className="me-2"
                        ),
                        dbc.Button(
                            "Reset to Defaults",
                            id="reset-config-button",
                            color="warning"
                        )
                    ], width=12)
                ], className="mb-4"),

                # Config file selection modal (initially hidden)
                dbc.Modal([
                    dbc.ModalHeader("Load Configuration"),
                    dbc.ModalBody(
                        html.Div(id="load-config-list", children=[
                            # Will be populated by callback
                            html.P("Loading available configurations...")
                        ])
                    ),
                    dbc.ModalFooter([
                        dbc.Button("Close", id="close-load-config-modal", className="ms-auto")
                    ])
                ], id="load-config-modal", is_open=False),

                # Save config modal (initially hidden)
                dbc.Modal([
                    dbc.ModalHeader("Save Configuration"),
                    dbc.ModalBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Configuration Name"),
                                dbc.Input(id="save-config-name", placeholder="Enter a name for this configuration", type="text")
                            ])
                        ])
                    ]),
                    dbc.ModalFooter([
                        dbc.Button("Save", id="confirm-save-config", color="success"),
                        dbc.Button("Cancel", id="cancel-save-config", className="ms-2")
                    ])
                ], id="save-config-modal", is_open=False),

                # Config status message
                html.Div(id="config-status-message", className="mt-3")
            ]),
            className="mb-4"
        ),

        # Configuration form
        dbc.Card(
            dbc.CardBody([
                create_config_form()
            ])
        ),

        # Hidden div for storing available configs
        html.Div(id="available-configs", style={"display": "none"})
    ], className="p-4")