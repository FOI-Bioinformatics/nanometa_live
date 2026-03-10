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
from nanometa_live.app.utils.plotly_theme import register_templates

register_templates()

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
            text=f"Genome Coverage Depth - {coverage.ref_name}",
            font=dict(size=14, color="#374151"),
        ),
        xaxis=dict(
            title="Genome Position (bp)",
            rangeslider=dict(visible=True, thickness=0.06),
            tickformat=",",
        ),
        yaxis=dict(title="Read Depth"),
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
    fractions = np.array([
        np.sum(depth >= t) / coverage.ref_length * 100 for t in thresholds
    ])

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
        title=dict(text="Cumulative Coverage", font=dict(size=13, color="#374151")),
        xaxis_title="Minimum Depth",
        yaxis_title="Genome Covered (%)",
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
        title=dict(text="Depth Distribution", font=dict(size=13, color="#374151")),
        xaxis_title="Depth",
        yaxis_title="Positions",
        yaxis_tickformat=",",
        template="nanometa",
        height=280,
        margin=dict(l=50, r=20, t=40, b=40),
        font=dict(family="Arial, sans-serif", size=12),
        showlegend=False,
        bargap=0.05,
    )

    return fig


def create_coverage_stats_summary(coverage: CoverageData) -> dbc.Row:
    """
    Create a row of summary statistics for coverage data.

    Args:
        coverage: CoverageData object.

    Returns:
        dbc.Row with stat badges.
    """
    items = [
        ("Breadth", f"{coverage.breadth * 100:.1f}%"),
        ("Mean Depth", f"{coverage.mean_depth:.1f}x"),
        ("Median Depth", f"{coverage.median_depth:.1f}x"),
        ("Max Depth", f"{coverage.max_depth:,}x"),
        ("Genome Length", f"{coverage.ref_length:,} bp"),
    ]

    cols = []
    for label, value in items:
        cols.append(dbc.Col(
            html.Div([
                html.Small(label, className="text-muted d-block"),
                html.Strong(value),
            ], className="text-center"),
            className="col",
        ))

    return dbc.Row(cols, className="mb-3 g-2")


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
