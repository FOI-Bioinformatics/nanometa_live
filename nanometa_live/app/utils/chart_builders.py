"""
Chart Builders for Nanometa Live.

Professional Plotly visualizations optimized for pathogen detection
and real-time monitoring. Designed to clearly communicate results
to non-expert operators.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional
import numpy as np

from .plotly_theme import (
    COLORS,
    get_threat_color,
    apply_theme_to_figure
)


def responsive_height(n_items: int, base: int = 300, per_item: int = 25, max_height: int = 800) -> int:
    """Calculate responsive chart height based on number of data items."""
    return min(max_height, base + n_items * per_item)


def create_pathogen_abundance_chart(
    organisms: List[Dict[str, Any]],
    watched_species: Optional[List[Dict[str, Any]]] = None,
    max_organisms: int = 20,
    title: str = "Detected Organisms by Abundance"
) -> go.Figure:
    """
    Create a horizontal bar chart showing organism abundance with threat highlighting.

    Watched species are highlighted with warning colors and indicators.

    Args:
        organisms: List of dicts with 'name', 'reads', 'abundance', 'taxid'
        watched_species: List of watched species config with 'taxid', 'threat_level'
        max_organisms: Maximum number of organisms to display
        title: Chart title

    Returns:
        Plotly Figure object
    """
    if not organisms:
        return _create_empty_chart("No organisms detected")

    # Build watched species lookup
    watched_lookup = {}
    if watched_species:
        for s in watched_species:
            taxid = s.get("taxid")
            name = s.get("name", "").lower().strip()
            if taxid:
                watched_lookup[str(taxid)] = s
            if name:
                watched_lookup[name] = s

    # Sort by abundance and limit
    sorted_organisms = sorted(
        organisms,
        key=lambda x: x.get("abundance", 0),
        reverse=True
    )[:max_organisms]

    # Prepare data
    names = []
    abundances = []
    colors = []
    hover_texts = []
    annotations = []

    for org in sorted_organisms:
        # Truncate long names
        name = org.get("name", "Unknown")
        display_name = name[:45] + "..." if len(name) > 45 else name
        names.append(display_name)
        abundances.append(org.get("abundance", 0))

        # Check if watched
        taxid = str(org.get("taxid", ""))
        name_lower = name.lower().strip()
        watch_config = watched_lookup.get(taxid) or watched_lookup.get(name_lower)

        if watch_config:
            threat_level = watch_config.get("threat_level", "moderate")
            colors.append(get_threat_color(threat_level))
            annotations.append(threat_level.upper())
        else:
            colors.append(COLORS["safe"])
            annotations.append("")

        # Rich hover text
        hover_texts.append(
            f"<b>{name}</b><br>"
            f"Abundance: {org.get('abundance', 0):.2f}%<br>"
            f"DNA sequences: {org.get('reads', 0):,}<br>"
            f"Level: {org.get('rank', 'Unknown')}"
        )

    fig = go.Figure()

    # Main bars
    fig.add_trace(go.Bar(
        y=names,
        x=abundances,
        orientation="h",
        marker=dict(
            color=colors,
            line=dict(color=COLORS["gray_800"], width=0.5)
        ),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts
    ))

    # Add background bands and warning indicators for watched species
    max_abund = max(abundances) if abundances else 1
    for i, (name, abund, annot) in enumerate(zip(names, abundances, annotations)):
        if annot:
            # Subtle background band to distinguish watched species rows
            fig.add_shape(
                type="rect",
                x0=0, x1=max_abund * 1.15,
                y0=i - 0.4, y1=i + 0.4,
                fillcolor=get_threat_color(annot.lower()),
                opacity=0.07,
                layer="below",
                line_width=0,
            )
            # Threat level badge - prominent for immediate recognition
            fig.add_annotation(
                x=abund + max_abund * 0.02,
                y=i,
                text=f"<b>{annot}</b>",
                showarrow=False,
                font=dict(size=11, color=COLORS["white"], family="Arial Black, Arial, sans-serif"),
                bgcolor=get_threat_color(annot.lower()),
                bordercolor=get_threat_color(annot.lower()),
                borderwidth=1,
                borderpad=4
            )

    # Add 1% detection threshold reference line
    fig.add_vline(
        x=1.0,
        line=dict(color=COLORS["gray_400"], width=1, dash="dot"),
        annotation=dict(text="1% threshold", font=dict(size=9))
    )

    # Layout
    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=16),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(
            title="Relative Abundance (%)",
            showgrid=True,
            gridcolor=COLORS["gray_200"]
        ),
        yaxis=dict(
            title="",
            autorange="reversed",
            tickfont=dict(size=11)
        ),
        height=responsive_height(len(names), base=100, per_item=30, max_height=800),
        margin=dict(l=180, r=60, t=60, b=60),
        showlegend=False
    )

    # Add legend annotation
    fig.add_annotation(
        text=(
            f"<span style='color:{COLORS['threat_critical']}'>&#9632;</span> Critical | "
            f"<span style='color:{COLORS['threat_high']}'>&#9632;</span> High | "
            f"<span style='color:{COLORS['threat_moderate']}'>&#9632;</span> Moderate | "
            f"<span style='color:{COLORS['safe']}'>&#9632;</span> Safe"
        ),
        xref="paper", yref="paper",
        x=0.5, y=-0.08,
        showarrow=False,
        font=dict(size=10),
        xanchor="center"
    )

    return apply_theme_to_figure(fig)


def create_threat_indicator_panel(
    detected_threats: List[Dict[str, Any]],
    max_display: int = 5
) -> go.Figure:
    """
    Create a visual threat indicator panel with traffic light system.

    Shows overall threat status and detected species.

    Args:
        detected_threats: List of detected threat organisms
        max_display: Maximum species to display

    Returns:
        Plotly Figure object
    """
    if not detected_threats:
        # All clear indicator
        fig = go.Figure()

        fig.add_trace(go.Indicator(
            mode="number",
            value=0,
            title={"text": "<b>Watched Species Detected</b>", "font": {"size": 14}},
            number={"font": {"size": 64, "color": COLORS["safe"]}},
            domain={"x": [0, 1], "y": [0.4, 1]}
        ))

        fig.add_annotation(
            text="<b>ALL CLEAR</b>",
            x=0.5, y=0.25,
            showarrow=False,
            font=dict(size=28, color=COLORS["safe"], family="Arial Black"),
            xref="paper", yref="paper"
        )

        fig.add_annotation(
            text="No dangerous pathogens detected in current sample",
            x=0.5, y=0.1,
            showarrow=False,
            font=dict(size=12, color=COLORS["gray_600"]),
            xref="paper", yref="paper"
        )

        fig.update_layout(
            height=250,
            paper_bgcolor=COLORS["safe_light"],
            margin=dict(l=20, r=20, t=30, b=20)
        )

        return apply_theme_to_figure(fig)

    # Determine overall threat level
    threat_counts = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
    for t in detected_threats:
        level = t.get("threat_level", "moderate").lower()
        threat_counts[level] = threat_counts.get(level, 0) + 1

    if threat_counts["critical"] > 0:
        bg_color = COLORS["danger_light"]
        text_color = COLORS["threat_critical"]
        status_text = "CRITICAL ALERT"
    elif threat_counts["high"] > 0:
        bg_color = COLORS["danger_light"]
        text_color = COLORS["threat_high"]
        status_text = "HIGH RISK DETECTED"
    else:
        bg_color = COLORS["warning_light"]
        text_color = COLORS["threat_moderate"]
        status_text = "MONITORING REQUIRED"

    fig = go.Figure()

    # Total count indicator
    fig.add_trace(go.Indicator(
        mode="number",
        value=len(detected_threats),
        title={"text": "<b>Watched Species Detected</b>", "font": {"size": 14}},
        number={"font": {"size": 64, "color": text_color}},
        domain={"x": [0, 1], "y": [0.5, 1]}
    ))

    # Status text
    fig.add_annotation(
        text=f"<b>{status_text}</b>",
        x=0.5, y=0.4,
        showarrow=False,
        font=dict(size=20, color=text_color, family="Arial Black"),
        xref="paper", yref="paper"
    )

    # Species list
    species_lines = []
    for t in detected_threats[:max_display]:
        name = t.get("name", "Unknown")[:25]
        reads = t.get("reads", 0)
        species_lines.append(f"<b>{name}</b> ({reads:,} reads)")

    if len(detected_threats) > max_display:
        species_lines.append(f"...and {len(detected_threats) - max_display} more")

    species_text = "<br>".join(species_lines)

    fig.add_annotation(
        text=species_text,
        x=0.5, y=0.18,
        showarrow=False,
        font=dict(size=11, color=COLORS["gray_700"]),
        xref="paper", yref="paper",
        align="center"
    )

    fig.update_layout(
        height=300,
        paper_bgcolor=bg_color,
        margin=dict(l=20, r=20, t=30, b=20)
    )

    return apply_theme_to_figure(fig)


def create_quality_gauge(
    score: float,
    metric_name: str = "Quality Score",
    thresholds: Optional[Dict[str, float]] = None
) -> go.Figure:
    """
    Create an enhanced quality gauge with clear zone indicators.

    Args:
        score: Quality score (0-100)
        metric_name: Name of the metric
        thresholds: Dict with 'poor', 'fair', 'good', 'excellent' thresholds

    Returns:
        Plotly Figure object
    """
    thresholds = thresholds or {
        "poor": 60,
        "fair": 75,
        "good": 85,
        "excellent": 100
    }

    # Determine zone and color
    if score < thresholds["poor"]:
        bar_color = COLORS["danger"]
        status = "POOR"
        status_desc = "Review recommended"
    elif score < thresholds["fair"]:
        bar_color = COLORS["warning"]
        status = "FAIR"
        status_desc = "Acceptable quality"
    elif score < thresholds["good"]:
        bar_color = COLORS["safe"]
        status = "GOOD"
        status_desc = "Reliable results"
    else:
        bar_color = "#198754"  # Darker green for excellent
        status = "EXCELLENT"
        status_desc = "High confidence"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={
            "font": {"size": 42, "color": bar_color},
            "suffix": "%"
        },
        title={
            "text": (
                f"<b>{metric_name}</b><br>"
                f"<span style='font-size:14px;color:{bar_color}'>"
                f"{status} - {status_desc}</span>"
            ),
            "font": {"size": 14}
        },
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickcolor": COLORS["gray_400"],
                "tickvals": [
                    thresholds["poor"] / 2,
                    (thresholds["poor"] + thresholds["fair"]) / 2,
                    (thresholds["fair"] + thresholds["good"]) / 2,
                    (thresholds["good"] + 100) / 2
                ],
                "ticktext": ["Poor", "Fair", "Good", "Excellent"],
                "tickfont": {"size": 10}
            },
            "bar": {"color": bar_color, "thickness": 0.6},
            "bgcolor": COLORS["gray_200"],
            "borderwidth": 0,
            "steps": [
                {"range": [0, thresholds["poor"]], "color": "rgba(220, 53, 69, 0.15)"},
                {"range": [thresholds["poor"], thresholds["fair"]], "color": "rgba(255, 193, 7, 0.15)"},
                {"range": [thresholds["fair"], thresholds["good"]], "color": "rgba(40, 167, 69, 0.15)"},
                {"range": [thresholds["good"], 100], "color": "rgba(25, 135, 84, 0.15)"}
            ]
        }
    ))

    fig.update_layout(
        height=220,
        margin=dict(l=30, r=30, t=80, b=20),
        paper_bgcolor=COLORS["white"],
        font={"family": "Inter, system-ui, sans-serif"}
    )

    return apply_theme_to_figure(fig)


def create_realtime_reads_chart(
    time_series_data: List[Dict[str, Any]],
    title: str = "Read Accumulation Over Time"
) -> go.Figure:
    """
    Create a real-time updating line chart showing read accumulation.

    Args:
        time_series_data: List of dicts with 'timestamp' and 'cumulative_reads'
        title: Chart title

    Returns:
        Plotly Figure object
    """
    if not time_series_data:
        return _create_empty_chart("Waiting for data...")

    times = [d.get("timestamp", "") for d in time_series_data]
    reads = [d.get("cumulative_reads", 0) for d in time_series_data]

    fig = go.Figure()

    # Area fill
    fig.add_trace(go.Scatter(
        x=times,
        y=reads,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(0, 123, 255, 0.1)",
        line=dict(color=COLORS["primary"], width=2),
        name="Cumulative Reads",
        hovertemplate="<b>%{x}</b><br>Reads: %{y:,.0f}<extra></extra>"
    ))

    # Current value annotation
    if reads:
        fig.add_annotation(
            x=times[-1],
            y=reads[-1],
            text=f"<b>{reads[-1]:,}</b>",
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowcolor=COLORS["primary"],
            font=dict(size=14, color=COLORS["primary"]),
            bgcolor=COLORS["white"],
            bordercolor=COLORS["primary"],
            borderwidth=1,
            borderpad=4
        )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=16), x=0.5, xanchor="center"),
        xaxis=dict(title="Time", showgrid=True, gridcolor=COLORS["gray_200"]),
        yaxis=dict(title="Cumulative Reads", showgrid=True, gridcolor=COLORS["gray_200"], rangemode="tozero"),
        height=350,
        margin=dict(l=60, r=40, t=60, b=50),
        transition=dict(duration=500, easing="cubic-in-out")
    )

    return apply_theme_to_figure(fig)


def create_sample_progress_chart(
    samples: List[Dict[str, Any]],
    title: str = "Sample Processing Progress"
) -> go.Figure:
    """
    Create a stacked bar showing sample processing status.

    Args:
        samples: List of dicts with 'name' and 'status' (complete, processing, pending, failed)
        title: Chart title

    Returns:
        Plotly Figure object
    """
    status_counts = {
        "complete": 0,
        "processing": 0,
        "pending": 0,
        "failed": 0
    }

    for s in samples:
        status = s.get("status", "pending").lower()
        if status in status_counts:
            status_counts[status] += 1

    total = sum(status_counts.values())
    if total == 0:
        return _create_empty_chart("No samples")

    fig = go.Figure()

    status_colors = {
        "complete": COLORS["safe"],
        "processing": COLORS["primary"],
        "pending": COLORS["gray_300"],
        "failed": COLORS["danger"]
    }

    for status, count in status_counts.items():
        if count > 0:
            fig.add_trace(go.Bar(
                y=["Progress"],
                x=[count],
                orientation="h",
                name=status.capitalize(),
                marker_color=status_colors[status],
                text=[str(count)] if count > 0 else [""],
                textposition="inside",
                hovertemplate=f"{status.capitalize()}: %{{x}}<extra></extra>"
            ))

    complete_pct = (status_counts["complete"] / total * 100) if total > 0 else 0

    fig.update_layout(
        barmode="stack",
        title=dict(
            text=f"<b>{title}: {status_counts['complete']}/{total} Complete ({complete_pct:.0f}%)</b>",
            font=dict(size=14),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(range=[0, total], showticklabels=False, showgrid=False),
        yaxis=dict(showticklabels=False),
        height=120,
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.5,
            xanchor="center",
            x=0.5
        ),
        showlegend=True
    )

    return apply_theme_to_figure(fig)


def create_classification_donut(
    classified: int,
    unclassified: int,
    title: str = "",
    compact: bool = True
) -> go.Figure:
    """
    Create a donut chart showing classified vs unclassified reads.

    Args:
        classified: Number of classified reads
        unclassified: Number of unclassified reads
        title: Chart title (optional for compact mode)
        compact: If True, optimizes for small dashboard card

    Returns:
        Plotly Figure object
    """
    total = classified + unclassified
    if total == 0:
        # Empty state for compact view
        fig = go.Figure()
        fig.add_annotation(
            text="Waiting for data...",
            x=0.5, y=0.5,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=12, color=COLORS["gray_500"])
        )
        fig.update_layout(
            height=180 if compact else 300,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )
        return fig

    classification_rate = (classified / total * 100) if total > 0 else 0

    # Determine status color based on classification rate
    if classification_rate >= 80:
        rate_color = COLORS["safe"]
    elif classification_rate >= 60:
        rate_color = COLORS["warning"]
    else:
        rate_color = COLORS["danger"]

    fig = go.Figure(go.Pie(
        labels=["Classified", "Unclassified"],
        values=[classified, unclassified],
        hole=0.65 if compact else 0.6,
        marker=dict(
            colors=[COLORS["primary"], COLORS["gray_300"]],
            line=dict(color=COLORS["white"], width=2)
        ),
        textinfo="none" if compact else "percent",
        textposition="outside",
        hovertemplate="<b>%{label}</b><br>Count: %{value:,}<br>%{percent}<extra></extra>"
    ))

    # Animated transitions for smooth data updates
    fig.update_traces(
        rotation=90,
        sort=False
    )

    # Center text - show percentage with subtitle for operational clarity
    if compact:
        fig.add_annotation(
            text=(
                f"<b>{classification_rate:.0f}%</b><br>"
                f"<span style='font-size:9px;color:{COLORS['gray_600']}'>of reads identified</span>"
            ),
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=28, color=rate_color, family="Arial Black, Arial, sans-serif")
        )
    else:
        fig.add_annotation(
            text=(
                f"<b>{classification_rate:.1f}%</b><br>"
                f"<span style='font-size:11px;color:{COLORS['gray_600']}'>of reads identified</span>"
            ),
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=24, color=rate_color, family="Arial Black, Arial, sans-serif")
        )

    # Layout optimized for compact card
    if compact:
        fig.update_layout(
            height=180,
            margin=dict(l=5, r=5, t=5, b=25),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.15,
                xanchor="center",
                x=0.5,
                font=dict(size=11)
            ),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )
    else:
        fig.update_layout(
            title=dict(text=f"<b>{title}</b>", font=dict(size=14), x=0.5, xanchor="center") if title else None,
            height=300,
            margin=dict(l=40, r=40, t=60, b=40),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5, font=dict(size=12))
        )

    return apply_theme_to_figure(fig)


def create_quality_distribution_histogram(
    quality_scores: List[float],
    title: str = "Read Quality Distribution"
) -> go.Figure:
    """
    Create a histogram showing read quality score distribution.

    Args:
        quality_scores: List of quality scores
        title: Chart title

    Returns:
        Plotly Figure object
    """
    if not quality_scores:
        return _create_empty_chart("No quality data")

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=quality_scores,
        nbinsx=30,
        marker=dict(
            color=COLORS["primary"],
            line=dict(color=COLORS["gray_800"], width=0.5)
        ),
        hovertemplate="Q-Score: %{x:.1f}<br>Count: %{y:,}<extra></extra>"
    ))

    # Add threshold lines
    thresholds = [
        (10, COLORS["danger"], "Q10"),
        (15, COLORS["warning"], "Q15"),
        (20, COLORS["safe"], "Q20")
    ]

    for val, color, label in thresholds:
        fig.add_vline(
            x=val,
            line=dict(color=color, width=2, dash="dash"),
            annotation=dict(
                text=label,
                font=dict(size=10, color=color),
                textangle=-90
            )
        )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=14), x=0.5, xanchor="center"),
        xaxis=dict(title="Quality Score (Phred)", showgrid=True, gridcolor=COLORS["gray_200"]),
        yaxis=dict(title="Number of Reads", showgrid=True, gridcolor=COLORS["gray_200"]),
        height=350,
        margin=dict(l=60, r=40, t=60, b=50),
        bargap=0.05
    )

    return apply_theme_to_figure(fig)


def create_status_summary_cards(
    metrics: Dict[str, Any]
) -> go.Figure:
    """
    Create a multi-indicator display for key status metrics.

    Args:
        metrics: Dict with 'total_reads', 'quality_score', 'organisms_count', 'alerts_count'

    Returns:
        Plotly Figure object
    """
    fig = make_subplots(
        rows=1, cols=4,
        specs=[[{"type": "indicator"}] * 4]
    )

    # Total Reads
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=metrics.get("total_reads", 0),
            title={"text": "Total Reads", "font": {"size": 12}},
            number={"font": {"size": 28, "color": COLORS["primary"]}}
        ),
        row=1, col=1
    )

    # Quality Score
    quality = metrics.get("quality_score", 0)
    quality_color = COLORS["safe"] if quality >= 75 else COLORS["warning"] if quality >= 60 else COLORS["danger"]
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=quality,
            title={"text": "Quality", "font": {"size": 12}},
            number={"font": {"size": 28, "color": quality_color}, "suffix": "%"}
        ),
        row=1, col=2
    )

    # Organisms
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=metrics.get("organisms_count", 0),
            title={"text": "Organisms", "font": {"size": 12}},
            number={"font": {"size": 28, "color": "#6f42c1"}}
        ),
        row=1, col=3
    )

    # Alerts
    alerts = metrics.get("alerts_count", 0)
    alert_color = COLORS["safe"] if alerts == 0 else COLORS["warning"] if alerts <= 2 else COLORS["danger"]
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=alerts,
            title={"text": "Alerts", "font": {"size": 12}},
            number={"font": {"size": 28, "color": alert_color}}
        ),
        row=1, col=4
    )

    fig.update_layout(
        height=120,
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor=COLORS["white"]
    )

    return apply_theme_to_figure(fig)


def create_multi_sample_heatmap(
    abundance_data: Dict[str, Dict[str, float]],
    title: str = "Organism Abundance Across Samples",
    max_organisms: int = 25,
    min_abundance: float = 0.1,
    watched_species: Optional[List[Dict[str, Any]]] = None,
    normalize: bool = True,
    colorscale: str = "Viridis"
) -> go.Figure:
    """
    Create a heatmap showing organism abundance across multiple samples.

    This visualization is useful for comparing pathogen presence and abundance
    across different barcodes/samples in a single view.

    Args:
        abundance_data: Dict mapping sample_id -> {organism_name: abundance_value}
        title: Chart title
        max_organisms: Maximum number of organisms to show (top by mean abundance)
        min_abundance: Minimum abundance threshold to include an organism
        watched_species: List of watched species for highlighting
        normalize: If True, normalize each row (organism) to 0-1 range
        colorscale: Plotly colorscale name

    Returns:
        Plotly Figure object
    """
    if not abundance_data or all(not v for v in abundance_data.values()):
        return _create_empty_chart("No multi-sample data available")

    # Collect all organisms and their abundances
    samples = list(abundance_data.keys())
    all_organisms: Dict[str, Dict[str, float]] = {}

    for sample, org_data in abundance_data.items():
        for org_name, abundance in org_data.items():
            if abundance >= min_abundance:
                if org_name not in all_organisms:
                    all_organisms[org_name] = {}
                all_organisms[org_name][sample] = abundance

    if not all_organisms:
        return _create_empty_chart("No organisms above threshold")

    # Calculate mean abundance for each organism (for sorting)
    org_mean_abundance = {}
    for org_name, sample_data in all_organisms.items():
        org_mean_abundance[org_name] = np.mean(list(sample_data.values()))

    # Sort by mean abundance and limit
    sorted_organisms = sorted(
        org_mean_abundance.keys(),
        key=lambda x: org_mean_abundance[x],
        reverse=True
    )[:max_organisms]

    if not sorted_organisms:
        return _create_empty_chart("No organisms to display")

    # Build watched species lookup
    watched_lookup = set()
    if watched_species:
        for s in watched_species:
            name = s.get("name", "").lower().strip()
            if name:
                watched_lookup.add(name)

    # Build abundance matrix
    z_values = []
    organism_labels = []
    hover_texts = []

    for org_name in sorted_organisms:
        row_values = []
        row_hover = []
        org_data = all_organisms.get(org_name, {})

        # Truncate name for display
        display_name = org_name[:30] + "..." if len(org_name) > 30 else org_name

        # Mark watched species with indicator
        if org_name.lower().strip() in watched_lookup:
            display_name = f"* {display_name}"

        organism_labels.append(display_name)

        for sample in samples:
            val = org_data.get(sample, 0)
            row_values.append(val)
            row_hover.append(
                f"<b>{org_name}</b><br>"
                f"Sample: {sample}<br>"
                f"Abundance: {val:.2f}%"
            )

        z_values.append(row_values)
        hover_texts.append(row_hover)

    # Convert to numpy for potential normalization
    z_array = np.array(z_values, dtype=float)

    # Normalize per row if requested
    if normalize and z_array.shape[0] > 0:
        row_maxes = z_array.max(axis=1, keepdims=True)
        row_maxes[row_maxes == 0] = 1  # Avoid division by zero
        z_normalized = z_array / row_maxes
    else:
        z_normalized = z_array

    # Create heatmap
    fig = go.Figure(go.Heatmap(
        z=z_normalized.tolist(),
        x=samples,
        y=organism_labels,
        colorscale=colorscale,
        xgap=1,
        ygap=1,
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts,
        colorbar=dict(
            title=dict(
                text="Relative<br>Abundance" if normalize else "Abundance (%)",
                font=dict(size=11)
            ),
            tickfont=dict(size=10),
            thickness=15,
            len=0.6
        )
    ))

    # Add row annotations showing mean abundance
    for i, org in enumerate(sorted_organisms):
        mean_val = org_mean_abundance[org]
        fig.add_annotation(
            x=len(samples),
            y=i,
            text=f"{mean_val:.1f}%",
            showarrow=False,
            font=dict(size=9, color=COLORS["gray_600"]),
            xanchor="left",
            xref="x",
            yref="y"
        )

    height = responsive_height(len(sorted_organisms), base=150, per_item=25, max_height=800)

    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=14),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(
            title="Sample",
            tickangle=-45,
            tickfont=dict(size=10),
            side="bottom"
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=10),
            autorange="reversed"
        ),
        height=height,
        margin=dict(l=200, r=80, t=60, b=100)
    )

    # Add annotation for watched species indicator
    if watched_lookup:
        fig.add_annotation(
            text="* Watched species",
            xref="paper", yref="paper",
            x=0, y=-0.12,
            showarrow=False,
            font=dict(size=10, color=COLORS["threat_moderate"]),
            xanchor="left"
        )

    return apply_theme_to_figure(fig)


def create_sample_comparison_bar(
    abundance_data: Dict[str, Dict[str, float]],
    organism_name: str,
    title: Optional[str] = None
) -> go.Figure:
    """
    Create a bar chart comparing one organism's abundance across samples.

    Args:
        abundance_data: Dict mapping sample_id -> {organism_name: abundance_value}
        organism_name: Name of the organism to compare
        title: Chart title (defaults to organism name)

    Returns:
        Plotly Figure object
    """
    if not abundance_data:
        return _create_empty_chart("No sample data available")

    samples = []
    abundances = []

    for sample, org_data in abundance_data.items():
        samples.append(sample)
        abundances.append(org_data.get(organism_name, 0))

    if not any(abundances):
        return _create_empty_chart(f"'{organism_name}' not detected in any sample")

    # Color bars based on abundance
    colors = []
    for val in abundances:
        if val >= 5:
            colors.append(COLORS["threat_high"])
        elif val >= 1:
            colors.append(COLORS["threat_moderate"])
        elif val > 0:
            colors.append(COLORS["warning"])
        else:
            colors.append(COLORS["gray_300"])

    fig = go.Figure(go.Bar(
        x=samples,
        y=abundances,
        marker=dict(
            color=colors,
            line=dict(color=COLORS["gray_800"], width=0.5)
        ),
        text=[f"{v:.2f}%" if v > 0 else "" for v in abundances],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Abundance: %{y:.2f}%<extra></extra>"
    ))

    fig.update_layout(
        title=dict(
            text=f"<b>{title or organism_name}</b>",
            font=dict(size=14),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(
            title="Sample",
            tickangle=-45,
            tickfont=dict(size=11)
        ),
        yaxis=dict(
            title="Relative Abundance (%)",
            showgrid=True,
            gridcolor=COLORS["gray_200"],
            rangemode="tozero"
        ),
        height=350,
        margin=dict(l=60, r=40, t=60, b=100)
    )

    return apply_theme_to_figure(fig)


def create_alpha_diversity_chart(
    diversity_data: List[Dict[str, Any]],
    metric: str = "shannon",
    title: str = "Alpha Diversity by Sample"
) -> go.Figure:
    """
    Create a bar chart showing alpha diversity across samples.

    Args:
        diversity_data: List of dicts with 'sample_id' and diversity metrics
        metric: Which metric to display ('shannon', 'simpson', 'observed_species', 'chao1', 'evenness')
        title: Chart title

    Returns:
        Plotly Figure object
    """
    if not diversity_data:
        return _create_empty_chart("No diversity data available")

    samples = [d.get("sample_id", f"Sample {i}") for i, d in enumerate(diversity_data)]
    values = [d.get(metric, 0) for d in diversity_data]

    # Color bars based on diversity (higher = better, generally)
    mean_val = np.mean(values) if values else 0
    colors = []
    for val in values:
        if val >= mean_val * 1.2:
            colors.append(COLORS["safe"])
        elif val >= mean_val * 0.8:
            colors.append(COLORS["primary"])
        else:
            colors.append(COLORS["warning"])

    metric_labels = {
        "shannon": "Shannon Index (H')",
        "simpson": "Simpson Index (1-D)",
        "observed_species": "Observed Species",
        "chao1": "Chao1 Richness",
        "evenness": "Pielou's Evenness (J')"
    }

    fig = go.Figure(go.Bar(
        x=samples,
        y=values,
        marker=dict(
            color=colors,
            line=dict(color=COLORS["gray_800"], width=0.5)
        ),
        text=[f"{v:.2f}" if isinstance(v, float) else str(v) for v in values],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>%{y:.3f}<extra></extra>"
    ))

    # Add mean line
    fig.add_hline(
        y=mean_val,
        line_dash="dash",
        line_color=COLORS["gray_500"],
        annotation_text=f"Mean: {mean_val:.2f}",
        annotation_position="top right"
    )

    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=14),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(
            title="Sample",
            tickangle=-45,
            tickfont=dict(size=10)
        ),
        yaxis=dict(
            title=metric_labels.get(metric, metric),
            showgrid=True,
            gridcolor=COLORS["gray_200"],
            rangemode="tozero"
        ),
        height=400,
        margin=dict(l=60, r=40, t=60, b=100)
    )

    return apply_theme_to_figure(fig)


def create_beta_diversity_heatmap(
    beta_matrix: Dict[str, Dict[str, float]],
    title: str = "Bray-Curtis Dissimilarity Matrix"
) -> go.Figure:
    """
    Create a heatmap showing beta diversity (dissimilarity) between samples.

    Args:
        beta_matrix: Dict of dicts representing the dissimilarity matrix
        title: Chart title

    Returns:
        Plotly Figure object
    """
    if not beta_matrix:
        return _create_empty_chart("No beta diversity data available")

    # Convert dict to sorted lists
    samples = sorted(beta_matrix.keys())
    z_values = [[beta_matrix[s1].get(s2, 0) for s2 in samples] for s1 in samples]

    fig = go.Figure(go.Heatmap(
        z=z_values,
        x=samples,
        y=samples,
        colorscale="RdYlBu_r",  # Red = high dissimilarity, Blue = low
        zmin=0,
        zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in z_values],
        texttemplate="%{text}",
        textfont={"size": 10},
        hovertemplate="<b>%{x} vs %{y}</b><br>Dissimilarity: %{z:.3f}<extra></extra>",
        colorbar=dict(
            title=dict(text="Dissimilarity", font=dict(size=11)),
            tickfont=dict(size=10),
            thickness=15
        )
    ))

    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=14),
            x=0.5,
            xanchor="center"
        ),
        xaxis=dict(
            title="Sample",
            tickangle=-45,
            tickfont=dict(size=10)
        ),
        yaxis=dict(
            title="Sample",
            tickfont=dict(size=10),
            autorange="reversed"
        ),
        height=responsive_height(len(samples), base=150, per_item=40, max_height=800),
        margin=dict(l=100, r=80, t=60, b=100)
    )

    # Add annotation explaining the scale
    fig.add_annotation(
        text="0 = Identical, 1 = Completely Different",
        xref="paper", yref="paper",
        x=0.5, y=-0.15,
        showarrow=False,
        font=dict(size=10, color=COLORS["gray_600"]),
        xanchor="center"
    )

    return apply_theme_to_figure(fig)


def create_diversity_summary_cards(
    summary: Dict[str, Any]
) -> go.Figure:
    """
    Create a multi-indicator display for diversity summary statistics.

    Args:
        summary: Dict with diversity summary metrics

    Returns:
        Plotly Figure object
    """
    fig = make_subplots(
        rows=1, cols=4,
        specs=[[{"type": "indicator"}] * 4]
    )

    # Mean Shannon
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=summary.get("mean_shannon", 0),
            title={"text": "Mean Shannon", "font": {"size": 12}},
            number={"font": {"size": 28, "color": COLORS["primary"]}}
        ),
        row=1, col=1
    )

    # Mean Simpson
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=summary.get("mean_simpson", 0),
            title={"text": "Mean Simpson", "font": {"size": 12}},
            number={"font": {"size": 28, "color": "#6f42c1"}}
        ),
        row=1, col=2
    )

    # Mean Species
    species = summary.get("mean_species", 0)
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=species,
            title={"text": "Avg Species", "font": {"size": 12}},
            number={"font": {"size": 28, "color": COLORS["safe"]}}
        ),
        row=1, col=3
    )

    # Species Range
    min_sp = summary.get("min_species", 0)
    max_sp = summary.get("max_species", 0)
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=max_sp - min_sp,
            title={"text": "Species Range", "font": {"size": 12}},
            number={"font": {"size": 28, "color": COLORS["warning"]}, "suffix": f" ({min_sp}-{max_sp})"}
        ),
        row=1, col=4
    )

    fig.update_layout(
        height=120,
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor=COLORS["white"]
    )

    return apply_theme_to_figure(fig)


def _create_empty_chart(message: str, waiting: bool = False) -> go.Figure:
    """Create an empty chart with a styled message.

    Args:
        message: Message to display
        waiting: If True, shows "waiting for data" style; if False, shows "no results" style
    """
    # Detect waiting vs no-results from common message patterns
    is_waiting = waiting or any(
        w in message.lower() for w in ["waiting", "no data", "no sample"]
    )

    if is_waiting:
        icon_text = "&#8987;"  # hourglass
        subtitle = "Pipeline data will appear here when available"
        bg_color = COLORS["gray_100"]
    else:
        icon_text = "&#8709;"  # empty set
        subtitle = ""
        bg_color = COLORS["gray_100"]

    fig = go.Figure()

    # Icon
    fig.add_annotation(
        text=f"<span style='font-size:28px;color:{COLORS['gray_400']}'>{icon_text}</span>",
        x=0.5, y=0.62,
        xref="paper", yref="paper",
        showarrow=False
    )

    # Main message
    fig.add_annotation(
        text=f"<b>{message}</b>",
        x=0.5, y=0.42,
        xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=14, color=COLORS["gray_600"])
    )

    # Subtitle hint
    if subtitle:
        fig.add_annotation(
            text=subtitle,
            x=0.5, y=0.28,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=11, color=COLORS["gray_400"])
        )

    fig.update_layout(
        height=200,
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color
    )

    return fig
