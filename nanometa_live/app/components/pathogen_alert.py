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
# Text token #664d03 is the CLAUDE.md-locked amber. The earlier
# #856404 here was Bootstrap's amber-on-amber default, which only
# clears AA at ~4.2:1 -- borderline for chip-size text.
_CHIP_COLORS = {
    "critical": ("#f8d7da", "rgba(114,28,36,0.35)", "#721c24"),
    "high":     ("#fff3cd", "rgba(102,77,3,0.35)",  "#664d03"),
    "watched":  ("#d1ecf1", "rgba(12,84,96,0.35)",  "#0c5460"),
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

    Suppression rule:
      - Returns None when samples is empty.
      - A "watched" hit spanning more than one sample collapses to a single
        count pill with the full list in a popover. Per-sample chips are too
        heavy for a moderate hit, but suppressing the row entirely (the
        original behaviour) left a multi-barcode positive with no attribution
        at all.

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

    # A multi-sample watched hit is summarised as a count pill rather than a
    # chip per barcode.
    summarise_only = tier == "watched" and len(samples) > 1
    if summarise_only:
        max_inline = 0

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
        pill_label = (
            f"{len(samples)} samples" if summarise_only else f"+{overflow} more"
        )
        chips.append(
            html.Span(
                pill_label,
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


# Threat level definitions with visual specifications.
# Derived from the single threat-level definition in
# core/config/threat_levels.py (2026-08-17 reaudit: this was one of seven
# independent, mutually disagreeing maps). Labels use the shared alias set
# (CRITICAL / HIGH RISK / MODERATE / LOW -- the old WATCH/INFO card labels
# were a fourth vocabulary for the same field), text colors are the
# AA-tightened text_hex values, and the border carries the level's
# identity color.
from nanometa_live.core.config.threat_levels import (
    THREAT_LEVELS as _CORE_THREAT_LEVELS,
)

THREAT_LEVELS = {
    level: {
        "label": info["alias"],
        "color": info["text_hex"],
        "bg_color": info["bg_hex"],
        "border_color": info["hex"],
        "icon": info["icon"],
        "description": info["meaning"],
        "action": info["action"],
    }
    for level, info in _CORE_THREAT_LEVELS.items()
}


# Validation status -> badge appearance.
# Used by the three pathogen-alert components to show whether the
# detection has been confirmed by the BLAST/minimap2 validation
# subworkflow (run inside nanometanf with -resume on the dashboard's
# Validate flow). Tokens align with the WCAG-AA palette tightened on
# 2026-04-29 (#155724 dark green, #664d03 dark amber, #721c24 dark red,
# #6c757d slate-grey for the pending state).
_VALIDATION_BADGE_STYLES = {
    "confirmed": {
        "label": "Validated",
        "icon": "bi-shield-check",
        "bg":   "#d4edda",
        "fg":   "#155724",
        "tooltip": "Sequences confirmed by reference-genome comparison",
    },
    "validated": {  # alias produced by ValidationStatus.status_display
        "label": "Validated",
        "icon": "bi-shield-check",
        "bg":   "#d4edda",
        "fg":   "#155724",
        "tooltip": "Sequences confirmed by reference-genome comparison",
    },
    "partial": {
        "label": "Partial",
        "icon": "bi-shield-exclamation",
        "bg":   "#fff3cd",
        "fg":   "#664d03",
        "tooltip": "Some samples confirmed; review per-sample detail",
    },
    "uncertain": {
        "label": "Partial",
        "icon": "bi-shield-exclamation",
        "bg":   "#fff3cd",
        "fg":   "#664d03",
        "tooltip": "Mixed validation outcome; review per-sample detail",
    },
    "low": {
        "label": "Not validated",
        "icon": "bi-shield-x",
        "bg":   "#f8d7da",
        "fg":   "#721c24",
        "tooltip": "Below validation threshold; treat with caution",
    },
    "failed": {
        "label": "Validation failed",
        "icon": "bi-shield-slash",
        "bg":   "#f8d7da",
        "fg":   "#721c24",
        "tooltip": "Validation pipeline error; check pipeline logs",
    },
    "pending": {
        "label": "Pending",
        "icon": "bi-hourglass-split",
        "bg":   "#e9ecef",
        "fg":   "#495057",
        "tooltip": (
            "Validation has run for other detections in this run, but "
            "this one has not been confirmed yet. Click Validate on the "
            "Organisms tab to add it."
        ),
    },
}


def _validation_badge(
    validation: Optional[Dict[str, Any]],
    *,
    show_identity: bool = True,
    badge_id: Optional[str] = None,
) -> html.Span:
    """Build a small validation badge for a pathogen-alert card.

    Returns ``html.Span()`` (an empty span) when ``validation`` is None,
    so callers can drop the result into their layout unconditionally
    without checking.

    Args:
        validation: Output of ``_summarise_validation_for_taxid`` -- or
            ``None`` to render nothing.
        show_identity: When True (default) and the badge is "Validated"
            or "Partial", append the average identity (e.g. "Validated
            95%"). The "Not validated" / "Pending" / "Failed" badges
            never show an identity number.
        badge_id: Optional component id for the wrapping span; useful
            for testing.

    Returns:
        html.Span containing an icon + status label, or an empty span.
    """
    if not validation:
        return html.Span()

    status = validation.get("status", "no_data")
    style = _VALIDATION_BADGE_STYLES.get(status)
    if style is None:
        return html.Span()

    label = style["label"]
    if show_identity and status in ("confirmed", "validated", "partial", "uncertain"):
        identity = validation.get("identity") or 0.0
        if identity > 0:
            label = f"{label} {identity:.0f}%"

    n_validated = validation.get("n_validated", 0)
    n_samples = validation.get("n_samples", 0)
    method = validation.get("method", "")
    detail_lines = [style.get("tooltip", "")]
    if n_samples > 0:
        if n_validated == n_samples:
            detail_lines.append(f"{n_validated}/{n_samples} samples have validation results")
        else:
            detail_lines.append(
                f"{n_validated} of {n_samples} samples have validation results"
            )
    if method:
        detail_lines.append(f"Method: {method}")
    tooltip_text = " . ".join(s for s in detail_lines if s)

    span_id = badge_id or f"validation-badge-{abs(hash(tooltip_text)) & 0xffff:x}"
    span = html.Span(
        [
            html.I(className=f"bi {style['icon']} me-1"),
            label,
        ],
        id=span_id,
        title=tooltip_text,
        style={
            "backgroundColor": style["bg"],
            "color": style["fg"],
            "padding": "2px 8px",
            "borderRadius": "4px",
            "fontSize": "0.75rem",
            "fontWeight": 600,
            "marginLeft": "8px",
            "verticalAlign": "middle",
            "display": "inline-block",
        },
    )
    return span


def CriticalPathogenAlert(
    pathogen_name: str,
    common_name: Optional[str] = None,
    read_count: int = 0,
    abundance_pct: float = 0.0,
    confidence: str = "HIGH",
    blast_verified: bool = False,
    taxid: Optional[int] = None,
    recommendation: Optional[str] = None,
    samples: Optional[List[Dict[str, Any]]] = None,
    validation: Optional[Dict[str, Any]] = None,
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

    # Validation badge built from cumulative validation_results.json --
    # operators see at a glance whether this critical alert was confirmed
    # or rejected by the BLAST/minimap2 validation flow. Empty span when
    # validation has not run for this run.
    validation_badge = _validation_badge(validation)

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
                        title=threat["description"],
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
                    ),
                    validation_badge,
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
    samples: Optional[List[Dict[str, Any]]] = None,
    validation: Optional[Dict[str, Any]] = None,
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
                        title=threat["description"],
                        className="fw-bold me-2",
                        style={"color": threat["color"]}
                    ),
                    html.Span(
                        name_display,
                        style={"fontStyle": "italic"}
                    ),
                    _validation_badge(validation),
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
               # 6px left-border + 8px radius matches the verdict
               # banner and OrganismCard treatment so the dashboard
               # speaks one visual dialect for all primary cards.
               "borderLeft": f"6px solid {threat['border_color']}",
               "borderRadius": "8px"
           })
    ], className="mb-3", role="alert")


def WatchedSpeciesAlert(
    pathogen_name: str,
    read_count: int = 0,
    abundance_pct: float = 0.0,
    taxid: Optional[int] = None,
    samples: Optional[List[Dict[str, Any]]] = None,
    validation: Optional[Dict[str, Any]] = None,
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
                title=threat["description"],
                className="fw-semibold me-2",
                style={"color": threat["color"]}
            ),
            html.Span(pathogen_name, style={"fontStyle": "italic"}),
            html.Span(f" - {read_count:,} matches", className="text-muted ms-2"),
            _validation_badge(validation),
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
                # 6px left-border + 8px radius matches the
                # CriticalPathogenAlert and HighRiskPathogenAlert
                # treatment. Watched species is a smaller card but
                # uses the same accent thickness so all three pathogen
                # tiers share the same visual language.
                "borderLeft": f"6px solid {threat['border_color']}",
                "borderRadius": "8px",
                "fontSize": "14px"
            }
        )
    ], className="mb-2")


def _calculate_confidence(pathogen: Dict[str, Any]) -> str:
    """Calculate confidence level based on read count and other metrics."""
    reads = pathogen.get("reads", 0)

    if reads >= 100:
        return "HIGH"
    elif reads >= 20:
        return "MEDIUM"
    else:
        return "LOW"
