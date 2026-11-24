"""The header row must size its outer columns to their content.

With fixed widths (4/5/3 of 12) the controls column -- Offline switch,
readiness pill, save badge and a large Start button -- needs more than a
quarter of a 1366 px laptop screen, so its contents spilled left over the
status text ("Visualization mode - displaying existing results" ran under
the Offline switch; 2026-11-23 live walk). Content-sized outer columns let
the status column take the remaining width and wrap, and let the row wrap
at narrow widths instead of overlapping.
"""

import dash_bootstrap_components as dbc
import pytest

from nanometa_live.app.components.header import create_header

pytestmark = pytest.mark.unit


def _top_row(header):
    stack = [header]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dbc.Row):
            return node
        children = getattr(node, "children", None)
        if children is None:
            continue
        stack.extend(children if isinstance(children, (list, tuple)) else [children])
    raise AssertionError("no dbc.Row in the header")


def test_outer_columns_are_content_sized():
    cols = _top_row(create_header("Run")).children
    assert len(cols) == 3
    logo, status, controls = cols
    assert logo.width == "auto"
    assert controls.width == "auto"
    assert getattr(status, "width", None) is None   # takes the remaining space
