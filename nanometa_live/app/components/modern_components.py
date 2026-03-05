"""
Modern UI components for non-technical operators.

This module provides reusable, plain-language components designed for
first responders and laboratory personnel without bioinformatics training.
Components use traffic light coloring, clear visual hierarchy, and
actionable language.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from dash import html, dcc
import dash_bootstrap_components as dbc


def WorkflowStepper(active_step: int = 1) -> html.Div:
    """
    Reusable workflow step indicator for the setup sequence.

    Shows a 4-step horizontal stepper: Configure -> Watchlist -> Prepare -> Analyse.
    Completed steps are green, the active step is blue, and future steps are grey.

    Args:
        active_step: Which step is currently active (1-4).
            1 = Configuration, 2 = Watchlist, 3 = Preparation, 4 = Analyse

    Returns:
        html.Div containing the step indicator row
    """
    steps = [
        {"num": "1", "label": "Configure"},
        {"num": "2", "label": "Watchlist"},
        {"num": "3", "label": "Prepare"},
        {"num": "4", "label": "Analyse", "icon": "bi-play-fill"},
    ]

    children = []
    for i, step in enumerate(steps):
        step_num = i + 1

        # Determine colours
        if step_num < active_step:
            bg = "#28a745"    # success green
            fg = "white"
            label_cls = "text-success mt-1 fw-bold"
        elif step_num == active_step:
            bg = "#007bff"    # primary blue
            fg = "white"
            label_cls = "fw-bold text-primary mt-1"
        else:
            bg = "#e9ecef"    # secondary grey
            fg = "#6c757d"
            label_cls = "text-muted mt-1"

        # Circle content
        if step.get("icon") and step_num != active_step and step_num > active_step:
            circle_content = html.I(className=f"bi {step['icon']}",
                                    style={"fontSize": "0.8rem"})
        elif step_num < active_step:
            circle_content = html.I(className="bi bi-check",
                                    style={"fontSize": "0.9rem"})
        else:
            circle_content = html.Span(step["num"],
                                       style={"fontSize": "0.8rem", "fontWeight": "bold"})

        circle = html.Div([
            circle_content,
        ], className="d-flex align-items-center justify-content-center",
           style={
               "width": "28px", "height": "28px",
               "borderRadius": "50%",
               "backgroundColor": bg,
               "color": fg,
           })

        col = dbc.Col([
            html.Div([
                circle,
                html.Small(step["label"], className=label_cls),
            ], className="d-flex flex-column align-items-center"),
        ], className="text-center", width=True)

        children.append(col)

        # Arrow between steps (not after last)
        if step_num < len(steps):
            arrow_color = "text-success" if step_num < active_step else "text-muted"
            arrow = dbc.Col([
                html.I(className=f"bi bi-chevron-right {arrow_color}",
                       style={"fontSize": "1.2rem"}),
            ], width="auto", className="d-flex align-items-center px-0")
            children.append(arrow)

    return html.Div([
        dbc.Row(children,
                className="g-0 align-items-center justify-content-center",
                style={"maxWidth": "500px", "margin": "0 auto"}),
    ], className="py-2 mb-3")


def StatusCard(
    title: str,
    value: str,
    status: str = "neutral",
    trend: Optional[str] = None,
    subtitle: str = "",
    card_id: Optional[str] = None
) -> dbc.Card:
    """
    Large metric card with traffic light coloring.

    Args:
        title: Card title (e.g., "Data Quality")
        value: Main display value (e.g., "95%")
        status: "success", "warning", "danger", "neutral"
        trend: "up", "down", or None
        subtitle: Explanatory text below value
        card_id: Optional ID for the card element

    Returns:
        dbc.Card component with colored border and large value display

    Example:
        >>> StatusCard(
        ...     title="Data Quality",
        ...     value="95%",
        ...     status="success",
        ...     trend="up",
        ...     subtitle="Excellent quality"
        ... )
    """
    # Map status to Bootstrap colors
    color_map = {
        "success": "success",
        "warning": "warning",
        "danger": "danger",
        "neutral": "secondary"
    }

    border_color = color_map.get(status, "secondary")

    # Trend indicator
    trend_icon = ""
    if trend == "up":
        trend_icon = html.Span("↑", className="text-success ms-2", style={"fontSize": "1.5rem"})
    elif trend == "down":
        trend_icon = html.Span("↓", className="text-danger ms-2", style={"fontSize": "1.5rem"})

    card_props = {"className": f"h-100 border-{border_color}", "style": {"borderWidth": "3px"}}
    if card_id:
        card_props["id"] = card_id

    return dbc.Card([
        dbc.CardBody([
            html.H6(title, className="text-muted mb-2"),
            html.Div([
                html.H2(value, className="mb-0 d-inline-block"),
                trend_icon
            ]),
            html.P(subtitle, className="text-muted small mb-0 mt-2") if subtitle else html.Div()
        ])
    ], **card_props)


def AlertBanner(
    message: str,
    severity: str = "info",
    dismissible: bool = True,
    banner_id: Optional[str] = None
) -> dbc.Alert:
    """
    Top-of-page alert banner.

    Args:
        message: Alert text in plain language
        severity: "success", "info", "warning", "danger"
        dismissible: Can user close it?
        banner_id: Optional ID for the alert element

    Returns:
        dbc.Alert component with appropriate styling

    Example:
        >>> AlertBanner(
        ...     message="Analysis is running smoothly",
        ...     severity="success",
        ...     dismissible=True
        ... )
    """
    alert_props = {
        "children": message,
        "color": severity,
        "dismissible": dismissible,
        "className": "mb-3"
    }

    if banner_id:
        alert_props["id"] = banner_id

    return dbc.Alert(**alert_props)


def ProgressRing(
    value: int,
    max_value: int,
    label: str,
    color: str = "primary",
    show_percentage: bool = True
) -> html.Div:
    """
    Circular progress indicator.

    Args:
        value: Current value
        max_value: Maximum value
        label: Text below the progress
        color: "primary", "success", "warning", "danger"
        show_percentage: Display percentage text

    Returns:
        html.Div containing circular progress visualization

    Example:
        >>> ProgressRing(
        ...     value=3,
        ...     max_value=12,
        ...     label="Samples processed",
        ...     color="primary"
        ... )
    """
    percentage = int((value / max_value * 100)) if max_value > 0 else 0

    # Use Bootstrap progress bar as circular approximation
    # In a full implementation, this would use CSS or a library for circular progress
    return html.Div([
        html.Div([
            html.H3(f"{percentage}%" if show_percentage else f"{value}/{max_value}",
                   className="mb-0"),
            html.P(label, className="small text-muted mb-0")
        ], className="text-center mb-2"),
        dbc.Progress(
            value=percentage,
            color=color,
            className="mb-2",
            style={"height": "8px"}
        )
    ], className="progress-ring-container")


def DataQualityMeter(
    score: int,
    show_label: bool = True,
    meter_id: Optional[str] = None
) -> html.Div:
    """
    Visual 0-100 quality score meter with color coding.

    Args:
        score: 0-100 quality score
        show_label: Display interpretation text
        meter_id: Optional ID for the meter container

    Returns:
        html.Div with colored progress bar and interpretation:
        - 90-100: Excellent (green)
        - 75-89: Good (light green/success)
        - 60-74: Fair (amber/warning)
        - <60: Poor (red/danger)

    Example:
        >>> DataQualityMeter(score=92)
        # Displays: "92 - Excellent" with green progress bar
    """
    # Determine color and label based on score
    if score >= 90:
        color = "success"
        label = "Excellent"
    elif score >= 75:
        color = "info"
        label = "Good"
    elif score >= 60:
        color = "warning"
        label = "Fair"
    else:
        color = "danger"
        label = "Poor"

    meter_props = {"className": "data-quality-meter"}
    if meter_id:
        meter_props["id"] = meter_id

    return html.Div([
        html.Div([
            html.Span(f"{score}", className="h4 mb-0 me-2"),
            html.Span(f"- {label}", className="text-muted") if show_label else html.Span()
        ], className="mb-2"),
        dbc.Progress(
            value=score,
            color=color,
            className="mb-0",
            style={"height": "20px"}
        )
    ], **meter_props)


def SampleStatusBadge(
    status: str,
    badge_id: Optional[str] = None
) -> dbc.Badge:
    """
    Color-coded status badge for samples.

    Args:
        status: "good", "review", "issue", "processing", "idle"
        badge_id: Optional ID for the badge

    Returns:
        dbc.Badge with appropriate icon, color, and text

    Example:
        >>> SampleStatusBadge(status="good")
        # Returns green badge with "Good" text
    """
    status_config = {
        "good": {"color": "success", "text": "Good", "icon": "✓"},
        "review": {"color": "warning", "text": "Needs Review", "icon": "⚠"},
        "issue": {"color": "danger", "text": "Issue Detected", "icon": "✗"},
        "processing": {"color": "primary", "text": "Processing", "icon": "⟳"},
        "idle": {"color": "secondary", "text": "Idle", "icon": "○"}
    }

    config = status_config.get(status, status_config["idle"])

    badge_props = {
        "children": f"{config['icon']} {config['text']}",
        "color": config["color"],
        "className": "px-3 py-2"
    }

    if badge_id:
        badge_props["id"] = badge_id

    return dbc.Badge(**badge_props)


def ActionButton(
    label: str,
    button_id: str,
    icon: Optional[str] = None,
    variant: str = "primary",
    size: str = "md",
    disabled: bool = False,
    loading: bool = False
) -> dbc.Button:
    """
    Prominent call-to-action button with optional loading state.

    Args:
        label: Button text in plain language
        button_id: Required ID for callbacks
        icon: Bootstrap icon class (e.g. "bi-play-fill")
        variant: "primary", "secondary", "success", "danger", "warning", "info"
        size: "sm", "md", "lg"
        disabled: Button disabled state
        loading: If True, shows a spinner and disables the button

    Returns:
        dbc.Button component

    Example:
        >>> ActionButton(
        ...     label="View Details",
        ...     button_id="view-details-btn",
        ...     variant="primary",
        ...     size="md"
        ... )
    """
    if loading:
        button_content = [
            dbc.Spinner(size="sm", spinner_class_name="me-2"),
            label
        ]
    elif icon:
        button_content = [
            html.I(className=f"bi {icon} me-2"),
            label
        ]
    else:
        button_content = label

    return dbc.Button(
        button_content,
        id=button_id,
        color=variant,
        size=size,
        disabled=disabled or loading
    )


def AlertListItem(
    message: str,
    severity: str = "info",
    timestamp: Optional[str] = None,
    action_button: Optional[Dict[str, Any]] = None
) -> dbc.ListGroupItem:
    """
    Single alert item for the alerts panel.

    Args:
        message: Alert message in plain language
        severity: "success", "info", "warning", "danger"
        timestamp: Optional timestamp string (e.g., "2 minutes ago")
        action_button: Optional dict with button config: {"label": "View", "id": "btn-id"}

    Returns:
        dbc.ListGroupItem with colored left border and optional action

    Example:
        >>> AlertListItem(
        ...     message="Low quality detected in sample 3",
        ...     severity="warning",
        ...     timestamp="5 min ago",
        ...     action_button={"label": "Review", "id": "review-sample-3"}
        ... )
    """
    color_map = {
        "success": "success",
        "info": "info",
        "warning": "warning",
        "danger": "danger"
    }

    color = color_map.get(severity, "info")

    # Icon mapping
    icon_map = {
        "success": "✓",
        "info": "ℹ",
        "warning": "⚠",
        "danger": "✗"
    }

    icon = icon_map.get(severity, "ℹ")

    content = [
        html.Div([
            html.Span(icon, className=f"text-{color} me-2 h5 mb-0"),
            html.Span(message, className="alert-message")
        ], className="d-flex align-items-start mb-1")
    ]

    if timestamp:
        content.append(
            html.Small(timestamp, className="text-muted")
        )

    if action_button:
        content.append(
            dbc.Button(
                action_button["label"],
                id=action_button["id"],
                size="sm",
                color="link",
                className="mt-2 p-0"
            )
        )

    return dbc.ListGroupItem(
        content,
        className=f"border-start border-{color} border-3"
    )


def StatCard(
    value: str,
    label: str,
    trend: Optional[str] = None,
    trend_value: Optional[str] = None,
    color: str = "primary"
) -> dbc.Card:
    """
    Compact statistic card for metrics grid.

    Args:
        value: Large display value (e.g., "1,234" or "95%")
        label: Description below value
        trend: "up" or "down"
        trend_value: Optional trend text (e.g., "+12%")
        color: "primary", "success", "warning", "danger", "info", "secondary"

    Returns:
        dbc.Card with large number and optional trend indicator

    Example:
        >>> StatCard(
        ...     value="1,234",
        ...     label="Total Reads",
        ...     trend="up",
        ...     trend_value="+12%",
        ...     color="primary"
        ... )
    """
    trend_display = None
    if trend and trend_value:
        trend_color = "success" if trend == "up" else "danger"
        trend_icon = "↑" if trend == "up" else "↓"
        trend_display = html.Span([
            html.Span(trend_icon, className=f"text-{trend_color}"),
            html.Span(f" {trend_value}", className=f"text-{trend_color} small")
        ], className="ms-2")

    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.H3(value, className="mb-0 d-inline-block", style={"color": f"var(--bs-{color})"}),
                trend_display if trend_display else html.Span()
            ]),
            html.P(label, className="text-muted small mb-0 mt-2")
        ])
    ], className="h-100 text-center")


def QualityScoreBadge(
    q_score: float,
    badge_id: Optional[str] = None
) -> dbc.Badge:
    """
    Color-coded Q-score badge for nanopore data quality.

    Args:
        q_score: Mean quality score from NanoPlot
        badge_id: Optional ID for the badge

    Returns:
        dbc.Badge with color based on Q-score thresholds:
        - Q20+: Excellent (green/success)
        - Q15-19: Good (info/blue)
        - Q10-14: Fair (warning/amber)
        - <Q10: Poor (danger/red)

    Example:
        >>> QualityScoreBadge(q_score=13.5)
        # Returns amber badge with "Q13.5" text
    """
    if q_score >= 20:
        color = "success"
        label = "Excellent"
    elif q_score >= 15:
        color = "info"
        label = "Good"
    elif q_score >= 10:
        color = "warning"
        label = "Fair"
    else:
        color = "danger"
        label = "Poor"

    badge_props = {
        "children": f"Q{q_score:.1f} - {label}",
        "color": color,
        "className": "px-3 py-2"
    }

    if badge_id:
        badge_props["id"] = badge_id

    return dbc.Badge(**badge_props)


def N50Badge(
    n50_value: int,
    badge_id: Optional[str] = None
) -> dbc.Badge:
    """
    N50 read length badge with color coding.

    Args:
        n50_value: Read length N50 value in base pairs
        badge_id: Optional ID for the badge

    Returns:
        dbc.Badge with color based on N50 thresholds:
        - 5000+: Excellent (green/success)
        - 2000-4999: Good (info/blue)
        - 1000-1999: Fair (warning/amber)
        - <1000: Short (danger/red)

    Example:
        >>> N50Badge(n50_value=4845)
        # Returns blue badge with "N50: 4.8 kb" text
    """
    if n50_value >= 5000:
        color = "success"
        label = "Long"
    elif n50_value >= 2000:
        color = "info"
        label = "Medium"
    elif n50_value >= 1000:
        color = "warning"
        label = "Short"
    else:
        color = "danger"
        label = "Very Short"

    # Format as kb for readability
    if n50_value >= 1000:
        display = f"N50: {n50_value/1000:.1f} kb"
    else:
        display = f"N50: {n50_value} bp"

    badge_props = {
        "children": f"{display} - {label}",
        "color": color,
        "className": "px-3 py-2"
    }

    if badge_id:
        badge_props["id"] = badge_id

    return dbc.Badge(**badge_props)


def ClassificationRateBadge(
    classified_reads: int,
    total_reads: int,
    badge_id: Optional[str] = None
) -> dbc.Badge:
    """
    Classification rate badge showing percentage of reads classified.

    Args:
        classified_reads: Number of reads with taxonomic classification
        total_reads: Total number of reads
        badge_id: Optional ID for the badge

    Returns:
        dbc.Badge with color based on classification rate:
        - 80%+: High (green/success)
        - 50-79%: Medium (info/blue)
        - 20-49%: Low (warning/amber)
        - <20%: Very Low (danger/red)

    Example:
        >>> ClassificationRateBadge(classified_reads=12000, total_reads=14695)
        # Returns green badge with "81.7% classified" text
    """
    if total_reads <= 0:
        rate = 0
    else:
        rate = (classified_reads / total_reads) * 100

    if rate >= 80:
        color = "success"
        label = "High"
    elif rate >= 50:
        color = "info"
        label = "Medium"
    elif rate >= 20:
        color = "warning"
        label = "Low"
    else:
        color = "danger"
        label = "Very Low"

    badge_props = {
        "children": f"{rate:.1f}% classified - {label}",
        "color": color,
        "className": "px-3 py-2"
    }

    if badge_id:
        badge_props["id"] = badge_id

    return dbc.Badge(**badge_props)


def MetricsRow(
    metrics: List[Dict[str, Any]]
) -> dbc.Row:
    """
    Row of metric cards for dashboard display.

    Args:
        metrics: List of dicts with keys:
            - value: Display value (str)
            - label: Metric name (str)
            - color: Bootstrap color (str, default "primary")
            - icon: Optional icon character (str)

    Returns:
        dbc.Row with evenly-spaced metric cards

    Example:
        >>> MetricsRow([
        ...     {"value": "14,695", "label": "Total Reads", "color": "primary"},
        ...     {"value": "57.5 Mb", "label": "Total Bases", "color": "success"},
        ...     {"value": "Q13.5", "label": "Mean Quality", "color": "info"}
        ... ])
    """
    cols = []
    for metric in metrics:
        card = dbc.Card([
            dbc.CardBody([
                html.H4(
                    metric.get("value", "N/A"),
                    className="mb-1",
                    style={"color": f"var(--bs-{metric.get('color', 'primary')})"}
                ),
                html.P(metric.get("label", ""), className="text-muted small mb-0")
            ], className="text-center py-2")
        ], className="h-100")
        cols.append(dbc.Col(card, md=12 // len(metrics), className="mb-2"))

    return dbc.Row(cols, className="g-2")


def EmptyStateMessage(
    title: str = "No Data Available",
    message: str = "Start an analysis to see results here",
    icon: str = "bi-inbox",
    action_button: Optional[Dict[str, Any]] = None
) -> html.Div:
    """
    Consistent empty state placeholder for use across all tabs.

    Use this component whenever a section has no data to display,
    instead of creating ad-hoc empty state messages.

    Args:
        title: Main heading
        message: Descriptive text explaining what the user can do
        icon: Bootstrap icon class (without 'bi' prefix is also accepted).
              Common options: "bi-inbox", "bi-bar-chart", "bi-clipboard-data",
              "bi-hourglass", "bi-shield-check", "bi-file-earmark-text"
        action_button: Optional dict with button config: {"label": "Start", "id": "btn-id"}

    Returns:
        html.Div with centered empty state message

    Example:
        >>> EmptyStateMessage(
        ...     title="No Samples Detected",
        ...     message="Upload sequence data to begin",
        ...     icon="bi-collection",
        ...     action_button={"label": "Upload Data", "id": "upload-btn"}
        ... )
    """
    # Normalize icon class
    icon_class = icon if icon.startswith("bi-") else f"bi-{icon}"

    content = [
        html.I(className=f"bi {icon_class} text-muted mb-3",
               style={"fontSize": "3rem"}),
        html.H5(title, className="text-muted mb-2"),
        html.P(message, className="text-muted small", style={"maxWidth": "400px"})
    ]

    if action_button:
        content.append(
            dbc.Button(
                action_button["label"],
                id=action_button["id"],
                color="primary",
                className="mt-3"
            )
        )

    return html.Div(
        content,
        className="text-center py-5",
        style={"minHeight": "250px", "display": "flex", "flexDirection": "column",
               "justifyContent": "center", "alignItems": "center"}
    )


def LastUpdatedBadge(
    timestamp: Optional[str] = None,
    stale: bool = False,
    badge_id: Optional[str] = None
) -> html.Span:
    """
    Small muted text showing when data was last updated.

    Args:
        timestamp: ISO format timestamp string, or None for "never"
        stale: If True, badge turns amber with stale warning
        badge_id: Optional ID for callback targeting

    Returns:
        html.Span with "Updated: HH:MM:SS" or stale warning
    """
    props = {"className": "text-muted small", "style": {"fontSize": "0.75rem"}}
    if badge_id:
        props["id"] = badge_id

    if not timestamp:
        return html.Span([
            html.I(className="bi bi-clock me-1"),
            "No data yet"
        ], **props)

    try:
        dt = datetime.fromisoformat(timestamp)
        time_str = dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        time_str = str(timestamp)

    if stale:
        props["className"] = "text-warning small fw-bold"
        return html.Span([
            html.I(className="bi bi-exclamation-triangle me-1"),
            f"Data may be stale (last: {time_str})"
        ], **props)

    return html.Span([
        html.I(className="bi bi-clock me-1"),
        f"Updated: {time_str}"
    ], **props)


# =============================================================================
# Shared DataTable Styling
# =============================================================================

# Base styles shared by all DataTables in the application.
# Using a shared definition avoids drift between tabs.

TABLE_STYLE_CELL = {
    "textAlign": "left",
    "padding": "12px",
    "fontSize": "14px",
}

TABLE_STYLE_HEADER = {
    "fontWeight": "bold",
    "backgroundColor": "#f8f9fa",
    "borderBottom": "2px solid #dee2e6",
}

# Status-row colour palette (Bootstrap semantic colours).
STATUS_COLORS = {
    "success": {"backgroundColor": "#d4edda", "color": "#155724"},
    "warning": {"backgroundColor": "#fff3cd", "color": "#856404"},
    "danger":  {"backgroundColor": "#f8d7da", "color": "#721c24"},
    "info":    {"backgroundColor": "#d1ecf1", "color": "#17a2b8"},
    "muted":   {"backgroundColor": "#e2e3e5", "color": "#383d41"},
}


def status_conditional_style(
    column_id: str = "status",
    mapping: Optional[Dict[str, str]] = None,
    use_border: bool = False,
) -> List[Dict[str, Any]]:
    """
    Generate ``style_data_conditional`` rules for a status column.

    Args:
        column_id: Column whose content is tested.
        mapping: Dict mapping filter substring to STATUS_COLORS key.
                 Defaults to common status words.
        use_border: If True, add a left-border accent (dashboard style).

    Returns:
        List of conditional style dicts ready for DataTable.
    """
    if mapping is None:
        mapping = {
            "Complete": "success",
            "Good": "success",
            "Processing": "warning",
            "Review": "warning",
            "Error": "danger",
            "Issue": "danger",
            "Pending": "info",
            "No Data": "muted",
        }

    rules: List[Dict[str, Any]] = []
    for keyword, palette_key in mapping.items():
        colors = STATUS_COLORS.get(palette_key, STATUS_COLORS["muted"])
        rule: Dict[str, Any] = {
            "if": {
                "filter_query": f"{{{column_id}}} contains '{keyword}'",
                "column_id": column_id,
            },
            **colors,
            "fontWeight": "bold",
        }
        if use_border:
            border_color = {
                "success": "#28a745", "warning": "#ffc107",
                "danger": "#dc3545", "info": "#17a2b8", "muted": "#6c757d",
            }.get(palette_key, "#6c757d")
            rule["borderLeft"] = f"4px solid {border_color}"
        rules.append(rule)
    return rules
