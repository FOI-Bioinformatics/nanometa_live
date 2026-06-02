"""
Unit tests for app/tabs/config_tab_helpers.py (extracted from config_tab.py).

_build_config_list_items renders saved-config metadata into ListGroup rows, with
the auto-saved last-session.yaml shown specially (renamed, no delete button).
"""

import inspect

import pytest
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.config_tab_helpers import (
    _build_config_list_items,
    build_config_from_form,
)

pytestmark = pytest.mark.unit


def _build(**overrides):
    """Call build_config_from_form with every form field None except overrides."""
    params = [
        p for p in inspect.signature(build_config_from_form).parameters
        if p != "current_config"
    ]
    kwargs = {p: None for p in params}
    kwargs.update(overrides)
    return build_config_from_form({"data_dir": "/tmp/nm_cfg_helper_test"}, **kwargs)


class TestBuildConfigFromForm:
    def test_missing_required_fields_return_errors_and_no_config(self):
        config, errors = _build()
        assert config is None
        joined = "\n".join(errors)
        assert "Nanopore Sequence Data Folder (input) is required" in joined
        assert "Kraken2 Database is required" in joined

    def test_numeric_bound_violation_reported(self):
        # gui_port below the 1024 floor is rejected even though the required
        # path fields are also missing -- errors accumulate into one list.
        _config, errors = _build(gui_port=80)
        assert any("GUI Port must be between 1024-65535" in e for e in errors)

    def test_returns_two_tuple_shape(self):
        result = _build()
        assert isinstance(result, tuple) and len(result) == 2


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
