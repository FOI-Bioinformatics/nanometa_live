"""Watchlist cards keep one row per ENTRY; entry identity is (NCBI taxid, db_taxid).

The Bioshield list carries *Escherichia coli*, *E. coli_E* and *E. coli_F* as
three entries with distinct database nodes and the one NCBI taxid 562 (GTDB
splits the polyphyletic species). The alert path keeps them apart since the
round-4 audit; the Organisms tab's cards (``get_all_watchlist_with_detection``)
still deduplicated on the NCBI taxid and so returned one row for the three,
which dropped *E. coli_F* at 11 reads (threshold 10) from the Detected cards
and understated the detected/total count beside them.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from nanometa_live.app.tabs import main_tab_helpers
from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

pytestmark = pytest.mark.unit

_VARIANTS = (
    ("Escherichia coli", 4000549),
    ("Escherichia coli_E", 4000558),
    ("Escherichia coli_F", 4000553),
)


def _manager():
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        m = WatchlistManager()
        for name, db_taxid in _VARIANTS:
            m.add_custom_entry({
                "taxid": 562, "db_taxid": db_taxid, "name": name,
                "threat_level": "high", "enabled": True, "alert_threshold": 10,
            })
        m._loaded = True
    return m


def _report(reads_by_db_taxid):
    rows = [{"taxid": 1, "name": "root", "rank": "R", "reads": 0,
             "cumul_reads": sum(reads_by_db_taxid.values()), "%": 100.0}]
    for name, db_taxid in _VARIANTS:
        if db_taxid in reads_by_db_taxid:
            rows.append({"taxid": db_taxid, "name": name, "rank": "S",
                         "reads": reads_by_db_taxid[db_taxid],
                         "cumul_reads": reads_by_db_taxid[db_taxid], "%": 1.0})
    return pd.DataFrame(rows)


def _cards(report):
    m = _manager()
    with patch.object(main_tab_helpers, "get_watchlist_manager", return_value=m), \
         patch("nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
               return_value=None):
        return main_tab_helpers.get_all_watchlist_with_detection(report, [])


def test_each_variant_entry_gets_its_own_card():
    cards = _cards(_report({4000549: 22, 4000553: 11, 4000558: 3}))
    assert sorted(c["name"] for c in cards) == sorted(n for n, _ in _VARIANTS)


def test_each_variant_reads_its_own_database_node():
    cards = _cards(_report({4000549: 22, 4000553: 11, 4000558: 3}))
    reads = {c["name"]: c["reads"] for c in cards}
    assert reads == {
        "Escherichia coli": 22,
        "Escherichia coli_F": 11,
        "Escherichia coli_E": 3,
    }
    assert {c["name"]: c["taxid"] for c in cards} == dict(_VARIANTS)


def test_an_absent_variant_does_not_borrow_a_siblings_reads():
    # Only E. coli itself is in the report: the two variants share its NCBI
    # taxid but have their own nodes, which carry nothing.
    cards = _cards(_report({4000549: 22}))
    detected = {c["name"] for c in cards if c["detected"]}
    assert detected == {"Escherichia coli"}
