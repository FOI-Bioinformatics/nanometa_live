"""Memoization of the per-tick pathogen checks.

The dashboard runs the watchlist matching pass 3-4 times per interval tick
(verdict banner above+below threshold, alert panel, dashboard alerts), and
nothing cached the result: at 129 entries x 2000 report rows that was ~3 s
of synchronous CPU per tick recomputing identical answers. Two memos fix it:

- ``_check_pathogens_both`` (dashboard_helpers) computes both threshold
  sides in one ``check_organisms*_split`` pass and memoizes on
  (organisms digest, watchlist signature, mapping signature). Returned
  alerts are per-call copies because downstream helpers attach validation
  summaries onto the dicts in place.
- ``check_for_dangerous_pathogens`` (pathogen_database) reuses the merged
  builtin+custom database instead of re-parsing pathogens.yaml per call.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    get_watchlist_manager,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit


DETECTED = [
    {"taxid": 88801, "name": "Testus criticus", "reads": 100, "abundance": 2.0},
    {"taxid": 88802, "name": "Testus quietus", "reads": 3, "abundance": 0.1},
    {"taxid": 77777, "name": "Innocuous bystander", "reads": 50,
     "abundance": 0.5},
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    from nanometa_live.app.tabs import dashboard_helpers
    dashboard_helpers._pathogen_check_memo.clear()
    # Deterministic path: no mapping collection -> check_organisms_split.
    monkeypatch.setattr(
        "nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
        lambda: None,
    )
    yield
    reset_watchlist_manager()
    dashboard_helpers._pathogen_check_memo.clear()


@pytest.fixture
def manager():
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = get_watchlist_manager()
        mgr._entries.clear()
        mgr._name_index.clear()
        mgr.add_custom_entry({
            "taxid": 88801, "name": "Testus criticus",
            "threat_level": "critical", "enabled": True, "alert_threshold": 5,
        })
        mgr.add_custom_entry({
            "taxid": 88802, "name": "Testus quietus",
            "threat_level": "moderate", "enabled": True, "alert_threshold": 10,
        })
        mgr._loaded = True
        yield mgr


def _both(rows=None):
    from nanometa_live.app.tabs.dashboard_helpers import _check_pathogens_both
    return _check_pathogens_both(rows if rows is not None else DETECTED, {})


class TestCheckPathogensBoth:
    def test_returns_both_sides_matching_the_wrapper(self, manager):
        from nanometa_live.app.tabs.dashboard_helpers import (
            _check_pathogens_with_mapping,
        )
        dangerous, subthreshold = _both()
        assert [a["taxid"] for a in dangerous] == [88801]
        assert [a["taxid"] for a in subthreshold] == [88802]
        assert dangerous == _check_pathogens_with_mapping(DETECTED, {})
        assert subthreshold == _check_pathogens_with_mapping(
            DETECTED, {}, below_threshold=True)

    def test_identical_call_is_served_from_the_memo(self, manager, monkeypatch):
        calls = {"n": 0}
        orig = WatchlistManager.check_organisms_split

        def counting(self, detected):
            calls["n"] += 1
            return orig(self, detected)

        monkeypatch.setattr(WatchlistManager, "check_organisms_split", counting)
        _both()
        _both()
        assert calls["n"] == 1

    def test_mutating_a_returned_alert_does_not_poison_the_memo(self, manager):
        dangerous, _ = _both()
        dangerous[0]["name"] = "MUTATED"
        dangerous[0]["ambiguous_with"].append("MUTATED TOO")
        dangerous2, _ = _both()
        assert dangerous2[0]["name"] == "Testus criticus"
        assert "MUTATED TOO" not in dangerous2[0]["ambiguous_with"]

    def test_a_watchlist_edit_busts_the_memo(self, manager):
        dangerous, subthreshold = _both()
        assert [a["taxid"] for a in subthreshold] == [88802]
        # Lower the quiet entry's threshold: it must move sides on the
        # next call rather than being served stale.
        manager._entries[88802].alert_threshold = 1
        dangerous, subthreshold = _both()
        assert [a["taxid"] for a in sorted(
            dangerous, key=lambda a: a["taxid"])] == [88801, 88802]
        assert subthreshold == []

    def test_different_organisms_bust_the_memo(self, manager, monkeypatch):
        calls = {"n": 0}
        orig = WatchlistManager.check_organisms_split

        def counting(self, detected):
            calls["n"] += 1
            return orig(self, detected)

        monkeypatch.setattr(WatchlistManager, "check_organisms_split", counting)
        _both()
        _both([{"taxid": 88801, "name": "Testus criticus", "reads": 999,
                "abundance": 5.0}])
        assert calls["n"] == 2

    def test_empty_detection_list_short_circuits(self, manager):
        assert _both([]) == ([], [])


class TestPathogenDatabaseMergeCache:
    CUSTOM = [
        {"taxid": 4242, "name": "Customus organismus", "threat_level": "high",
         "alert_threshold": 10},
    ]

    def test_same_custom_watchlist_does_not_reload_the_database(
            self, monkeypatch):
        from nanometa_live.core.utils import pathogen_database as pd
        pd._merged_db_cache = None
        calls = {"n": 0}
        orig = pd.PathogenDatabase.load

        def counting(self, *a, **kw):
            calls["n"] += 1
            return orig(self, *a, **kw)

        monkeypatch.setattr(pd.PathogenDatabase, "load", counting)
        pd.check_for_dangerous_pathogens(DETECTED, self.CUSTOM)
        pd.check_for_dangerous_pathogens(DETECTED, self.CUSTOM)
        assert calls["n"] == 1

    def test_a_changed_custom_watchlist_reloads(self, monkeypatch):
        from nanometa_live.core.utils import pathogen_database as pd
        pd._merged_db_cache = None
        calls = {"n": 0}
        orig = pd.PathogenDatabase.load

        def counting(self, *a, **kw):
            calls["n"] += 1
            return orig(self, *a, **kw)

        monkeypatch.setattr(pd.PathogenDatabase, "load", counting)
        pd.check_for_dangerous_pathogens(DETECTED, self.CUSTOM)
        changed = [dict(self.CUSTOM[0], alert_threshold=1)]
        alerts = pd.check_for_dangerous_pathogens(
            [{"taxid": 4242, "name": "Customus organismus", "reads": 5,
              "abundance": 0.1}], changed)
        assert calls["n"] == 2
        assert [a["name"] for a in alerts] == ["Customus organismus"]
