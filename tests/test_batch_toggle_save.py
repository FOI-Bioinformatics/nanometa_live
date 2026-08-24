"""Enable/Disable All persists toggle state once, not once per entry.

`toggle_entry` fsyncs the full toggle-state YAML on every call, so
"Enable All" on a 500-entry watchlist was 500 fcntl locks + 500 YAML dumps
+ 500 fsyncs, serially, on the click thread (round-2 audit, 2026-08-22).
`set_entries_enabled` applies the whole batch under one lock with a single
save; the disk format is unchanged.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
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
        for i in range(50):
            mgr.add_custom_entry({
                "taxid": 91000 + i, "name": f"Fillerus organismus{i}",
                "threat_level": "high", "enabled": True, "alert_threshold": 10,
            })
        yield mgr


class TestSetEntriesEnabled:
    def test_one_save_for_the_whole_batch(self, manager):
        saves = {"n": 0}
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: saves.__setitem__("n", saves["n"] + 1)):
            changed = manager.set_entries_enabled(
                [91000 + i for i in range(50)], False)
        assert changed == 50
        assert saves["n"] == 1, (
            f"{saves['n']} toggle-state saves for one batch operation; "
            f"one lock + one dump + one fsync must cover the whole batch"
        )
        assert all(not manager._entries[91000 + i].enabled for i in range(50))

    def test_unknown_taxids_are_skipped_not_fatal(self, manager):
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: None):
            changed = manager.set_entries_enabled([91000, 999999], False)
        assert changed == 1
        assert manager._entries[91000].enabled is False

    def test_empty_batch_saves_nothing(self, manager):
        saves = {"n": 0}
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: saves.__setitem__("n", saves["n"] + 1)):
            assert manager.set_entries_enabled([], True) == 0
        assert saves["n"] == 0


class TestCallersUseTheBatchMethod:
    def test_toggle_all_pathogens_saves_once(self, manager):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs import watchlist_tab
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        app = make_callback_app(register_watchlist_callbacks)
        fn = get_callback_fn(
            app, "watchlist-tab-state", input_contains="watchlist-enable-all-btn")

        saves = {"n": 0}
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: saves.__setitem__("n", saves["n"] + 1)), \
             patch.object(watchlist_tab, "get_watchlist_manager",
                          return_value=manager), \
             patch.object(watchlist_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "watchlist-disable-all-btn"
            fn(None, 1, 0)
        assert saves["n"] == 1
        assert all(not e.enabled for e in manager._entries.values())

    def test_toggle_category_saves_once(self, manager):
        """toggle_category had the same per-entry pattern; it batches too."""
        saves = {"n": 0}
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: saves.__setitem__("n", saves["n"] + 1)):
            manager.toggle_category("bioterrorism", True)
        assert saves["n"] <= 1