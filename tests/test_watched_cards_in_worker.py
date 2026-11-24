"""Watched-organism cards built in the background worker keep threat levels.

update_main_results is background=True, so the WatchlistManager singleton it
reads is empty in the worker process. get_all_watchlist_with_detection then
fell through to the legacy {name, taxid} list and every watched card said
threat "Unknown" -- F. tularensis included, which the Select Agents list
marks critical and the Details modal (main process) called CRITICAL (live
test 2026-11-24). The cards now use the watchlist-entries-snapshot Store,
which carries threat level, category and annotation, when the singleton is
empty (CLAUDE.md, "Background callback isolation").
"""

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from nanometa_live.app.tabs import main_tab_helpers

pytestmark = pytest.mark.unit

SNAPSHOT = [{
    "name": "Francisella tularensis", "taxid": 263, "db_taxid": None,
    "enabled": True, "threat_level": "critical", "category": "select_agent",
    "annotation": "Tier 1", "organism_type": "bacteria",
}, {
    "name": "Disabled organism", "taxid": 999, "db_taxid": None,
    "enabled": False, "threat_level": "high", "category": "x",
}]

REPORT = pd.DataFrame([
    {"taxid": 1, "name": "root", "rank": "R", "reads": 0, "cumul_reads": 500, "%": 100.0},
    {"taxid": 263, "name": "Francisella tularensis", "rank": "S", "reads": 500,
     "cumul_reads": 500, "%": 100.0},
])


def _empty_manager():
    return SimpleNamespace(get_active_entries=lambda: {})


def test_cards_take_threat_level_from_the_snapshot():
    with patch.object(main_tab_helpers, "get_watchlist_manager", _empty_manager), \
         patch("nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
               return_value=None):
        cards = main_tab_helpers.get_all_watchlist_with_detection(
            REPORT, [], entries_snapshot=SNAPSHOT)
    card = next(c for c in cards if c["name"] == "Francisella tularensis")
    assert card["threat_level"] == "critical"
    assert card["category"] == "select_agent"
    assert card["annotation"] == "Tier 1"
    assert card["detected"] and card["reads"] == 500
    assert not any(c["name"] == "Disabled organism" for c in cards)


def test_snapshot_carries_the_card_fields():
    from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks
    from tests.dash_test_utils import get_callback_fn, make_callback_app

    entry = {"name": "F", "taxid": 263, "api_rank": "species", "enabled": True,
             "db_taxid": None, "threat_level": "critical", "category": "select_agent",
             "annotation": "Tier 1", "organism_type": "bacteria"}
    manager = SimpleNamespace(_loaded=True, get_entries_with_toggle_state=lambda: [entry])
    app = make_callback_app(register_preparation_callbacks)
    fn = get_callback_fn(app, "watchlist-entries-snapshot.data")
    with patch("nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
               return_value=manager):
        snap = fn(None, None, {})
    assert snap[0]["threat_level"] == "critical"
    assert snap[0]["category"] == "select_agent"
    assert snap[0]["annotation"] == "Tier 1"
