"""Minimum abundance: 0 means 0, and values below 0.1% can be entered.

``min_abundance or 0.1`` turned a typed 0 into 0.1, and ``step=0.1`` made
0.05 invalid in the browser (sent as None, so 0.1 again): a watched-free
organism at 0.05% could not be shown at all (live test 2026-11-24).
"""

import pytest

from nanometa_live.app.tabs.main_tab_helpers import resolve_min_abundance

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value,expected", [
    (None, 0.1), ("", 0.1), (0, 0.0), (0.05, 0.05), (2, 2.0), (-1, 0.0),
])
def test_resolve_min_abundance(value, expected):
    assert resolve_min_abundance(value) == pytest.approx(expected)


def test_input_accepts_any_decimal():
    from nanometa_live.app.layouts.main_layout import create_main_layout

    def walk(n):
        yield n
        ch = getattr(n, "children", None)
        for c in (ch if isinstance(ch, (list, tuple)) else [ch] if ch is not None else []):
            yield from walk(c)

    box = next(n for n in walk(create_main_layout()) if getattr(n, "id", None) == "min-abundance")
    assert box.step == "any"
