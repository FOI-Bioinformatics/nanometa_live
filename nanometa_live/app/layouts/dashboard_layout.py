"""
Overview Dashboard layout for non-technical operators.

This module defines the main dashboard layout optimized for first responders
and laboratory personnel. Features plain language, traffic light coloring,
and at-a-glance status information.

MODERNIZED: Simplified metrics, large traffic light status, prominent alerts,
operator-friendly sample table.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from nanometa_live.app.components.modern_components import (
    StatusCard,
    StatCard,
    SampleStatusBadge,
    AlertListItem,
    EmptyStateMessage,
    LastUpdatedBadge,
    QualityScoreBadge,
    N50Badge,
    ClassificationRateBadge,
    MetricsRow,
    TABLE_STYLE_CELL,
    TABLE_STYLE_HEADER,
    status_conditional_style,
)
from nanometa_live.app.components.pathogen_alert import (
    PathogenAlertPanel,
    ThreatSummaryIndicator
)
from nanometa_live.app.components.watchlist_manager_ui import (
    create_watchlist_stats_card
)
from nanometa_live.app.components.watchlist_modal import create_all_modals


def create_dashboard_layout():
    """
    Create the overview dashboard layout for non-technical users.

    Layout includes:
    - Run status banner (large traffic light indicator)
    - Key metrics grid (4 stat cards)
    - Quality metrics badges
    - Sample status table
    - Alert panel
    - Pathogen report modal

    Returns:
        html.Div containing the complete dashboard layout
    """
    return html.Div([
        # Hidden stores for dashboard state
        dcc.Store(id='dashboard-data-cache', data={}),
        dcc.Store(id='pathogen-report-data', data={}),
        dcc.Store(id='dashboard-last-updated', data=None),

        # Pathogen Report Modal
        dbc.Modal([
            dbc.ModalHeader([
                dbc.ModalTitle([
                    html.I(className="bi bi-file-medical me-2"),
                    html.Span(id="pathogen-modal-title", children="Pathogen Report")
                ]),
            ], close_button=True),
            dbc.ModalBody([
                # Threat level banner
                html.Div(id="pathogen-modal-threat-banner", className="mb-3"),

                # Main pathogen info
                dbc.Row([
                    dbc.Col([
                        html.H4(id="pathogen-modal-name", className="mb-1"),
                        html.P(id="pathogen-modal-common-name", className="text-muted mb-2"),
                        dbc.Badge(id="pathogen-modal-category", color="secondary", className="me-2"),
                        dbc.Badge(id="pathogen-modal-bsl", color="info"),
                    ], md=8),
                    dbc.Col([
                        html.Div([
                            html.H2(id="pathogen-modal-reads", className="mb-0 text-primary"),
                            html.Small("sequences detected", className="text-muted")
                        ], className="text-center")
                    ], md=4)
                ], className="mb-4"),

                # Detection details
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-bar-chart me-2"),
                        html.Strong("Detection Details")
                    ]),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Abundance", className="text-muted small"),
                                html.H5(id="pathogen-modal-abundance")
                            ], md=4),
                            dbc.Col([
                                html.Label("Confidence", className="text-muted small"),
                                html.H5(id="pathogen-modal-confidence")
                            ], md=4),
                            dbc.Col([
                                html.Label("Taxonomy ID", className="text-muted small"),
                                html.H5(id="pathogen-modal-taxid")
                            ], md=4),
                        ])
                    ])
                ], className="mb-3"),

                # Action required
                dbc.Alert([
                    html.H5([
                        html.I(className="bi bi-exclamation-diamond me-2"),
                        "Recommended Action"
                    ], className="alert-heading"),
                    html.P(id="pathogen-modal-action", className="mb-0")
                ], id="pathogen-modal-action-alert", color="warning", className="mb-3"),

                # Notes
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-journal-text me-2"),
                        html.Strong("Additional Information")
                    ]),
                    dbc.CardBody([
                        html.P(id="pathogen-modal-notes", className="mb-0")
                    ])
                ], className="mb-3"),

                # Reference links
                html.Div([
                    html.Label("References", className="text-muted small d-block mb-2"),
                    html.A(
                        [html.I(className="bi bi-box-arrow-up-right me-1"), "NCBI Taxonomy"],
                        id="pathogen-modal-ncbi-link",
                        href="#",
                        target="_blank",
                        className="btn btn-outline-secondary btn-sm me-2"
                    ),
                    html.A(
                        [html.I(className="bi bi-box-arrow-up-right me-1"), "CDC Information"],
                        href="https://www.cdc.gov/niosh/topics/emres/chemagent.html",
                        target="_blank",
                        className="btn btn-outline-secondary btn-sm"
                    )
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button(
                    [html.I(className="bi bi-check-lg me-2"), "Acknowledge Alert"],
                    id="pathogen-modal-acknowledge",
                    color="success",
                    className="me-2"
                ),
                dbc.Button(
                    [html.I(className="bi bi-printer me-2"), "Print Report"],
                    id="pathogen-modal-print",
                    color="secondary",
                    outline=True,
                    className="me-2"
                ),
                dbc.Button("Close", id="pathogen-modal-close", color="secondary")
            ])
        ], id="pathogen-report-modal", size="lg", is_open=False),

        # Top Status Banner (Large Traffic Light)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            # Large Traffic Light Status Indicator (Enhanced for accessibility)
                            dbc.Col([
                                html.Div([
                                    # Status circle (large traffic light) - 100px for visibility
                                    html.Div(
                                        id="dashboard-status-indicator",
                                        className="dashboard-traffic-light status-idle",
                                        **{"aria-hidden": "true"},
                                        children=[
                                            html.I(
                                                id="dashboard-status-icon",
                                                className="bi bi-pause-circle",
                                                style={"fontSize": "48px", "color": "white"}
                                            )
                                        ]
                                    ),
                                    # Accessible text label below traffic light (for colorblind users)
                                    html.Div(
                                        id="dashboard-status-label",
                                        children=[
                                            html.Span(
                                                id="dashboard-status-label-text",
                                                children="IDLE",
                                                className="fw-bold",
                                                style={"fontSize": "14px"}
                                            ),
                                            html.I(
                                                id="dashboard-status-label-icon",
                                                className="bi bi-pause-fill ms-1",
                                                style={"fontSize": "14px"}
                                            )
                                        ],
                                        className="text-center mt-2 text-muted"
                                    )
                                ], className="d-flex flex-column align-items-center")
                            ], md=2, className="d-flex align-items-center justify-content-center"),

                            # Status Text
                            dbc.Col([
                                html.H3(
                                    id="dashboard-status-text",
                                    children="System Idle",
                                    className="mb-1",
                                    role="status",
                                    **{"aria-live": "polite"}
                                ),
                                html.P(
                                    id="dashboard-status-subtitle",
                                    children="Click 'Start Analysis' in Configuration to begin",
                                    className="text-muted mb-0",
                                    style={"fontSize": "16px"}
                                ),
                                # Progress bar (hidden when idle)
                                html.Div(
                                    id="dashboard-progress-container",
                                    children=[
                                        dbc.Progress(
                                            id="dashboard-progress-bar",
                                            value=0,
                                            striped=True,
                                            animated=True,
                                            className="mt-2",
                                            style={"height": "8px"}
                                        )
                                    ],
                                    style={"display": "none"}
                                )
                            ], md=6),

                            # Time and File Count
                            dbc.Col([
                                dbc.Row([
                                    dbc.Col([
                                        html.Div([
                                            html.I(className="bi bi-clock me-2", style={"fontSize": "20px"}),
                                            html.Span("Elapsed", className="text-muted d-block small"),
                                            html.H4(
                                                id="dashboard-time-elapsed",
                                                children="00:00:00",
                                                className="mb-0"
                                            )
                                        ], className="text-center")
                                    ], width=6),
                                    dbc.Col([
                                        html.Div([
                                            html.I(className="bi bi-file-earmark-text me-2", style={"fontSize": "20px"}),
                                            html.Span("Files Processed", className="text-muted d-block small"),
                                            html.H4(
                                                id="dashboard-files-processed",
                                                children="0 / 0",
                                                className="mb-0"
                                            )
                                        ], className="text-center")
                                    ], width=6)
                                ])
                            ], md=4)
                        ], className="align-items-center")
                    ])
                ], id="dashboard-status-card", className="mb-4", style={"borderWidth": "3px"})
            ], width=12)
        ]),

        # Pathogen Alert Banner (appears when dangerous pathogens detected)
        dbc.Row([
            dbc.Col([
                html.Div(
                    id="dashboard-pathogen-alert-container",
                    children=[
                        # Pathogen alerts will be dynamically inserted here
                        # Initially empty - populated by callback when threats detected
                    ],
                    style={"display": "none"},  # Hidden until threats detected
                    role="alert",
                    **{"aria-live": "assertive"}
                )
            ], width=12)
        ], id="pathogen-alert-row", className="mb-0"),

        # Threat Summary Section (always visible - shows current threat status)
        dbc.Row([
            # Threat Status Indicator
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            # Large threat indicator icon
                            html.Div(
                                id="dashboard-threat-indicator",
                                children=[
                                    html.I(
                                        id="dashboard-threat-icon",
                                        className="bi bi-shield-check",
                                        style={"fontSize": "48px", "color": "#28a745"}
                                    )
                                ],
                                className="mb-2"
                            ),
                            html.H4(
                                id="dashboard-threat-status",
                                children="ALL CLEAR",
                                className="mb-1",
                                role="status",
                                **{"aria-live": "polite"}
                            ),
                            html.P(
                                id="dashboard-threat-subtitle",
                                children="No dangerous pathogens detected",
                                className="text-muted mb-0 small"
                            )
                        ], className="text-center")
                    ], className="py-3")
                ], id="dashboard-threat-card", className="h-100", style={"borderColor": "#28a745", "borderWidth": "2px"})
            ], md=3, className="mb-3"),

            # Pathogen Detection Summary
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.I(className="bi bi-biohazard me-2", style={"color": "#dc3545"}),
                            html.H6("Pathogen Screening", className="mb-0 d-inline")
                        ])
                    ], className="py-2"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-pathogen-summary",
                            type="circle",
                            color="#dc3545",
                            children=[
                                html.Div(
                                    id="dashboard-pathogen-summary",
                                    children=[
                                        html.Div([
                                            html.I(className="bi bi-hourglass text-muted me-2"),
                                            html.Span("Waiting for classification data...", className="text-muted")
                                        ], className="text-center py-2")
                                    ]
                                )
                            ]
                        )
                    ], className="py-2")
                ], className="h-100")
            ], md=5, className="mb-3"),

            # Classification Summary Donut
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.I(className="bi bi-pie-chart me-2"),
                            html.H6("Classification", className="mb-0 d-inline")
                        ])
                    ], className="py-2"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-classification-donut",
                            type="circle",
                            color="#0d6efd",
                            children=[
                                dcc.Graph(
                                    id="dashboard-classification-donut",
                                    config={"displayModeBar": False},
                                    style={"height": "180px"}
                                )
                            ]
                        )
                    ], className="py-1")
                ], className="h-100")
            ], md=4, className="mb-3")
        ], className="mb-3"),

        # Pipeline Stages Progress (Nextflow workflow stages)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.I(className="bi bi-diagram-3 me-2"),
                            html.H5("Pipeline Stages", className="mb-0 d-inline"),
                            html.Span(
                                id="dashboard-current-stage",
                                children="",
                                className="ms-2 text-muted small"
                            )
                        ])
                    ]),
                    dbc.CardBody([
                        html.Div(
                            id="dashboard-stages-container",
                            children=[
                                html.Div([
                                    html.I(className="bi bi-hourglass text-muted", style={"fontSize": "24px"}),
                                    html.P("Waiting for pipeline to start...", className="text-muted mb-0 mt-2")
                                ], className="text-center py-3")
                            ],
                            style={"minHeight": "60px"}
                        )
                    ])
                ], className="mb-4")
            ], width=12)
        ]),

        # Key Metrics Grid (4 cards)
        html.Div([
            html.Span(id="dashboard-last-updated-badge", children=[
                LastUpdatedBadge(timestamp=None)
            ])
        ], className="text-end mb-2"),
        dbc.Row([
            # Sequences Processed
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-bar-chart-fill", style={"fontSize": "32px", "color": "#0d6efd"}),
                        ], className="mb-2"),
                        html.H2(
                            id="dashboard-sequences-count",
                            children="0",
                            className="mb-0"
                        ),
                        html.P("DNA Sequences Processed", className="text-muted mb-0")
                    ], className="text-center py-3")
                ], className="h-100")
            ], md=3, className="mb-3"),

            # Quality Score
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-shield-check", style={"fontSize": "32px", "color": "#198754"}),
                        ], className="mb-2"),
                        html.H2(
                            id="dashboard-quality-score",
                            children="--",
                            className="mb-0"
                        ),
                        html.P("Quality Score", className="text-muted mb-0"),
                        html.Div(
                            id="dashboard-quality-badge-container",
                            className="mt-2"
                        )
                    ], className="text-center py-3")
                ], className="h-100")
            ], md=3, className="mb-3"),

            # Organisms Detected
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-bug-fill", style={"fontSize": "32px", "color": "#6f42c1"}),
                        ], className="mb-2"),
                        html.H2(
                            id="dashboard-organisms-count",
                            children="0",
                            className="mb-0"
                        ),
                        html.P("Organisms Detected", className="text-muted mb-0")
                    ], className="text-center py-3")
                ], className="h-100")
            ], md=3, className="mb-3"),

            # Active Alerts
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(
                                id="dashboard-alerts-icon",
                                className="bi bi-bell",
                                style={"fontSize": "32px", "color": "#6c757d"}
                            ),
                        ], className="mb-2"),
                        html.H2(
                            id="dashboard-alerts-count-display",
                            children="0",
                            className="mb-0"
                        ),
                        html.P("Active Alerts", className="text-muted mb-0")
                    ], className="text-center py-3")
                ], id="dashboard-alerts-card", className="h-100")
            ], md=3, className="mb-3"),
        ]),

        # Quality Metrics Badges Row
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("Sequencing Quality Metrics", className="mb-0")
                    ]),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.Label([
                                        "Mean Q-Score",
                                        html.I(
                                            className="bi bi-info-circle ms-1",
                                            id="q-score-info",
                                            style={"cursor": "pointer", "fontSize": "0.8rem"}
                                        ),
                                        dbc.Tooltip(
                                            "Average quality of DNA reads. Higher = better accuracy. Above Q15 is good, above Q20 is excellent.",
                                            target="q-score-info",
                                            placement="top"
                                        )
                                    ], className="small text-muted d-block mb-1"),
                                    html.Div(id="dashboard-q-score-badge", children=[
                                        dbc.Badge("--", color="secondary", className="px-3 py-2", style={"fontSize": "1.1rem"})
                                    ])
                                ], className="text-center")
                            ], md=3),
                            dbc.Col([
                                html.Div([
                                    html.Label([
                                        "Read Length N50",
                                        html.I(
                                            className="bi bi-info-circle ms-1",
                                            id="n50-info",
                                            style={"cursor": "pointer", "fontSize": "0.8rem"}
                                        ),
                                        dbc.Tooltip(
                                            "Half of your DNA data comes from reads longer than this value. Higher N50 = longer DNA fragments = better for identification.",
                                            target="n50-info",
                                            placement="top"
                                        )
                                    ], className="small text-muted d-block mb-1"),
                                    html.Div(id="dashboard-n50-badge", children=[
                                        dbc.Badge("--", color="secondary", className="px-3 py-2", style={"fontSize": "1.1rem"})
                                    ])
                                ], className="text-center")
                            ], md=3),
                            dbc.Col([
                                html.Div([
                                    html.Label([
                                        "Classification Rate",
                                        html.I(
                                            className="bi bi-info-circle ms-1",
                                            id="classification-info",
                                            style={"cursor": "pointer", "fontSize": "0.8rem"}
                                        ),
                                        dbc.Tooltip(
                                            "Percentage of DNA sequences successfully identified as organisms. Above 70% is typical; lower may indicate novel or degraded samples.",
                                            target="classification-info",
                                            placement="top"
                                        )
                                    ], className="small text-muted d-block mb-1"),
                                    html.Div(id="dashboard-classification-badge", children=[
                                        dbc.Badge("--", color="secondary", className="px-3 py-2", style={"fontSize": "1.1rem"})
                                    ])
                                ], className="text-center")
                            ], md=3),
                            dbc.Col([
                                html.Div([
                                    html.Label([
                                        "Total Bases",
                                        html.I(
                                            className="bi bi-info-circle ms-1",
                                            id="bases-info",
                                            style={"cursor": "pointer", "fontSize": "0.8rem"}
                                        ),
                                        dbc.Tooltip(
                                            "Total amount of DNA data generated, measured in base pairs (bp). More data generally improves detection sensitivity.",
                                            target="bases-info",
                                            placement="top"
                                        )
                                    ], className="small text-muted d-block mb-1"),
                                    html.Div(id="dashboard-total-bases", children=[
                                        dbc.Badge("--", color="secondary", className="px-3 py-2", style={"fontSize": "1.1rem"})
                                    ])
                                ], className="text-center")
                            ], md=3)
                        ], className="align-items-center")
                    ])
                ], className="mb-4")
            ], width=12)
        ]),

        # Main content area: Sample table (left) and Alerts (right)
        dbc.Row([
            # Sample Status Table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.H5("Sample Status", className="mb-0 d-inline"),
                            dbc.Badge(
                                id="dashboard-sample-count",
                                children="0 samples",
                                color="primary",
                                className="ms-2"
                            )
                        ]),
                        html.Small("Click a row to view sample details", className="text-muted d-block")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-sample-table",
                            type="default",
                            color="#0d6efd",
                            children=[
                                html.Div(id="dashboard-sample-table-container", children=[
                                    # Simplified sample table (5 columns for quick scanning)
                                    dash_table.DataTable(
                                id="dashboard-sample-table",
                                columns=[
                                    {"name": "Sample", "id": "sample"},
                                    {"name": "Status", "id": "status"},
                                    {"name": "Quality", "id": "quality"},
                                    {"name": "Reads", "id": "reads"},
                                    {"name": "Organisms", "id": "organisms"},
                                ],
                                data=[],
                                style_cell={**TABLE_STYLE_CELL, "padding": "12px 16px"},
                                style_header=TABLE_STYLE_HEADER,
                                style_data_conditional=status_conditional_style(
                                    "status", use_border=True
                                ),
                                row_selectable="single",
                                selected_rows=[],
                                page_action="native",
                                page_size=8,
                                sort_action="native",
                                tooltip_header={
                                    "quality": "Data quality assessment",
                                    "reads": "Number of DNA sequences",
                                    "organisms": "Detected organism count"
                                },
                                tooltip_delay=500,
                                tooltip_duration=3000
                            ),
                            # Note about detailed view
                                    html.Small(
                                        "Click a row to view detailed sample metrics in other tabs",
                                        className="text-muted d-block mt-2"
                                    )
                                ], style={"minHeight": "350px"})
                            ]
                        )  # end dcc.Loading
                    ])
                ], className="h-100")
            ], md=8),

            # Alerts Panel
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.H5("Alerts", className="mb-0 d-inline"),
                            dbc.Badge(
                                "0",
                                id="dashboard-alerts-count",
                                color="secondary",
                                className="ms-2"
                            )
                        ])
                    ]),
                    dbc.CardBody([
                        html.Div(id="dashboard-alerts-panel", children=[
                            html.Div([
                                html.I(className="bi bi-check-circle text-success", style={"fontSize": "48px"}),
                                html.H5("No Active Alerts", className="mt-3 mb-2"),
                                html.P("System is operating normally", className="text-muted mb-0")
                            ], className="text-center py-4")
                        ], style={"maxHeight": "350px", "overflowY": "auto"})
                    ])
                ], className="h-100")
            ], md=4)
        ], className="mb-4"),

        # Active Watchlist Panel (expandable)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.I(className="bi bi-eye-fill me-2"),
                                    html.H5("Active Watchlist", className="mb-0 d-inline"),
                                    dbc.Badge(
                                        id="dashboard-watchlist-count",
                                        children="0 species",
                                        color="primary",
                                        className="ms-2"
                                    ),
                                    dbc.Badge(
                                        id="dashboard-taxonomy-badge",
                                        children="Auto",
                                        color="info",
                                        className="ms-2"
                                    ),
                                ])
                            ], width=8),
                            dbc.Col([
                                dbc.Button(
                                    [
                                        html.I(className="bi bi-chevron-down me-1", id="watchlist-expand-icon"),
                                        "Details"
                                    ],
                                    id="dashboard-watchlist-expand-btn",
                                    color="link",
                                    size="sm",
                                    className="float-end"
                                )
                            ], width=4, className="text-end")
                        ], align="center")
                    ], style={"cursor": "pointer"}, id="dashboard-watchlist-header"),
                    dbc.Collapse([
                        dbc.CardBody([
                            # Threat level summary badges
                            html.Div([
                                dbc.Badge(
                                    id="dashboard-wl-critical-count",
                                    children="0 Critical",
                                    color="danger",
                                    className="me-2 mb-2"
                                ),
                                dbc.Badge(
                                    id="dashboard-wl-high-count",
                                    children="0 High",
                                    color="warning",
                                    className="me-2 mb-2"
                                ),
                                dbc.Badge(
                                    id="dashboard-wl-moderate-count",
                                    children="0 Moderate",
                                    color="info",
                                    className="me-2 mb-2"
                                ),
                                dbc.Badge(
                                    id="dashboard-wl-low-count",
                                    children="0 Low",
                                    color="secondary",
                                    className="me-2 mb-2"
                                ),
                            ], className="mb-3"),

                            # Active watchlist entries grouped by threat level
                            html.Div(
                                id="dashboard-watchlist-entries",
                                style={"maxHeight": "300px", "overflowY": "auto"},
                                children=[
                                    html.Div([
                                        html.I(className="bi bi-hourglass text-muted me-2"),
                                        html.Span("Configure watchlist in Settings tab", className="text-muted")
                                    ], className="text-center py-3")
                                ]
                            ),

                            # Footer with link to config
                            html.Div([
                                html.Hr(className="my-2"),
                                html.Small([
                                    html.I(className="bi bi-gear me-1"),
                                    "Manage watchlists in the ",
                                    html.A("Configuration", href="#", id="dashboard-goto-config-link"),
                                    " tab"
                                ], className="text-muted")
                            ])
                        ])
                    ], id="dashboard-watchlist-collapse", is_open=False)
                ], className="mb-4")
            ], width=12)
        ]),

        # Watchlist modals
        create_all_modals(id_prefix="dashboard-wl"),

        # Quick Help Section
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.I(className="bi bi-lightbulb text-warning me-2", style={"fontSize": "20px"}),
                                    html.Strong("Quick Tips: "),
                                    html.Span(
                                        "Green = Good | Yellow = Review Needed | Red = Action Required",
                                        className="text-muted"
                                    )
                                ])
                            ], md=8),
                            dbc.Col([
                                dbc.ButtonGroup([
                                    dbc.Button([
                                        html.I(className="bi bi-question-circle me-1"),
                                        "Help"
                                    ], id="dashboard-help-btn", color="info", outline=True, size="sm"),
                                    dbc.Button([
                                        html.I(className="bi bi-arrow-clockwise me-1"),
                                        "Refresh"
                                    ], id="dashboard-refresh-btn", color="secondary", outline=True, size="sm")
                                ], className="float-end")
                            ], md=4)
                        ])
                    ])
                ], style={"backgroundColor": "#f8f9fa"})
            ], width=12)
        ])
    ], className="p-4")


def create_pipeline_stages_display(stages: list, current_stage: str = None) -> html.Div:
    """
    Create a visual display of pipeline stages with status indicators.

    Args:
        stages: List of stage dictionaries with name, status, completed, total
        current_stage: Name of the currently running stage

    Returns:
        html.Div containing the stages display
    """
    if not stages:
        return html.Div([
            html.I(className="bi bi-hourglass text-muted", style={"fontSize": "24px"}),
            html.P("Waiting for pipeline to start...", className="text-muted mb-0 mt-2")
        ], className="text-center py-3")

    # Status icons and colors
    status_config = {
        "completed": {"icon": "bi-check-circle-fill", "color": "#28a745", "bg": "#d4edda"},
        "running": {"icon": "bi-arrow-repeat", "color": "#0d6efd", "bg": "#cce5ff"},
        "failed": {"icon": "bi-x-circle-fill", "color": "#dc3545", "bg": "#f8d7da"},
        "pending": {"icon": "bi-circle", "color": "#6c757d", "bg": "#f8f9fa"}
    }

    stage_elements = []
    for i, stage in enumerate(stages):
        name = stage.get("name", "Unknown")
        status = stage.get("status", "pending")
        completed = stage.get("completed", 0)
        total = stage.get("total", 0)

        config = status_config.get(status, status_config["pending"])

        # Create stage badge
        stage_badge = html.Div([
            html.Div([
                html.I(
                    className=f"bi {config['icon']}",
                    style={
                        "fontSize": "16px",
                        "color": config["color"],
                        "animation": "spin 1s linear infinite" if status == "running" else "none"
                    }
                ),
                html.Span(
                    name,
                    className="ms-2 fw-semibold",
                    style={"fontSize": "12px"}
                ),
                html.Span(
                    f" ({completed}/{total})" if total > 0 else "",
                    className="text-muted ms-1",
                    style={"fontSize": "11px"}
                )
            ], className="d-flex align-items-center")
        ],
        className="px-3 py-2 rounded me-2 mb-2",
        style={
            "backgroundColor": config["bg"],
            "display": "inline-flex",
            "border": f"1px solid {config['color']}40"
        })

        stage_elements.append(stage_badge)

        # Add connector arrow (except for last stage)
        if i < len(stages) - 1:
            stage_elements.append(
                html.I(
                    className="bi bi-chevron-right text-muted me-2 mb-2",
                    style={"fontSize": "12px", "alignSelf": "center"}
                )
            )

    return html.Div(
        stage_elements,
        className="d-flex flex-wrap align-items-center"
    )


def create_alerts_list(alerts_data: list) -> dbc.ListGroup:
    """
    Create the alerts list component.

    Args:
        alerts_data: List of dicts with alert information

    Returns:
        dbc.ListGroup with alert items sorted by severity
    """
    if not alerts_data:
        return html.Div([
            html.I(className="bi bi-check-circle text-success", style={"fontSize": "48px"}),
            html.H5("No Active Alerts", className="mt-3 mb-2"),
            html.P("System is operating normally", className="text-muted mb-0")
        ], className="text-center py-4")

    # Severity icons and colors
    severity_config = {
        "danger": {"icon": "bi-exclamation-triangle-fill", "color": "danger"},
        "warning": {"icon": "bi-exclamation-circle-fill", "color": "warning"},
        "info": {"icon": "bi-info-circle-fill", "color": "info"},
        "success": {"icon": "bi-check-circle-fill", "color": "success"}
    }

    # Sort by severity (danger > warning > info > success)
    severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    sorted_alerts = sorted(
        alerts_data,
        key=lambda x: severity_order.get(x.get("severity", "info"), 2)
    )

    alert_items = []
    for alert in sorted_alerts:
        severity = alert.get("severity", "info")
        config = severity_config.get(severity, severity_config["info"])

        alert_items.append(
            dbc.ListGroupItem([
                html.Div([
                    html.I(className=f"bi {config['icon']} me-2", style={"color": f"var(--bs-{config['color']})"}),
                    html.Span(alert.get("message", "Unknown alert")),
                ]),
                html.Small(alert.get("timestamp", ""), className="text-muted d-block mt-1")
            ], className="py-2")
        )

    return dbc.ListGroup(alert_items, flush=True)
