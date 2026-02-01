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
        # Hidden Store for refresh trigger
        dcc.Store(id="refresh-form-trigger", data=False),

        # Configuration Status Banner - Shows source and modified state
        html.Div(
            id="config-status-banner",
            className="config-status-banner mb-3",
            children=[
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            # Config source indicator
                            html.Span([
                                html.I(className="bi bi-file-earmark-code me-2"),
                                html.Strong("Current Configuration: "),
                                html.Span(id="config-source-display", children="Default Configuration"),
                            ], className="config-source-info"),
                            # Modified badge (hidden by default)
                            dbc.Badge(
                                "Modified",
                                id="config-modified-badge",
                                color="warning",
                                className="ms-2",
                                style={"display": "none"}
                            ),
                            # Saved indicator
                            dbc.Badge(
                                "Saved",
                                id="config-saved-badge",
                                color="success",
                                className="ms-2",
                                style={"display": "inline"}
                            ),
                        ], className="d-flex align-items-center")
                    ], md=8),
                    dbc.Col([
                        # Config file path (truncated)
                        html.Small(
                            id="config-path-display",
                            children="",
                            className="text-muted text-truncate d-block",
                            style={"maxWidth": "300px"}
                        )
                    ], md=4, className="text-end")
                ], className="align-items-center")
            ]
        ),

        # Introduction section
        dbc.Card(
            dbc.CardBody([
                html.H3("Configuration", className="card-title"),
                html.P(
                    "Configure Nanometa Live before starting your analysis. "
                    "Fill in the required fields, save your configuration, and start the analysis.",
                    className="card-text text-muted"
                ),
                html.Hr(),

                # Configuration quick actions with clear visual hierarchy
                dbc.Row([
                    # Primary action (most important) - Use These Settings
                    dbc.Col([
                        dbc.Button([
                            html.I(className="bi bi-play-circle-fill me-2"),
                            "Use These Settings"
                        ],
                            id="apply-config-button",
                            color="success",
                            size="lg",
                            className="w-100"
                        ),
                        dbc.Tooltip(
                            "Apply these settings and start/continue the analysis",
                            target="apply-config-button",
                            placement="bottom"
                        )
                    ], md=4, className="mb-2"),

                    # Secondary actions (grouped)
                    dbc.Col([
                        html.Div([
                            # Load button
                            dbc.Button([
                                html.I(className="bi bi-folder2-open me-1"),
                                "Load"
                            ],
                                id="load-config-button",
                                color="secondary",
                                outline=True,
                                className="me-2"
                            ),
                            dbc.Tooltip(
                                "Load a previously saved configuration",
                                target="load-config-button",
                                placement="bottom"
                            ),

                            # Save button
                            dbc.Button([
                                html.I(className="bi bi-save me-1"),
                                "Save for Later"
                            ],
                                id="save-config-button",
                                color="secondary",
                                outline=True,
                                className="me-2"
                            ),
                            dbc.Tooltip(
                                "Save these settings to use again next time",
                                target="save-config-button",
                                placement="bottom"
                            ),

                            # Reset button
                            dbc.Button([
                                html.I(className="bi bi-arrow-counterclockwise me-1"),
                                "Reset"
                            ],
                                id="reset-config-button",
                                color="secondary",
                                outline=True
                            ),
                            dbc.Tooltip(
                                "Reset all settings to default values",
                                target="reset-config-button",
                                placement="bottom"
                            )
                        ], className="d-flex align-items-center justify-content-end")
                    ], md=8, className="mb-2 d-flex align-items-center")
                ], className="mb-3"),

                # Simplified explanation
                html.Small([
                    html.I(className="bi bi-info-circle me-1 text-muted"),
                    html.Span("Click 'Use These Settings' to apply. Use 'Save for Later' to keep settings for future sessions.", className="text-muted")
                ], className="d-block mb-0"),

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

                # Folder browser modal (simplified)
                dbc.Modal([
                    dbc.ModalHeader("Select Directory"),
                    dbc.ModalBody([
                        dcc.Store(id="current-browse-path", data=os.path.expanduser("~")),
                        dcc.Store(id="browse-target-field", data=None),
                        html.Div([
                            # Path input with navigation
                            dbc.InputGroup([
                                dbc.InputGroupText(html.I(className="bi bi-folder2")),
                                dbc.Input(
                                    id="current-path-display",
                                    type="text",
                                    value=os.path.expanduser("~"),
                                    placeholder="Type path or browse..."
                                ),
                                dbc.Button(
                                    html.I(className="bi bi-house"),
                                    id="quick-home",
                                    color="secondary",
                                    outline=True,
                                    title="Go to home directory"
                                ),
                                dbc.Button(
                                    html.I(className="bi bi-arrow-up"),
                                    id="browse-parent-dir",
                                    color="secondary",
                                    outline=True,
                                    title="Go to parent directory"
                                ),
                            ], className="mb-3"),

                            # Directory tree
                            html.Div(id="directory-tree", style={
                                "maxHeight": "400px",
                                "overflowY": "auto",
                                "border": "1px solid #dee2e6",
                                "borderRadius": "0.25rem",
                                "padding": "0.5rem",
                                "backgroundColor": "#f8f9fa"
                            }),

                            # Hidden buttons for backward compatibility
                            html.Div([
                                html.Button(id="quick-desktop", style={"display": "none"}),
                                html.Button(id="quick-documents", style={"display": "none"}),
                                html.Button(id="quick-root", style={"display": "none"}),
                                html.Button(id="use-current-dir", style={"display": "none"}),
                            ], style={"display": "none"}),
                        ])
                    ]),
                    dbc.ModalFooter([
                        dbc.Button(
                            [html.I(className="bi bi-check-lg me-1"), "Select"],
                            id="confirm-directory-select",
                            color="primary"
                        ),
                        dbc.Button(
                            "Cancel",
                            id="cancel-directory-select",
                            color="secondary",
                            outline=True,
                            className="ms-2"
                        )
                    ])
                ], id="folder-browser-modal", is_open=False, size="md"),

                # Config status message
                html.Div(id="config-status-message", className="mt-3")
            ]),
            className="mb-4"
        ),

        # Configuration form
        dbc.Card(
            dbc.CardBody([
                # Configuration feedback alert - shows when changes are applied
                dbc.Alert(
                    "Configuration changes have been applied",
                    id="config-feedback-alert",
                    color="success",
                    dismissable=True,
                    is_open=False,
                    duration=3000
                ),
                create_config_form()
            ])
        ),

        # Hidden div for storing available configs
        html.Div(id="available-configs", style={"display": "none"})
    ], className="p-4")