"""A species and its subspecies are different organisms, not one entry.

The Bioshield watchlist names both a species and its subspecies where the
distinction is clinical: *Burkholderia mallei* subsp. *mallei* (db 4003795,
glanders) beside *Burkholderia mallei* (db 4003703), and *Brucella melitensis*
subsp. *melitensis* (db 4005493) beside *Brucella melitensis* (db 4005448).
They are separate nodes in the Kraken2 database and carry separate
``db_taxid`` values.

They also share an NCBI taxid, because NCBI has no separate id for the
subspecies -- 13373 and 29459 respectively. ``WatchlistManager`` keys
``_entries`` by ``entry.taxid`` (the NCBI id) and MERGES on collision, so the
moment those entries were given a real ``taxid_ncbi`` the pair collapsed into
one and the loser's ``db_taxid`` went with it. Measured in the GUI when the
Bioshield list was enriched: 129 entries loaded as **125**, Critical 30 -> 28,
High 43 -> 41. The four lost were the two species/subspecies pairs above and
two of the three *E. coli* variants (all three map to 562).

That is a silent detection hole, not a display quirk: the surviving entry
watches ONE database node, so the other node -- glanders, in the worst case --
is matched by nothing.

The rule: **``db_taxid`` is the organism's identity in the loaded database.
Two entries with different ``db_taxid`` are different organisms and must never
merge, whatever their NCBI taxid says.** Merging stays correct for entries
that are genuinely the same thing -- the same organism contributed by two
watchlist files, where ``db_taxid`` matches or neither states one.
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


def _entry(name, taxid, db_taxid=None, threat="critical", threshold=10):
    d = {
        "name": name,
        "taxid": taxid,
        "threat_level": threat,
        "alert_threshold": threshold,
        "enabled": True,
    }
    if db_taxid is not None:
        d["db_taxid"] = db_taxid
    return d


GLANDERS = _entry("Burkholderia mallei subsp. mallei", 13373, 4003795)
MALLEI = _entry("Burkholderia mallei", 13373, 4003703)


class TestDistinctDatabaseNodesStaySeparate:
    def test_species_and_subspecies_are_two_entries(self):
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        assert len(m._entries) == 2, (
            "a species and its own subspecies collapsed into one entry; the "
            "loser's db_taxid is dropped and that database node becomes "
            "unwatched"
        )

    def test_both_database_nodes_are_still_watched(self):
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        db_taxids = {e.db_taxid for e in m._entries.values()}
        assert db_taxids == {4003795, 4003703}

    def test_both_names_survive(self):
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        names = {e.name for e in m._entries.values()}
        assert names == {
            "Burkholderia mallei subsp. mallei",
            "Burkholderia mallei",
        }

    def test_each_keeps_its_ncbi_taxid_for_genome_download(self):
        # The whole point of the enrichment: both must still resolve to a real
        # NCBI id so a reference genome can be fetched.
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        assert {e.taxid for e in m._entries.values()} == {13373}

    def test_three_variants_of_one_species_all_survive(self):
        # E. coli, E. coli_E, E. coli_F -- three GTDB nodes, one NCBI taxid.
        m = _mgr()
        for name, db in (
            ("Escherichia coli", 4000549),
            ("Escherichia coli_E", 4000558),
            ("Escherichia coli_F", 4000553),
        ):
            m._add_entry_from_dict(
                _entry(name, 562, db, threat="high"),
                WatchlistSource.USER, watchlist_id="bio")
        assert len(m._entries) == 3


class TestGenuineDuplicatesStillMerge:
    """Merging is right when the entries really are the same organism."""

    def test_same_db_taxid_merges(self):
        m = _mgr()
        m._add_entry_from_dict(
            _entry("Bacillus anthracis", 1392, 4005020, threat="high", threshold=50),
            WatchlistSource.USER, watchlist_id="list_a")
        m._add_entry_from_dict(
            _entry("Bacillus anthracis", 1392, 4005020, threat="critical", threshold=10),
            WatchlistSource.USER, watchlist_id="list_b")
        assert len(m._entries) == 1
        entry = next(iter(m._entries.values()))
        # Existing merge policy is preserved: severest threat, lowest threshold.
        assert entry.threat_level.value == "critical"
        assert entry.alert_threshold == 10
        assert entry.watchlist_ids == {"list_a", "list_b"}

    def test_neither_stating_a_db_taxid_merges(self):
        m = _mgr()
        m._add_entry_from_dict(
            _entry("Yersinia pestis", 632), WatchlistSource.USER, watchlist_id="a")
        m._add_entry_from_dict(
            _entry("Yersinia pestis", 632), WatchlistSource.USER, watchlist_id="b")
        assert len(m._entries) == 1

    def test_one_side_unspecified_still_merges(self):
        # An NCBI-only watchlist contributing the same organism as a
        # database-aware one must not fork it.
        m = _mgr()
        m._add_entry_from_dict(
            _entry("Coxiella burnetii", 777, 4019022),
            WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(
            _entry("Coxiella burnetii", 777),
            WatchlistSource.USER, watchlist_id="clinical")
        assert len(m._entries) == 1
        entry = next(iter(m._entries.values()))
        assert entry.db_taxid == 4019022, "the database node must not be lost"


class TestLookupStillWorks:
    def test_entry_is_retrievable_after_a_fork(self):
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        # Every stored entry must be reachable by the key it is stored under,
        # or the UI's per-entry actions (toggle, edit, remove) break.
        for key, entry in m._entries.items():
            assert m._entries[key] is entry

    def test_active_entries_include_both(self):
        m = _mgr()
        m._add_entry_from_dict(GLANDERS, WatchlistSource.USER, watchlist_id="bio")
        m._add_entry_from_dict(MALLEI, WatchlistSource.USER, watchlist_id="bio")
        assert len(m.get_active_entries()) == 2
