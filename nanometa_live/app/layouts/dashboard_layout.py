"""
Overview Dashboard layout for non-technical operators.

This module defines the main dashboard layout optimized for first responders
and laboratory personnel. Features plain language, traffic light coloring,
and at-a-glance status information organized into four clinical priority zones.

Zone 1: Clinical verdict banner - single banner whose background color is the answer.
Zone 2: Active threat cards - pathogen alerts, hidden when none present.
Zone 3: Supporting data strip - four equal metric cards.
Zone 4: Sample details - collapsed accordion with per-sample table.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from nanometa_live.app.components.modern_components import (
    LastUpdatedBadge,
)
from nanometa_live.app.components.waiting_banner import (
    waiting_for_first_batch_banner as _lazy_waiting_banner,
)


def _metric_card(value_id: str, icon_class: str, icon_color: str, label: str, value: str):
    """Build one Zone 3 supporting-data metric card.

    Renders an icon, a live value (``html.H3`` carrying ``value_id`` for
    callbacks to target) and a static label inside the shared
    ``dashboard-metric-card`` shell.
    """
    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className=icon_class,
                           style={"fontSize": "28px", "color": icon_color}),
                ], className="mb-1"),
                html.H3(
                    id=value_id,
                    children=value,
                    className="dashboard-metric-value mb-0"
                ),
                html.P(label,
                       className="dashboard-metric-label text-muted mb-0")
            ], className="text-center py-2")
        ], className="h-100 dashboard-metric-card")
    ], md=3, xs=6, className="mb-3")


def create_dashboard_layout():
    """
    Create the overview dashboard layout for clinical operators.

    Returns:
        html.Div containing the complete dashboard layout
    """
    return html.Div([
        # Hidden stores for dashboard state
        dcc.Store(id='dashboard-data-cache', data={}),
        dcc.Store(id='dashboard-last-updated', data=None),
        dcc.Store(id='dashboard-overall-status-cache', data=None),

        # Help modal
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Dashboard Help")),
            dbc.ModalBody([
                html.H5("Clinical Verdict Banner"),
                html.P(
                    "The banner at the top shows the overall clinical conclusion. "
                    "Background color indicates urgency: green (all clear), "
                    "red (action required), amber (monitoring or screening in progress), "
                    "and grey (standby)."
                ),
                html.H5("Pathogen Alerts"),
                html.P(
                    "When a monitored pathogen is detected, alert cards appear below "
                    "the verdict banner. Each card shows the organism, read count, and "
                    "recommended action."
                ),
                html.H5("Supporting Metrics"),
                html.Ul([
                    html.Li([html.Strong("Sequences Analyzed: "), "Total DNA fragments processed."]),
                    html.Li([html.Strong("Sample Quality: "), "Overall data quality based on Q-score."]),
                    html.Li([html.Strong("Species Detected: "), "Distinct organisms found."]),
                    html.Li([html.Strong("Run Time: "), "Elapsed time since analysis started."]),
                ]),
                html.H5("Sample Details"),
                html.P(
                    "Expand the Sample Details accordion to view per-sample statistics. "
                    "Click a row to filter other tabs to that sample."
                ),
                html.H5("Refresh"),
                html.P(
                    "Data refreshes automatically at the configured interval. "
                    "Use the Refresh button to trigger an immediate update."
                ),
            ]),
            dbc.ModalFooter(
                dbc.Button("Close", id="dashboard-help-close", color="secondary")
            ),
        ], id="dashboard-help-modal", size="lg", is_open=False),

        # =============================================
        # Zone 1 — Clinical Verdict Banner
        # =============================================
        dbc.Row([
            dbc.Col([
                html.Div(
                    id="dashboard-verdict-banner",
                    children=_standby_verdict_content(),
                    style={
                        # CLAUDE.md Zone 1 spec: 6px LEFT border accent
                        # plus a subtle full outline; the bg colour
                        # remains the dominant visual for the verdict
                        # state. Initial standby uses a muted slate
                        # accent; the live verdict callback rewrites
                        # this style via _verdict_style() in
                        # dashboard_tab.py.
                        "backgroundColor": "#f8f9fa",
                        "borderLeft": "6px solid #6c757d",
                        "border": "1px solid rgba(0, 0, 0, 0.08)",
                        "borderLeftWidth": "6px",
                        "borderLeftColor": "#6c757d",
                        "borderRadius": "8px",
                        "padding": "24px 32px",
                        "minHeight": "120px",
                    },
                    className="mb-3",
                    role="status",
                    **{"aria-live": "polite"}
                )
            ], width=12)
        ]),

        # U4: subordinate "waiting for first batch" banner. Hidden by
        # default; toggle_waiting_banner flips the container style when
        # the pipeline is running but the fingerprint has not yet
        # observed a non-empty file in any tracked subdirectory.
        html.Div(
            id="waiting-banner-container",
            children=_lazy_waiting_banner(),
            style={"display": "none"},
            role="status",
            **{"aria-live": "polite"},
        ),

        # =============================================
        # Zone 2 — Active Threat Cards (hidden when empty)
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
        ], id="pathogen-alert-row", className="dashboard-zone-gap"),

        # =============================================
        # Zone 3 — Supporting Data Strip (4 equal cards)
        # =============================================
        html.Div([
            html.Span(id="dashboard-last-updated-badge", children=[
                LastUpdatedBadge(timestamp=None)
            ])
        ], className="text-end mb-1"),
        dbc.Row([
            # Card A: Sequences Analyzed
            _metric_card(
                value_id="dashboard-sequences-count",
                icon_class="bi bi-bar-chart-fill",
                icon_color="#0d6efd",
                label="Sequences Analyzed",
                value="0",
            ),

            # Card B: Sample Quality
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div(
                            id="dashboard-quality-card-content",
                            children=[
                                html.I(className="bi bi-shield-check",
                                       style={"fontSize": "28px", "color": "#6c757d"}),
                                html.H3("--", className="dashboard-metric-value mb-0"),
                                html.P("Sample Quality",
                                       className="dashboard-metric-label text-muted mb-0")
                            ],
                            className="text-center py-2"
                        )
                    ])
                ], className="h-100 dashboard-metric-card")
            ], md=3, xs=6, className="mb-3"),

            # Card C: Species Detected
            _metric_card(
                value_id="dashboard-organisms-count",
                icon_class="bi bi-bug-fill",
                icon_color="#6f42c1",
                label="Species Detected",
                value="0",
            ),

            # Card D: Run Time
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="bi bi-clock",
                                   style={"fontSize": "28px", "color": "#6c757d"}),
                        ], className="mb-1"),
                        html.H3(
                            id="dashboard-time-elapsed",
                            children="00:00:00",
                            className="dashboard-metric-value mb-0"
                        ),
                        dbc.Badge(
                            id="dashboard-run-state-badge",
                            children="STANDBY",
                            color="secondary",
                            className="mt-1",
                            style={"borderRadius": "8px"}
                        ),
                        html.P("Run Time",
                               className="dashboard-metric-label text-muted mb-0 mt-1")
                    ], className="text-center py-2")
                ], className="h-100 dashboard-metric-card")
            ], md=3, xs=6, className="mb-3"),
        ], className="dashboard-zone-gap"),

        # =============================================
        # Zone 4 — Sample Details (collapsed accordion)
        # =============================================
        dbc.Accordion([
            dbc.AccordionItem([
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
                                                    "condition": "params.value === 'Complete'",
                                                    "style": {
                                                        "backgroundColor": "#d4edda",
                                                        "color": "#155724",
                                                        "fontWeight": "bold",
                                                        "borderLeft": "4px solid #28a745"
                                                    },
                                                },
                                                {
                                                    "condition": "params.value === 'Processing'",
                                                    "style": {
                                                        "backgroundColor": "#cce5ff",
                                                        "color": "#004085",
                                                        "fontWeight": "bold",
                                                        "borderLeft": "4px solid #0d6efd"
                                                    },
                                                },
                                                {
                                                    "condition": "params.value === 'Needs Review'",
                                                    "style": {
                                                        "backgroundColor": "#fff3cd",
                                                        "color": "#664d03",
                                                        "fontWeight": "bold",
                                                        "borderLeft": "4px solid #ffc107"
                                                    },
                                                },
                                                {
                                                    "condition": "params.value === 'Error' || params.value === 'Issue Detected'",
                                                    "style": {
                                                        "backgroundColor": "#f8d7da",
                                                        "color": "#721c24",
                                                        "fontWeight": "bold",
                                                        "borderLeft": "4px solid #dc3545"
                                                    },
                                                },
                                            ],
                                        },
                                    },
                                    {
                                        "headerName": "Sample Quality",
                                        "field": "quality",
                                        "headerTooltip": "Data quality assessment",
                                    },
                                    {
                                        "headerName": "Sequences Analyzed",
                                        "field": "reads",
                                        "headerTooltip": "Number of DNA sequence fragments analyzed",
                                    },
                                    {
                                        "headerName": "Species",
                                        "field": "organisms",
                                        "headerTooltip": "Number of distinct species detected",
                                    },
                                    {
                                        "headerName": "Data Size",
                                        "field": "bases",
                                        "headerTooltip": "Total amount of DNA data in this sample",
                                    },
                                    {
                                        "headerName": "Read Length",
                                        "field": "n50",
                                        "headerTooltip": "Typical DNA read length (N50)",
                                    },
                                    {
                                        "headerName": "Match Rate",
                                        "field": "class_rate",
                                        "headerTooltip": "Percentage of sequences matched to a known organism",
                                    },
                                ],
                                rowData=[],
                                defaultColDef={"sortable": True, "filter": True, "resizable": True},
                                # Page size 25 (from 8) puts up to 24
                                # barcodes on a single page so the
                                # operator can scan a multiplexed run
                                # without paginating. The size selector
                                # exposes 10/25/50/100 for operators
                                # who want a tighter or looser view.
                                # Closes P1-T02 from
                                # docs/audit-2026-04-28-throughput-ux.md.
                                # ``getRowId`` keys each row by sample id
                                # so AgGrid preserves the operator's sort,
                                # filter, and row selection across the 30s
                                # interval tick that rewrites rowData.
                                # Without it, every tick rebuilds all DOM
                                # rows and resets interaction state.
                                dashGridOptions={
                                    "pagination": True,
                                    "paginationPageSize": 25,
                                    "paginationPageSizeSelector": [10, 25, 50, 100],
                                    "rowSelection": {"mode": "singleRow"},
                                    "tooltipShowDelay": 500,
                                    "getRowId": {"function": "params.data.sample"},
                                },
                                style={"width": "100%"},
                            ),
                        ])
                    ]
                ),
                html.Small(
                    "Select a row to view sample details in other tabs",
                    className="text-muted d-block mt-2"
                )
            ], title=html.Div([
                html.Span("Sample Details", className="me-2"),
                dbc.Badge(
                    id="dashboard-sample-count",
                    children="0 samples",
                    color="primary",
                )
            ])),
            dbc.AccordionItem([
                html.Div(id="dashboard-alerts-panel", children=[
                    html.Div([
                        html.I(className="bi bi-check-circle text-success",
                               style={"fontSize": "36px"}),
                        html.H6("No Active Alerts", className="mt-2 mb-1"),
                        html.P("System is operating normally",
                               className="text-muted small mb-0")
                    ], className="text-center py-3")
                ], style={"maxHeight": "450px", "overflowY": "auto"})
            ], title=html.Div([
                html.Span("System Alerts", className="me-2"),
                dbc.Badge(
                    "0",
                    id="dashboard-alerts-count",
                    color="secondary",
                )
            ])),
        ], active_item=None, className="mb-3"),

        # =============================================
        # Footer Bar
        # =============================================
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Small([
                        html.Span("Status key: ", className="text-muted fw-semibold"),
                        dbc.Badge("All Clear", color="success", className="me-1",
                                  style={"fontSize": "0.8rem"}),
                        dbc.Badge("Monitoring", color="warning", className="me-1",
                                  style={"fontSize": "0.8rem"}),
                        dbc.Badge("Action Required", color="danger", className="me-1",
                                  style={"fontSize": "0.8rem"}),
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


def _standby_verdict_content():
    """Return default STANDBY banner content for initial render."""
    return dbc.Row([
        dbc.Col([
            html.Div([
                html.I(
                    className="bi bi-pause-circle d-none d-sm-inline",
                    style={"fontSize": "40px", "color": "#6c757d", "flexShrink": "0"}
                ),
                html.Div([
                    html.H3("STANDBY", className="dashboard-verdict-h3 mb-0"),
                    html.P("Start an analysis to begin",
                           className="dashboard-verdict-sub mb-0",
                           style={"color": "#6c757d"})
                ], className="ms-0 ms-sm-3")
            ], className="d-flex align-items-center")
        ], md=9),
        dbc.Col([
            html.Div([
                dbc.Badge("STANDBY", color="secondary", style={"borderRadius": "8px"}),
                html.Div("00:00:00", className="small text-muted mt-1")
            ], className="text-end")
        ], md=3, className="d-flex align-items-center justify-content-end")
    ], className="align-items-center g-0")


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
        "critical": {"icon": "bi-exclamation-octagon-fill", "color": "danger"},
        "danger": {"icon": "bi-exclamation-octagon-fill", "color": "danger"},
        "warning": {"icon": "bi-exclamation-circle-fill", "color": "warning"},
        "info": {"icon": "bi-info-circle-fill", "color": "info"},
        "success": {"icon": "bi-check-circle-fill", "color": "success"}
    }

    def _icon_element(icon_str, color):
        """Render a Bootstrap Icon class."""
        if icon_str.startswith("bi-"):
            return html.I(className=f"bi {icon_str} me-2",
                          style={"color": f"var(--bs-{color})"})
        return html.Span(icon_str, className="me-2",
                         style={"fontSize": "1.5em", "color": f"var(--bs-{color})"})

    # Sort by severity (critical/danger > warning > info > success)
    severity_order = {"critical": 0, "danger": 0, "warning": 1, "info": 2, "success": 3}
    sorted_alerts = sorted(
        alerts_data,
        key=lambda x: severity_order.get(x.get("severity", "info"), 2)
    )

    # Group by category
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
            cfg = severity_config.get(severity, severity_config["info"])
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
                        _icon_element(cfg["icon"], cfg["color"]),
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
            cfg = severity_config.get(severity, severity_config["info"])
            alert_items.append(
                dbc.ListGroupItem([
                    html.Div([
                        _icon_element(cfg["icon"], cfg["color"]),
                        html.Span(alert.get("message", "Unknown alert")),
                    ]),
                    html.Small(alert.get("timestamp", ""), className="text-muted d-block mt-1")
                ], className="py-2")
            )

    return dbc.ListGroup(alert_items, flush=True)
