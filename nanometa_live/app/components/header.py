"""
Header component for Nanometa Live.

This module defines the header component that appears at the top of the application,
containing the title, status indicators, and control buttons.
"""

from dash import html
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
                        alt="Nanometa Live",
                        style={"height": "96px", "width": "auto"},
                        className="me-2",
                    ),
                    html.H2(
                        id="header-title",
                        className="mb-0 visually-hidden",
                        children=title,
                    ),
                    dbc.Badge(
                        "OFFLINE",
                        id="offline-mode-badge",
                        color="warning",
                        className="ms-2 align-self-center",
                        style={"display": "none", "fontSize": "0.7rem"}
                    ),
                ], className="d-flex align-items-center")
            ], width=4),

            # Status indicators
            dbc.Col([
                html.Div([
                    html.Div([
                        # Prominent status badge
                        html.Div([
                            daq.Indicator(
                                id="status-indicator",
                                label="",
                                color="gray",
                                value=True,
                                style={"marginRight": "8px"}
                            ),
                            html.Span(
                                id="status-text",
                                className="fw-bold",
                                children="STANDBY",
                                role="status",
                                style={"fontSize": "1.1rem", "letterSpacing": "0.5px"},
                                **{"aria-live": "polite"}
                            ),
                        ], className="d-flex align-items-center me-3"),
                        # Status detail text
                        html.Span(
                            id="status-details",
                            className="text-muted small",
                            children="Click 'Start Analysis' to begin"
                        ),
                        # Throughput tile (U1). Lives between status-details
                        # and the elapsed-time block per the 2026-05-09 UX
                        # spec; the inner content + className are owned by
                        # update_throughput_tile.
                        html.Div(
                            id="throughput-tile",
                            children=[],
                            className="throughput-tile ms-3 small text-muted",
                            role="status",
                            **{"aria-live": "polite"},
                        ),
                        # Elapsed time display (prominent when running)
                        html.Div([
                            html.I(className="bi bi-stopwatch me-1"),
                            html.Span(
                                id="elapsed-time-display",
                                children="00:00:00",
                                style={"fontSize": "1.1rem", "fontWeight": "600"}
                            ),
                        ], className="elapsed-time ms-3", id="elapsed-time-container", style={"display": "none"}),
                        # Countdown timer
                        html.Div([
                            html.I(className="bi bi-clock me-1"),
                            html.Span(id="update-countdown", children="Next: --s"),
                        ], className="update-timer ms-3", style={"fontSize": "0.85rem"}),
                        # Pipeline stage display
                        html.Div([
                            html.Span(id="current-pipeline-stage", children=""),
                            html.Span(id="pipeline-progress-text", children="", className="text-muted small ms-2")
                        ], className="pipeline-info ms-3", id="pipeline-stage-container", style={"display": "none"})
                    ], className="d-flex align-items-center flex-wrap", **{"aria-label": "Analysis status"})
                ], className="d-flex justify-content-center h-100")
            ], width=5),

            # Control buttons
            dbc.Col([
                html.Div([
                    # Readiness indicator with hover details
                    html.Div(
                        id="readiness-indicator",
                        children=[
                            dbc.Badge(
                                [html.I(className="bi bi-check-circle-fill me-1"), "Ready"],
                                id="readiness-badge",
                                color="secondary",
                                className="me-2 align-self-center",
                                pill=True,
                                style={"cursor": "pointer", "fontSize": "0.85rem"},
                            ),
                            dbc.Popover(
                                id="readiness-popover",
                                target="readiness-badge",
                                trigger="hover",
                                placement="bottom",
                                children=[
                                    dbc.PopoverHeader("Readiness Checks"),
                                    dbc.PopoverBody(
                                        id="readiness-popover-body",
                                        children="Loading...",
                                    ),
                                ],
                            ),
                        ],
                        style={"display": "inline-block"}
                    ),

                    dbc.Badge(
                        "Auto-saved",
                        id="config-status-badge",
                        color="success",
                        className="me-2 align-self-center",
                        pill=True,
                        style={"fontSize": "0.75rem", "display": "none"}
                    ),

                    dbc.Button(
                        [html.I(className="bi bi-play-fill me-2"), "Start Analysis"],
                        id="start-stop-button",
                        color="primary",
                        size="lg",
                        className="me-2"
                    ),
                    dbc.Tooltip(
                        id="start-analysis-tooltip",
                        children="Begin analysing DNA samples for organisms of interest",
                        target="start-stop-button",
                        placement="bottom"
                    )
                ], className="d-flex justify-content-end align-items-center")
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