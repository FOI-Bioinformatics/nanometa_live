"""
State-management coverage for WatchlistManager (core/watchlist/watchlist_manager.py).

The existing ``test_watchlist_manager.py`` exercises the entry-store accessors
against a hand-built custom entry set. This file complements it by covering the
config-driven loading path, per-entry toggle/threshold mutation with disk
persistence stubbed, custom-species addition, and the project > user > builtin
source-priority resolution that the WatchlistLoader feeds the manager.

All disk and home-directory access is redirected to ``tmp_path`` so nothing
touches the operator's real ``~/.nanometa``. No network (NCBI/GTDB) paths are
exercised here.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nanometa_live.core.config.pathogen_loader import ThreatLevel
from nanometa_live.core.watchlist import watchlist_loader as wl_loader_mod
from nanometa_live.core.watchlist.watchlist_loader import (
    WatchlistLoader,
    reset_watchlist_loader,
)
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistEntry,
    WatchlistManager,
    WatchlistSource,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect data dir + home so toggle-state writes never touch real home,
    and reset both module singletons around every test."""
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))
    # Home redirect protects the loader's user-watchlist search path.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    reset_watchlist_manager()
    reset_watchlist_loader()
    yield
    reset_watchlist_manager()
    reset_watchlist_loader()


def _write_watchlist(path: Path, wl_id: str, pathogens, *, name=None):
    """Write a minimal v2.0-schema watchlist YAML and return its file path."""
    path.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": "2.0",
        "taxonomy_support": ["ncbi", "gtdb"],
        "metadata": {"name": name or wl_id, "description": "test"},
        "pathogens": pathogens,
    }
    file_path = path / f"{wl_id}.yaml"
    file_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return file_path


@pytest.fixture
def no_disk():
    """Stub toggle-state persistence so mutation tests never write to disk."""
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        yield


# ---------------------------------------------------------------------------
# 1. Loading from a temp project watchlist dir via load_config
# ---------------------------------------------------------------------------

class TestLoadFromProject:
    def test_load_config_loads_builtin_named_watchlist(self, tmp_path, monkeypatch):
        """A watchlist file dropped in <project_dir>/watchlists and named in the
        config's ``watchlist.builtin`` list is loaded into the entry store."""
        project = tmp_path / "proj"
        _write_watchlist(
            project / "watchlists",
            "mylist",
            [
                {"name": "Bacillus anthracis", "taxid_ncbi": 1392,
                 "threat_level": "critical", "alert_threshold": 5, "bsl_level": 3},
                {"name": "Yersinia pestis", "taxid_ncbi": 632,
                 "threat_level": "high", "alert_threshold": 10},
            ],
        )
        # Point the loader at our temp project dir; app_root is irrelevant here
        # because we reference the watchlist by its project-dir filename.
        loader = WatchlistLoader(project_dir=project / "watchlists")
        # set_project_dir expects the project root (it appends watchlists/),
        # so override the singleton with one already aimed at the right dir.
        loader._project_dir = project
        monkeypatch.setattr(wl_loader_mod, "_watchlist_loader", loader)

        with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
            mgr = WatchlistManager()
            mgr.load_config({
                "results_output_directory": str(project),
                "watchlist": {"enabled": True, "builtin": ["mylist"]},
            })

        entries = mgr.get_all_entries()
        assert 1392 in entries
        assert 632 in entries
        assert entries[1392].name == "Bacillus anthracis"
        assert entries[1392].threat_level == ThreatLevel.CRITICAL
        # builtin watchlist entries are loaded enabled
        assert set(mgr.get_active_entries()) == {1392, 632}
        assert "mylist" in mgr.get_enabled_watchlists()


# ---------------------------------------------------------------------------
# 2. Enable/disable toggle reflected in active-entries accessor
# ---------------------------------------------------------------------------

class TestToggle:
    @pytest.fixture
    def mgr(self, no_disk):
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        m.add_custom_entry({"taxid": 11, "name": "Alpha", "threat_level": "high",
                            "enabled": True})
        m.add_custom_entry({"taxid": 22, "name": "Beta", "threat_level": "low",
                            "enabled": False})
        return m

    def test_disable_drops_from_active(self, mgr):
        assert 11 in mgr.get_active_entries()
        assert mgr.toggle_entry(11, False) is True
        assert 11 not in mgr.get_active_entries()
        assert 11 in mgr.get_all_entries()  # still present, just disabled

    def test_enable_adds_to_active(self, mgr):
        assert 22 not in mgr.get_active_entries()
        assert mgr.toggle_entry(22, True) is True
        assert 22 in mgr.get_active_entries()

    def test_toggle_unknown_taxid_returns_false(self, mgr):
        assert mgr.toggle_entry(999999, True) is False

    def test_toggle_persists_via_save_call(self):
        """toggle_entry calls _save_toggle_state; verify it is invoked."""
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
            m.add_custom_entry({"taxid": 33, "name": "Gamma", "enabled": False})
        with patch.object(WatchlistManager, "_save_toggle_state") as save:
            assert m.toggle_entry(33, True) is True
            save.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Threshold update persists/returns the new value
# ---------------------------------------------------------------------------

class TestThreshold:
    @pytest.fixture
    def mgr(self, no_disk):
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        m.add_custom_entry({"taxid": 50, "name": "Delta", "threat_level": "high",
                            "alert_threshold": 10})
        return m

    def test_update_threshold_changes_value(self, mgr):
        assert mgr.update_entry_threshold(50, 42) is True
        assert mgr.get_entry_by_taxid(50).alert_threshold == 42

    def test_update_threshold_records_override_original(self, mgr):
        original = mgr.get_entry_by_taxid(50).alert_threshold
        mgr.update_entry_threshold(50, 7)
        entry = mgr.get_entry_by_taxid(50)
        assert entry.user_override is True
        assert entry.original_threshold == original

    def test_update_threshold_unknown_returns_false(self, mgr):
        assert mgr.update_entry_threshold(123456, 5) is False


# ---------------------------------------------------------------------------
# 4. add_custom_entry creates a new entry that appears in the loaded set
# ---------------------------------------------------------------------------

class TestAddCustom:
    def test_add_custom_with_taxid(self, no_disk):
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        entry = m.add_custom_entry({"taxid": 777, "name": "Epsilon species",
                                    "threat_level": "moderate", "enabled": True})
        assert isinstance(entry, WatchlistEntry)
        assert entry.source == WatchlistSource.USER
        assert 777 in m.get_all_entries()
        assert m.get_entry_by_name("epsilon species").taxid == 777

    def test_add_custom_name_only_gets_pseudo_taxid(self, no_disk):
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        entry = m.add_custom_entry({"name": "Nameonly organism", "enabled": True})
        # No NCBI taxid supplied -> pseudo-taxid assigned, still findable.
        assert entry is not None
        assert entry.taxid != 0
        assert m.get_entry_by_name("nameonly organism") is entry

    def test_add_custom_appears_in_statistics(self, no_disk):
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        m.add_custom_entry({"taxid": 801, "name": "Stat one", "enabled": True})
        m.add_custom_entry({"taxid": 802, "name": "Stat two", "enabled": False})
        stats = m.get_statistics()
        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 1
        assert stats["disabled_entries"] == 1
        assert stats["by_source"]["user"] == 1  # only active counted by source


# ---------------------------------------------------------------------------
# 5. Source priority: project > user > builtin for same watchlist id
# ---------------------------------------------------------------------------

class TestSourcePriority:
    def test_project_overrides_user_in_discovery(self, tmp_path):
        """Same watchlist id present in both project and user dirs: the project
        copy wins in discover_watchlists / load_watchlist."""
        home = tmp_path / "home"
        project = tmp_path / "proj"

        # User copy: low threat, threshold 100
        _write_watchlist(
            home / ".nanometa" / "watchlists",
            "shared",
            [{"name": "Conflict organism", "taxid_ncbi": 4242,
              "threat_level": "low", "alert_threshold": 100}],
            name="User shared",
        )
        # Project copy: critical threat, threshold 5 -> should win
        _write_watchlist(
            project / "watchlists",
            "shared",
            [{"name": "Conflict organism", "taxid_ncbi": 4242,
              "threat_level": "critical", "alert_threshold": 5}],
            name="Project shared",
        )

        # app_root points at an empty dir so no real built-in collides.
        loader = WatchlistLoader(project_dir=project, app_root=tmp_path / "noapp")
        discovered = {wl.id: wl for wl in loader.discover_watchlists()}
        assert discovered["shared"].source == "project"
        assert discovered["shared"].name == "Project shared"

        pathogens = loader.load_watchlist("shared")
        assert len(pathogens) == 1
        assert pathogens[0].threat_level == "critical"
        assert pathogens[0].alert_threshold == 5

    def test_user_overrides_builtin_when_no_project(self, tmp_path):
        """With no project copy, the user dir wins over the bundled built-in
        for a colliding id."""
        home = tmp_path / "home"
        # Reuse a real built-in id so the built-in dir also contains it.
        _write_watchlist(
            home / ".nanometa" / "watchlists",
            "foodborne",
            [{"name": "Override foodborne", "taxid_ncbi": 9001,
              "threat_level": "high", "alert_threshold": 3}],
            name="User foodborne override",
        )
        # Default app_root resolves to the real package built-ins.
        loader = WatchlistLoader(project_dir=None)
        discovered = {wl.id: wl for wl in loader.discover_watchlists()}
        assert discovered["foodborne"].source == "user"
        assert discovered["foodborne"].name == "User foodborne override"

        pathogens = loader.load_watchlist("foodborne")
        assert len(pathogens) == 1
        assert pathogens[0].name == "Override foodborne"

    def test_manager_merge_keeps_more_sensitive_threshold_and_both_sources(self, no_disk):
        """When the same taxid is added from two watchlists, the manager merges
        in place: the lower (more sensitive) alert threshold survives, the more
        severe threat level wins (by severity rank, not string order), and both
        contributing watchlist ids are tracked."""
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        # First source: loose threshold, "low" threat.
        m._add_entry_from_dict(
            {"taxid": 555, "name": "Merge me", "threat_level": "low",
             "alert_threshold": 100},
            WatchlistSource.USER,
            watchlist_id="wl_a",
        )
        # Second source: tighter threshold, more severe threat.
        m._add_entry_from_dict(
            {"taxid": 555, "name": "Merge me", "threat_level": "moderate",
             "alert_threshold": 5},
            WatchlistSource.USER,
            watchlist_id="wl_b",
        )
        entry = m.get_entry_by_taxid(555)
        assert entry.alert_threshold == 5                  # more sensitive wins
        assert entry.threat_level == ThreatLevel.MODERATE  # more severe wins
        assert entry.watchlist_ids == {"wl_a", "wl_b"}     # both sources tracked

    def test_manager_merge_keeps_more_severe_threat_level(self, no_disk):
        """Severity ordering, not lexical: a CRITICAL entry merging onto a LOW
        one must escalate to CRITICAL ("critical" < "low" lexically, so the old
        string compare under-escalated), and a HIGH entry merging onto CRITICAL
        must NOT downgrade it ("high" > "critical" lexically would have)."""
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        # Existing LOW, incoming CRITICAL -> must become CRITICAL.
        m._add_entry_from_dict(
            {"taxid": 777, "name": "Escalate", "threat_level": "low",
             "alert_threshold": 100},
            WatchlistSource.USER, watchlist_id="wl_a",
        )
        m._add_entry_from_dict(
            {"taxid": 777, "name": "Escalate", "threat_level": "critical",
             "alert_threshold": 5},
            WatchlistSource.USER, watchlist_id="wl_b",
        )
        assert m.get_entry_by_taxid(777).threat_level == ThreatLevel.CRITICAL

        # Existing CRITICAL, incoming HIGH -> must stay CRITICAL.
        m._add_entry_from_dict(
            {"taxid": 778, "name": "Hold", "threat_level": "critical",
             "alert_threshold": 5},
            WatchlistSource.USER, watchlist_id="wl_a",
        )
        m._add_entry_from_dict(
            {"taxid": 778, "name": "Hold", "threat_level": "high",
             "alert_threshold": 10},
            WatchlistSource.USER, watchlist_id="wl_b",
        )
        assert m.get_entry_by_taxid(778).threat_level == ThreatLevel.CRITICAL

    def test_manager_merge_user_override_of_builtin(self, no_disk):
        """A non-builtin entry merging onto a builtin marks the survivor as a
        user override and records the original threshold."""
        m = WatchlistManager()
        m._entries.clear()
        m._name_index.clear()
        m._add_entry_from_dict(
            {"taxid": 556, "name": "Base", "threat_level": "low",
             "alert_threshold": 100},
            WatchlistSource.BUILTIN,
            watchlist_id="builtin_wl",
        )
        m._add_entry_from_dict(
            {"taxid": 556, "name": "Base", "threat_level": "low",
             "alert_threshold": 20},
            WatchlistSource.USER,
            watchlist_id="user_wl",
        )
        entry = m.get_entry_by_taxid(556)
        assert entry.user_override is True
        # original_threshold records the builtin's TRUE pre-merge value (100),
        # snapshotted before the min()-merge tightened it to 20.
        assert entry.original_threshold == 100
        assert entry.alert_threshold == 20
