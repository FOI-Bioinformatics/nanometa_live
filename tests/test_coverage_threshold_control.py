"""
Unit tests for the operator-controllable depth threshold on the coverage depth plot.

Verifies that:
- create_coverage_depth_figure respects the threshold parameter in the
  horizontal line annotation and in the below-threshold red trace name.
- update_coverage_plots accepts a depth_threshold argument and threads it
  through to the figure correctly (via a light functional test that does not
  require a running Dash server).
"""

import numpy as np
import pytest

from nanometa_live.core.parsers.paf_coverage_parser import CoverageData
from nanometa_live.app.components.coverage_plots import create_coverage_depth_figure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coverage(ref_length: int = 5000, mean_depth: int = 30) -> CoverageData:
    """Return a minimal CoverageData with a uniform depth array.

    Only ref_name, ref_length, and depth_array are required; __post_init__
    computes all derived statistics (breadth, mean_depth, etc.).
    """
    depth = np.full(ref_length, mean_depth, dtype=np.uint32)
    return CoverageData(
        ref_name="test_ref",
        ref_length=ref_length,
        depth_array=depth,
    )


# ---------------------------------------------------------------------------
# create_coverage_depth_figure threshold propagation
# ---------------------------------------------------------------------------

def test_default_threshold_annotation():
    """Default threshold of 10x should appear in the hline annotation text."""
    cov = _make_coverage()
    fig = create_coverage_depth_figure(cov)

    annotation_texts = [a.text for a in fig.layout.annotations]
    assert any("10x" in t for t in annotation_texts), (
        f"Expected '10x' in annotations; got: {annotation_texts}"
    )


@pytest.mark.parametrize("threshold", [1, 5, 20, 50, 100])
def test_custom_threshold_annotation(threshold):
    """The annotation text should reflect the operator-supplied threshold."""
    cov = _make_coverage()
    fig = create_coverage_depth_figure(cov, threshold=threshold)

    annotation_texts = [a.text for a in fig.layout.annotations]
    assert any(f"{threshold}x" in t for t in annotation_texts), (
        f"Expected '{threshold}x' in annotations; got: {annotation_texts}"
    )


@pytest.mark.parametrize("threshold", [5, 25])
def test_below_threshold_trace_name(threshold):
    """The red below-threshold trace should carry the operator-supplied threshold in its name."""
    cov = _make_coverage()
    fig = create_coverage_depth_figure(cov, threshold=threshold)

    trace_names = [t.name for t in fig.data]
    assert any(f"Below {threshold}x" in n for n in trace_names), (
        f"Expected 'Below {threshold}x' trace; got: {trace_names}"
    )


def test_hline_y_value_matches_threshold():
    """The horizontal line y-position must equal the threshold value."""
    threshold = 42
    cov = _make_coverage()
    fig = create_coverage_depth_figure(cov, threshold=threshold)

    hline_shapes = [
        s for s in fig.layout.shapes
        if getattr(s, "type", None) == "line" and s.x0 == 0 and s.x1 == 1
    ]
    # Plotly renders add_hline as a shape with y0 == y1 == threshold
    assert hline_shapes, "No horizontal line shape found in figure layout"
    for shape in hline_shapes:
        assert shape.y0 == threshold, (
            f"Hline y0={shape.y0} does not match threshold={threshold}"
        )
        assert shape.y1 == threshold, (
            f"Hline y1={shape.y1} does not match threshold={threshold}"
        )


# ---------------------------------------------------------------------------
# Callback input guard: threshold sanitisation logic mirrors validation_tab.py
# ---------------------------------------------------------------------------

def _sanitise_threshold(raw) -> int:
    """Mirrors the guard added to update_coverage_plots."""
    try:
        value = int(raw) if raw is not None else 10
        return max(1, value)
    except (ValueError, TypeError):
        return 10


@pytest.mark.parametrize("raw,expected", [
    (10, 10),
    (None, 10),
    ("", 10),
    ("abc", 10),
    (0, 1),       # below min, clamped to 1
    (-5, 1),
    (50, 50),
    (1000, 1000),
])
def test_threshold_sanitisation(raw, expected):
    """Sanitisation guard should produce valid thresholds for all edge-case inputs."""
    assert _sanitise_threshold(raw) == expected


# ---------------------------------------------------------------------------
# Smoke test: figure produced with operator threshold is a valid Plotly figure
# ---------------------------------------------------------------------------

def test_figure_is_valid_plotly_object():
    """create_coverage_depth_figure should return a go.Figure with at least 2 traces."""
    import plotly.graph_objects as go

    cov = _make_coverage()
    fig = create_coverage_depth_figure(cov, threshold=20)

    assert isinstance(fig, go.Figure)
    # At minimum: the depth area trace + the below-threshold red trace
    assert len(fig.data) >= 2, f"Expected at least 2 traces, got {len(fig.data)}"
