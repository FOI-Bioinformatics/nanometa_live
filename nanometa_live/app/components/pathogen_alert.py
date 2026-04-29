"""
Pathogen Alert Components for Nanometa Live.

Provides prominent, unmissable alert banners for dangerous pathogen detection.
Designed for non-expert operators who need immediate visual feedback on threats.
"""

import hashlib
from typing import Optional, List, Dict, Any
from dash import html
import dash_bootstrap_components as dbc


def _attribution_pill_id(samples: List[Dict[str, Any]], tier: str) -> str:
    """Stable id used as the Popover target for the "+N more" pill.

    Hashing the (tier, sample-name list) gives a deterministic id that
    survives re-renders within a tick but is unique across distinct
    pathogen alert cards on the page. dbc.Popover requires the target
    to exist in the layout when the page renders, so the id must be
    embedded in the chip itself.
    """
    seed = tier + "|" + "|".join(s.get("sample", "") for s in samples)
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]
    return f"alert-attribution-pill-{digest}"


# --- Per-tier chip color tokens (bg / border / text) ---
_CHIP_COLORS = {
    "critical": ("#f8d7da", "rgba(114,28,36,0.35)", "#721c24"),
    "high":     ("#fff3cd", "rgba(133,100,4,0.35)",  "#856404"),
    "watched":  ("#d1ecf1", "rgba(12,84,96,0.35)",   "#0c5460"),
}
_CHIP_NC    = ("#e9ecef", "#ced4da", "#6c757d")   # negative-control override
_CHIP_MORE  = ("#e9ecef", "#ced4da", "#495057")   # "+X more" pill


def _render_sample_attribution(
    samples: Optional[List[Dict[str, Any]]],
    tier: str,
    max_inline: int = 3,
) -> Optional[html.Div]:
    """
    Render the "DETECTED IN:" attribution row for a pathogen alert card.

    Suppression rule (per design spec):
      - Returns None when samples is empty.
      - Returns None when tier is "watched" and len(samples) > 1.

    Chip colors are tier-specific with a negative-control override.
    Tooltip: "{reads} reads | {abundance}% of sample | #{rank} by read count"

    Args:
        samples: List of {sample, reads, abundance, is_negative_control} dicts,
                 already sorted descending by reads.
        tier:    "critical", "high", or "watched".
        max_inline: Maximum chips shown before a "+X more" pill (default 3).

    Returns:
        html.Div attribution row, or None when suppressed.
    """
    if not samples:
        return None

    # Suppression: watched tier with multiple samples shows no attribution row
    if tier == "watched" and len(samples) > 1:
        return None

    # Determine chip palette for this tier
    tier_key = tier if tier in _CHIP_COLORS else "watched"
    bg, border, text = _CHIP_COLORS[tier_key]

    chip_style_base = {
        "borderRadius": "3px",
        "fontSize": "10px",
        "fontWeight": "500",
        "padding": "2px 7px",
        "border": f"1px solid {border}",
        "display": "inline-block",
        "lineHeight": "1.4",
    }

    # Build chips (truncate at max_inline)
    visible = samples[:max_inline]
    overflow = len(samples) - max_inline

    chips = []
    for rank, s in enumerate(visible, start=1):
        reads = s.get("reads", 0)
        abund = s.get("abundance", 0.0)
        label = s.get("sample", "")
        is_nc = s.get("is_negative_control", False)

        if is_nc:
            chip_bg, chip_border, chip_text = _CHIP_NC
            label = f"{label} (NC)"
        else:
            chip_bg, chip_border, chip_text = bg, border, text

        tooltip = f"{reads:,} reads | {abund:.2f}% of sample | #{rank} by read count"

        chips.append(
            html.Span(
                label,
                title=tooltip,
                style={
                    **chip_style_base,
                    "backgroundColor": chip_bg,
                    "borderColor": chip_border,
                    "color": chip_text,
                }
            )
        )

    popover_components = []
    if overflow > 0:
        pill_bg, pill_border, pill_text = _CHIP_MORE
        pill_id = _attribution_pill_id(samples, tier_key)
        chips.append(
            html.Span(
                f"+{overflow} more",
                id=pill_id,
                title=(
                    f"Click to see all {len(samples)} samples where this "
                    f"pathogen was detected"
                ),
                style={
                    **chip_style_base,
                    "backgroundColor": pill_bg,
                    "borderColor": pill_border,
                    "color": pill_text,
                    "cursor": "pointer",
                    "textDecoration": "underline dotted",
                    "textUnderlineOffset": "2px",
                }
            )
        )
        # Popover lists every sample, not just the overflow. Operators
        # asking "which barcodes carry this pathogen?" want the complete
        # list, not the tail.
        popover_components.append(
            _build_attribution_popover(samples, pill_id, tier_key)
        )

    return html.Div(
        [
            html.Span(
                [
                    html.Span("DETECTED IN:", className="dashboard-attribution-label-full"),
                    html.Span("IN:", className="dashboard-attribution-label-short"),
                ]
            ),
            *chips,
            *popover_components,
        ],
        className="dashboard-attribution-row",
    )


def _build_attribution_popover(
    samples: List[Dict[str, Any]],
    target_id: str,
    tier_key: str,
) -> dbc.Popover:
    """Popover listing every triggering sample with reads + abundance.

    Hung off the "+N more" pill so an operator can answer the clinical
    question "which of 24 barcodes carries this pathogen?" Closes
    P0-T01 from docs/audit-2026-04-28-throughput-ux.md, where the pill
    was a non-interactive dead end.
    """
    rows = []
    for rank, s in enumerate(samples, start=1):
        sample_label = s.get("sample", "")
        reads = s.get("reads", 0)
        abund = s.get("abundance", 0.0)
        is_nc = s.get("is_negative_control", False)
        suffix = " (NC)" if is_nc else ""
        text_color = "#6c757d" if is_nc else None
        rows.append(
            html.Div(
                [
                    html.Span(
                        f"{rank}.",
                        style={
                            "display": "inline-block",
                            "width": "1.6em",
                            "color": "#6c757d",
                            "fontVariantNumeric": "tabular-nums",
                        },
                    ),
                    html.Span(
                        f"{sample_label}{suffix}",
                        style={
                            "fontWeight": "600",
                            "marginRight": "0.5em",
                            "color": text_color or "inherit",
                        },
                    ),
                    html.Span(
                        f"{reads:,} reads ({abund:.2f}%)",
                        style={"color": "#6c757d", "fontSize": "0.85em"},
                    ),
                ],
                style={"padding": "2px 0", "fontSize": "12px"},
            )
        )

    return dbc.Popover(
        [
            dbc.PopoverHeader(
                f"All {len(samples)} samples (sorted by read count)",
                style={"fontSize": "12px", "fontWeight": "600"},
            ),
            dbc.PopoverBody(
                rows,
                style={"maxHeight": "320px", "overflowY": "auto", "padding": "8px 12px"},
            ),
        ],
        target=target_id,
        trigger="legacy",
        placement="bottom",
        hide_arrow=False,
    )


# Threat level definitions with visual specifications
THREAT_LEVELS = {
    "critical": {
        "label": "CRITICAL",
        "color": "#8b0000",
        "bg_color": "#f8d7da",
        "border_color": "#8b0000",
        "icon": "bi-exclamation-octagon-fill",
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
    recommendation: Optional[str] = None,
    samples: Optional[List[Dict[str, Any]]] = None
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
                html.Span(
                    threat["icon"],
                    style={
                        "fontSize": "48px",
                        "color": "white"
                    }
                ) if not threat["icon"].startswith("bi-") else html.I(
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
                    style={"fontSize": "22px", "fontWeight": "600",
                           "marginBottom": "0.5rem"}
                ),

                # Metrics
                html.Div(metrics, className="mb-3"),

                # Per-sample attribution row (always visible for critical tier)
                *([attr_row] if (attr_row := _render_sample_attribution(samples or [], "critical")) else []),

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
    recommendation: Optional[str] = None,
    samples: Optional[List[Dict[str, Any]]] = None
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
        samples: Per-sample attribution list (sorted descending by reads)
    """
    threat = THREAT_LEVELS["high"]
    action_text = recommendation or threat["action"]

    name_display = pathogen_name
    if common_name:
        name_display = f"{pathogen_name} ({common_name})"

    attr_row = _render_sample_attribution(samples or [], "high")

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
                ], className="text-muted"),
                # Per-sample attribution row (always visible for high-risk tier)
                *([attr_row] if attr_row else []),
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
                    id={"type": "pathogen-dismiss", "taxid": taxid or 0},
                    title="Dismiss alert"
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
    taxid: Optional[int] = None,
    samples: Optional[List[Dict[str, Any]]] = None
) -> html.Div:
    """
    Alert for monitored/watched species (informational level).

    Blue styling for species that are being tracked but not immediately dangerous.

    Attribution display rules for watched tier (per design spec):
    - 2+ samples: row suppressed (too wide for the compact card).
    - Exactly 1 sample: single chip shown inline after a pipe divider.

    Args:
        pathogen_name: Scientific name of the organism
        read_count: Number of reads detected
        abundance_pct: Abundance percentage
        taxid: NCBI taxonomy ID
        samples: Per-sample attribution list (sorted descending by reads)
    """
    threat = THREAT_LEVELS["moderate"]

    # Attribution: suppressed for multi-sample by _render_sample_attribution;
    # for exactly 1 sample it returns the row which we render below the main line.
    attr_row = _render_sample_attribution(samples or [], "watched")

    main_row_children = [
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
    ]

    inner_children = [
        html.Div(main_row_children, className="d-flex align-items-center"),
        *([attr_row] if attr_row else []),
    ]

    return html.Div([
        html.Div(
            inner_children,
            className="p-2",
            style={
                "backgroundColor": threat["bg_color"],
                "borderLeft": f"3px solid {threat['border_color']}",
                "borderRadius": "3px",
                "fontSize": "14px"
            }
        )
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
