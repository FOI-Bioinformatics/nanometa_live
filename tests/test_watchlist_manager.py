"""
Tests for the WatchlistManager public API (core/watchlist/watchlist_manager.py,
was 30% covered).

Exercises the entry-store surface the rest of the app relies on against a
controlled set of custom entries (built-ins cleared for determinism). Disk
persistence is stubbed and NANOMETA_DATA_DIR redirected so no state touches the
operator's home.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.config.pathogen_loader import ThreatLevel
from nanometa_live.core.watchlist import watchlist_manager as wm_mod
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
    # Stub disk persistence so toggles/threshold edits never write to disk.
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = WatchlistManager()
        # Clear any auto-loaded built-ins for a controlled entry set.
        mgr._entries.clear()
        mgr._name_index.clear()
        mgr.add_custom_entry({
            "taxid": 99901, "name": "Testus criticus", "threat_level": "critical",
            "enabled": True, "alert_threshold": 5,
        })
        mgr.add_custom_entry({
            "taxid": 99902, "name": "Testus lowus", "threat_level": "low",
            "enabled": False,
        })
        yield mgr


class TestEntryAccess:
    def test_all_vs_active(self, manager):
        assert set(manager.get_all_entries()) == {99901, 99902}
        assert set(manager.get_active_entries()) == {99901}  # only enabled

    def test_get_by_taxid(self, manager):
        assert manager.get_entry_by_taxid(99901).name == "Testus criticus"
        assert manager.get_entry_by_taxid(404) is None

    def test_get_by_name(self, manager):
        assert manager.get_entry_by_name("testus criticus").taxid == 99901

    def test_critical_entries(self, manager):
        crit = manager.get_critical_entries()
        assert [e.taxid for e in crit] == [99901]

    def test_threat_level_filter_excludes_disabled(self, manager):
        # 99902 is low but disabled; the filter only returns enabled entries.
        assert manager.get_entries_by_threat_level(ThreatLevel.LOW) == []


class TestMutation:
    def test_toggle_entry(self, manager):
        assert manager.toggle_entry(99902, True) is True
        assert 99902 in manager.get_active_entries()
        assert manager.toggle_entry(404, True) is False

    def test_update_threshold(self, manager):
        with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
            assert manager.update_entry_threshold(99901, 20) is True
        assert manager.get_entry_by_taxid(99901).alert_threshold == 20

    def test_remove_user_entry(self, manager):
        assert manager.remove_entry(99901) is True
        assert manager.get_entry_by_taxid(99901) is None


class TestStatistics:
    def test_statistics_shape(self, manager):
        stats = manager.get_statistics()
        assert isinstance(stats, dict)
        assert stats  # non-empty


class TestMalformedEntryDoesNotTruncateWatchlist:
    """One malformed field in a custom watchlist must cost one entry at most.

    ``int(alert_threshold)`` was unguarded, so ``alert_threshold: null`` (or
    a non-numeric string) raised TypeError out of the per-entry loop into the
    per-FILE except: entries before the bad one stayed loaded, entries after
    were silently dropped, and the watchlist was never marked enabled -- the
    UI reported it off while some organisms were live. Audit 2026-08-16,
    finding L10.
    """

    def test_null_alert_threshold_falls_back_to_threat_default(self):
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistEntry

        e = WatchlistEntry.from_dict({
            "name": "Bacillus anthracis", "taxid_ncbi": 1392,
            "threat_level": "critical", "alert_threshold": None,
        })
        assert isinstance(e.alert_threshold, int)
        assert e.alert_threshold > 0

    def test_non_numeric_alert_threshold_falls_back(self):
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistEntry

        e = WatchlistEntry.from_dict({
            "name": "Yersinia pestis", "taxid_ncbi": 632,
            "threat_level": "high", "alert_threshold": "not a number",
        })
        assert isinstance(e.alert_threshold, int)
        assert e.alert_threshold > 0

    def test_bad_entry_mid_file_does_not_drop_the_rest(self, tmp_path):
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

        f = tmp_path / "custom.yaml"
        f.write_text(
            "pathogens:\n"
            "  - name: Bacillus anthracis\n"
            "    taxid_ncbi: 1392\n"
            "    threat_level: critical\n"
            "  - name: Broken entry\n"
            "    taxid_ncbi: 99999\n"
            "    watchlist_ids: 5\n"          # set(5) raises TypeError
            "  - name: Yersinia pestis\n"
            "    taxid_ncbi: 632\n"
            "    threat_level: high\n"
        )

        m = WatchlistManager()
        m._load_custom_yaml_file(str(f))

        names = {e.name for e in m._entries.values()}
        assert "Yersinia pestis" in names, (
            "a malformed entry mid-file silently dropped every entry after it"
        )
        assert "custom" in m._enabled_watchlists, (
            "the watchlist was left unmarked as enabled, so the UI reports "
            "it off while some of its organisms are live"
        )
