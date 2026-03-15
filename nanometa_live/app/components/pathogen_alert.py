"""
Pathogen Alert Components for Nanometa Live.

Provides prominent, unmissable alert banners for dangerous pathogen detection.
Designed for non-expert operators who need immediate visual feedback on threats.
"""

from typing import Optional, List, Dict, Any
from dash import html
import dash_bootstrap_components as dbc


# Threat level definitions with visual specifications
THREAT_LEVELS = {
    "critical": {
        "label": "CRITICAL",
        "color": "#8b0000",
        "bg_color": "#f8d7da",
        "border_color": "#8b0000",
        "icon": "bi-radioactive",
        "description": "Dangerous organism requiring immediate action",
        "action": "Contact your safety officer immediately"
    },
    "high": {
        "label": "HIGH RISK",
        "color": "#dc3545",
        "bg_color": "#f8d7da",
        "border_color": "#dc3545",
        "icon": "bi-exclamation-triangle-fill",
        "description": "High-risk organism of concern",
        "action": "Follow your safety protocols"
    },
    "moderate": {
        "label": "WATCH",
        "color": "#fd7e14",
        "bg_color": "#fff3cd",
        "border_color": "#fd7e14",
        "icon": "bi-eye-fill",
        "description": "Monitored species detected",
        "action": "Document and monitor"
    },
    "low": {
        "label": "INFO",
        "color": "#17a2b8",
        "bg_color": "#d1ecf1",
        "border_color": "#17a2b8",
        "icon": "bi-info-circle-fill",
        "description": "Species of interest noted",
        "action": "No immediate action required"
    }
}


def CriticalPathogenAlert(
    pathogen_name: str,
    common_name: Optional[str] = None,
    read_count: int = 0,
    abundance_pct: float = 0.0,
    confidence: str = "HIGH",
    blast_verified: bool = False,
    taxid: Optional[int] = None,
    recommendation: Optional[str] = None
) -> html.Div:
    """
    Full-width critical pathogen alert banner.

    Designed to be unmissable with:
    - Large biohazard icon in circular container
    - Prominent pathogen name (scientific + common)
    - Key metrics (reads, abundance, confidence)
    - Clear action recommendation
    - Acknowledgment button

    Args:
        pathogen_name: Scientific name of the pathogen
        common_name: Common name (e.g., "Anthrax")
        read_count: Number of reads classified to this organism
        abundance_pct: Relative abundance as percentage
        confidence: Confidence level (HIGH, MEDIUM, LOW)
        blast_verified: Whether BLAST validation confirmed identity
        taxid: NCBI taxonomy ID
        recommendation: Custom action recommendation

    Returns:
        Dash HTML Div containing the alert banner
    """
    threat = THREAT_LEVELS["critical"]

    # Build pathogen name display
    name_display = [
        html.Span(
            pathogen_name,
            className="pathogen-name",
            style={"fontStyle": "italic", "fontWeight": "bold"}
        )
    ]
    if common_name:
        name_display.append(
            html.Span(
                f" ({common_name})",
                className="pathogen-common-name",
                style={"fontStyle": "normal", "color": "#6c757d"}
            )
        )

    # Build metric badges
    metrics = [
        dbc.Badge(
            f"{read_count:,} DNA matches",
            color="light",
            text_color="dark",
            className="me-2"
        ),
        dbc.Badge(
            f"{abundance_pct:.2f}% of sample",
            color="light",
            text_color="dark",
            className="me-2"
        ),
        dbc.Badge(
            f"{confidence} confidence",
            color="success" if confidence == "HIGH" else "warning",
            className="me-2"
        )
    ]

    if blast_verified:
        metrics.append(
            dbc.Badge(
                [html.I(className="bi bi-check-circle me-1"), "BLAST Verified"],
                color="success",
                className="me-2"
            )
        )

    if taxid:
        metrics.append(
            dbc.Badge(
                f"TaxID: {taxid}",
                color="secondary",
                className="me-2"
            )
        )

    # Default recommendation if not provided
    action_text = recommendation or threat["action"]

    return html.Div([
        html.Div([
            # Icon section
            html.Div([
                html.I(
                    className=f"bi {threat['icon']}",
                    style={
                        "fontSize": "48px",
                        "color": "white"
                    }
                )
            ], className="pathogen-alert-icon-container"),

            # Content section
            html.Div([
                # Severity label
                html.Div([
                    html.Span(
                        threat["label"],
                        className="text-uppercase fw-bold",
                        style={
                            "color": threat["color"],
                            "fontSize": "12px",
                            "letterSpacing": "0.1em"
                        }
                    ),
                    html.Span(
                        " - PATHOGEN DETECTED",
                        className="text-uppercase",
                        style={
                            "color": "#6c757d",
                            "fontSize": "12px",
                            "letterSpacing": "0.05em"
                        }
                    )
                ], className="mb-1"),

                # Pathogen name
                html.H4(
                    name_display,
                    className="mb-2",
                    style={"fontSize": "1.5rem", "marginBottom": "0.5rem"}
                ),

                # Metrics
                html.Div(metrics, className="mb-3"),

                # Confidence bar
                html.Div([
                    html.Small("Detection certainty", className="text-muted me-2"),
                    dbc.Progress(
                        value=100 if confidence == "HIGH" else 60 if confidence == "MEDIUM" else 25,
                        color="success" if confidence == "HIGH" else "warning" if confidence == "MEDIUM" else "danger",
                        style={"height": "6px", "flex": "1"},
                        className="my-1"
                    ),
                    html.Small(confidence, className="ms-2 fw-semibold")
                ], className="d-flex align-items-center mb-3", style={"maxWidth": "300px"}),

                # Recommendation
                html.Div([
                    html.I(className="bi bi-exclamation-diamond me-2"),
                    html.Strong("Recommended Action: "),
                    html.Span(action_text)
                ], className="alert-recommendation", style={"fontSize": "14px"})

            ], className="flex-grow-1 ps-4"),

            # Action buttons
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-file-medical me-2"), "View Report"],
                    color="danger",
                    className="mb-2 w-100",
                    size="lg",
                    style={"padding": "10px 24px", "fontWeight": "bold"},
                    id={"type": "pathogen-view-report", "taxid": taxid or 0}
                ),
                dbc.Button(
                    [html.I(className="bi bi-check-lg me-2"), "Acknowledge"],
                    color="outline-danger",
                    className="w-100",
                    id={"type": "pathogen-acknowledge", "taxid": taxid or 0}
                )
            ], style={"minWidth": "150px"})

        ], className="pathogen-alert-critical d-flex align-items-start gap-3 p-4")
    ], className="mb-4", role="alert", **{"aria-live": "assertive"})


def HighRiskPathogenAlert(
    pathogen_name: str,
    common_name: Optional[str] = None,
    read_count: int = 0,
    abundance_pct: float = 0.0,
    confidence: str = "HIGH",
    taxid: Optional[int] = None,
    recommendation: Optional[str] = None
) -> html.Div:
    """
    High-risk pathogen alert (less severe than critical).

    Orange/amber styling with attention-grabbing but less alarming appearance.

    Args:
        pathogen_name: Scientific name of the pathogen
        common_name: Common name if available
        read_count: Number of reads detected
        abundance_pct: Abundance percentage
        confidence: Confidence level of detection
        taxid: NCBI taxonomy ID
        recommendation: Action recommendation for operator
    """
    threat = THREAT_LEVELS["high"]
    action_text = recommendation or threat["action"]

    name_display = pathogen_name
    if common_name:
        name_display = f"{pathogen_name} ({common_name})"

    return html.Div([
        html.Div([
            # Icon
            html.Div([
                html.I(
                    className=f"bi {threat['icon']}",
                    style={"fontSize": "32px", "color": threat["color"]}
                )
            ], className="me-3"),

            # Content
            html.Div([
                html.Div([
                    html.Span(
                        threat["label"],
                        className="fw-bold me-2",
                        style={"color": threat["color"]}
                    ),
                    html.Span(
                        name_display,
                        style={"fontStyle": "italic"}
                    )
                ]),
                html.Small([
                    f"{read_count:,} DNA matches | ",
                    f"{abundance_pct:.2f}% of sample | ",
                    f"{confidence} confidence"
                ], className="text-muted")
            ], className="flex-grow-1"),

            # Action buttons
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-file-medical me-1"), "Report"],
                    color="warning",
                    outline=True,
                    size="sm",
                    className="me-2",
                    id={"type": "pathogen-view-report", "taxid": taxid or 0}
                ),
                dbc.Button(
                    html.I(className="bi bi-x-lg"),
                    color="link",
                    className="text-muted",
                    id={"type": "pathogen-dismiss", "taxid": taxid or 0}
                )
            ], className="d-flex align-items-center")

        ], className="d-flex align-items-center p-3",
           style={
               "backgroundColor": threat["bg_color"],
               "borderLeft": f"4px solid {threat['border_color']}",
               "borderRadius": "4px"
           })
    ], className="mb-3", role="alert")


def WatchedSpeciesAlert(
    pathogen_name: str,
    read_count: int = 0,
    abundance_pct: float = 0.0,
    taxid: Optional[int] = None
) -> html.Div:
    """
    Alert for monitored/watched species (informational level).

    Blue styling for species that are being tracked but not immediately dangerous.
    """
    threat = THREAT_LEVELS["moderate"]

    return html.Div([
        html.Div([
            html.Div([
                html.I(
                    className=f"bi {threat['icon']} me-2",
                    style={"color": threat["color"]}
                ),
                html.Span(
                    threat["label"],
                    className="fw-semibold me-2",
                    style={"color": threat["color"]}
                ),
                html.Span(pathogen_name, style={"fontStyle": "italic"}),
                html.Span(f" - {read_count:,} matches", className="text-muted ms-2")
            ], className="flex-grow-1"),
            dbc.Button(
                [html.I(className="bi bi-file-text me-1"), "Details"],
                color="info",
                outline=True,
                size="sm",
                id={"type": "pathogen-view-report", "taxid": taxid or 0}
            )
        ], className="p-2 d-flex align-items-center",
           style={
               "backgroundColor": threat["bg_color"],
               "borderLeft": f"3px solid {threat['border_color']}",
               "borderRadius": "3px",
               "fontSize": "14px"
           })
    ], className="mb-2")


def PathogenAlertPanel(
    detected_pathogens: List[Dict[str, Any]],
    watched_species_config: List[Dict[str, Any]]
) -> html.Div:
    """
    Panel displaying all pathogen alerts grouped by severity.

    Args:
        detected_pathogens: List of detected organisms with their data
        watched_species_config: Configuration of watched species with threat levels

    Returns:
        Panel with alerts organized by severity
    """
    # Build lookup for watched species
    watched_lookup = {
        str(s.get("taxid", "")): s for s in watched_species_config
    }
    watched_names = {
        s.get("name", "").lower().strip(): s for s in watched_species_config
    }

    # Categorize detected pathogens
    critical_alerts = []
    high_alerts = []
    watch_alerts = []

    for pathogen in detected_pathogens:
        taxid = str(pathogen.get("taxid", ""))
        name = pathogen.get("name", "").lower().strip()

        # Check if this is a watched species
        watch_config = watched_lookup.get(taxid) or watched_names.get(name)

        if watch_config:
            threat_level = watch_config.get("threat_level", "moderate")

            alert_data = {
                "pathogen_name": pathogen.get("name", "Unknown"),
                "common_name": watch_config.get("common_name"),
                "read_count": pathogen.get("reads", 0),
                "abundance_pct": pathogen.get("abundance", 0.0),
                "confidence": _calculate_confidence(pathogen),
                "taxid": pathogen.get("taxid"),
                "blast_verified": pathogen.get("blast_verified", False)
            }

            if threat_level == "critical":
                critical_alerts.append(alert_data)
            elif threat_level in ["high", "high_risk"]:
                high_alerts.append(alert_data)
            else:
                watch_alerts.append(alert_data)

    # Build the panel
    alerts = []

    # Summary header showing counts by threat level
    total_detected = len(critical_alerts) + len(high_alerts) + len(watch_alerts)
    if total_detected > 0:
        summary_badges = []
        if critical_alerts:
            summary_badges.append(
                dbc.Badge(f"{len(critical_alerts)} Critical", color="danger", className="me-1")
            )
        if high_alerts:
            summary_badges.append(
                dbc.Badge(f"{len(high_alerts)} High", color="warning", className="me-1")
            )
        if watch_alerts:
            summary_badges.append(
                dbc.Badge(f"{len(watch_alerts)} Watch", color="info")
            )
        alerts.append(
            html.Div([
                html.Strong(f"{total_detected} watched species detected: "),
                *summary_badges,
            ], className="mb-3")
        )

    # Critical alerts first (most prominent)
    for alert in critical_alerts:
        alerts.append(CriticalPathogenAlert(**alert))

    # High risk alerts
    for alert in high_alerts:
        alerts.append(HighRiskPathogenAlert(**alert))

    # Watched species (if any)
    if watch_alerts:
        alerts.append(
            html.Div([
                html.H6([
                    html.I(className="bi bi-eye me-2"),
                    f"Watched Species ({len(watch_alerts)})"
                ], className="text-muted mb-2")
            ])
        )
        for alert in watch_alerts:
            alerts.append(WatchedSpeciesAlert(
                pathogen_name=alert["pathogen_name"],
                read_count=alert["read_count"],
                abundance_pct=alert["abundance_pct"],
                taxid=alert["taxid"]
            ))

    # If no alerts, show all-clear message
    if not alerts:
        alerts.append(
            html.Div([
                html.Div([
                    html.I(
                        className="bi bi-shield-check",
                        style={"fontSize": "48px", "color": "#28a745"}
                    )
                ], className="text-center mb-3"),
                html.H5(
                    "All Clear",
                    className="text-center text-success mb-2"
                ),
                html.P(
                    "No watched pathogens detected in current sample.",
                    className="text-center text-muted mb-0"
                )
            ], className="p-4",
               style={
                   "backgroundColor": "#d4edda",
                   "borderRadius": "8px",
                   "border": "1px solid #c3e6cb"
               })
        )

    return html.Div(
        alerts,
        id="pathogen-alert-panel",
        className="pathogen-alert-panel"
    )


def ThreatSummaryIndicator(
    critical_count: int = 0,
    high_count: int = 0,
    watch_count: int = 0
) -> html.Div:
    """
    Compact threat summary indicator for dashboard header.

    Shows counts of each threat level with color-coded badges.
    """
    if critical_count > 0:
        overall_status = "CRITICAL"
        overall_color = "#8b0000"
        bg_color = "#f8d7da"
    elif high_count > 0:
        overall_status = "HIGH RISK"
        overall_color = "#dc3545"
        bg_color = "#f8d7da"
    elif watch_count > 0:
        overall_status = "MONITORING"
        overall_color = "#fd7e14"
        bg_color = "#fff3cd"
    else:
        overall_status = "ALL CLEAR"
        overall_color = "#28a745"
        bg_color = "#d4edda"

    return html.Div([
        html.Div([
            html.Span(
                overall_status,
                className="fw-bold me-3",
                style={"color": overall_color}
            ),
            dbc.Badge(
                f"{critical_count} Critical",
                color="danger" if critical_count > 0 else "secondary",
                className="me-1"
            ),
            dbc.Badge(
                f"{high_count} High",
                color="warning" if high_count > 0 else "secondary",
                className="me-1"
            ),
            dbc.Badge(
                f"{watch_count} Watch",
                color="info" if watch_count > 0 else "secondary"
            )
        ], className="d-flex align-items-center p-2",
           style={
               "backgroundColor": bg_color,
               "borderRadius": "4px"
           })
    ], id="threat-summary-indicator")


def _calculate_confidence(pathogen: Dict[str, Any]) -> str:
    """Calculate confidence level based on read count and other metrics."""
    reads = pathogen.get("reads", 0)

    if reads >= 100:
        return "HIGH"
    elif reads >= 20:
        return "MEDIUM"
    else:
        return "LOW"
