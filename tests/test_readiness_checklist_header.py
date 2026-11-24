"""The checklist header must say what the non-passing checks are.

"11/25 checks passed" read as fourteen failures when most of the rest were
amber warnings that do not block a run (2026-11-23 live walk). The header now
states the warnings and the critical failures beside the passed count.
"""

import pytest

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


def _text(node):
    if isinstance(node, str):
        return node
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if not isinstance(children, (list, tuple)):
        children = [children]
    return "".join(_text(c) for c in children)


def test_header_states_warnings_and_critical_failures():
    from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks
    app = make_callback_app(register_preparation_callbacks)
    fn = get_callback_fn(app, "readiness-results.children")
    state = {
        "ready": False,
        "checks": [{"name": "x", "passed": False, "severity": "warning", "message": ""}],
        "summary": {"total": 25, "passed": 11, "warnings": 9,
                    "critical_failures": 5, "failed": 14},
    }
    content, _ = fn(state)
    header = _text(content.children[0])
    assert "11 of 25 checks passed" in header
    assert "9 warnings" in header
    assert "5 critical" in header


@pytest.mark.parametrize("crit,warn,text,color", [
    (5, 9, "5 blocking", "danger"),
    (0, 3, "3 warnings", "warning"),
    (0, 1, "1 warning", "warning"),
])
def test_header_pill_names_what_blocks(crit, warn, text, color):
    """The pill read "17/25 checks" in red; it now says what is wrong."""
    from nanometa_live.app.callbacks.readiness import register_readiness
    from unittest.mock import MagicMock

    app = make_callback_app(lambda a: register_readiness(a, MagicMock()))
    fn = get_callback_fn(app, "readiness-badge.children")
    state = {
        "ready": False,
        "checks": [{"name": "x", "passed": False, "severity": "warning"}],
        "summary": {"total": 25, "passed": 25 - crit - warn,
                    "warnings": warn, "critical_failures": crit},
    }
    children, badge_color, _ = fn(state)
    assert text in "".join(c for c in children if isinstance(c, str))
    assert badge_color == color
