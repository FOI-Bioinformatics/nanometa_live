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
    on_demand_validation: Optional[Dict] = None
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
                            "color": "#6c757d" if is_undetected else "inherit"
                        }
                    ),
                    html.Small(
                        f" ({common_name})" if common_name else "",
                        className="text-muted"
                    ),
                    status_badge
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

            # Confidence badge with explanatory tooltip
            html.Div([
                dbc.Badge([
                    html.I(className=f"bi bi-{confidence_icon} me-1"),
                    confidence_label
                ],
                    color=confidence_color,
                    className="me-2",
                    id={"type": "confidence-badge", "taxid": taxid or 0},
                ),
                dbc.Tooltip(
                    "Based on the number of matching DNA sequences. "
                    "More sequences means higher confidence that this organism "
                    "is truly present in the sample.",
                    target={"type": "confidence-badge", "taxid": taxid or 0},
                    placement="top",
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
                    # Use same ID type as pathogen report for unified view
                    id={"type": "pathogen-view-report", "taxid": taxid} if taxid else {"type": "pathogen-view-report", "taxid": 0},
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


def FilteringBreakdownVisual(
    total_reads: int,
    passed_reads: int,
    removal_reasons: Dict[str, int]
) -> html.Div:
    """
    Create visual breakdown of quality filtering statistics with stacked bar chart.

    Args:
        total_reads: Total DNA sequences before filtering
        passed_reads: Sequences that passed quality control
        removal_reasons: Dict mapping reason -> count

    Returns:
        Filtering visualization component with stacked bar chart
    """
    # When post-filter count exceeds pre-filter baseline (e.g., seqkit counted
    # slightly more reads than kraken2 processed), cap to avoid impossible percentages
    if passed_reads > total_reads and total_reads > 0:
        total_reads = passed_reads
    failed_reads = max(0, total_reads - passed_reads)
    pass_rate = min((passed_reads / total_reads * 100) if total_reads > 0 else 0, 100.0)
    fail_rate = max(0, 100 - pass_rate)

    # Calculate percentages for removal reasons (of total, not of failed)
    reason_percentages_of_total = {}
    for reason, count in removal_reasons.items():
        reason_percentages_of_total[reason] = (count / total_reads * 100) if total_reads > 0 else 0

    # Plain language labels and colors
    reason_config = {
        "low_quality": {"label": "Low Quality", "color": "#dc3545", "icon": "!"},
        "too_short": {"label": "Too Short", "color": "#fd7e14", "icon": "-"},
        "low_complexity": {"label": "Repetitive", "color": "#6f42c1", "icon": "~"}
    }

    # Build stacked bar data for Plotly
    categories = ["Filtering Result"]

    # Create figure with stacked horizontal bar
    fig = go.Figure()

    # Add passed reads bar (green)
    fig.add_trace(go.Bar(
        name=f"Passed ({pass_rate:.1f}%)",
        y=categories,
        x=[pass_rate],
        orientation='h',
        marker_color='#28a745',
        text=[f"Passed: {passed_reads:,}"],
        textposition='inside',
        insidetextanchor='middle',
        hovertemplate="<b>Passed Quality</b><br>%{x:.1f}% of total<br>%{text}<extra></extra>"
    ))

    # Add each removal reason as a stacked segment
    for reason in ["low_quality", "too_short", "low_complexity"]:
        if reason in removal_reasons and removal_reasons[reason] > 0:
            config = reason_config.get(reason, {"label": reason, "color": "#dc3545", "icon": "?"})
            pct = reason_percentages_of_total.get(reason, 0)
            count = removal_reasons[reason]

            fig.add_trace(go.Bar(
                name=f"{config['label']} ({pct:.1f}%)",
                y=categories,
                x=[pct],
                orientation='h',
                marker_color=config['color'],
                text=[f"{config['label']}: {count:,}"],
                textposition='inside',
                insidetextanchor='middle',
                hovertemplate=f"<b>{config['label']}</b><br>%{{x:.1f}}% of total<br>{count:,} sequences<extra></extra>"
            ))

    # Update layout for stacked bar
    fig.update_layout(
        barmode='stack',
        height=80,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family="Arial, sans-serif", size=11),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.3,
            xanchor="center",
            x=0.5,
            font=dict(size=10),
        ),
        xaxis=dict(
            range=[0, 100],
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
    )

    # Build detailed breakdown list
    breakdown_items = []
    sorted_reasons = sorted(removal_reasons.keys(), key=lambda x: removal_reasons[x], reverse=True)
    for reason in sorted_reasons:
        if removal_reasons[reason] > 0:
            config = reason_config.get(reason, {"label": reason, "color": "#dc3545", "icon": "?"})
            pct_of_failed = (removal_reasons[reason] / failed_reads * 100) if failed_reads > 0 else 0
            breakdown_items.append(
                html.Div([
                    html.Span(
                        config['icon'],
                        className="filtering-reason-icon",
                        style={"backgroundColor": config['color']}
                    ),
                    html.Span(f"{config['label']}: ", style={"fontWeight": "bold"}),
                    html.Span(f"{removal_reasons[reason]:,} sequences ({pct_of_failed:.1f}% of removed)")
                ], className="filtering-reason-item mb-2")
            )

    return html.Div([
        # Overall stats header
        dbc.Row([
            dbc.Col([
                html.H5(f"Total DNA Sequences: {total_reads:,}", className="mb-0")
            ], md=6),
            dbc.Col([
                html.Div([
                    dbc.Badge(f"{pass_rate:.1f}% Pass Rate", color="success", className="me-2"),
                    dbc.Badge(f"{fail_rate:.1f}% Removed", color="danger")
                ], className="text-end")
            ], md=6)
        ], className="mb-3 align-items-center"),

        # Stacked bar chart
        html.Div([
            dcc.Graph(
                figure=fig,
                config={'displayModeBar': False},
                style={'height': '80px'}
            )
        ], className="mb-3"),

        # Pass/Fail summary with icons
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Span(className="status-icon status-icon-success me-2"),
                    html.Strong("Passed Quality: "),
                    html.Span(f"{passed_reads:,} sequences")
                ], className="d-flex align-items-center")
            ], md=6),
            dbc.Col([
                html.Div([
                    html.Span(className="status-icon status-icon-danger me-2"),
                    html.Strong("Removed: "),
                    html.Span(f"{failed_reads:,} sequences")
                ], className="d-flex align-items-center")
            ], md=6)
        ], className="mb-4"),

        # Detailed removal reasons breakdown
        html.Div([
            html.H6("Removal Breakdown:", className="mb-3"),
            html.Div(breakdown_items, className="filtering-breakdown-list")
        ]) if breakdown_items else None,

        # Note about read count sources
        html.Div([
            html.I(className="bi bi-info-circle me-1"),
            html.Small(
                "Read counts may differ slightly between pipeline steps "
                "(seqkit stats vs. Kraken2) due to processing overhead.",
                className="text-muted"
            )
        ], className="mt-3", style={"fontSize": "11px"})
        if pass_rate >= 99.5 and failed_reads == 0 else None
    ], className="filtering-breakdown-container")


def QualityScoreIndicator(
    score: int,
    label: str = "Data Quality",
    size: str = "large",
    show_interpretation: bool = True,
    pass_rate: Optional[float] = None,
    classification_rate: Optional[float] = None
) -> html.Div:
    """
    Create a compact quality score indicator with component breakdown.

    Displays overall quality score alongside its component metrics (pass rate
    and classification rate) in a space-efficient layout without a gauge chart.

    Args:
        score: Overall quality score 0-100
        label: Label for the metric
        size: Display size ("small", "medium", "large") - affects text sizing
        show_interpretation: Whether to show text interpretation
        pass_rate: QC pass rate percentage (0-100), shown as component
        classification_rate: Classification success rate (0-100), shown as component

    Returns:
        Quality indicator component with visual breakdown

    Color thresholds:
        - Red (danger): < 60
        - Yellow (warning): 60-75
        - Green (success): > 75
    """
    from nanometa_live.core.utils.language_utils import get_quality_interpretation

    rating, interpretation, color_name = get_quality_interpretation(score)

    # Color configuration with icons for WCAG compliance
    color_config = {
        "danger": {"bg": "#dc3545", "bg_light": "rgba(220, 53, 69, 0.12)", "icon": "x-circle-fill", "text": "#721c24"},
        "warning": {"bg": "#ffc107", "bg_light": "rgba(255, 193, 7, 0.15)", "icon": "exclamation-triangle-fill", "text": "#856404"},
        "success": {"bg": "#28a745", "bg_light": "rgba(40, 167, 69, 0.12)", "icon": "check-circle-fill", "text": "#155724"},
        "good": {"bg": "#28a745", "bg_light": "rgba(40, 167, 69, 0.12)", "icon": "check-circle-fill", "text": "#155724"},
        "secondary": {"bg": "#6c757d", "bg_light": "rgba(108, 117, 125, 0.12)", "icon": "dash-circle", "text": "#383d41"},
    }
    colors = color_config.get(color_name, color_config["success"])

    # Size configuration
    sizes = {
        "small": {"score_font": "32px", "label_font": "12px", "bar_height": "6px"},
        "medium": {"score_font": "40px", "label_font": "13px", "bar_height": "8px"},
        "large": {"score_font": "48px", "label_font": "14px", "bar_height": "10px"},
    }
    size_config = sizes.get(size, sizes["large"])

    def get_metric_color(value: float) -> dict:
        """Get color configuration for a metric value."""
        if value < 60:
            return color_config["danger"]
        elif value < 75:
            return color_config["warning"]
        return color_config["success"]

    def create_component_metric(value: float, metric_label: str, description: str) -> html.Div:
        """Create a compact metric display with progress bar."""
        metric_colors = get_metric_color(value)
        return html.Div([
            # Label and value row
            html.Div([
                html.Span(metric_label, style={"fontWeight": "500", "fontSize": size_config["label_font"]}),
                html.Span([
                    html.I(className=f"bi bi-{metric_colors['icon']} me-1",
                           style={"color": metric_colors["bg"], "fontSize": "11px"}),
                    f"{value:.1f}%"
                ], style={"fontWeight": "600", "fontSize": size_config["label_font"], "color": metric_colors["bg"]})
            ], className="d-flex justify-content-between align-items-center mb-1"),
            # Progress bar
            html.Div([
                html.Div(style={
                    "width": f"{min(100, max(0, value))}%",
                    "height": size_config["bar_height"],
                    "backgroundColor": metric_colors["bg"],
                    "borderRadius": "4px",
                    "transition": "width 0.3s ease"
                })
            ], style={
                "backgroundColor": "#e9ecef",
                "borderRadius": "4px",
                "height": size_config["bar_height"],
                "overflow": "hidden"
            }),
            # Description
            html.Small(description, className="text-muted", style={"fontSize": "11px"})
        ], className="mb-2")

    # Build the component
    # Main score section - horizontal layout with score and breakdown
    main_content = html.Div([
        # Left: Overall Score Display
        html.Div([
            html.Div([
                html.I(className=f"bi bi-{colors['icon']}",
                       style={"fontSize": "28px", "color": colors["bg"]}),
            ], className="mb-2"),
            html.Div([
                html.Span(str(score), style={
                    "fontSize": size_config["score_font"],
                    "fontWeight": "700",
                    "color": colors["bg"],
                    "lineHeight": "1"
                }),
                html.Span("/100", style={"fontSize": "14px", "color": "#6c757d", "marginLeft": "2px"})
            ]),
            dbc.Badge(rating, color=color_name, className="mt-2",
                      style={"fontSize": "11px", "padding": "4px 10px"})
        ], className="text-center", style={"minWidth": "100px"}),

        # Divider
        html.Div(style={
            "width": "1px",
            "backgroundColor": "#dee2e6",
            "margin": "0 20px",
            "alignSelf": "stretch"
        }),

        # Right: Component Breakdown
        html.Div([
            html.Div([
                html.Small("Score Components", className="text-muted fw-bold",
                           style={"fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                html.Small("50% weight each", className="text-muted", style={"fontSize": "10px"})
            ], className="d-flex justify-content-between mb-2"),

            create_component_metric(
                pass_rate if pass_rate is not None else 0,
                "Pass Rate",
                "Sequences passing quality filters"
            ) if pass_rate is not None else None,

            create_component_metric(
                classification_rate if classification_rate is not None else 0,
                "Classification",
                "Sequences matched to organisms"
            ) if classification_rate is not None else None,

        ], style={"flex": "1", "minWidth": "200px"}) if (pass_rate is not None or classification_rate is not None) else None

    ], className="d-flex align-items-center justify-content-center", style={"gap": "0"})

    # Assemble final component
    components = [
        html.H6(label, className="text-center mb-3", style={"fontWeight": "600", "color": "#495057"}),
        main_content
    ]

    # Add interpretation if requested
    if show_interpretation:
        components.append(
            html.P(interpretation, className="text-muted text-center mb-0 mt-3", style={"fontSize": "12px"})
        )

    return html.Div(
        components,
        className="quality-indicator-compact",
        style={
            "backgroundColor": colors["bg_light"],
            "borderRadius": "12px",
            "padding": "16px 20px",
            "border": f"1px solid {colors['bg']}25"
        }
    )


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


def KeyMetricsSummaryCard(
    total_reads: int,
    pass_rate: float,
    classified_rate: float,
    sample_count: int
) -> html.Div:
    """
    Create a compact key metrics summary card matching the QualityScoreIndicator design.

    Displays critical QC metrics in a visually consistent, operator-friendly format
    with color-coded indicators based on threshold values.

    Args:
        total_reads: Total DNA sequences processed
        pass_rate: Percentage of reads passing QC (0-100)
        classified_rate: Percentage of reads classified (0-100)
        sample_count: Number of samples/barcodes detected

    Returns:
        Key metrics summary card component

    Color thresholds (matching QualityScoreIndicator):
        - Green (success): >= 75%
        - Yellow (warning): 60-75%
        - Red (danger): < 60%
    """
    # Color configuration matching QualityScoreIndicator
    color_config = {
        "danger": {
            "bg": "#dc3545",
            "bg_light": "rgba(220, 53, 69, 0.12)",
            "icon": "x-circle-fill",
            "border": "rgba(220, 53, 69, 0.25)"
        },
        "warning": {
            "bg": "#ffc107",
            "bg_light": "rgba(255, 193, 7, 0.15)",
            "icon": "exclamation-triangle-fill",
            "border": "rgba(255, 193, 7, 0.30)"
        },
        "success": {
            "bg": "#28a745",
            "bg_light": "rgba(40, 167, 69, 0.12)",
            "icon": "check-circle-fill",
            "border": "rgba(40, 167, 69, 0.25)"
        },
    }

    def get_metric_color(value: float) -> dict:
        """Get color configuration for a percentage metric value."""
        if value < 60:
            return color_config["danger"]
        elif value < 75:
            return color_config["warning"]
        return color_config["success"]

    def format_reads(count: int) -> str:
        """Format read count with appropriate suffix for readability."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    def create_metric_bar(value: float, label: str, description: str) -> html.Div:
        """Create a compact metric display with progress bar."""
        colors = get_metric_color(value)
        return html.Div([
            # Label and value row
            html.Div([
                html.Span(label, style={
                    "fontWeight": "500",
                    "fontSize": "13px",
                    "color": "#495057"
                }),
                html.Span([
                    html.I(
                        className=f"bi bi-{colors['icon']} me-1",
                        style={"color": colors["bg"], "fontSize": "11px"}
                    ),
                    f"{value:.1f}%"
                ], style={
                    "fontWeight": "600",
                    "fontSize": "14px",
                    "color": colors["bg"]
                })
            ], className="d-flex justify-content-between align-items-center mb-1"),
            # Progress bar
            html.Div([
                html.Div(style={
                    "width": f"{min(100, max(0, value))}%",
                    "height": "8px",
                    "backgroundColor": colors["bg"],
                    "borderRadius": "4px",
                    "transition": "width 0.3s ease"
                })
            ], style={
                "backgroundColor": "#e9ecef",
                "borderRadius": "4px",
                "height": "8px",
                "overflow": "hidden"
            }),
            # Description
            html.Small(description, className="text-muted", style={"fontSize": "11px"})
        ], className="mb-2")

    # Determine overall card color based on the lower of pass_rate and classified_rate
    overall_metric = min(pass_rate, classified_rate)
    card_colors = get_metric_color(overall_metric)

    return html.Div([
        # Left section: Total Reads (hero metric)
        html.Div([
            html.Div([
                html.I(
                    className="bi bi-bar-chart-fill",
                    style={"fontSize": "24px", "color": "#007bff"}
                ),
            ], className="mb-1"),
            html.Div([
                html.Span(
                    format_reads(total_reads),
                    style={
                        "fontSize": "36px",
                        "fontWeight": "700",
                        "color": "#007bff",
                        "lineHeight": "1"
                    }
                ),
            ]),
            html.Small(
                "Total Reads",
                className="text-muted",
                style={"fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "0.5px"}
            ),
            html.Div([
                html.Small(
                    f"{total_reads:,}",
                    className="text-muted",
                    style={"fontSize": "10px"}
                )
            ], className="mt-1") if total_reads >= 1000 else None
        ], className="text-center", style={"minWidth": "90px"}),

        # First vertical divider
        html.Div(style={
            "width": "1px",
            "backgroundColor": "#dee2e6",
            "margin": "0 16px",
            "alignSelf": "stretch"
        }),

        # Middle section: Pass Rate and Classified Rate stacked
        html.Div([
            html.Div([
                html.Small(
                    "Quality Metrics",
                    className="text-muted fw-bold",
                    style={
                        "fontSize": "11px",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.5px"
                    }
                ),
            ], className="mb-2"),
            create_metric_bar(
                pass_rate,
                "Pass Rate",
                "Reads passing quality filters"
            ),
            create_metric_bar(
                classified_rate,
                "Classified",
                "Reads matched to organisms"
            ),
        ], style={"flex": "1", "minWidth": "180px"}),

        # Second vertical divider
        html.Div(style={
            "width": "1px",
            "backgroundColor": "#dee2e6",
            "margin": "0 16px",
            "alignSelf": "stretch"
        }),

        # Right section: Sample count
        html.Div([
            html.Div([
                html.I(
                    className="bi bi-collection-fill",
                    style={"fontSize": "20px", "color": "#6c757d"}
                ),
            ], className="mb-1"),
            html.Div([
                html.Span(
                    str(sample_count),
                    style={
                        "fontSize": "32px",
                        "fontWeight": "700",
                        "color": "#495057",
                        "lineHeight": "1"
                    }
                ),
            ]),
            html.Small(
                "Samples" if sample_count != 1 else "Sample",
                className="text-muted",
                style={"fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "0.5px"}
            ),
        ], className="text-center", style={"minWidth": "70px"}),

    ], className="d-flex align-items-center key-metrics-summary-card", style={
        "backgroundColor": card_colors["bg_light"],
        "borderRadius": "12px",
        "padding": "16px 20px",
        "border": f"1px solid {card_colors['border']}"
    })


def BaseQualityCard(
    q20_rate: float,
    q30_rate: float,
    total_bases: int,
    quality_curve: Optional[List[float]] = None,
    source: str = "unknown"
) -> html.Div:
    """
    Create a base quality card showing Q20/Q30 rates with optional quality sparkline.

    Displays base-level quality metrics (Q20/Q30 percentages) alongside total bases
    processed. When FASTP data is available, shows per-position quality curve as
    a sparkline.

    Args:
        q20_rate: Percentage of bases with Q >= 20 (0-100)
        q30_rate: Percentage of bases with Q >= 30 (0-100)
        total_bases: Total base pairs processed
        quality_curve: Per-position mean quality scores (FASTP only)
        source: Data source ("fastp" or "seqkit") - affects sparkline availability

    Returns:
        Base quality card component

    Color thresholds (calibrated for Oxford Nanopore):
        Q20: >= 65% (good), 50-65% (warning), < 50% (poor)
        Q30: >= 45% (good), 30-45% (warning), < 30% (poor)
    """
    # Color configuration
    color_config = {
        "danger": {"bg": "#dc3545", "bg_light": "rgba(220, 53, 69, 0.12)", "icon": "x-circle-fill"},
        "warning": {"bg": "#ffc107", "bg_light": "rgba(255, 193, 7, 0.15)", "icon": "exclamation-triangle-fill"},
        "success": {"bg": "#28a745", "bg_light": "rgba(40, 167, 69, 0.12)", "icon": "check-circle-fill"},
    }

    def get_q20_color(value: float) -> dict:
        """Get color for Q20 rate (nanopore-calibrated)."""
        if value < 50:
            return color_config["danger"]
        elif value < 65:
            return color_config["warning"]
        return color_config["success"]

    def get_q30_color(value: float) -> dict:
        """Get color for Q30 rate (nanopore-calibrated)."""
        if value < 30:
            return color_config["danger"]
        elif value < 45:
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

    q20_colors = get_q20_color(q20_rate)
    q30_colors = get_q30_color(q30_rate)

    # Determine overall card color based on lower metric (nanopore-calibrated)
    overall_metric = min(q20_rate, q30_rate)
    if overall_metric < 30:
        card_bg = color_config["danger"]["bg_light"]
        card_border = "rgba(220, 53, 69, 0.25)"
    elif overall_metric < 45:
        card_bg = color_config["warning"]["bg_light"]
        card_border = "rgba(255, 193, 7, 0.30)"
    else:
        card_bg = color_config["success"]["bg_light"]
        card_border = "rgba(40, 167, 69, 0.25)"

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
                html.I(className="bi bi-info-circle me-1", style={"color": "#6c757d"}),
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
            html.I(className="bi bi-speedometer2 me-2", style={"color": "#495057"}),
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
                    html.Span("Q20+", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                    html.Span(
                        " (99% accurate)",
                        style={"fontSize": "10px", "color": "#6c757d", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{q20_colors['icon']} me-1",
                           style={"color": q20_colors["bg"], "fontSize": "12px"}),
                    html.Span(f"{q20_rate:.1f}%", style={
                        "fontSize": "24px", "fontWeight": "700", "color": q20_colors["bg"]
                    })
                ]),
                # Progress bar
                html.Div([
                    html.Div(style={
                        "width": f"{min(100, max(0, q20_rate))}%",
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
                    "Good" if q20_rate >= 65 else "Fair" if q20_rate >= 50 else "Poor",
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
                    html.Span("Q30+", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                    html.Span(
                        " (99.9% accurate)",
                        style={"fontSize": "10px", "color": "#6c757d", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{q30_colors['icon']} me-1",
                           style={"color": q30_colors["bg"], "fontSize": "12px"}),
                    html.Span(f"{q30_rate:.1f}%", style={
                        "fontSize": "24px", "fontWeight": "700", "color": q30_colors["bg"]
                    })
                ]),
                # Progress bar
                html.Div([
                    html.Div(style={
                        "width": f"{min(100, max(0, q30_rate))}%",
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
                    "Good" if q30_rate >= 45 else "Fair" if q30_rate >= 30 else "Poor",
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
                    html.Span("Total Bases", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                ]),
                html.Div([
                    html.Span(format_bases(total_bases), style={
                        "fontSize": "24px", "fontWeight": "700", "color": "#007bff"
                    })
                ]),
                html.Small(f"{total_bases:,} bp", className="text-muted", style={"fontSize": "10px"})
            ], className="text-center", style={"flex": "1"}),

        ], className="d-flex align-items-stretch"),

        # Sparkline section (conditional)
        sparkline_section

    ], className="base-quality-card", style={
        "backgroundColor": card_bg,
        "borderRadius": "12px",
        "padding": "16px 20px",
        "border": f"1px solid {card_border}"
    })


def ReadStatisticsCard(
    mean_length: float,
    mean_length_before: Optional[float] = None,
    n50: Optional[int] = None,
    gc_content: Optional[float] = None,
    source: str = "unknown"
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

    Returns:
        Read statistics card component

    Color thresholds:
        GC Content: 40-60% (normal), 35-40% or 60-65% (warning), <35% or >65% (unusual)
        N50: >= 2000 bp (good), 1000-2000 bp (warning), < 1000 bp (poor)
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
        """Get color for N50."""
        if value is None:
            return color_config["info"]
        if value < 1000:
            return color_config["danger"]
        elif value < 2000:
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

    # Use neutral background since these are informational metrics
    card_bg = "rgba(0, 123, 255, 0.08)"
    card_border = "rgba(0, 123, 255, 0.20)"

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
            html.I(className="bi bi-rulers me-2", style={"color": "#495057"}),
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
                    html.Span("Mean Length", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                ]),
                html.Div([
                    html.Span(f"{format_length(mean_length)}", style={
                        "fontSize": "24px", "fontWeight": "700", "color": "#007bff"
                    }),
                    html.Span(" bp", style={"fontSize": "12px", "color": "#6c757d"})
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
                    html.Span("N50", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                    html.Span(
                        " (length metric)",
                        style={"fontSize": "10px", "color": "#6c757d", "fontWeight": "400"}
                    ),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{n50_colors['icon']} me-1",
                           style={"color": n50_colors["bg"], "fontSize": "12px"}) if n50 is not None else None,
                    html.Span(
                        f"{format_length(n50)}" if n50 is not None else "N/A",
                        style={
                            "fontSize": "24px",
                            "fontWeight": "700",
                            "color": n50_colors["bg"] if n50 is not None else "#6c757d"
                        }
                    ),
                    html.Span(" bp", style={"fontSize": "12px", "color": "#6c757d"}) if n50 is not None else None
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
                    html.Span("GC Content", style={"fontWeight": "600", "fontSize": "12px", "color": "#495057"}),
                ]),
                html.Div([
                    html.I(className=f"bi bi-{gc_colors['icon']} me-1",
                           style={"color": gc_colors["bg"], "fontSize": "12px"}) if gc_content is not None else None,
                    html.Span(
                        f"{gc_content:.1f}%" if gc_content is not None else "N/A",
                        style={
                            "fontSize": "24px",
                            "fontWeight": "700",
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
        "backgroundColor": card_bg,
        "borderRadius": "12px",
        "padding": "16px 20px",
        "border": f"1px solid {card_border}"
    })
