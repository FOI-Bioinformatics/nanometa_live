"""
Header component for Nanometa Live.

This module defines the header component that appears at the top of the application,
containing the title, status indicators, and control buttons.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_daq as daq


def create_header(title="Nanometa Live"):
    """
    Create the header component for the Nanometa Live application.

    Args:
        title: Title to display in the header

    Returns:
        A dash component representing the header
    """
    return html.Div([
        # Hidden notification store
        dcc.Store(id="notification-trigger", data=None),

        dbc.Row([
            # Title and logo
            dbc.Col([
                html.Div([
                    html.Img(src="/assets/logo.png", height="40px", className="me-2"),
                    html.H2(id="header-title", className="mb-0", children=title)
                ], className="d-flex align-items-center")
            ], width=4),

            # Status indicators
            dbc.Col([
                html.Div([
                    html.Div([
                        daq.Indicator(
                            id="status-indicator",
                            label="Status",
                            color="gray",
                            value=True
                        ),
                        html.Span(id="status-text", className="ms-2", children="Idle"),
                        html.Span(" - "),
                        html.Span(id="status-details", className="text-muted", children="Click 'Start Analysis' to begin")
                    ], className="d-flex align-items-center")
                ], className="d-flex justify-content-center h-100")
            ], width=5),

            # Control buttons
            dbc.Col([
                html.Div([
                    dbc.Button(
                        "Prepare Data",
                        id="prepare-data-button",
                        color="info",
                        className="me-2"
                    ),
                    dbc.Tooltip(
                        "Extract taxonomy IDs and prepare validation databases",
                        target="prepare-data-button",
                        placement="bottom"
                    ),

                    dbc.Button(
                        "Start Analysis",
                        id="start-stop-button",
                        color="primary",
                        className="me-2"
                    ),
                    dbc.Tooltip(
                        "Begin processing the nanopore sequence data",
                        target="start-stop-button",
                        placement="bottom"
                    )
                ], className="d-flex justify-content-end")
            ], width=3)
        ], className="py-3 border-bottom"),

        # Notification area
        html.Div(
            id="notification-container",
            className="position-fixed",
            style={
                "top": "20px",
                "right": "20px",
                "maxWidth": "400px",
                "zIndex": "1000"
            }
        )
    ], className="header mb-4")