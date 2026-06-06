"""Tests for WatchlistManager.check_organisms -- the core detection/scoring
path that turns Kraken2 hits into watchlist alerts. Previously uncovered.
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
        mgr.add_custom_entry({
            "taxid": 99901, "name": "Testus criticus", "threat_level": "critical",
            "enabled": True, "alert_threshold": 5,
        })
        mgr.add_custom_entry({
            "taxid": 99903, "name": "Testus moderatus", "threat_level": "moderate",
            "enabled": True, "alert_threshold": 10,
        })
        mgr.add_custom_entry({
            "taxid": 99902, "name": "Testus disabledus", "threat_level": "high",
            "enabled": False, "alert_threshold": 1,
        })
        yield mgr


def _detect(taxid, name, reads, abundance=0.0):
    return {"taxid": taxid, "name": name, "reads": reads, "abundance": abundance}


def test_taxid_match_above_threshold_alerts(manager):
    alerts = manager.check_organisms([_detect(99901, "Testus criticus", 100, 2.5)])
    assert len(alerts) == 1
    a = alerts[0]
    assert a["taxid"] == 99901
    assert a["threat_level"] == "critical"
    assert a["reads"] == 100
    assert a["abundance"] == 2.5
    assert a["match_score"] == 1.0
    assert a["threshold"] == 5


def test_reads_below_threshold_no_alert(manager):
    # threshold is 5; 3 reads must not alert
    assert manager.check_organisms([_detect(99901, "Testus criticus", 3)]) == []


def test_disabled_entry_never_alerts(manager):
    # 99902 is disabled (not in active entries) even with huge read count
    assert manager.check_organisms([_detect(99902, "Testus disabledus", 9999)]) == []


def test_unwatched_taxid_no_alert(manager):
    assert manager.check_organisms([_detect(4242, "Random bug", 9999)]) == []


def test_alerts_sorted_critical_first(manager):
    detected = [
        _detect(99903, "Testus moderatus", 50),   # moderate
        _detect(99901, "Testus criticus", 50),    # critical
    ]
    alerts = manager.check_organisms(detected)
    assert [a["threat_level"] for a in alerts] == ["critical", "moderate"]


def test_name_match_without_taxid_alerts(manager):
    # No taxid (0) -> falls through to the TaxonomyMatcher name path; an exact
    # name match scores well above the 0.7 floor.
    alerts = manager.check_organisms([_detect(0, "Testus criticus", 100)])
    assert len(alerts) == 1
    assert alerts[0]["taxid"] == 99901
    assert alerts[0]["match_score"] >= 0.7


def test_empty_detection_list_returns_empty(manager):
    assert manager.check_organisms([]) == []
