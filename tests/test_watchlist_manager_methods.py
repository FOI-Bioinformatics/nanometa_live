"""Tests for previously-uncovered WatchlistManager methods: toggle-state view,
config export, and taxonomy-mode selection.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    WatchlistSource,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    yield
    reset_watchlist_manager()


@pytest.fixture
def manager():
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = WatchlistManager()
        mgr._entries.clear()
        mgr._name_index.clear()
        mgr.add_custom_entry({
            "taxid": 700, "name": "Aaa criticus", "threat_level": "critical",
            "enabled": True, "alert_threshold": 5, "bsl_level": 3,
        })
        mgr.add_custom_entry({
            "taxid": 701, "name": "Zzz lowus", "threat_level": "low", "enabled": False,
        })
        yield mgr


def test_entries_with_toggle_state_shape_and_sort(manager):
    rows = manager.get_entries_with_toggle_state()
    assert len(rows) == 2
    # critical sorts before low
    assert rows[0]["taxid"] == 700
    r = rows[0]
    assert r["can_toggle"] is True
    assert r["can_remove"] is True            # custom (USER) entries are removable
    assert r["threat_level_display"] == "Critical"
    assert r["bsl_display"] == "BSL-3"
    assert rows[1]["bsl_display"] == "N/A"     # no bsl on the low entry


def test_export_config_includes_custom_entries(manager):
    cfg = manager.export_config()
    assert cfg["enabled"] is True
    assert "taxonomy_mode" in cfg
    custom_taxids = {e["taxid"] for e in cfg["custom"]}
    assert custom_taxids == {700, 701}        # both are USER-source custom entries


def test_export_config_records_builtin_override(manager):
    # Turn a custom entry into an "override" by simulating a builtin source +
    # user_override, then confirm export captures it under overrides.
    entry = manager._entries[700]
    entry.source = WatchlistSource.BUILTIN
    entry.user_override = True
    entry.alert_threshold = 42
    cfg = manager.export_config()
    overrides = {o["taxid"]: o for o in cfg["overrides"]}
    assert 700 in overrides
    assert overrides[700]["alert_threshold"] == 42


@pytest.mark.parametrize("mode", ["ncbi", "gtdb", "auto"])
def test_set_and_get_taxonomy_mode(manager, mode):
    manager.set_taxonomy_mode(mode)
    assert manager.get_taxonomy_mode() == mode


def test_set_taxonomy_mode_ignores_invalid(manager):
    manager.set_taxonomy_mode("ncbi")
    manager.set_taxonomy_mode("nonsense")     # invalid -> unchanged
    assert manager.get_taxonomy_mode() == "ncbi"
