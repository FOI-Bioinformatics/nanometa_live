"""Large-watchlist matching: equivalence and scaling contracts.

The 129-entry Bioshield watchlist made the per-poll name-matching loop the
dominant dashboard cost: ``check_organisms`` and
``check_organisms_with_mapping`` ran ``matcher.match_organism`` for every
(report row x watchlist entry) pair, ~5.9 us per pair, ~1.5 s per pass at
N=129 / M=2000 rows. The fix is a precomputed per-entry index
(``TaxonomyMatcher.build_entry_index`` / ``match_row_indexed``) that resolves
the alert-relevant tiers (score >= 0.7) by dict lookup.

Two contracts pinned here:

- **Equivalence.** The indexed path must reproduce the naive loop's winner
  and score exactly for every alert-relevant row, including tie-breaks
  (max score wins; first entry in iteration order wins a tie). Tiers below
  the 0.7 alert floor never produce an alert, so "no entry" and "a sub-0.7
  entry" are interchangeable outcomes.
- **Scaling.** Matching cost is O(M + N) normalizer calls, not O(M x N).
"""

import pytest
from unittest.mock import patch

from nanometa_live.core.watchlist.taxonomy_matcher import get_taxonomy_matcher
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


def _entry(taxid, name, threshold=10, names_alt=None, threat="high",
           db_taxid=None):
    data = {
        "taxid": taxid, "name": name, "threat_level": threat,
        "enabled": True, "alert_threshold": threshold,
    }
    if names_alt:
        data["names_alt"] = names_alt
    if db_taxid is not None:
        data["db_taxid"] = db_taxid
    return data


@pytest.fixture
def manager():
    """A Bioshield-shaped watchlist: 129 entries, every one carrying alt
    names, mixed ranks, one family-level (single-token) entry, one
    operator-set db_taxid, plus deliberate tie-break traps."""
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = WatchlistManager()
        mgr._entries.clear()
        mgr._name_index.clear()

        # Tie-break traps: for detected "Xkyz abc", T1 scores 0.85
        # (genus+species) and T2 -- LATER in iteration order -- scores 0.95
        # (alt name). The naive loop picks T2 (higher score beats earlier
        # position). For detected "Foo bar", T3 and T4 both score 0.95;
        # T3 wins by position (strict > keeps the first).
        mgr.add_custom_entry(_entry(90001, "Xkyz abc qrs"))                    # T1
        mgr.add_custom_entry(_entry(90002, "Unrelated thing",
                                    names_alt=["Xkyz abc"]))                   # T2
        mgr.add_custom_entry(_entry(90003, "Firstus altus",
                                    names_alt=["Foo bar"]))                    # T3
        mgr.add_custom_entry(_entry(90004, "Secondus altus",
                                    names_alt=["Foo bar"]))                    # T4

        # Representative clinical shapes.
        mgr.add_custom_entry(_entry(90005, "Bacillus anthracis", threshold=5,
                                    threat="critical",
                                    names_alt=["Bacillus_A anthracis"]))
        mgr.add_custom_entry(_entry(90006, "Francisella tularensis",
                                    threshold=8, threat="critical",
                                    names_alt=["Francisella_A tularensis"]))
        mgr.add_custom_entry(_entry(90007, "Adenoviridae", threshold=20))      # family
        mgr.add_custom_entry(_entry(90008, "Yersinia pestis", threat="critical",
                                    db_taxid=4005555,
                                    names_alt=["Yersinia_B pestis"]))

        # Filler up to 129 entries, all with alt names like the real list.
        for i in range(121):
            mgr.add_custom_entry(_entry(
                91000 + i, f"Fillerus organismus{i}",
                names_alt=[f"Fillerus_A organismus{i}",
                           f"Fillerus organismus{i} subsp typicus"],
            ))
        assert len(mgr.get_active_entries()) == 129
        yield mgr


def _rows():
    """Detected rows covering every alert-relevant tier plus non-matches."""
    rows = [
        # exact (1.0), above threshold
        {"taxid": 555001, "name": "Bacillus anthracis", "reads": 100,
         "abundance": 1.5},
        # alt-name (0.95)
        {"taxid": 555002, "name": "Francisella_A tularensis", "reads": 50,
         "abundance": 0.9},
        # genus+species with GTDB suffix (0.85)
        {"taxid": 555003, "name": "Francisella tularensis_B", "reads": 40,
         "abundance": 0.7},
        # single-token family entry as substring (0.7)
        {"taxid": 555004, "name": "Human Adenoviridae C serotype", "reads": 60,
         "abundance": 1.0},
        # tie-break: later entry at 0.95 beats earlier at 0.85
        {"taxid": 555005, "name": "Xkyz abc", "reads": 30, "abundance": 0.5},
        # tie-break: equal scores, first entry in order wins
        {"taxid": 555006, "name": "Foo bar", "reads": 30, "abundance": 0.5},
        # operator db_taxid hit (taxid path, no name agreement)
        {"taxid": 4005555, "name": "unrecognisable node", "reads": 80,
         "abundance": 1.1},
        # below threshold (exact match, threshold 8)
        {"taxid": 555007, "name": "Francisella tularensis", "reads": 3,
         "abundance": 0.1},
        # same genus only (0.3) -- sub-floor, never alerts
        {"taxid": 555008, "name": "Bacillus subtilis", "reads": 500,
         "abundance": 4.0},
        # detected-in-entry substring (0.6) -- sub-floor, never alerts
        {"taxid": 555009, "name": "Fillerus", "reads": 500, "abundance": 4.0},
        # no relation at all
        {"taxid": 555010, "name": "Saccharomyces cerevisiae", "reads": 900,
         "abundance": 9.0},
    ]
    # Bulk misses so the fixture resembles a real report tail.
    for i in range(60):
        rows.append({"taxid": 600000 + i, "name": f"Backgroundus taxon{i}",
                     "reads": 5 + i, "abundance": 0.01})
    return rows


def _naive_best(matcher, organism, active_entries):
    """The pre-index inner loop, verbatim semantics: max score wins, first
    entry in iteration order wins a tie (strict >)."""
    entry, best = None, 0.0
    for e in active_entries.values():
        score = matcher.match_organism(
            detected=organism, entry_name=e.name,
            entry_alt_names=e.names_alt,
            entry_taxid=e.taxid if e.taxid else None,
        )
        if score > best:
            best, entry = score, e
    return entry, best


def _oracle_check_organisms(mgr, detected, below_threshold):
    """Reference implementation of check_organisms' selection semantics,
    built from the naive loop. Shares the manager's own non-matching
    helpers (taxid index, ambiguity, dedupe) since those are not under
    refactor."""
    active = mgr.get_active_entries()
    matcher = get_taxonomy_matcher()
    db_is_ncbi = mgr._database_taxids_are_ncbi()
    db_to_ncbi = mgr._build_db_taxid_index(active, None)
    alerts = []
    for organism in detected:
        taxid = organism.get("taxid")
        name = organism.get("name", "").strip()
        reads = organism.get("reads", 0)
        entry, best = None, 0.0
        if taxid and taxid in db_to_ncbi:
            entry = active.get(db_to_ncbi[taxid][0])
            best = 1.0 if entry else 0.0
        if entry is None and db_is_ncbi and taxid and taxid in active:
            entry, best = active[taxid], 1.0
        if entry is None:
            entry, best = _naive_best(matcher, organism, active)
        if entry and best >= 0.7:
            if (reads >= entry.alert_threshold) == below_threshold:
                continue
            alerts.append({
                "taxid": entry.taxid,
                "detected_taxid": taxid,
                "name": entry.name,
                "reads": reads,
                "threshold": entry.alert_threshold,
                "match_score": best,
                "detected_name": name,
            })
    return alerts


def _key_fields(alerts):
    return [
        {k: a[k] for k in ("taxid", "detected_taxid", "name", "reads",
                           "threshold", "match_score", "detected_name")}
        for a in alerts
    ]


def _sorted_oracle(mgr, oracle_alerts):
    deduped = mgr._dedupe_alerts_by_entry(oracle_alerts)
    threat = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    entries = mgr.get_active_entries()
    by_taxid = {e.taxid: e for e in entries.values()}
    deduped.sort(key=lambda a: threat.get(
        by_taxid[a["taxid"]].threat_level.value, 4))
    return deduped


class TestCharacterization:
    """check_organisms must keep producing exactly what the naive loop
    produced, both threshold sides."""

    @pytest.mark.parametrize("below", [False, True])
    def test_check_organisms_matches_the_naive_reference(self, manager, below):
        got = manager.check_organisms(_rows(), below_threshold=below)
        want = _sorted_oracle(
            manager, _oracle_check_organisms(manager, _rows(), below))
        assert _key_fields(got) == _key_fields(want)

    @pytest.mark.parametrize("below", [False, True])
    def test_mapping_path_matches_the_naive_reference(self, manager, below):
        from nanometa_live.core.taxonomy.taxid_mapping import (
            MappingConfidence, TaxidMapping, TaxidMappingCollection,
        )
        collection = TaxidMappingCollection(database_path="/tmp/db")
        collection.mappings[90005] = TaxidMapping(
            ncbi_taxid=90005, canonical_name="Bacillus anthracis",
            db_taxid=4009999, confidence=MappingConfidence.EXACT,
            match_score=0.95,
        )
        rows = _rows() + [
            {"taxid": 4009999, "name": "opaque grafted node", "reads": 200,
             "abundance": 2.0},
        ]
        got = manager.check_organisms_with_mapping(
            rows, collection, below_threshold=below)
        # Reference: the mapping steps resolve rows 90005-via-4009999 and the
        # db_taxid row; every other row falls to the naive name loop.
        active = manager.get_active_entries()
        matcher = get_taxonomy_matcher()
        db_to_ncbi = manager._build_db_taxid_index(active, collection)
        alerts = []
        for organism in rows:
            taxid = organism.get("taxid")
            reads = organism.get("reads", 0)
            entry, best = None, 0.0
            if not entry and taxid and taxid in db_to_ncbi:
                ncbi = db_to_ncbi[taxid][0]
                if ncbi in active:
                    entry = active[ncbi]
                    mapping = collection.mappings.get(ncbi)
                    if mapping:
                        best = (mapping.match_score
                                if mapping.match_score is not None else 0.9)
                    elif getattr(entry, "db_taxid", None) == taxid:
                        best = 1.0
                    else:
                        best = 0.9
            if not entry:
                entry, best = _naive_best(matcher, organism, active)
            if entry and best >= 0.7:
                if (reads >= entry.alert_threshold) == below:
                    continue
                alerts.append({
                    "taxid": entry.taxid, "detected_taxid": taxid,
                    "name": entry.name, "reads": reads,
                    "threshold": entry.alert_threshold, "match_score": best,
                    "detected_name": organism.get("name", "").strip(),
                })
        want = _sorted_oracle(manager, alerts)
        assert _key_fields(got) == _key_fields(want)


class TestEntryMatchIndex:
    """The new indexed matcher must reproduce the naive loop for every
    alert-relevant row."""

    def test_indexed_matches_naive_for_every_row(self, manager):
        matcher = get_taxonomy_matcher()
        active = manager.get_active_entries()
        index = matcher.build_entry_index(list(active.values()))
        for organism in _rows():
            naive_entry, naive_score = _naive_best(matcher, organism, active)
            got_entry, got_score = matcher.match_row_indexed(
                organism.get("name", ""), index)
            if naive_score >= 0.7:
                assert got_entry is naive_entry, organism["name"]
                assert got_score == naive_score, organism["name"]
            else:
                # Sub-floor scores never alert; the indexed path reports
                # no match at all.
                assert got_score < 0.7, organism["name"]
                assert got_entry is None, organism["name"]

    def test_later_higher_tier_beats_earlier_lower_tier(self, manager):
        matcher = get_taxonomy_matcher()
        index = matcher.build_entry_index(
            list(manager.get_active_entries().values()))
        entry, score = matcher.match_row_indexed("Xkyz abc", index)
        assert entry.taxid == 90002
        assert score == 0.95

    def test_equal_tier_first_entry_in_order_wins(self, manager):
        matcher = get_taxonomy_matcher()
        index = matcher.build_entry_index(
            list(manager.get_active_entries().values()))
        entry, score = matcher.match_row_indexed("Foo bar", index)
        assert entry.taxid == 90003
        assert score == 0.95

    def test_empty_name_matches_nothing(self, manager):
        matcher = get_taxonomy_matcher()
        index = matcher.build_entry_index(
            list(manager.get_active_entries().values()))
        entry, score = matcher.match_row_indexed("", index)
        assert entry is None and score == 0.0


class TestCheckOrganismsSplit:
    """One pass produces both threshold sides, equal to the two-call form."""

    def test_split_equals_the_two_single_side_calls(self, manager):
        rows = _rows()
        above, below = manager.check_organisms_split(rows)
        assert _key_fields(above) == _key_fields(
            manager.check_organisms(rows, below_threshold=False))
        assert _key_fields(below) == _key_fields(
            manager.check_organisms(rows, below_threshold=True))

    def test_mapping_split_equals_the_two_single_side_calls(self, manager):
        from nanometa_live.core.taxonomy.taxid_mapping import (
            TaxidMappingCollection,
        )
        collection = TaxidMappingCollection(database_path="/tmp/db")
        rows = _rows()
        above, below = manager.check_organisms_with_mapping_split(
            rows, collection)
        assert _key_fields(above) == _key_fields(
            manager.check_organisms_with_mapping(
                rows, collection, below_threshold=False))
        assert _key_fields(below) == _key_fields(
            manager.check_organisms_with_mapping(
                rows, collection, below_threshold=True))

    def test_mapping_split_without_collection_falls_back(self, manager):
        rows = _rows()
        above, below = manager.check_organisms_with_mapping_split(rows, None)
        assert _key_fields(above) == _key_fields(
            manager.check_organisms(rows, below_threshold=False))
        assert _key_fields(below) == _key_fields(
            manager.check_organisms(rows, below_threshold=True))


class TestWatchlistSignature:
    def test_stable_across_calls(self, manager):
        assert manager.watchlist_signature() == manager.watchlist_signature()

    def test_changes_when_an_entry_is_toggled(self, manager):
        before = manager.watchlist_signature()
        manager.toggle_entry(90005, False)
        assert manager.watchlist_signature() != before

    def test_changes_when_a_threshold_changes(self, manager):
        before = manager.watchlist_signature()
        manager._entries[90005].alert_threshold = 999
        assert manager.watchlist_signature() != before

    def test_changes_when_alt_names_change(self, manager):
        before = manager.watchlist_signature()
        manager._entries[90006].names_alt.append("Novel synonym")
        assert manager.watchlist_signature() != before


class TestScaling:
    """Matching issues O(M + N) normalizer calls, not O(M x N)."""

    def test_normalize_call_count_is_linear(self, manager, monkeypatch):
        from nanometa_live.core.watchlist.validation.name_normalizer import (
            get_name_normalizer,
        )
        rows = [{"taxid": 700000 + i, "name": f"Missus organismus{i} extra",
                 "reads": 50, "abundance": 0.1} for i in range(400)]
        normalizer = get_name_normalizer()
        calls = {"n": 0}
        orig = normalizer.normalize

        def counting(name):
            calls["n"] += 1
            return orig(name)

        monkeypatch.setattr(normalizer, "normalize", counting)
        manager.check_organisms(rows)
        n_entries = 129
        m_rows = len(rows)
        # Index build: entry name + alts + variants ~ 12 calls/entry.
        # Per row: normalize + variant set ~ 6 calls. Generous headroom;
        # the naive loop would need >= m_rows * n_entries = 51,600.
        assert calls["n"] <= 15 * n_entries + 8 * m_rows, calls["n"]
