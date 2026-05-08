"""
Configuration tab layout for Nanometa Live.

This module defines the layout for the configuration tab, which allows
users to configure the application before starting the analysis.
"""

import os

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.config_form import create_config_form
from nanometa_live.app.components.modern_components import WorkflowStepper


def create_config_layout():
    """
    Create the layout for the configuration tab.

    Returns:
        A dash component representing the configuration tab layout
    """
    return html.Div([
        # Hidden Store for refresh trigger
        dcc.Store(id="refresh-form-trigger", data=False),
        # Track whether form has been initialized (to suppress initial "Modified" badge)
        dcc.Store(id="config-form-initialized", data=False),

        # Workflow step indicator
        WorkflowStepper(active_step=1),

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
                            # Config state indicator (Default / Saved)
                            dbc.Badge(
                                "Default",
                                id="config-saved-badge",
                                color="secondary",
                                className="ms-2",
                                style={"display": "inline"}
                            ),
                        ], className="d-flex align-items-center")
                    ], md=8),
                    dbc.Col([
                        # Full absolute path of the loaded config file.
                        # text-break wraps long paths cleanly within
                        # the column rather than truncating with an
                        # ellipsis (operators need to read the path
                        # to disambiguate between multiple loaded
                        # configs). text-end keeps the right-alignment.
                        html.Small(
                            id="config-path-display",
                            children="",
                            className="text-muted text-break d-block",
                            style={"wordBreak": "break-all"},
                        )
                    ], md=4, className="text-end")
                ], className="align-items-center")
            ]
        ),

        # Introduction section
        dbc.Card(
            dbc.CardBody([
                html.Div([
                    html.I(className="bi bi-gear-fill me-2",
                           style={"fontSize": "1.3rem"}),
                    html.H4("Configuration", className="card-title mb-0 d-inline"),
                ], className="d-flex align-items-center mb-2"),
                html.P(
                    "Tell the system where your sequencing data is and where to find the "
                    "species database. Most users only need to fill in the two required fields "
                    "below -- everything else has sensible defaults.",
                    className="card-text text-muted small"
                ),
                dbc.Alert([
                    html.I(className="bi bi-lightbulb me-2"),
                    html.Strong("Tip: "),
                    "If this is your first time, just set the ",
                    html.Strong("Nanopore Sequence Data Folder (input)"),
                    " and the ",
                    html.Strong("Species Identification Database"),
                    ", then click ",
                    html.Strong("Apply Settings"),
                    " at the bottom.",
                ], color="info", className="small py-2 mb-0", dismissable=True),
                html.Hr(),

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
                html.Div(id="config-status-message", className="mt-3"),

                # Reset confirmation modal
                dbc.Modal([
                    dbc.ModalHeader([
                        html.I(className="bi bi-exclamation-triangle-fill text-warning me-2"),
                        dbc.ModalTitle("Reset All Settings?"),
                    ]),
                    dbc.ModalBody([
                        html.P(
                            "This will discard all your current settings and restore "
                            "factory defaults. Any unsaved changes will be lost."
                        ),
                        html.P(
                            "Saved presets will not be affected.",
                            className="text-muted small mb-0"
                        ),
                    ]),
                    dbc.ModalFooter([
                        dbc.Button(
                            "Cancel",
                            id="reset-config-cancel",
                            color="secondary",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-arrow-counterclockwise me-1"),
                             "Reset to Defaults"],
                            id="reset-config-confirm",
                            color="warning",
                        ),
                    ]),
                ], id="reset-config-modal", is_open=False, centered=True),
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
        html.Div(id="available-configs", style={"display": "none"}),

        # Configuration action buttons (below form)
        dbc.Card(
            dbc.CardBody([
                dbc.Row([
                    # Primary action - Apply Settings
                    dbc.Col([
                        dbc.Button([
                            html.I(className="bi bi-check-circle-fill me-2"),
                            "Apply Settings"
                        ],
                            id="apply-config-button",
                            color="success",
                            size="lg",
                            className="w-100"
                        ),
                        dbc.Tooltip(
                            "Apply these settings and start/continue the analysis",
                            target="apply-config-button",
                            placement="top"
                        )
                    ], md=4, className="mb-2"),

                    # Secondary actions
                    dbc.Col([
                        html.Div([
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
                                placement="top"
                            ),
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
                                "Save these settings as a named preset you can load later",
                                target="save-config-button",
                                placement="top"
                            ),
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
                                placement="top"
                            )
                        ], className="d-flex align-items-center justify-content-end")
                    ], md=8, className="mb-2 d-flex align-items-center")
                ]),
                html.Small([
                    html.I(className="bi bi-info-circle me-1 text-muted"),
                    html.Span(
                        "Click 'Apply Settings' to use these parameters. "
                        "Settings are saved automatically and restored on next launch. "
                        "Use 'Save for Later' to store named presets.",
                        className="text-muted",
                    )
                ], className="d-block mt-2 mb-0"),
            ]),
            className="mb-4"
        ),

        # Storage Locations panel. Surfaces the absolute path of every
        # zone Nanometa Live writes to under data_dir (default:
        # ~/.nanometa) plus the genome cache. The "Open" button on
        # each row launches the OS file manager via the helper at
        # app/utils/file_manager_open.py. Read-only display this
        # round; migration to a non-dot-prefixed default is deferred
        # so existing operator data (genomes, BLAST DBs that took
        # hours to build) is not disturbed.
        dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.I(className="bi bi-folder2-open me-2"),
                        html.Strong("Storage Locations"),
                        html.Small(
                            " - where Nanometa Live keeps your data on this computer",
                            className="text-muted ms-2",
                        ),
                    ], className="d-flex align-items-center"),
                ),
                dbc.CardBody(
                    html.Div(id="storage-locations-table"),
                ),
            ],
            className="mb-4",
        ),

        # Next step navigation
        html.Div([
            html.Hr(className="my-4"),
            html.Div([
                dbc.Button([
                    "Next: Set up Watchlist ",
                    html.I(className="bi bi-arrow-right ms-1"),
                ],
                    id="config-next-watchlist-btn",
                    color="primary",
                    outline=True,
                    size="lg",
                ),
            ], className="text-end"),
        ]),
    ], className="p-4")
