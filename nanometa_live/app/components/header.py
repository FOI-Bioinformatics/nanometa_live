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
        # Notification store is defined in main app.py to avoid duplication

        dbc.Row([
            # Title and logo
            dbc.Col([
                html.Div([
                    html.Img(
                        src="/assets/logo.png",
                        height="40px",
                        className="me-2",
                        alt="Nanometa Live logo"
                    ),
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
                        html.Span(
                            id="status-text",
                            className="ms-2",
                            children="Idle",
                            role="status",
                            **{"aria-live": "polite"}
                        ),
                        html.Span(" - ", **{"aria-hidden": "true"}),
                        html.Span(id="status-details", className="text-muted", children="Click 'Start Analysis' to begin"),
                        # Countdown timer
                        html.Div([
                            html.I(className="bi bi-clock me-1"),
                            html.Span(id="update-countdown", children="Next: --s"),
                        ], className="update-timer ms-3", style={"fontSize": "0.9rem"}),
                        # Elapsed time display
                        html.Div([
                            html.I(className="bi bi-stopwatch me-1"),
                            html.Span(id="elapsed-time-display", children="00:00:00"),
                        ], className="elapsed-time ms-3", id="elapsed-time-container", style={"display": "none"}),
                        # Pipeline stage display
                        html.Div([
                            html.Span(id="current-pipeline-stage", children=""),
                            html.Span(id="pipeline-progress-text", children="", className="text-muted small ms-2")
                        ], className="pipeline-info ms-3", id="pipeline-stage-container", style={"display": "none"})
                    ], className="d-flex align-items-center", **{"aria-label": "Analysis status"})
                ], className="d-flex justify-content-center h-100")
            ], width=5),

            # Control buttons
            dbc.Col([
                html.Div([
                    html.Div(
                        id="prepare-data-wrapper",
                        children=[
                            dbc.Button(
                                [html.I(className="bi bi-shield-check me-1"), "Setup Validation"],
                                id="prepare-data-button",
                                color="info",
                                className="me-2"
                            ),
                            dbc.Tooltip(
                                id="prepare-data-tooltip",
                                children="Download reference genomes and build BLAST databases for read validation",
                                target="prepare-data-button",
                                placement="bottom"
                            ),
                        ],
                        style={"display": "inline-block"}
                    ),

                    dbc.Button(
                        "Start Analysis",
                        id="start-stop-button",
                        color="primary",
                        className="me-2"
                    ),
                    dbc.Tooltip(
                        id="start-analysis-tooltip",
                        children="Begin processing the nanopore sequence data",
                        target="start-stop-button",
                        placement="bottom"
                    )
                ], className="d-flex justify-content-end")
            ], width=3)
        ], className="py-3 border-bottom"),

        # Stop Analysis Confirmation Modal
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle([
                    html.I(className="bi bi-exclamation-triangle-fill text-warning me-2"),
                    "Stop Analysis?"
                ]),
                close_button=True
            ),
            dbc.ModalBody(
                "Are you sure you want to stop the analysis? "
                "This will terminate the running pipeline."
            ),
            dbc.ModalFooter([
                dbc.Button(
                    "Cancel",
                    id="cancel-stop-analysis",
                    color="secondary",
                    className="me-2"
                ),
                dbc.Button(
                    [html.I(className="bi bi-stop-fill me-2"), "Stop Analysis"],
                    id="confirm-stop-analysis",
                    color="danger"
                ),
            ])
        ], id="stop-confirm-modal", is_open=False, centered=True),

        # Notification area
        html.Div(
            id="notification-container",
            className="position-fixed",
            role="alert",
            **{"aria-live": "assertive"},
            style={
                "top": "20px",
                "right": "20px",
                "maxWidth": "400px",
                "zIndex": "1000"
            }
        )
    ], className="header mb-4", role="banner")