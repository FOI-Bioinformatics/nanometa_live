"""
Tooltip and contextual help components for Nanometa Live v2.0.

Provides inline help, tooltips, and contextual guidance for operators.
"""

from typing import Optional, Union, List, Dict
from dash import html, dcc
import dash_bootstrap_components as dbc


def Tooltip(
    text: str,
    target_id: str,
    placement: str = "top",
    delay: Optional[Dict[str, int]] = None
) -> dbc.Tooltip:
    """
    Create a Bootstrap tooltip with operator-friendly styling.

    Args:
        text: Tooltip content
        target_id: ID of the element to attach tooltip to
        placement: Tooltip placement ("top", "bottom", "left", "right")
        delay: Show/hide delay in ms (default: {"show": 500, "hide": 100})

    Returns:
        dbc.Tooltip component

    Examples:
        >>> Tooltip("Total DNA sequences processed", "reads-metric")
    """
    if delay is None:
        delay = {"show": 500, "hide": 100}

    return dbc.Tooltip(
        text,
        target=target_id,
        placement=placement,
        delay=delay,
        style={
            "fontSize": "14px",
            "maxWidth": "300px",
            "backgroundColor": "var(--dark)",
            "padding": "8px 12px",
            "borderRadius": "8px"
        }
    )


def HelpIcon(
    tooltip_text: str,
    icon_id: Optional[str] = None,
    size: str = "sm"
) -> html.Div:
    """
    Create a help icon with tooltip.

    Args:
        tooltip_text: Help text to display on hover
        icon_id: Unique ID for the icon (auto-generated if None)
        size: Icon size ("sm", "md", "lg")

    Returns:
        Div containing help icon and tooltip

    Examples:
        >>> HelpIcon("Quality score ranges from 0-100. Higher is better.")
    """
    import uuid
    if icon_id is None:
        icon_id = f"help-icon-{uuid.uuid4().hex[:8]}"

    size_map = {
        "sm": "20px",
        "md": "24px",
        "lg": "28px"
    }

    icon = html.Span(
        "?",
        id=icon_id,
        className="help-icon",
        style={
            "width": size_map.get(size, "20px"),
            "height": size_map.get(size, "20px"),
            "fontSize": "12px" if size == "sm" else "14px" if size == "md" else "16px"
        }
    )

    tooltip = Tooltip(tooltip_text, icon_id)

    return html.Div([icon, tooltip], style={"display": "inline-block", "marginLeft": "8px"})


def InlineHelp(
    title: str,
    content: Union[str, List[str]],
    severity: str = "info"
) -> dbc.Alert:
    """
    Create an inline help box with icon and formatted content.

    Args:
        title: Help box title
        content: Help content (string or list of strings for bullets)
        severity: Alert type ("info", "warning", "success", "danger")

    Returns:
        dbc.Alert component

    Examples:
        >>> InlineHelp(
        ...     "Understanding Quality Scores",
        ...     ["Scores above 75 are good", "Scores below 60 need attention"]
        ... )
    """
    icon_map = {
        "info": "ℹ️",
        "warning": "⚠️",
        "success": "✓",
        "danger": "✗"
    }

    # Format content
    if isinstance(content, list):
        content_element = html.Ul([
            html.Li(item) for item in content
        ], style={"marginBottom": "0", "paddingLeft": "20px"})
    else:
        content_element = html.P(content, style={"marginBottom": "0"})

    return dbc.Alert(
        [
            html.Div([
                html.Span(
                    icon_map.get(severity, "ℹ️"),
                    style={
                        "fontSize": "24px",
                        "marginRight": "12px",
                        "verticalAlign": "middle"
                    }
                ),
                html.Strong(title, style={"verticalAlign": "middle"})
            ], style={"marginBottom": "8px"}),
            content_element
        ],
        color=severity,
        className="alert-modern",
        dismissable=True
    )


def ContextualCard(
    title: str,
    description: str,
    action_text: Optional[str] = None,
    action_id: Optional[str] = None,
    status: str = "info"
) -> dbc.Card:
    """
    Create a contextual guidance card with call-to-action.

    Args:
        title: Card title
        description: Guidance description
        action_text: Optional action button text
        action_id: ID for action button (required if action_text provided)
        status: Card status color ("info", "success", "warning", "danger")

    Returns:
        dbc.Card component

    Examples:
        >>> ContextualCard(
        ...     "Analysis Complete",
        ...     "Review results and generate report",
        ...     action_text="Generate Report",
        ...     action_id="generate-report-btn"
        ... )
    """
    color_map = {
        "info": "primary",
        "success": "success",
        "warning": "warning",
        "danger": "danger"
    }

    card_content = [
        dbc.CardHeader(
            html.H5(title, className="mb-0"),
            style={"backgroundColor": f"var(--status-{status}-bg)"}
        ),
        dbc.CardBody([
            html.P(description, className="mb-3")
        ] + ([
            dbc.Button(
                action_text,
                id=action_id,
                color=color_map.get(status, "primary"),
                className="mt-2"
            )
        ] if action_text and action_id else []))
    ]

    return dbc.Card(
        card_content,
        className="mb-3",
        style={
            "borderLeft": f"4px solid var(--status-{status})",
            "boxShadow": "var(--shadow-md)"
        }
    )


def QuickGuidePanel(
    title: str,
    steps: List[Dict[str, str]],
    collapsible: bool = True
) -> Union[dbc.Card, dbc.Collapse]:
    """
    Create a quick guide panel with numbered steps.

    Args:
        title: Guide title
        steps: List of dicts with "step" and "description" keys
        collapsible: Whether the panel can be collapsed

    Returns:
        Guide panel component

    Examples:
        >>> QuickGuidePanel(
        ...     "Getting Started",
        ...     [
        ...         {"step": "Configure Analysis", "description": "Set parameters"},
        ...         {"step": "Start Run", "description": "Click start button"}
        ...     ]
        ... )
    """
    step_elements = []
    for idx, step in enumerate(steps, 1):
        step_elements.append(
            html.Div([
                html.Div(
                    str(idx),
                    style={
                        "display": "inline-block",
                        "width": "32px",
                        "height": "32px",
                        "borderRadius": "50%",
                        "backgroundColor": "var(--primary)",
                        "color": "white",
                        "textAlign": "center",
                        "lineHeight": "32px",
                        "fontWeight": "bold",
                        "marginRight": "12px"
                    }
                ),
                html.Div([
                    html.Strong(step["step"]),
                    html.Br(),
                    html.Small(step["description"], className="text-muted")
                ], style={"display": "inline-block", "verticalAlign": "top"})
            ], style={"marginBottom": "16px"})
        )

    card = dbc.Card([
        dbc.CardHeader([
            html.H5(title, className="d-inline"),
            html.Span("▼", className="float-end") if collapsible else None
        ]),
        dbc.CardBody(step_elements, id=f"guide-body-{title.lower().replace(' ', '-')}")
    ])

    if collapsible:
        return dbc.Collapse(
            card,
            id=f"guide-collapse-{title.lower().replace(' ', '-')}",
            is_open=False
        )

    return card


def StatusExplanation(
    status: str,
    title: str,
    description: str,
    recommendation: Optional[str] = None
) -> html.Div:
    """
    Create a status explanation box with visual indicator.

    Args:
        status: Status type ("good", "warning", "danger", "info")
        title: Status title
        description: Status description
        recommendation: Optional recommended action

    Returns:
        Status explanation component

    Examples:
        >>> StatusExplanation(
        ...     "warning",
        ...     "Fair Data Quality",
        ...     "Quality is acceptable but could be improved",
        ...     "Check sequencing conditions"
        ... )
    """
    icon_map = {
        "good": "✓",
        "warning": "⚠️",
        "danger": "✗",
        "info": "ℹ️"
    }

    return html.Div([
        html.Div([
            html.Div(
                icon_map.get(status, "ℹ️"),
                className=f"traffic-light traffic-light-{status}",
                style={
                    "width": "40px",
                    "height": "40px",
                    "display": "inline-flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "marginRight": "16px",
                    "fontSize": "20px"
                }
            ),
            html.Div([
                html.H6(title, className="mb-1"),
                html.P(description, className="mb-1 text-muted", style={"fontSize": "14px"}),
                html.Small(
                    f"→ {recommendation}",
                    className="font-italic"
                ) if recommendation else None
            ], style={"display": "inline-block", "verticalAlign": "middle"})
        ], style={"display": "flex", "alignItems": "center"}),
    ], className=f"alert alert-{status} alert-modern", style={"marginBottom": "16px"})


def MetricWithHelp(
    value: str,
    label: str,
    help_text: str,
    color: str = "primary",
    metric_id: Optional[str] = None
) -> html.Div:
    """
    Create a metric display with integrated help icon.

    Args:
        value: Metric value to display
        label: Metric label
        help_text: Help text for tooltip
        color: Color theme ("primary", "success", "warning", "danger")
        metric_id: Optional unique ID for the metric

    Returns:
        Metric component with help

    Examples:
        >>> MetricWithHelp(
        ...     "10,000",
        ...     "DNA Sequences",
        ...     "Total number of DNA sequences processed through quality control",
        ...     color="success"
        ... )
    """
    import uuid
    if metric_id is None:
        metric_id = f"metric-{uuid.uuid4().hex[:8]}"

    return html.Div([
        html.Div([
            html.H3(value, className="mb-0", style={"color": f"var(--status-{color})", "fontWeight": "700"}),
            HelpIcon(help_text, f"{metric_id}-help")
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
        html.P(label, className="text-muted mb-0", style={"fontSize": "12px", "textTransform": "uppercase", "letterSpacing": "0.5px"})
    ], className="text-center p-3")


def GuidedTour(
    steps: List[Dict[str, Union[str, List[str]]]],
    tour_id: str = "guided-tour"
) -> dbc.Modal:
    """
    Create a guided tour modal for first-time users.

    Args:
        steps: List of tour steps with "title", "content", and optional "image" keys
        tour_id: Unique ID for the tour

    Returns:
        Modal component with tour steps

    Examples:
        >>> GuidedTour([
        ...     {
        ...         "title": "Welcome to Nanometa Live",
        ...         "content": "Let's take a quick tour of the main features"
        ...     },
        ...     {
        ...         "title": "Dashboard Overview",
        ...         "content": "The dashboard shows real-time analysis status"
        ...     }
        ... ])
    """
    tour_steps = []
    for idx, step in enumerate(steps):
        tour_steps.append(
            html.Div([
                html.H4(step["title"], className="mb-3"),
                html.P(step["content"]) if isinstance(step["content"], str) else html.Div([
                    html.P(p) for p in step["content"]
                ]),
                html.Small(f"Step {idx + 1} of {len(steps)}", className="text-muted")
            ], id=f"{tour_id}-step-{idx}", style={"display": "none" if idx > 0 else "block"})
        )

    return dbc.Modal([
        dbc.ModalHeader("Quick Tour"),
        dbc.ModalBody(tour_steps, id=f"{tour_id}-body"),
        dbc.ModalFooter([
            dbc.Button("Previous", id=f"{tour_id}-prev", color="secondary", className="me-2"),
            dbc.Button("Next", id=f"{tour_id}-next", color="primary"),
            dbc.Button("Skip Tour", id=f"{tour_id}-skip", color="link")
        ])
    ], id=tour_id, size="lg", is_open=False)
