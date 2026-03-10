"""
Overview Dashboard layout for non-technical operators.

This module defines the main dashboard layout optimized for first responders
and laboratory personnel. Features plain language, traffic light coloring,
and at-a-glance status information.

MODERNIZED: Simplified metrics, large traffic light status, prominent alerts,
operator-friendly sample table.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

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
    DecisionBanner,
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
    Create the overview dashboard layout for clinical operators.

    Layout is ordered by clinical decision priority:
    1. Run status banner (is the system running?)
    2. Pathogen screening + classification (are there threats?)
    3. Key metrics (how much data, what quality?)
    4. Sample status table + alerts (per-sample details)
    5. Active watchlist (what are we monitoring?)
    6. Quality metrics details (technical details)
    7. Pipeline stages (only relevant during active runs)

    Returns:
        html.Div containing the complete dashboard layout
    """
    return html.Div([
        # Hidden stores for dashboard state
        dcc.Store(id='dashboard-data-cache', data={}),
        dcc.Store(id='dashboard-last-updated', data=None),
        dcc.Store(id='dashboard-overall-status-cache', data=None),

        # Help modal for dashboard usage
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Dashboard Help")),
            dbc.ModalBody([
                html.H5("Status Traffic Light"),
                html.P(
                    "The large status indicator shows the overall state of the analysis run. "
                    "Green means all systems are operating normally, amber indicates items "
                    "that may need review, and red signals critical findings or errors."
                ),
                html.H5("Alert Severity Levels"),
                html.Ul([
                    html.Li([html.Strong("Critical (red): "), "High-risk pathogen detected or system error requiring immediate action."]),
                    html.Li([html.Strong("Warning (amber): "), "Potential concern such as a moderate-risk organism or quality issue."]),
                    html.Li([html.Strong("Info (blue): "), "Informational notice, no action required."]),
                ]),
                html.H5("Key Metrics"),
                html.P(
                    "The metrics bar shows total reads processed, quality pass rate, "
                    "classification rate, and the number of active samples. These update "
                    "automatically at each refresh interval."
                ),
                html.H5("Sample Selection"),
                html.P(
                    "Click a row in the sample table to filter all dashboard panels to "
                    "that specific sample or barcode. Click again to deselect and return "
                    "to the combined view."
                ),
                html.H5("Refresh"),
                html.P(
                    "Data refreshes automatically based on the configured interval. "
                    "Use the Refresh button to trigger an immediate update."
                ),
            ]),
            dbc.ModalFooter(
                dbc.Button("Close", id="dashboard-help-close", color="secondary")
            ),
        ], id="dashboard-help-modal", size="lg", is_open=False),

        # =============================================
        # 0. PRE-FLIGHT CHECKLIST (visible when idle)
        # =============================================
        html.Div(
            id="preflight-container",
            children=[
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.I(className="bi bi-clipboard-check me-2", style={"fontSize": "1.3rem"}),
                                    html.H5("Pre-flight Checklist", className="mb-0 d-inline"),
                                ], className="d-flex align-items-center"),
                            ], width=8),
                            dbc.Col([
                                dbc.Button(
                                    [html.I(className="bi bi-arrow-right me-1"), "Go to Preparation"],
                                    id="preflight-goto-prep",
                                    color="outline-primary",
                                    size="sm",
                                ),
                            ], width=4, className="text-end"),
                        ], className="mb-3"),
                        html.Div(id="preflight-checks-list", children=[
                            html.Div("Loading readiness checks...", className="text-muted")
                        ]),
                    ])
                ], className="mb-3 border-start border-4 border-info"),
            ],
            style={"display": "block"},
        ),

        # =============================================
        # 1. TOP STATUS BANNER (Large Traffic Light)
        # =============================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            # Large Traffic Light Status Indicator
                            dbc.Col([
                                html.Div([
                                    html.Div(
                                        id="dashboard-status-indicator",
                                        className="dashboard-traffic-light status-idle",
                                        **{"aria-hidden": "true"},
                                        children=[
                                            html.I(
                                                id="dashboard-status-icon",
                                                className="bi bi-pause-circle",
                                                style={"fontSize": "64px", "color": "white"}
                                            )
                                        ]
                                    ),
                                    html.Div(
                                        id="dashboard-status-label",
                                        children=[
                                            html.Span(
                                                id="dashboard-status-label-text",
                                                children="STANDBY",
                                                className="fw-bold",
                                                style={"fontSize": "18px", "letterSpacing": "1px"}
                                            ),
                                            html.I(
                                                id="dashboard-status-label-icon",
                                                className="bi bi-pause-fill ms-1",
                                                style={"fontSize": "18px"}
                                            )
                                        ],
                                        className="text-center mt-2 text-muted"
                                    )
                                ], className="d-flex flex-column align-items-center")
                            ], md=3, className="d-flex align-items-center justify-content-center"),

                            # Status Text
                            dbc.Col([
                                html.H3(
                                    id="dashboard-status-text",
                                    children="STANDBY - Ready to begin",
                                    className="mb-1",
                                    role="status",
                                    **{"aria-live": "polite"}
                                ),
                                html.P(
                                    id="dashboard-status-subtitle",
                                    children="Click 'Start Analysis' in the header to begin",
                                    className="text-muted mb-0",
                                    style={"fontSize": "16px"}
                                ),
                                html.Span(
                                    id="dashboard-next-update",
                                    children="",
                                    className="text-muted small ms-2"
                                ),
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
                ], id="dashboard-status-card", className="mb-3", style={"borderWidth": "3px"})
            ], width=12)
        ]),

        # =============================================
        # 2. PATHOGEN ALERT BANNER (dynamic, highest priority)
        # =============================================
        dbc.Row([
            dbc.Col([
                html.Div(
                    id="dashboard-pathogen-alert-container",
                    children=[],
                    style={"display": "none"},
                    role="alert",
                    **{"aria-live": "assertive"}
                )
            ], width=12)
        ], id="pathogen-alert-row", className="mb-0"),

        # =============================================
        # 2b. DECISION BANNER (binary safe/action-required)
        # =============================================
        dbc.Row([
            dbc.Col([
                html.Div(
                    id="dashboard-decision-banner",
                    children=[],
                    className="mb-3"
                )
            ], width=12)
        ]),

        # =============================================
        # 3. THREAT STATUS + PATHOGEN SCREENING + CLASSIFICATION
        # (Clinical decision: are there threats?)
        # =============================================
        dbc.Row([
            # Threat Status Indicator
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
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
                            ),
                            html.Span(
                                id="dashboard-threat-since",
                                children="",
                                className="small text-muted"
                            )
                        ], className="text-center")
                    ], className="py-3")
                ], id="dashboard-threat-card", className="h-100", style={
                    "borderColor": "#28a745",
                    "borderWidth": "2px",
                    "backgroundColor": "rgba(40, 167, 69, 0.06)"
                })
            ], md=3, className="mb-3"),

            # Pathogen Detection Summary
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.I(className="bi bi-biohazard me-2", style={"color": "#dc3545", "fontSize": "1.2rem"}),
                            html.H5("Pathogen Screening", className="mb-0 d-inline"),
                            html.Span(
                                id="dashboard-screening-count",
                                children="",
                                className="ms-2 text-muted small"
                            )
                        ]),
                        html.Span(
                            id="dashboard-last-scan",
                            children="",
                            className="text-muted small"
                        )
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
                                            html.I(className="bi bi-arrow-repeat text-muted me-2"),
                                            html.Span("Screening begins when analysis starts", className="text-muted")
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
                            html.H5("Classification", className="mb-0 d-inline")
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
                                    style={"height": "200px"}
                                )
                            ]
                        )
                    ], className="py-1")
                ], className="h-100")
            ], md=4, className="mb-3")
        ], className="mb-2"),

        # =============================================
        # 4. KEY METRICS GRID (5 cards) + timestamp
        # =============================================
        html.Div([
            html.Span(id="dashboard-last-updated-badge", children=[
                LastUpdatedBadge(timestamp=None)
            ])
        ], className="text-end mb-1"),
        dbc.Row([
            # Input Files
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-files", style={"fontSize": "28px", "color": "#6c757d"}),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-total-files-count",
                            children="0",
                            className="mb-0"
                        ),
                        html.Span(id="dashboard-total-files-trend", children="", className="metric-trend"),
                        html.P("Input Files", className="text-muted small mb-0")
                    ], className="text-center py-2")
                ], className="h-100 dashboard-metric-card")
            ], className="mb-3"),

            # Sequences Processed
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-bar-chart-fill", style={"fontSize": "28px", "color": "#0d6efd"}),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-sequences-count",
                            children="0",
                            className="mb-0"
                        ),
                        html.Span(id="dashboard-sequences-trend", children="", className="metric-trend"),
                        html.P("Sequences", className="text-muted small mb-0")
                    ], className="text-center py-2")
                ], className="h-100 dashboard-metric-card")
            ], className="mb-3"),

            # Quality Score
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-shield-check", style={"fontSize": "28px", "color": "#198754"}),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-quality-score",
                            children="--",
                            className="mb-0"
                        ),
                        html.Span(id="dashboard-quality-trend", children="", className="metric-trend"),
                        html.P("Quality Score", className="text-muted small mb-0"),
                        html.Div(
                            id="dashboard-quality-badge-container",
                            className="mt-1"
                        )
                    ], className="text-center py-2")
                ], className="h-100 dashboard-metric-card")
            ], className="mb-3"),

            # Organisms Detected
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-bug-fill", style={"fontSize": "28px", "color": "#6f42c1"}),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-organisms-count",
                            children="0",
                            className="mb-0"
                        ),
                        html.Span(id="dashboard-organisms-trend", children="", className="metric-trend"),
                        html.P("Organisms", className="text-muted small mb-0")
                    ], className="text-center py-2")
                ], className="h-100 dashboard-metric-card")
            ], className="mb-3"),

            # Active Alerts
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(
                                id="dashboard-alerts-icon",
                                className="bi bi-bell",
                                style={"fontSize": "28px", "color": "#6c757d"}
                            ),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-alerts-count-display",
                            children="0",
                            className="mb-0"
                        ),
                        html.Span(id="dashboard-alerts-trend", children="", className="metric-trend"),
                        html.P("Alerts", className="text-muted small mb-0")
                    ], className="text-center py-2")
                ], id="dashboard-alerts-card", className="h-100 dashboard-metric-card")
            ], className="mb-3"),
        ]),

        # =============================================
        # 5. SAMPLE STATUS TABLE + ALERTS (side by side)
        # =============================================
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
                        html.Small("Select a row to view sample details in other tabs", className="text-muted d-block")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-sample-table",
                            type="circle",
                            color="#0d6efd",
                            children=[
                                html.Div(id="dashboard-sample-table-container", children=[
                                    dag.AgGrid(
                                        id="dashboard-sample-table",
                                        columnDefs=[
                                            {
                                                "headerName": "Sample",
                                                "field": "sample",
                                                "headerTooltip": "Click a row to filter all tabs to this sample",
                                            },
                                            {
                                                "headerName": "Status",
                                                "field": "status",
                                                "headerTooltip": "Sample processing status",
                                                "cellStyle": {
                                                    "styleConditions": [
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Complete') >= 0",
                                                            "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "bold", "borderLeft": "4px solid #28a745"},
                                                        },
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Good') >= 0",
                                                            "style": {"backgroundColor": "#d4edda", "color": "#155724", "fontWeight": "bold", "borderLeft": "4px solid #28a745"},
                                                        },
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Processing') >= 0",
                                                            "style": {"backgroundColor": "#fff3cd", "color": "#856404", "fontWeight": "bold", "borderLeft": "4px solid #ffc107"},
                                                        },
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Review') >= 0",
                                                            "style": {"backgroundColor": "#fff3cd", "color": "#856404", "fontWeight": "bold", "borderLeft": "4px solid #ffc107"},
                                                        },
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Error') >= 0",
                                                            "style": {"backgroundColor": "#f8d7da", "color": "#721c24", "fontWeight": "bold", "borderLeft": "4px solid #dc3545"},
                                                        },
                                                        {
                                                            "condition": "params.value && params.value.indexOf('Issue') >= 0",
                                                            "style": {"backgroundColor": "#f8d7da", "color": "#721c24", "fontWeight": "bold", "borderLeft": "4px solid #dc3545"},
                                                        },
                                                    ],
                                                },
                                            },
                                            {
                                                "headerName": "Quality",
                                                "field": "quality",
                                                "headerTooltip": "Data quality assessment",
                                            },
                                            {
                                                "headerName": "Reads",
                                                "field": "reads",
                                                "headerTooltip": "Number of DNA sequences",
                                            },
                                            {
                                                "headerName": "Organisms",
                                                "field": "organisms",
                                                "headerTooltip": "Detected organism count",
                                            },
                                            {
                                                "headerName": "Bases",
                                                "field": "bases",
                                                "headerTooltip": "Total base pairs sequenced",
                                            },
                                            {
                                                "headerName": "N50",
                                                "field": "n50",
                                                "headerTooltip": "Read length N50 (half of data from reads longer than this)",
                                            },
                                            {
                                                "headerName": "Class. Rate",
                                                "field": "class_rate",
                                                "headerTooltip": "Percentage of reads classified to an organism",
                                            },
                                        ],
                                        rowData=[],
                                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                                        dashGridOptions={
                                            "pagination": True,
                                            "paginationPageSize": 8,
                                            "rowSelection": {"mode": "singleRow"},
                                            "tooltipShowDelay": 500,
                                        },
                                        style={"width": "100%"},
                                    ),
                                ])
                            ]
                        )
                    ])
                ], className="h-100")
            ], md=7),

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
                                html.I(className="bi bi-check-circle text-success", style={"fontSize": "36px"}),
                                html.H6("No Active Alerts", className="mt-2 mb-1"),
                                html.P("System is operating normally", className="text-muted small mb-0")
                            ], className="text-center py-3")
                        ], style={"maxHeight": "450px", "overflowY": "auto"})
                    ])
                ], className="h-100")
            ], md=5)
        ], className="mb-3"),

        # =============================================
        # 6. ACTIVE WATCHLIST (default open - critical clinical info)
        # =============================================
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
                                        html.I(className="bi bi-chevron-up me-1", id="watchlist-expand-icon"),
                                        "Collapse"
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
                                style={"maxHeight": "250px", "overflowY": "auto"},
                                children=[
                                    html.Div([
                                        html.I(className="bi bi-hourglass text-muted me-2"),
                                        html.Span("Configure watchlist in Settings tab", className="text-muted")
                                    ], className="text-center py-3")
                                ]
                            ),

                            # Footer with link to watchlist tab
                            html.Div([
                                html.Hr(className="my-2"),
                                html.Small([
                                    html.I(className="bi bi-star me-1"),
                                    "Manage watchlists in the ",
                                    html.A("Watchlist", href="#", id="dashboard-goto-config-link"),
                                    " tab"
                                ], className="text-muted")
                            ])
                        ])
                    ], id="dashboard-watchlist-collapse", is_open=True)
                ], className="mb-3")
            ], width=12)
        ]),

        # Watchlist modals
        create_all_modals(id_prefix="dashboard-wl"),

        # =============================================
        # 7. SEQUENCING QUALITY METRICS (technical detail)
        # =============================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("Sequencing Quality Metrics", className="mb-0")
                    ], className="py-2"),
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
                                        dbc.Badge("--", color="secondary", className="px-3 py-2")
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
                                        dbc.Badge("--", color="secondary", className="px-3 py-2")
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
                                        dbc.Badge("--", color="secondary", className="px-3 py-2")
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
                                        dbc.Badge("--", color="secondary", className="px-3 py-2")
                                    ])
                                ], className="text-center")
                            ], md=3)
                        ], className="align-items-center")
                    ], className="py-2")
                ], className="mb-3")
            ], width=12)
        ]),

        # =============================================
        # 8. PIPELINE STAGES (collapsible, less prominent)
        # =============================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.I(className="bi bi-diagram-3 me-2"),
                            html.H6("Pipeline Stages", className="mb-0 d-inline"),
                            html.Span(
                                id="dashboard-current-stage",
                                children="",
                                className="ms-2 text-muted small"
                            )
                        ])
                    ], className="py-2"),
                    dbc.CardBody([
                        html.Div(
                            id="dashboard-stages-container",
                            children=[
                                html.Div([
                                    html.I(className="bi bi-hourglass text-muted", style={"fontSize": "24px"}),
                                    html.P("Waiting for pipeline to start...", className="text-muted mb-0 mt-2")
                                ], className="text-center py-3")
                            ],
                            style={"minHeight": "50px"}
                        )
                    ], className="py-2")
                ], className="mb-3")
            ], width=12)
        ]),

        # =============================================
        # 9. FOOTER BAR (Help + Refresh + color legend)
        # =============================================
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Small([
                        html.Span("Status key: ", className="text-muted fw-semibold"),
                        dbc.Badge("Good", color="success", className="me-1", style={"fontSize": "0.8rem"}),
                        dbc.Badge("Review", color="warning", className="me-1", style={"fontSize": "0.8rem"}),
                        dbc.Badge("Action Required", color="danger", className="me-1", style={"fontSize": "0.8rem"}),
                    ], className="d-flex align-items-center")
                ])
            ], md=8),
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button([
                        html.I(className="bi bi-download me-1"),
                        "Export Results"
                    ], id="dashboard-export-btn", color="outline-primary", size="sm"),
                    dbc.Button([
                        html.I(className="bi bi-question-circle me-1"),
                        "Help"
                    ], id="dashboard-help-btn", color="link", size="sm"),
                    dbc.Button([
                        html.I(className="bi bi-arrow-clockwise me-1"),
                        "Refresh"
                    ], id="dashboard-refresh-btn", color="link", size="sm")
                ], className="float-end")
            ], md=4)
        ], className="mb-2 px-2"),

        # Export Results Modal
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Export Results")),
            dbc.ModalBody([
                dbc.Label("Output Directory"),
                dbc.Input(
                    id="export-output-dir",
                    type="text",
                    placeholder="Path to export directory...",
                    className="mb-3"
                ),
                dbc.Checkbox(
                    id="export-include-raw",
                    label="Include raw data files (kraken2, fastp, validation)",
                    value=True,
                    className="mb-3"
                ),
                html.Div(id="export-status-message")
            ]),
            dbc.ModalFooter([
                dbc.Button(
                    "Cancel",
                    id="export-cancel-btn",
                    color="secondary",
                    className="me-2"
                ),
                dbc.Button(
                    [html.I(className="bi bi-download me-1"), "Generate Report"],
                    id="export-generate-btn",
                    color="primary"
                ),
            ]),
        ], id="report-export-modal", is_open=False, centered=True),
    ], className="p-3")


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
    # Maps both alert engine names ("critical") and Bootstrap names ("danger")
    severity_config = {
        "critical": {"icon": "bi-exclamation-triangle-fill", "color": "danger"},
        "danger": {"icon": "bi-exclamation-triangle-fill", "color": "danger"},
        "warning": {"icon": "bi-exclamation-circle-fill", "color": "warning"},
        "info": {"icon": "bi-info-circle-fill", "color": "info"},
        "success": {"icon": "bi-check-circle-fill", "color": "success"}
    }

    # Sort by severity (critical/danger > warning > info > success)
    severity_order = {"critical": 0, "danger": 0, "warning": 1, "info": 2, "success": 3}
    sorted_alerts = sorted(
        alerts_data,
        key=lambda x: severity_order.get(x.get("severity", "info"), 2)
    )

    # Group alerts by category
    category_map = {
        "pathogen": "Pathogen Alerts",
        "quality": "Quality Alerts",
        "pipeline": "Pipeline Alerts",
    }
    categories = {}
    for alert in sorted_alerts:
        cat = alert.get("category", "pipeline")
        categories.setdefault(cat, []).append(alert)

    alert_items = []
    # Render in fixed category order
    for cat_key in ["pathogen", "quality", "pipeline"]:
        cat_alerts = categories.pop(cat_key, [])
        if not cat_alerts:
            continue
        cat_label = category_map.get(cat_key, cat_key.title() + " Alerts")
        alert_items.append(
            dbc.ListGroupItem(
                html.Small(cat_label, className="fw-bold text-uppercase"),
                className="py-1 bg-light",
                style={"letterSpacing": "0.05em"}
            )
        )
        for alert in cat_alerts:
            severity = alert.get("severity", "info")
            config = severity_config.get(severity, severity_config["info"])
            is_critical = severity in ("critical", "danger")
            is_resolved = alert.get("resolved", False)

            item_class = "py-2"
            if is_critical:
                item_class += " critical-alert-item"
            if is_resolved:
                item_class += " resolved-alert-item"

            alert_items.append(
                dbc.ListGroupItem([
                    html.Div([
                        html.I(className=f"bi {config['icon']} me-2", style={"color": f"var(--bs-{config['color']})"}),
                        html.Span(alert.get("message", "Unknown alert")),
                    ]),
                    html.Small(alert.get("timestamp", ""), className="text-muted d-block mt-1")
                ], className=item_class)
            )

    # Any remaining uncategorized alerts
    for cat_key, cat_alerts in categories.items():
        cat_label = cat_key.title() + " Alerts"
        alert_items.append(
            dbc.ListGroupItem(
                html.Small(cat_label, className="fw-bold text-uppercase"),
                className="py-1 bg-light",
                style={"letterSpacing": "0.05em"}
            )
        )
        for alert in cat_alerts:
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
