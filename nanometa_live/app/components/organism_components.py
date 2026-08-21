"""
Organism Display Components for Nanometa Live v2.0.

Visual, operator-friendly components for displaying organism information
in Main Results and Classification tabs.
"""

from typing import Optional, Dict, List
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go


def BlastValidationBadge(
    validation_data: Optional[Dict] = None
) -> Optional[html.Div]:
    """
    Create a BLAST validation badge showing verification status.

    Color coding:
    - Green (success): >= 80% validated
    - Amber (warning): 50-80% validated
    - Red (danger): < 50% validated
    - Gray: No validation data

    Args:
        validation_data: Dict with 'validated_reads', 'total_reads',
                        'validation_rate', and 'status' keys

    Returns:
        Badge component or None if no data
    """
    if validation_data is None:
        return None

    status = validation_data.get('status', 'no_data')
    validation_rate = validation_data.get('validation_rate', 0)
    validated_reads = validation_data.get('validated_reads', 0)
    total_reads = validation_data.get('total_reads', 0)

    # Status to color/icon mapping
    status_config = {
        'validated': {
            'color': 'success',
            'icon': 'check-circle-fill',
            'label': 'BLAST Verified'
        },
        'partial': {
            'color': 'warning',
            'icon': 'exclamation-circle-fill',
            'label': 'Partial Match'
        },
        'failed': {
            'color': 'danger',
            'icon': 'x-circle-fill',
            'label': 'Low Match'
        },
        'no_data': {
            'color': 'secondary',
            'icon': 'question-circle',
            'label': 'Not Verified'
        }
    }

    config = status_config.get(status, status_config['no_data'])

    # Format the display text
    if status == 'no_data':
        detail_text = "BLAST validation not available"
    else:
        detail_text = f"{validation_rate:.0f}% verified ({validated_reads:,} of {total_reads:,} reads)"

    return html.Div([
        dbc.Badge([
            html.I(className=f"bi bi-{config['icon']} me-1"),
            config['label']
        ],
            color=config['color'],
            className="me-2"
        ),
        html.Small(
            detail_text,
            className="text-muted",
            style={"fontSize": "12px"}
        )
    ], className="d-flex align-items-center mt-2")


def ValidationBadge(
    validation_data: Optional[Dict] = None,
    method: str = "blast"
) -> Optional[html.Div]:
    """
    Create a validation badge showing verification status for BLAST or minimap2.

    Args:
        validation_data: Dict with validation stats
        method: 'blast' or 'minimap2'

    Returns:
        Badge component or None if no data
    """
    if validation_data is None:
        return None

    status = validation_data.get('status', 'no_data')
    validation_rate = validation_data.get('validation_rate', 0)
    validated_reads = validation_data.get('validated_reads', 0)
    total_reads = validation_data.get('total_reads', 0)
    avg_mapq = validation_data.get('avg_mapq', 0)

    status_config = {
        'validated': {'color': 'success', 'icon': 'check-circle-fill'},
        'partial': {'color': 'warning', 'icon': 'exclamation-circle-fill'},
        'failed': {'color': 'danger', 'icon': 'x-circle-fill'},
        'no_data': {'color': 'secondary', 'icon': 'question-circle'},
    }
    config = status_config.get(status, status_config['no_data'])

    method_label = "minimap2" if method == "minimap2" else "BLAST"
    method_badge_color = "info" if method == "minimap2" else "warning"

    if status == 'no_data':
        detail_text = f"{method_label} validation not available"
    else:
        detail_text = f"{validation_rate:.0f}% ({validated_reads:,}/{total_reads:,})"
        if method == "minimap2" and avg_mapq > 0:
            detail_text += f" MapQ:{avg_mapq:.0f}"

    return html.Div([
        dbc.Badge([
            html.I(className=f"bi bi-{config['icon']} me-1"),
            method_label
        ],
            color=method_badge_color,
            className="me-1",
            style={"fontSize": "0.7rem"}
        ),
        dbc.Badge(
            f"{validation_rate:.0f}%" if status != 'no_data' else "N/A",
            color=config['color'],
            className="me-2",
            style={"fontSize": "0.7rem"}
        ),
        html.Small(
            detail_text,
            className="text-muted",
            style={"fontSize": "11px"}
        )
    ], className="d-flex align-items-center mt-1")


def DualValidationBadge(
    blast_data: Optional[Dict] = None,
    minimap2_data: Optional[Dict] = None
) -> Optional[html.Div]:
    """
    Create a compact dual validation badge showing both BLAST and minimap2 results.

    Args:
        blast_data: BLAST validation data
        minimap2_data: minimap2 validation data

    Returns:
        Badge component or None if no data
    """
    if blast_data is None and minimap2_data is None:
        return None

    badges = []
    if blast_data is not None:
        badges.append(ValidationBadge(blast_data, method="blast"))
    if minimap2_data is not None:
        badges.append(ValidationBadge(minimap2_data, method="minimap2"))

    if not badges:
        return None

    return html.Div(badges, className="mt-2")


def _render_validation_badges(validation_data: Optional[Dict] = None) -> Optional[html.Div]:
    """
    Render BLAST and/or minimap2 validation badges.

    If the validation data contains minimap2 fields, renders a dual badge.
    Otherwise falls back to the standard BLAST-only badge.

    Args:
        validation_data: Validation data dict, possibly containing minimap2_* keys

    Returns:
        Badge component(s) or None
    """
    if validation_data is None:
        return None

    has_minimap2 = validation_data.get('minimap2_validated_reads') is not None

    if has_minimap2:
        blast_data = validation_data
        mm2_data = {
            'status': validation_data.get('minimap2_status', 'no_data'),
            'validation_rate': validation_data.get('minimap2_validation_rate', 0),
            'validated_reads': validation_data.get('minimap2_validated_reads', 0),
            'total_reads': validation_data.get('total_reads', 0),
            'avg_mapq': validation_data.get('minimap2_avg_mapq', 0),
        }
        # Map status values
        if mm2_data['status'] == 'confirmed':
            mm2_data['status'] = 'validated'
        elif mm2_data['status'] == 'uncertain':
            mm2_data['status'] = 'partial'
        elif mm2_data['status'] == 'rejected':
            mm2_data['status'] = 'failed'

        return DualValidationBadge(blast_data=blast_data, minimap2_data=mm2_data)
    else:
        return BlastValidationBadge(validation_data)


def OrganismCard(
    name: str,
    abundance: float,
    read_count: int,
    confidence: str = "high",
    common_name: Optional[str] = None,
    taxid: Optional[int] = None,
    rank: str = "S",
    is_watched: bool = False,
    blast_validation: Optional[Dict] = None,
    show_validate_button: bool = False,
    on_demand_validation: Optional[Dict] = None,
    annotation: Optional[str] = None,
    threat_level: Optional[str] = None,
) -> dbc.Card:
    """
    Create a visual card for displaying organism information.

    Args:
        name: Scientific name of organism
        abundance: Percentage abundance (0-100)
        read_count: Number of DNA sequences
        confidence: Confidence level ("high", "medium", "low")
        common_name: Optional common name
        taxid: Optional taxonomy ID
        rank: Taxonomic rank (default: "S" for species)
        is_watched: Whether this organism is in the watchlist
        blast_validation: Optional BLAST validation data dict with keys:
            - validated_reads: Number of reads verified by BLAST
            - total_reads: Total reads for this species
            - validation_rate: Percentage verified (0-100)
            - status: 'validated', 'partial', 'failed', or 'no_data'
        show_validate_button: Show on-demand validation button (for unexpected organisms)
        on_demand_validation: Optional on-demand validation result data
        threat_level: Watchlist threat level (critical/high/moderate/low).
            Rendered as a badge on watched cards -- without it a select
            agent and a commensal looked identical here (2026-08-17
            reaudit). Hover shows the level's meaning.

    Returns:
        Organism card component

    Examples:
        >>> OrganismCard(
        ...     "Escherichia coli",
        ...     15.2,
        ...     12456,
        ...     confidence="high",
        ...     common_name="E. coli",
        ...     is_watched=True,
        ...     blast_validation={'validation_rate': 85, 'status': 'validated'}
        ... )
    """
    # Confidence badge styling
    # "none" = not detected (watchlist entry with 0 reads)
    confidence_colors = {
        "high": "success",
        "medium": "warning",
        "low": "danger",
        "none": "secondary"  # Gray for undetected
    }
    confidence_icons = {
        "high": "check-circle-fill",
        "medium": "dash-circle-fill",
        "low": "exclamation-triangle-fill",
        "none": "circle"  # Empty circle for undetected
    }
    confidence_labels = {
        "high": "High Confidence",
        "medium": "Medium Confidence",
        "low": "Low Confidence",
        "none": "Not Detected"
    }

    confidence_color = confidence_colors.get(confidence.lower(), "secondary")
    confidence_icon = confidence_icons.get(confidence.lower(), "question-circle")
    confidence_label = confidence_labels.get(confidence.lower(), "Unknown")

    # Check if this is an undetected species
    is_undetected = confidence.lower() == "none"

    # Format read count with thousands separator
    read_count_formatted = f"{read_count:,}" if read_count > 0 else "0"

    # Create abundance bar (visual percentage)
    abundance_bar_width = min(100, abundance)  # Cap at 100%

    # Card styling based on watched status and detection
    card_style = {"boxShadow": "var(--shadow-md)"}
    card_class = "mb-3"

    if is_undetected:
        # Undetected species - gray/muted styling
        card_style["borderColor"] = "#dee2e6"  # Light gray border
        card_style["borderWidth"] = "1px"
        card_style["backgroundColor"] = "#f8f9fa"  # Very light gray background
        card_style["opacity"] = "0.75"
        card_class = "mb-3"
    elif is_watched:
        # Detected and watched - highlight styling
        card_style["borderColor"] = "var(--status-warning)"
        card_style["borderWidth"] = "2px"
        card_style["backgroundColor"] = "var(--status-warning-bg)"
        card_class = "mb-3 border-warning"

    # Header icon (star for watched, empty circle for undetected watched, microbe for others)
    if is_watched and is_undetected:
        # Watched but not detected - gray star
        header_icon = html.I(
            className="bi bi-star me-2",
            style={"color": "#adb5bd", "fontSize": "20px"}
        )
    elif is_watched:
        # Watched and detected - filled star
        header_icon = html.I(
            className="bi bi-star-fill me-2",
            style={"color": "var(--status-warning)", "fontSize": "20px"}
        )
    else:
        header_icon = html.Span("", style={"fontSize": "24px", "marginRight": "12px"})

    # Determine badge and text based on detection status
    threat_badge_el = None
    if is_watched and threat_level:
        from nanometa_live.app.utils.threat_display import threat_badge
        threat_badge_el = threat_badge(threat_level, className="ms-2")

    if is_undetected and is_watched:
        status_badge = dbc.Badge("NOT DETECTED", color="secondary", className="ms-2")
        read_count_text = html.Div([
            html.Span("Not detected in this sample", className="text-muted")
        ], className="mb-2", style={"fontSize": "14px"})
        abundance_text = "Not detected"
        abundance_bar_color = "#dee2e6"  # Gray
    elif is_watched:
        status_badge = dbc.Badge("DETECTED", color="danger", className="ms-2")
        read_count_text = html.Div([
            html.Strong(read_count_formatted),
            html.Span(" DNA sequences identified", className="text-muted")
        ], className="mb-2", style={"fontSize": "14px"})
        abundance_text = f"{abundance:.1f}% of all DNA sequences"
        abundance_bar_color = "var(--status-warning)"
    else:
        status_badge = None
        read_count_text = html.Div([
            html.Strong(read_count_formatted),
            html.Span(" DNA sequences identified", className="text-muted")
        ], className="mb-2", style={"fontSize": "14px"})
        abundance_text = f"{abundance:.1f}% of all DNA sequences"
        abundance_bar_color = "var(--primary)"

    return dbc.Card([
        dbc.CardBody([
            # Organism name and icon
            html.Div([
                header_icon,
                html.Div([
                    html.H5(
                        name,
                        className="mb-1",
                        style={
                            "display": "inline-block",
                            "color": "var(--text-muted-inline)" if is_undetected else "inherit"
                        }
                    ),
                    html.Small(
                        f" ({common_name})" if common_name else "",
                        className="text-muted"
                    ),
                    status_badge,
                    threat_badge_el if threat_badge_el is not None else "",
                    html.Small(
                        annotation,
                        className="text-info fst-italic d-block"
                    ) if annotation else "",
                ], style={"display": "inline-block", "verticalAlign": "middle"})
            ], className="mb-3 d-flex align-items-center"),

            # Abundance bar (shown even for undetected, but gray/empty)
            html.Div([
                html.Div(
                    style={
                        "width": f"{max(abundance_bar_width, 0)}%" if not is_undetected else "0%",
                        "height": "12px",
                        "backgroundColor": abundance_bar_color,
                        "borderRadius": "6px",
                        "transition": "width 0.3s ease"
                    }
                ),
                html.Small(
                    abundance_text,
                    className="text-muted",
                    style={"marginTop": "4px", "display": "block"}
                )
            ], style={
                "backgroundColor": "var(--light)",
                "borderRadius": "6px",
                "marginBottom": "12px",
                "padding": "2px"
            }),

            # Read count
            read_count_text,

            # Confidence badge. The explanation is a native title attribute,
            # not a dbc.Tooltip: each Tooltip is a react-popper instance
            # with its own DOM listeners, and one per card (129 on a large
            # watchlist) froze the browser (audit 2026-08-21).
            html.Div([
                html.Span(
                    dbc.Badge([
                        html.I(className=f"bi bi-{confidence_icon} me-1"),
                        confidence_label
                    ],
                        color=confidence_color,
                        className="me-2",
                        id={"type": "confidence-badge", "taxid": taxid or 0},
                    ),
                    title=(
                        "Based on the number of matching DNA sequences. "
                        "More sequences means higher confidence that this "
                        "organism is truly present in the sample."
                    ),
                ),
                html.Small(
                    f"Identified at {_rank_to_plain_language(rank)} level",
                    className="text-muted"
                ) if rank and not is_undetected else None
            ], className="mb-2"),

            # Validation badge(s) for watched species
            _render_validation_badges(blast_validation) if blast_validation else None,

            # Spacer before action buttons
            html.Div(className="mb-3") if not blast_validation else html.Div(className="mb-3"),

            # Action buttons
            dbc.ButtonGroup([
                dbc.Button([
                    html.I(className="bi bi-info-circle me-1"),
                    "Details"
                ],
                    # Opens the same pathogen-report modal as the Dashboard's
                    # alert cards, but under its OWN id type. Sharing the alert
                    # cards' type put two components with the SAME dict id in
                    # the layout whenever an organism appeared on both surfaces
                    # (every watched detection); duplicate ids tear the
                    # n_clicks bookkeeping, so a genuine click arrived with a
                    # None triggered value and the modal callback's
                    # spurious-reopen guard swallowed it (2026-08-19
                    # bug-report reproduction).
                    id={"type": "organism-view-report", "taxid": taxid or 0},
                    color="primary",
                    outline=True,
                    size="sm"
                ),
                dbc.Button([
                    html.I(className="bi bi-star" if not is_watched else "bi bi-star-fill"),
                    " Watch" if not is_watched else " Watching"
                ],
                    id={"type": "toggle-watch", "taxid": taxid} if taxid else {"type": "toggle-watch", "name": name},
                    color="warning" if is_watched else "secondary",
                    outline=not is_watched,
                    size="sm"
                ),
                # On-demand validation button (for non-watched organisms with sufficient reads)
                dbc.Button([
                    html.I(className="bi bi-check2-square me-1"),
                    "Validate" if not on_demand_validation else f"{on_demand_validation.get('validation_rate', 0):.0f}%"
                ],
                    id={"type": "on-demand-validate", "taxid": taxid, "name": name} if taxid else None,
                    color="success" if on_demand_validation and on_demand_validation.get('validation_rate', 0) >= 80 else "info",
                    outline=not on_demand_validation,
                    size="sm",
                    title="Run BLAST validation for this organism"
                ) if show_validate_button and taxid and not is_watched else None
            ], size="sm")
        ])
    ], className=card_class, style=card_style)


def OrganismSummaryCard(
    total_organisms: int,
    total_reads: int,
    classification_rate: float,
    most_abundant: Optional[Dict[str, any]] = None
) -> dbc.Card:
    """
    Create summary card for organism overview.

    Args:
        total_organisms: Total number of unique organisms found
        total_reads: Total DNA sequences analyzed
        classification_rate: Percentage successfully classified
        most_abundant: Dict with "name" and "abundance" for top organism

    Returns:
        Summary card component
    """
    return dbc.Card([
        dbc.CardHeader(
            html.H4("Organism Analysis Summary", className="mb-0")
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.H2(str(total_organisms), className="mb-0", style={"color": "var(--primary)"}),
                        html.P("Organisms Found", className="text-muted mb-0")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(f"{total_reads:,}", className="mb-0", style={"color": "var(--primary)"}),
                        html.P("DNA Sequences Analyzed", className="text-muted mb-0")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(f"{classification_rate:.1f}%", className="mb-0", style={"color": "var(--status-good)"}),
                        html.P("Sequences Identified", className="text-muted mb-0",
                               id="summary-classification-rate"),
                        dbc.Tooltip(
                            "Percentage of DNA sequences that could be matched to a known organism. "
                            "Higher is better. Values below 50% may indicate database limitations "
                            "or novel organisms.",
                            target="summary-classification-rate",
                            placement="bottom",
                        ),
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H6("Most Abundant:", className="mb-1"),
                        html.P(
                            most_abundant.get("name", "N/A") if most_abundant else "N/A",
                            className="mb-0",
                            style={"fontSize": "14px"}
                        ),
                        html.Small(
                            f"({most_abundant.get('abundance', 0):.1f}%)" if most_abundant else "",
                            className="text-muted"
                        )
                    ])
                ], md=3)
            ])
        ])
    ], className="mb-4", style={"boxShadow": "var(--shadow-md)"})


def _rank_to_plain_language(rank: str) -> str:
    """Convert taxonomic rank code to plain language."""
    rank_map = {
        "D": "Domain",
        "K": "Kingdom",
        "P": "Phylum",
        "C": "Class",
        "O": "Order",
        "F": "Family",
        "G": "Genus",
        "S": "Species",
        "U": "Unclassified"
    }
    return rank_map.get(rank, rank)


def BaseQualityCard(
    q20_rate: Optional[float],
    q30_rate: Optional[float],
    total_bases: int,
    quality_curve: Optional[List[float]] = None,
    source: str = "unknown",
    amplicon_mode: bool = False,
) -> html.Div:
    """
    Create a base quality card showing Q20/Q30 rates with optional quality sparkline.

    Displays base-level quality metrics (Q20/Q30 percentages) alongside total bases
    processed. When FASTP data is available, shows per-position quality curve as
    a sparkline.

    Args:
        q20_rate: Percentage of bases with Q >= 20 (0-100), or None when the
            QC output does not record it. None renders as "not recorded"
            rather than 0.0% -- a missing measurement must not display as a
            poor one (2026-08-17 audit, finding Q2).
        q30_rate: Percentage of bases with Q >= 30 (0-100), or None (as above)
        total_bases: Total base pairs processed
        quality_curve: Per-position mean quality scores (FASTP only)
        source: Data source ("fastp" or "seqkit") - affects sparkline availability
        amplicon_mode: When True, use relaxed Q-score bands tuned for short
            amplicon ONT reads (V3-V4, ITS, custom designs). Short reads
            carry proportionally more end-of-read low-quality bases, so
            Q30/Q20 sit lower on amplicons even when the data is good.
            See docs/audit-2026-04-29-short-amplicons.md for the rationale.

    Returns:
        Base quality card component

    Color thresholds (long-read mode, default):
        Q20: >= 65% (good), 50-65% (warning), < 50% (poor)
        Q30: >= 45% (good), 25-44% (warning), < 25% (poor)

    Color thresholds (amplicon mode):
        Q20: >= 40% (good), 20-39% (warning), < 20% (poor)
        Q30: >= 25% (good), 10-24% (warning), < 10% (poor)
    """
    # Color configuration
    color_config = {
        "danger": {"bg": "#dc3545", "bg_light": "rgba(220, 53, 69, 0.12)", "icon": "x-circle-fill"},
        "warning": {"bg": "#ffc107", "bg_light": "rgba(255, 193, 7, 0.15)", "icon": "exclamation-triangle-fill"},
        "success": {"bg": "#28a745", "bg_light": "rgba(40, 167, 69, 0.12)", "icon": "check-circle-fill"},
    }

    if amplicon_mode:
        _q20_red, _q20_amber = 20, 40
        _q30_red, _q30_amber = 10, 25
    else:
        _q20_red, _q20_amber = 50, 65
        _q30_red, _q30_amber = 25, 45

    def get_q20_color(value: float) -> dict:
        """Get color for Q20 rate (nanopore-calibrated)."""
        if value < _q20_red:
            return color_config["danger"]
        elif value < _q20_amber:
            return color_config["warning"]
        return color_config["success"]

    def get_q30_color(value: float) -> dict:
        """Get color for Q30 rate (nanopore-calibrated)."""
        if value < _q30_red:
            return color_config["danger"]
        elif value < _q30_amber:
            return color_config["warning"]
        return color_config["success"]

    def format_bases(bases: int) -> str:
        """Format base count with appropriate unit."""
        if bases >= 1_000_000_000:
            return f"{bases / 1_000_000_000:.2f} Gb"
        elif bases >= 1_000_000:
            return f"{bases / 1_000_000:.1f} Mb"
        elif bases >= 1_000:
            return f"{bases / 1_000:.1f} Kb"
        return f"{bases} bp"

    _not_recorded = {
        "bg": "#6c757d",
        "bg_light": "rgba(108, 117, 125, 0.12)",
        "icon": "dash-circle",
    }
    q20_colors = get_q20_color(q20_rate) if q20_rate is not None else _not_recorded
    q30_colors = get_q30_color(q30_rate) if q30_rate is not None else _not_recorded

    def _band_label(value, red, amber):
        if value is None:
            return "Not recorded"
        return "Good" if value >= amber else "Fair" if value >= red else "Poor"

    # Band labels use the SAME thresholds as the colors -- these were
    # previously hardcoded to the long-read bands, so an amplicon run could
    # show a green metric labelled "Poor".
    q20_label = _band_label(q20_rate, _q20_red, _q20_amber)
    q30_label = _band_label(q30_rate, _q30_red, _q30_amber)

    # Card surface: white with neutral border + 6px left accent in the threshold
    # color. Matches the Dashboard 8px radius / 6px accent design language.
    _known = [v for v in (q20_rate, q30_rate) if v is not None]
    overall_metric = min(_known) if _known else None
    if overall_metric is None:
        card_accent = "#6c757d"
    elif overall_metric < 30:
        card_accent = "#721c24"
    elif overall_metric < 45:
        card_accent = "#664d03"
    else:
        card_accent = "#155724"

    # Build sparkline if quality curve is available
    sparkline_section = None
    if quality_curve and len(quality_curve) > 10:
        # Create sparkline figure
        fig = go.Figure()

        # Limit to first 150 positions for readability
        curve_data = quality_curve[:150]
        x_values = list(range(len(curve_data)))

        fig.add_trace(go.Scatter(
            x=x_values,
            y=curve_data,
            mode='lines',
            line=dict(color='#007bff', width=1.5),
            fill='tozeroy',
            fillcolor='rgba(0, 123, 255, 0.1)',
            hovertemplate='Position %{x}: Q%{y:.1f}<extra></extra>'
        ))

        # Add Q20 and Q30 reference lines
        fig.add_hline(y=20, line_dash="dash", line_color="#ffc107", line_width=1,
                      annotation_text="Q20", annotation_position="right")
        fig.add_hline(y=30, line_dash="dash", line_color="#28a745", line_width=1,
                      annotation_text="Q30", annotation_position="right")

        fig.update_layout(
            height=60,
            margin=dict(l=0, r=30, t=0, b=0),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Arial, sans-serif"),
            showlegend=False,
            xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
            yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, 45]),
            hovermode="x",
        )

        sparkline_section = html.Div([
            html.Div(style={
                "height": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "12px 0"
            }),
            html.Small(
                "Per-Position Quality",
                className="text-muted d-block mb-1",
                style={"fontSize": "10px", "textTransform": "uppercase", "letterSpacing": "0.5px"}
            ),
            dcc.Graph(
                figure=fig,
                config={'displayModeBar': False},
                style={'height': '60px'}
            )
        ])
    elif source == "seqkit":
        sparkline_section = html.Div([
            html.Div(style={
                "height": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "12px 0"
            }),
            html.Div([
                html.I(className="bi bi-info-circle me-1", style={"color": "var(--text-muted-inline)"}),
                html.Small(
                    "Per-position quality curve not available (Chopper QC)",
                    className="text-muted",
                    style={"fontSize": "11px"}
                )
            ], className="text-center py-2")
        ])

    return html.Div([
        # Header
        html.Div([
            html.I(className="bi bi-speedometer2 me-2", style={"color": "var(--text-label)"}),
            html.Span("Base Quality", style={"fontWeight": "600", "fontSize": "14px"}),
            html.Small(
                " - How accurate is each letter of the DNA sequence?",
                className="text-muted",
                style={"fontSize": "11px", "fontWeight": "400"}
            ),
        ], className="mb-3"),

        # Metrics row
        html.Div([
            # Q20 Rate
            html.Div([
                html.Div([
                    html.Span("Q20+", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                    html.Span(
                        " (99% accurate)",
                        style={"fontSize": "10px", "color": "var(--text-muted-inline)", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{q20_colors['icon']} me-1",
                           style={"color": q20_colors["bg"], "fontSize": "12px"}),
                    html.Span(
                        f"{q20_rate:.1f}%" if q20_rate is not None else "—",
                        style={
                            "fontSize": "28px", "fontWeight": "700",
                            "letterSpacing": "-0.01em", "color": q20_colors["bg"]
                        })
                ]),
                # Progress bar
                html.Div([
                    html.Div(style={
                        "width": f"{min(100, max(0, q20_rate or 0))}%",
                        "height": "6px",
                        "backgroundColor": q20_colors["bg"],
                        "borderRadius": "3px"
                    })
                ], style={
                    "backgroundColor": "#e9ecef",
                    "borderRadius": "3px",
                    "height": "6px",
                    "marginTop": "4px"
                }),
                html.Small(
                    q20_label,
                    style={
                        "fontSize": "10px",
                        "fontWeight": "600",
                        "color": q20_colors["bg"]
                    }
                )
            ], className="text-center", style={"flex": "1"}),

            # Divider
            html.Div(style={
                "width": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "0 12px",
                "alignSelf": "stretch"
            }),

            # Q30 Rate
            html.Div([
                html.Div([
                    html.Span("Q30+", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                    html.Span(
                        " (99.9% accurate)",
                        style={"fontSize": "10px", "color": "var(--text-muted-inline)", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{q30_colors['icon']} me-1",
                           style={"color": q30_colors["bg"], "fontSize": "12px"}),
                    html.Span(
                        f"{q30_rate:.1f}%" if q30_rate is not None else "—",
                        style={
                            "fontSize": "28px", "fontWeight": "700",
                            "letterSpacing": "-0.01em", "color": q30_colors["bg"]
                        })
                ]),
                # Progress bar
                html.Div([
                    html.Div(style={
                        "width": f"{min(100, max(0, q30_rate or 0))}%",
                        "height": "6px",
                        "backgroundColor": q30_colors["bg"],
                        "borderRadius": "3px"
                    })
                ], style={
                    "backgroundColor": "#e9ecef",
                    "borderRadius": "3px",
                    "height": "6px",
                    "marginTop": "4px"
                }),
                html.Small(
                    q30_label,
                    style={
                        "fontSize": "10px",
                        "fontWeight": "600",
                        "color": q30_colors["bg"]
                    }
                )
            ], className="text-center", style={"flex": "1"}),

            # Divider
            html.Div(style={
                "width": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "0 12px",
                "alignSelf": "stretch"
            }),

            # Total Bases
            html.Div([
                html.Div([
                    html.Span("Total Bases", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                ]),
                html.Div([
                    html.Span(format_bases(total_bases), style={
                        "fontSize": "28px", "fontWeight": "700",
                        "letterSpacing": "-0.01em", "color": "var(--text-strong)"
                    })
                ]),
                html.Small(f"{total_bases:,} bp", className="text-muted", style={"fontSize": "10px"})
            ], className="text-center", style={"flex": "1"}),

        ], className="d-flex align-items-stretch"),

        # Sparkline section (conditional)
        sparkline_section

    ], className="base-quality-card", style={
        "backgroundColor": "#ffffff",
        "borderRadius": "8px",
        "padding": "16px 20px",
        "border": "1px solid #e9ecef",
        "borderLeft": f"6px solid {card_accent}",
    })


def ReadStatisticsCard(
    mean_length: float,
    mean_length_before: Optional[float] = None,
    n50: Optional[int] = None,
    gc_content: Optional[float] = None,
    source: str = "unknown",
    amplicon_mode: bool = False,
) -> html.Div:
    """
    Create a read statistics card showing length, N50, and GC content.

    Displays read-level statistics including mean length (with before/after comparison
    when using FASTP), N50 (when using Chopper/Seqkit), and GC content percentage.

    Args:
        mean_length: Average read length after filtering (bp)
        mean_length_before: Average read length before filtering (FASTP only)
        n50: N50 statistic (Seqkit/Chopper only)
        gc_content: GC content percentage (0-100)
        source: Data source ("fastp" or "seqkit")
        amplicon_mode: When True, use N50 bands tuned for short-amplicon
            protocols. The whole-genome bands mark every amplicon run red
            even when the N50 equals the amplicon length by design.

    Returns:
        Read statistics card component

    Color thresholds:
        GC Content: 40-60% (normal), 35-40% or 60-65% (warning), <35% or >65% (unusual)
        N50 (whole-genome): >= 2000 bp (good), 1000-2000 bp (warning), < 1000 bp (poor)
        N50 (amplicon): >= 200 bp (good), 100-200 bp (warning), < 100 bp (poor)
    """
    # Color configuration
    color_config = {
        "danger": {"bg": "#dc3545", "bg_light": "rgba(220, 53, 69, 0.12)", "icon": "x-circle-fill"},
        "warning": {"bg": "#ffc107", "bg_light": "rgba(255, 193, 7, 0.15)", "icon": "exclamation-triangle-fill"},
        "success": {"bg": "#28a745", "bg_light": "rgba(40, 167, 69, 0.12)", "icon": "check-circle-fill"},
        "info": {"bg": "#007bff", "bg_light": "rgba(0, 123, 255, 0.10)", "icon": "info-circle-fill"},
    }

    def get_gc_color(value: Optional[float]) -> dict:
        """Get color for GC content."""
        if value is None:
            return color_config["info"]
        if value < 35 or value > 65:
            return color_config["danger"]
        elif value < 40 or value > 60:
            return color_config["warning"]
        return color_config["success"]

    def get_n50_color(value: Optional[int]) -> dict:
        """Get color for N50 (bands depend on protocol; see docstring)."""
        if value is None:
            return color_config["info"]
        danger_below, warning_below = (100, 200) if amplicon_mode else (1000, 2000)
        if value < danger_below:
            return color_config["danger"]
        elif value < warning_below:
            return color_config["warning"]
        return color_config["success"]

    def get_gc_status(value: Optional[float]) -> str:
        """Get GC status label."""
        if value is None:
            return "N/A"
        if 40 <= value <= 60:
            return "Normal"
        elif 35 <= value < 40 or 60 < value <= 65:
            return "Unusual"
        return "Atypical"

    def format_length(length: float) -> str:
        """Format read length."""
        if length >= 10000:
            return f"{length / 1000:.1f}K"
        return f"{length:,.0f}"

    gc_colors = get_gc_color(gc_content)
    n50_colors = get_n50_color(n50)

    # Card surface: white with neutral border + 6px left accent. Read statistics
    # are informational (no severity), so accent uses the Dashboard info-blue token.
    card_accent = "#084298"

    # Build length comparison text
    length_comparison = None
    if mean_length_before is not None and mean_length_before > 0:
        change = mean_length - mean_length_before
        change_pct = (change / mean_length_before) * 100
        if abs(change) > 1:
            change_color = "#28a745" if change > 0 else "#dc3545"
            change_icon = "arrow-up" if change > 0 else "arrow-down"
            length_comparison = html.Div([
                html.I(className=f"bi bi-{change_icon}", style={"color": change_color, "fontSize": "10px"}),
                html.Small(f" {abs(change_pct):.1f}% vs raw", style={"color": change_color, "fontSize": "10px"})
            ], className="mt-1")

    return html.Div([
        # Header
        html.Div([
            html.I(className="bi bi-rulers me-2", style={"color": "var(--text-label)"}),
            html.Span("Read Statistics", style={"fontWeight": "600", "fontSize": "14px"}),
            html.Small(
                " - How long are the DNA sequences?",
                className="text-muted",
                style={"fontSize": "11px", "fontWeight": "400"}
            ),
        ], className="mb-3"),

        # Metrics row
        html.Div([
            # Mean Length
            html.Div([
                html.Div([
                    html.Span("Mean Length", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                ]),
                html.Div([
                    html.Span(f"{format_length(mean_length)}", style={
                        "fontSize": "28px", "fontWeight": "700",
                        "letterSpacing": "-0.01em", "color": "var(--text-strong)"
                    }),
                    html.Span(" bp", style={"fontSize": "12px", "color": "var(--text-muted-inline)"})
                ]),
                length_comparison if length_comparison else html.Small(
                    f"{mean_length:,.0f} bp",
                    className="text-muted",
                    style={"fontSize": "10px"}
                )
            ], className="text-center", style={"flex": "1"}),

            # Divider
            html.Div(style={
                "width": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "0 12px",
                "alignSelf": "stretch"
            }),

            # N50
            html.Div([
                html.Div([
                    html.Span("N50", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                    html.Span(
                        " (length metric)",
                        style={"fontSize": "10px", "color": "var(--text-muted-inline)", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{n50_colors['icon']} me-1",
                           style={"color": n50_colors["bg"], "fontSize": "12px"}) if n50 is not None else None,
                    html.Span(
                        f"{format_length(n50)}" if n50 is not None else "N/A",
                        style={
                            "fontSize": "28px",
                            "fontWeight": "700",
                            "letterSpacing": "-0.01em",
                            "color": n50_colors["bg"] if n50 is not None else "#6c757d"
                        }
                    ),
                    html.Span(" bp", style={"fontSize": "12px", "color": "var(--text-muted-inline)"}) if n50 is not None else None
                ]),
                html.Small(
                    ("Good" if n50 >= 2000 else "Fair" if n50 >= 1000 else "Short")
                    if n50 is not None else "Not available (FASTP mode)",
                    style={
                        "fontSize": "10px",
                        "fontWeight": "600" if n50 is not None else "400",
                        "color": n50_colors["bg"] if n50 is not None else "#6c757d"
                    }
                )
            ], className="text-center", style={"flex": "1"}),

            # Divider
            html.Div(style={
                "width": "1px",
                "backgroundColor": "#dee2e6",
                "margin": "0 12px",
                "alignSelf": "stretch"
            }),

            # GC Content
            html.Div([
                html.Div([
                    html.Span("GC Content", style={"fontWeight": "600", "fontSize": "12px", "color": "var(--text-label)"}),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{gc_colors['icon']} me-1",
                           style={"color": gc_colors["bg"], "fontSize": "12px"}) if gc_content is not None else None,
                    html.Span(
                        f"{gc_content:.1f}%" if gc_content is not None else "N/A",
                        style={
                            "fontSize": "28px",
                            "fontWeight": "700",
                            "letterSpacing": "-0.01em",
                            "color": gc_colors["bg"] if gc_content is not None else "#6c757d"
                        }
                    )
                ]),
                html.Small(
                    get_gc_status(gc_content),
                    className="text-muted",
                    style={"fontSize": "10px"}
                )
            ], className="text-center", style={"flex": "1"}),

        ], className="d-flex align-items-stretch"),

    ], className="read-statistics-card", style={
        "backgroundColor": "#ffffff",
        "borderRadius": "8px",
        "padding": "16px 20px",
        "border": "1px solid #e9ecef",
        "borderLeft": f"6px solid {card_accent}",
    })
