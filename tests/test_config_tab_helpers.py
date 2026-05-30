"""
Unit tests for app/tabs/config_tab_helpers.py (extracted from config_tab.py).

_build_config_list_items renders saved-config metadata into ListGroup rows, with
the auto-saved last-session.yaml shown specially (renamed, no delete button).
"""

import pytest
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.config_tab_helpers import _build_config_list_items

pytestmark = pytest.mark.unit


class TestBuildConfigListItems:
    def test_empty(self):
        assert _build_config_list_items([]) == []

    def test_regular_config_has_load_and_delete(self):
        items = _build_config_list_items([
            {"name": "My Run", "filename": "my_run.yaml",
             "timestamp": "2026-05-30T10:00:00"},
        ])
        assert len(items) == 1
        text = str(items[0])
        assert "My Run" in text
        assert "load-config-item" in text
        assert "delete-config-item" in text  # regular config is deletable
        assert "2026-05-30 10:00:00" in text  # timestamp formatted

    def test_autosave_renamed_and_not_deletable(self):
        items = _build_config_list_items([
            {"name": "whatever", "filename": "last-session.yaml",
             "timestamp": "2026-05-30T10:00:00"},
        ])
        text = str(items[0])
        assert "Last Session (auto-saved)" in text
        assert "delete-config-item" not in text  # autosave cannot be deleted

    def test_bad_timestamp_passed_through(self):
        items = _build_config_list_items([
            {"name": "x", "filename": "x.yaml", "timestamp": "not-a-date"},
        ])
        assert "not-a-date" in str(items[0])

    def test_indices_increment(self):
        items = _build_config_list_items([
            {"name": "a", "filename": "a.yaml"},
            {"name": "b", "filename": "b.yaml"},
        ])
        assert '"index": 0' in str(items[0]) or "'index': 0" in str(items[0])
        assert '"index": 1' in str(items[1]) or "'index': 1" in str(items[1])
