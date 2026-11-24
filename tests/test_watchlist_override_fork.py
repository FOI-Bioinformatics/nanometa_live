"""An override must land on the entry it names, not on its fork.

Entry identity is the pair (NCBI taxid, ``db_taxid``): the Bioshield list
carries *E. coli*, *E. coli_E* and *E. coli_F* as three entries with distinct
database nodes and the single NCBI taxid 562, and ``_identity_key`` stores the
forks under their ``db_taxid``. ``_apply_override`` indexed ``_entries[taxid]``
instead, so an override for one *E. coli* variant was applied to whichever of
the three holds the bare NCBI key -- the operator raised one entry's threshold
and a different organism's threshold moved (audit 2026-11-06, finding 18).

The override record also had to start carrying ``db_taxid`` and ``name``: a
taxid alone cannot name one of a fork pair, so a round trip through
``export_config`` / ``load_config`` could not have resolved the right entry
however the lookup was written.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    WatchlistSource,
)


def _mgr():
    m = WatchlistManager()
    m._entries = {}
    m._name_index = {}
    m._enabled_watchlists = set()
    return m


def _entry(name, taxid, db_taxid, threshold):
    return {
        "name": name,
        "taxid": taxid,
        "db_taxid": db_taxid,
        "threat_level": "high",
        "alert_threshold": threshold,
        "enabled": True,
    }


# One NCBI taxid, three database nodes.
COLI = _entry("Escherichia coli", 562, 4000549, 20)
COLI_F = _entry("Escherichia coli_F", 562, 4000553, 10)


def _loaded():
    m = _mgr()
    m._add_entry_from_dict(COLI, WatchlistSource.BUILTIN, watchlist_id="bio")
    m._add_entry_from_dict(COLI_F, WatchlistSource.BUILTIN, watchlist_id="bio")
    assert len(m._entries) == 2
    return m


def _by_name(m, name):
    return next(e for e in m._entries.values() if e.name == name)


class TestOverrideTargeting:
    def test_an_override_for_the_fork_reaches_the_fork(self):
        m = _loaded()
        m._apply_override({
            "taxid": 562,
            "db_taxid": 4000553,
            "name": "Escherichia coli_F",
            "alert_threshold": 500,
        })

        assert _by_name(m, "Escherichia coli_F").alert_threshold == 500

    def test_it_does_not_move_the_other_variant(self):
        m = _loaded()
        m._apply_override({
            "taxid": 562,
            "db_taxid": 4000553,
            "name": "Escherichia coli_F",
            "alert_threshold": 500,
        })

        assert _by_name(m, "Escherichia coli").alert_threshold == 20, (
            "the override was applied to a different organism than the one "
            "it names"
        )

    def test_an_override_for_the_primary_entry_still_works(self):
        m = _loaded()
        m._apply_override({
            "taxid": 562,
            "db_taxid": 4000549,
            "name": "Escherichia coli",
            "alert_threshold": 99,
        })

        assert _by_name(m, "Escherichia coli").alert_threshold == 99
        assert _by_name(m, "Escherichia coli_F").alert_threshold == 10

    def test_a_legacy_override_without_db_taxid_still_applies(self):
        """Records written before this fix carry only the taxid."""
        m = _loaded()
        m._apply_override({"taxid": 562, "alert_threshold": 77})

        assert _by_name(m, "Escherichia coli").alert_threshold == 77

    def test_an_unknown_entry_is_ignored(self):
        m = _loaded()
        m._apply_override({"taxid": 999999, "alert_threshold": 1})

        assert {e.alert_threshold for e in m._entries.values()} == {20, 10}


class TestOverrideRecordsIdentifyTheirEntry:
    def test_export_carries_db_taxid_and_name(self):
        m = _loaded()
        entry = _by_name(m, "Escherichia coli_F")
        entry.source = WatchlistSource.BUILTIN
        entry.user_override = True
        entry.alert_threshold = 500

        overrides = m.export_config()["overrides"]
        record = next(o for o in overrides
                      if o.get("name") == "Escherichia coli_F")

        assert record["db_taxid"] == 4000553, (
            "the exported override cannot say which fork it belongs to, so "
            "session restore applies it to the wrong entry"
        )

    def test_a_round_trip_keeps_the_override_on_its_own_entry(self):
        m = _loaded()
        entry = _by_name(m, "Escherichia coli_F")
        entry.user_override = True
        entry.alert_threshold = 500

        restored = _loaded()
        for override in m.export_config()["overrides"]:
            restored._apply_override(override)

        assert _by_name(restored, "Escherichia coli_F").alert_threshold == 500
        assert _by_name(restored, "Escherichia coli").alert_threshold == 20
