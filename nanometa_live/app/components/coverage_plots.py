"""
Coverage plot components for the validation tab.

Provides three Plotly figure creators for visualizing per-position genome
coverage from minimap2 PAF alignments:

1. Genome coverage depth (area chart with range slider)
2. Cumulative coverage curve
3. Depth distribution histogram
"""

import numpy as np
import plotly.graph_objects as go
from dash import html
import dash_bootstrap_components as dbc
# Importing plotly_theme registers the "nanometa" Plotly template as an
# import-time side effect (plotly_theme calls _safe_register_templates() at
# module load); the figures below reference that template by name. The
# previous explicit register_templates() call re-registered it on every
# worker-process import for no benefit.
import nanometa_live.app.utils.plotly_theme  # noqa: F401

from nanometa_live.core.parsers.paf_coverage_parser import CoverageData


def create_coverage_depth_figure(
    coverage: CoverageData,
    threshold: int = 10,
    window_size: int = 0,
) -> go.Figure:
    """
    Create a genome coverage depth area chart.

    Args:
        coverage: CoverageData with depth array.
        threshold: Depth threshold for horizontal line.
        window_size: Rolling average window. 0 = auto (1000 for genomes > 500 Kbp).

    Returns:
        Plotly Figure.
    """
    depth = coverage.depth_array

    # Auto window size
    if window_size == 0:
        if coverage.ref_length > 500_000:
            window_size = max(1, coverage.ref_length // 5000)
        else:
            window_size = max(1, coverage.ref_length // 1000)

    # Smooth for display
    if window_size > 1 and len(depth) > window_size:
        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(depth, kernel, mode="same")
    else:
        smoothed = depth.astype(float)

    # Downsample to max ~5000 points for performance
    max_points = 5000
    if len(smoothed) > max_points:
        step = len(smoothed) // max_points
        x = np.arange(0, len(smoothed), step)
        y = smoothed[::step]
    else:
        x = np.arange(len(smoothed))
        y = smoothed

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(31, 119, 180, 0.3)",
        line=dict(color="rgba(31, 119, 180, 0.8)", width=1),
        name="Depth",
        hovertemplate="Position: %{x:,.0f} bp<br>Depth: %{y:.1f}x<extra></extra>",
    ))

    # Highlight regions below threshold
    below_y = np.where(y < threshold, y, np.nan)
    fig.add_trace(go.Scatter(
        x=x, y=below_y,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(220, 53, 69, 0.25)",
        line=dict(color="rgba(220, 53, 69, 0.6)", width=0),
        name=f"Below {threshold}x",
        hoverinfo="skip",
        showlegend=True,
    ))

    # Threshold line
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#6c757d",
        annotation_text=f"{threshold}x threshold",
        annotation_position="top right",
        annotation_font_size=11,
        annotation_font_color="#6c757d",
    )

    fig.update_layout(
        title=dict(
            text=f"How deeply each part of the genome is covered - {coverage.ref_name}",
            font=dict(size=14, color="#374151"),
        ),
        xaxis=dict(
            title="Position along genome",
            rangeslider=dict(visible=True, thickness=0.06),
            tickformat=",",
        ),
        yaxis=dict(title="Number of overlapping sequences"),
        template="nanometa",
        height=450,
        margin=dict(l=50, r=30, t=50, b=30),
        font=dict(family="Arial, sans-serif", size=12),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        showlegend=True,
        hovermode="x unified",
    )

    return fig


def create_cumulative_coverage_figure(coverage: CoverageData) -> go.Figure:
    """
    Create a cumulative coverage curve showing fraction of genome at >= N depth.

    Args:
        coverage: CoverageData with depth array.

    Returns:
        Plotly Figure.
    """
    depth = coverage.depth_array
    max_d = min(int(np.percentile(depth[depth > 0], 99)) if np.any(depth > 0) else 1, 500)

    thresholds = np.arange(0, max_d + 1)
    # Vectorized: count(depth >= t) for every threshold at once. Sorting once
    # then searchsorted is O(N log N + max_d) instead of the previous
    # O(max_d * N) Python loop (up to ~2.5e9 comparisons on a 5 Mbp genome).
    # count(depth >= t) == N - (number of elements < t).
    sorted_depth = np.sort(depth)
    counts_at_or_above = sorted_depth.size - np.searchsorted(
        sorted_depth, thresholds, side="left"
    )
    fractions = counts_at_or_above / coverage.ref_length * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=thresholds, y=fractions,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(40, 167, 69, 0.2)",
        line=dict(color="#28a745", width=2),
        hovertemplate="Depth >= %{x}x<br>Genome covered: %{y:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text="How much of the genome is covered at each depth", font=dict(size=13, color="#374151")),
        xaxis_title="Minimum number of overlapping sequences",
        yaxis_title="Genome covered (%)",
        yaxis_range=[0, 105],
        template="nanometa",
        height=280,
        margin=dict(l=50, r=20, t=40, b=40),
        font=dict(family="Arial, sans-serif", size=12),
        showlegend=False,
        hovermode="x",
    )

    return fig


def create_depth_histogram_figure(
    coverage: CoverageData, n_bins: int = 50
) -> go.Figure:
    """
    Create a depth distribution histogram.

    Args:
        coverage: CoverageData with depth array.
        n_bins: Number of histogram bins.

    Returns:
        Plotly Figure.
    """
    depth = coverage.depth_array
    # Exclude zeros for cleaner histogram, but note them
    nonzero = depth[depth > 0]
    if len(nonzero) == 0:
        nonzero = depth

    max_d = int(np.percentile(nonzero, 99)) if len(nonzero) > 0 else 1
    bins = np.linspace(0, max_d, n_bins + 1)
    counts, edges = np.histogram(depth, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=centers, y=counts,
        marker_color="rgba(13, 110, 253, 0.7)",
        hovertemplate="Depth: %{x:.0f}x<br>Positions: %{y:,}<extra></extra>",
    ))

    # Mark mean depth
    fig.add_vline(
        x=coverage.mean_depth,
        line_dash="dash",
        line_color="#fd7e14",
        annotation_text=f"Mean: {coverage.mean_depth:.1f}x",
        annotation_position="top right",
        annotation_font_size=10,
    )

    fig.update_layout(
        title=dict(text="Distribution of coverage depth across the genome", font=dict(size=13, color="#374151")),
        xaxis_title="Number of overlapping sequences",
        yaxis_title="Number of genome positions",
        yaxis_tickformat=",",
        template="nanometa",
        height=280,
        margin=dict(l=50, r=20, t=40, b=40),
        font=dict(family="Arial, sans-serif", size=12),
        showlegend=False,
        bargap=0.05,
    )

    return fig


def create_coverage_stats_summary(coverage: CoverageData) -> html.Div:
    """
    Create a row of summary statistics for coverage data.

    Uses plain-language labels so that non-expert operators can
    interpret the results without bioinformatics knowledge.

    Args:
        coverage: CoverageData object.

    Returns:
        html.Div with stat badges and an interpretation line.
    """
    items = [
        ("Genome Covered", f"{coverage.breadth * 100:.1f}%",
         "Percentage of the reference genome with at least one matching sequence"),
        ("Avg. Depth", f"{coverage.mean_depth:.1f}x",
         "Average number of sequences covering each position"),
        ("Typical Depth", f"{coverage.median_depth:.1f}x",
         "Median depth - less affected by outlier regions"),
        ("Peak Depth", f"{coverage.max_depth:,}x",
         "Maximum depth at any single position"),
        ("Genome Size", f"{coverage.ref_length:,} bp",
         "Total length of the reference genome"),
    ]

    cols = []
    for label, value, tooltip_text in items:
        cols.append(dbc.Col(
            html.Div([
                html.Small(label, className="text-muted d-block"),
                html.Strong(value),
            ], className="text-center",
               title=tooltip_text),
            className="col",
        ))

    # Add interpretation line
    breadth_pct = coverage.breadth * 100
    if breadth_pct >= 80 and coverage.mean_depth >= 10:
        interp_color = "success"
        interp_text = "Good coverage - species identification is well-supported by the data."
    elif breadth_pct >= 50 or coverage.mean_depth >= 5:
        interp_color = "warning"
        interp_text = ("Partial coverage - some evidence supports this identification, "
                       "but more sequencing data would strengthen confidence.")
    elif breadth_pct > 0:
        interp_color = "danger"
        interp_text = ("Low coverage - insufficient data to confirm this species. "
                       "Continue sequencing or verify with an alternative method.")
    else:
        interp_color = "secondary"
        interp_text = "No coverage detected for this reference genome."

    return html.Div([
        dbc.Row(cols, className="mb-2 g-2"),
        dbc.Alert(
            [
                html.I(className=f"bi bi-{'check-circle' if interp_color == 'success' else 'exclamation-triangle' if interp_color in ('warning', 'danger') else 'info-circle'}-fill me-2"),
                html.Span(interp_text),
            ],
            color=interp_color,
            className="mb-0 py-2",
            style={"fontSize": "13px"},
        ),
    ])


def create_empty_coverage_figure(
    title: str = "No coverage data",
    message: str = "Select a species to view coverage",
) -> go.Figure:
    """Create a placeholder figure when no data is available."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color="#9CA3AF"),
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#374151")),
        template="nanometa",
        height=300,
        margin=dict(l=50, r=30, t=40, b=30),
        font=dict(family="Arial, sans-serif", size=12),
    )
    return fig
