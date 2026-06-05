"""Readiness watchlist checks must use the injected snapshot.

Regression for the local-server report where the readiness checklist said the
watchlist was "not enabled" even though entries were enabled and genomes
downloaded: the readiness callback runs in a DiskcacheManager worker where the
WatchlistManager singleton is empty, so it must read the watchlist from the
``watchlist-entries-snapshot`` store instead.
"""

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker


def _checker():
    return ReadinessChecker()


def test_resolve_active_watchlist_filters_enabled_and_taxid():
    rc = _checker()
    snapshot = [
        {"name": "E. coli", "taxid": 562, "enabled": True},
        {"name": "disabled bug", "taxid": 999, "enabled": False},
        {"name": "no taxid", "taxid": 0, "enabled": True},
    ]
    active = rc._resolve_active_watchlist(snapshot)
    assert active == [{"name": "E. coli", "taxid": 562}]


def test_resolve_active_watchlist_empty_snapshot_is_definitive():
    # An explicit (possibly empty) snapshot means "loaded, nothing enabled" --
    # NOT "could not determine", so it must return a list (here empty).
    rc = _checker()
    assert rc._resolve_active_watchlist([]) == []


def test_watchlist_active_uses_snapshot_enabled_entries():
    rc = _checker()
    active = rc._resolve_active_watchlist(
        [{"name": "E. coli", "taxid": 562, "enabled": True}]
    )
    result = rc._check_watchlist_active({}, active)
    assert result.passed is True
    assert "1 pathogen" in result.message


def test_watchlist_active_reports_not_enabled_for_empty_snapshot():
    rc = _checker()
    result = rc._check_watchlist_active({}, [])
    assert result.passed is False
    assert "No watchlist enabled" in result.message


def test_check_readiness_threads_snapshot_into_watchlist_checks():
    """End-to-end: passing watchlist_entries makes the Watchlist Active check
    pass without any populated singleton."""
    rc = _checker()
    report = rc.check_readiness(
        {"kraken_db": ""},
        nanometa_home="/tmp/nm_readiness_test_home",
        watchlist_entries=[{"name": "E. coli", "taxid": 562, "enabled": True}],
    )
    active = [c for c in report.checks if c.name == "Watchlist Active"]
    assert active and active[0].passed is True
