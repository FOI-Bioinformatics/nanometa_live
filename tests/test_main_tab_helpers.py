"""
Unit tests for app/tabs/main_tab_helpers.py (extracted from main_tab.py).

The watchlist add/remove/contains helpers and the alert banner are pure; the
detection filters use the WatchlistManager + taxid mapping singletons, which are
patched so the legacy-watchlist matching path is exercised deterministically.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs import main_tab_helpers as mh
from nanometa_live.app.tabs.main_tab_helpers import (
    add_species_to_watchlist,
    create_species_alert_banner,
    filter_detected_species,
    get_all_watchlist_with_detection,
    remove_species_from_watchlist,
    species_in_watchlist,
)

pytestmark = pytest.mark.unit


class TestWatchlistListOps:
    def test_species_in_watchlist(self):
        wl = [{"taxid": 562}]
        assert species_in_watchlist(562, wl) is True
        assert species_in_watchlist(99, wl) is False
        assert species_in_watchlist(562, []) is False

    def test_add_dedups_by_taxid(self):
        wl = [{"taxid": 562}]
        assert add_species_to_watchlist({"taxid": 562}, wl) == wl  # no dup
        added = add_species_to_watchlist({"taxid": 1280}, wl)
        assert {s["taxid"] for s in added} == {562, 1280}

    def test_add_to_empty(self):
        assert add_species_to_watchlist({"taxid": 1}, None) == [{"taxid": 1}]

    def test_remove(self):
        wl = [{"taxid": 562}, {"taxid": 1280}]
        assert remove_species_from_watchlist(562, wl) == [{"taxid": 1280}]
        assert remove_species_from_watchlist(1, []) == []


class TestAlertBanner:
    def test_empty_returns_none(self):
        assert create_species_alert_banner([]) is None

    def test_singular(self):
        banner = create_species_alert_banner([{"name": "E. coli"}])
        assert isinstance(banner, dbc.Alert)
        assert banner.color == "warning"
        assert "1 watched species with reads" in str(banner.children)

    def test_more_than_five_summarised(self):
        species = [{"name": f"sp{i}"} for i in range(7)]
        banner = create_species_alert_banner(species)
        assert "+2 more" in str(banner.children)


@pytest.fixture
def _no_managers():
    """Empty WatchlistManager + no taxid mapping -> legacy-watchlist matching."""
    mgr = MagicMock()
    mgr.get_active_entries.return_value = {}
    with patch.object(mh, "get_watchlist_manager", return_value=mgr), \
         patch("nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
               return_value=None):
        yield


def _kraken_df(rows):
    return pd.DataFrame(rows)


class TestFilterDetectedSpecies:
    def test_returns_detected_watched_species(self, _no_managers):
        df = _kraken_df([
            {"taxid": 562, "name": "Escherichia coli", "rank": "S",
             "cumul_reads": 100, "reads": 100, "%": 50.0},
            {"taxid": 1280, "name": "Staphylococcus aureus", "rank": "S",
             "cumul_reads": 0, "reads": 0, "%": 0.0},
        ])
        watchlist = [{"taxid": 562, "name": "Escherichia coli"}]
        out = filter_detected_species(df, watchlist)
        assert [e["taxid"] for e in out] == [562]
        assert out[0]["reads"] == 100

    def test_empty_inputs(self, _no_managers):
        assert filter_detected_species(None, [{"taxid": 1}]) == []
        assert filter_detected_species(_kraken_df([]), [{"taxid": 1}]) == []
        assert filter_detected_species(_kraken_df([{"taxid": 1}]), []) == []

    def test_higher_ranks_excluded(self, _no_managers):
        df = _kraken_df([
            {"taxid": 561, "name": "Escherichia", "rank": "G",
             "cumul_reads": 100, "reads": 100, "%": 50.0},
        ])
        # Genus-rank row must not count as a species detection.
        assert filter_detected_species(df, [{"taxid": 561, "name": "Escherichia"}]) == []


class TestGetAllWatchlistWithDetection:
    def test_detected_and_undetected(self, _no_managers):
        df = _kraken_df([
            {"taxid": 562, "name": "Escherichia coli", "rank": "S",
             "cumul_reads": 100, "reads": 100, "%": 50.0},
        ])
        watchlist = [
            {"taxid": 562, "name": "Escherichia coli"},
            {"taxid": 99999, "name": "Absent species"},
        ]
        out = get_all_watchlist_with_detection(df, watchlist)
        by_taxid = {e["ncbi_taxid"]: e for e in out}
        assert by_taxid[562]["detected"] is True
        assert by_taxid[562]["reads"] == 100
        assert by_taxid[99999]["detected"] is False
        assert by_taxid[99999]["reads"] == 0
        # Detected entries sort first.
        assert out[0]["ncbi_taxid"] == 562
