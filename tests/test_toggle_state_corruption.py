"""A corrupt toggle-state file must not silently re-enable everything.

Round-3 finding: ``_restore_toggle_state`` catches YAML corruption at
``logger.debug`` and proceeds with every entry enabled -- entries the
operator deliberately disabled come back on with no notice. On a
biothreat panel that is a real surprise; the failure is toward
fail-loud (more screening, not less), but it must be SAID.
"""

import logging

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    WatchlistSource,
)


def _mgr(tmp_path):
    m = WatchlistManager()
    m._entries = {}
    m._name_index = {}
    m._enabled_watchlists = set()
    state_file = tmp_path / "watchlist_toggle_state.yaml"
    m._toggle_state_read_candidates = lambda: [state_file]
    m._state_file = state_file
    m._add_entry_from_dict(
        {"name": "Bacillus anthracis", "taxid": 1392, "threat_level":
         "critical", "alert_threshold": 10, "enabled": True},
        WatchlistSource.USER, watchlist_id="bio")
    return m


class TestCorruptToggleState:
    def test_corrupt_file_logs_a_warning(self, tmp_path, caplog):
        m = _mgr(tmp_path)
        m._state_file.write_text("{{{{not yaml::::")
        with caplog.at_level(logging.WARNING):
            m._restore_toggle_state()
        assert any("toggle state" in r.message.lower()
                   for r in caplog.records if r.levelno >= logging.WARNING)

    def test_corrupt_file_sets_a_consumable_warning(self, tmp_path):
        m = _mgr(tmp_path)
        m._state_file.write_text("{{{{not yaml::::")
        m._restore_toggle_state()
        msg = m.consume_toggle_restore_warning()
        assert msg and "enabled" in msg.lower()
        assert m.consume_toggle_restore_warning() is None, "consume-once"

    def test_missing_file_is_not_a_warning(self, tmp_path):
        m = _mgr(tmp_path)
        m._restore_toggle_state()
        assert m.consume_toggle_restore_warning() is None

    def test_valid_file_is_not_a_warning(self, tmp_path):
        m = _mgr(tmp_path)
        m._state_file.write_text("disabled_taxids: [1392]\n")
        m._restore_toggle_state()
        assert m.consume_toggle_restore_warning() is None
        assert m._entries[1392].enabled is False
