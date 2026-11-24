"""The Reports tab's real-time panel labels the pipeline's read estimate.

nanometanf estimates a batch's reads from its file size
(``file_size * 4 / 4000``); the panel showed that figure as "Total reads"
beside the counted reads on the Dashboard (Barcelona exercise feedback,
2026-11-24).
"""

import pytest
from dash.development.base_component import Component

from nanometa_live.app.tabs.reports_helpers import (
    ESTIMATE_NOTE,
    build_realtime_performance_panel,
)

pytestmark = pytest.mark.unit


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if isinstance(child, Component):
            yield from _walk(child)


def _all_text(component):
    parts = []
    for node in _walk(component):
        children = getattr(node, "children", None)
        if isinstance(children, str):
            parts.append(children)
        elif isinstance(children, (list, tuple)):
            parts.extend(c for c in children if isinstance(c, str))
    return " ".join(parts)


def _all_titles(component):
    return [getattr(n, "title", None) for n in _walk(component)
            if getattr(n, "title", None)]


def test_estimated_reads_tile_is_labelled_as_estimate():
    panel = build_realtime_performance_panel({
        "totals": {"total_estimated_reads": 596019},
        "performance": {"reads_per_second": 168.0},
    })
    text = _all_text(panel)
    assert "Reads (estimated)" in text
    assert "Est. reads/sec" in text
    assert "Total reads" not in text


def test_estimate_tiles_carry_the_explanation_as_title():
    panel = build_realtime_performance_panel(
        {"totals": {"total_estimated_reads": 10}}
    )
    assert _all_titles(panel).count(ESTIMATE_NOTE) == 2


def test_trend_axis_says_estimated():
    panel = build_realtime_performance_panel({
        "totals": {"total_estimated_reads": 10},
        "trends": {"batch_read_counts": [5, 5]},
    })
    graphs = [n for n in _walk(panel) if n.__class__.__name__ == "Graph"]
    assert graphs
    assert graphs[0].figure.layout.yaxis.title.text == "Reads (estimated)"
