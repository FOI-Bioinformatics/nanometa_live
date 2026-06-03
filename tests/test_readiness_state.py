"""Tests for the readiness single-source Store: dedup helpers + header pill.

The recompute callback (update_readiness_state) deduplicates Store writes so an
idle update-interval tick neither re-runs ReadinessChecker nor re-fires the
renderers (which would re-open the Preparation checklist every 30 s). These
cover the pure dedup helpers and the header-pill renderer; the end-to-end
no-rewrite-on-idle behaviour is checked by the browser smoke test.
"""

import pytest
from dash import Dash

from dash_test_utils import get_callback_fn
from nanometa_live.app.callbacks.readiness import (
    _readiness_fingerprint,
    _readiness_unchanged,
    register_readiness,
)

pytestmark = pytest.mark.callback


def _text(component):
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, (list, tuple)):
            for c in node:
                walk(c)
        else:
            ch = getattr(node, "children", None)
            if ch is not None:
                walk(ch)

    walk(component)
    return " ".join(out)


class TestFingerprint:
    def test_irrelevant_field_does_not_change_fingerprint(self):
        base = {"kraken_db": "/db", "main_dir": "/m"}
        noisy = {**base, "last_selected_sample": "barcode09", "ui_theme": "dark"}
        assert _readiness_fingerprint(base) == _readiness_fingerprint(noisy)

    def test_relevant_field_changes_fingerprint(self):
        assert _readiness_fingerprint({"kraken_db": "/a"}) != \
            _readiness_fingerprint({"kraken_db": "/b"})

    def test_no_config_sentinel(self):
        assert _readiness_fingerprint(None) == "no-config"


class TestUnchanged:
    def _state(self, ready=True, computed_at=1.0):
        return {
            "ready": ready,
            "error": None,
            "summary": {"total": 2, "passed": 2 if ready else 1},
            "checks": [{"name": "Kraken2 Database", "passed": True}],
            "computed_at": computed_at,
        }

    def test_equal_ignoring_computed_at(self):
        # Same readiness, different timestamp -> treated as unchanged.
        assert _readiness_unchanged(self._state(computed_at=1.0),
                                    self._state(computed_at=999.0)) is True

    def test_changed_ready_flag(self):
        assert _readiness_unchanged(self._state(ready=True),
                                    self._state(ready=False)) is False

    def test_no_prev_is_changed(self):
        assert _readiness_unchanged(None, self._state()) is False


class TestHeaderPill:
    @pytest.fixture
    def render(self):
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_readiness(app, None)
        return get_callback_fn(app, "readiness-badge.children")

    def test_ready_is_green(self, render):
        state = {"ready": True, "checks": [{"name": "x", "passed": True}],
                 "summary": {"passed": 1, "total": 1, "critical_failures": 0}}
        children, color, _popover = render(state)
        assert color == "success"
        assert "Ready" in _text(children)

    def test_critical_failure_is_danger(self, render):
        state = {"ready": False,
                 "checks": [{"name": "Kraken2 Database", "passed": False,
                             "severity": "critical", "message": "missing"}],
                 "summary": {"passed": 0, "total": 1, "critical_failures": 1}}
        children, color, _popover = render(state)
        assert color == "danger"
        assert "0/1 checks" in _text(children)

    def test_warning_only_is_warning(self, render):
        state = {"ready": False,
                 "checks": [{"name": "Disk Space", "passed": False,
                             "severity": "warning", "message": "low"}],
                 "summary": {"passed": 0, "total": 1, "critical_failures": 0}}
        _children, color, _popover = render(state)
        assert color == "warning"

    def test_no_config_is_secondary(self, render):
        children, color, _popover = render(
            {"checks": [], "error": "No configuration loaded"})
        assert color == "secondary"
        assert "Not configured" in _text(children)
