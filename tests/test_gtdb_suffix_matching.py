"""The name matcher bridges an NCBI watchlist name to its GTDB counterpart.

GTDB splits a polyphyletic genus and suffixes the parts alphabetically, so
*Bacillus anthracis* is ``Bacillus_A anthracis`` in a GTDB database. A report
row carries the real suffix; a watchlist entry usually carries the plain NCBI
binomial. With no taxid mapping in hand -- a GTDB build the operator has not
scanned -- the only bridge is the matcher generating the entry's speculative
GTDB genus-suffix forms, which it now does when the database profile asks
(GTDB or undetectable nomenclature). Before this, such a run matched the
grafted pathogens by name only through the taxid-mapping collection, and a
mapping-less GTDB database silently matched nothing (bug audit 2026-11-06,
follow-up to finding 2).

The genus differs between the two names, so the genus+species and
same-genus tiers cannot bridge them and the substring tier cannot either
(``bacillus anthracis`` is not a substring of ``bacillus_a anthracis``).
Only the explicit GTDB variants reach it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanometa_live.core.watchlist.taxonomy_matcher import (
    TaxonomyMatcher, get_taxonomy_matcher,
)

pytestmark = pytest.mark.unit


def _entry(name, names_alt=None):
    return SimpleNamespace(name=name, names_alt=names_alt or [])


class TestGtdbGenusSuffixBridge:
    def test_ncbi_entry_matches_gtdb_report_when_enabled(self):
        m = get_taxonomy_matcher()
        idx = m.build_entry_index([_entry("Bacillus anthracis")],
                                  generates_gtdb_variants=True)
        entry, score = m.match_row_indexed("Bacillus_A anthracis", idx)
        assert entry is not None and score >= 0.7

    def test_the_bridge_is_off_by_default(self):
        # The conservative default keeps the NCBI-database index cheap and
        # every existing caller/test unchanged.
        m = get_taxonomy_matcher()
        idx = m.build_entry_index([_entry("Bacillus anthracis")])
        entry, score = m.match_row_indexed("Bacillus_A anthracis", idx)
        assert entry is None

    def test_exact_name_is_unaffected_by_the_flag(self):
        m = get_taxonomy_matcher()
        for gtdb in (False, True):
            idx = m.build_entry_index([_entry("Bacillus anthracis")],
                                      generates_gtdb_variants=gtdb)
            entry, score = m.match_row_indexed("Bacillus anthracis", idx)
            assert entry is not None and score == 1.0

    def test_a_different_genus_does_not_false_match(self):
        # The suffix forms are genus-specific: Clostridium must not match the
        # Bacillus entry even with the forms generated.
        m = get_taxonomy_matcher()
        idx = m.build_entry_index([_entry("Bacillus anthracis")],
                                  generates_gtdb_variants=True)
        entry, _ = m.match_row_indexed("Clostridium_A botulinum", idx)
        assert entry is None

    def test_gtdb_variants_helper_is_genus_specific(self):
        forms = TaxonomyMatcher._gtdb_genus_variants("Bacillus anthracis")
        assert "bacillus_a anthracis" in forms
        assert all("anthracis" in f for f in forms)
        assert TaxonomyMatcher._gtdb_genus_variants("") == []


class TestManagerThreadsTheFlag:
    def test_manager_passes_the_profile_flag_to_the_index(self, monkeypatch):
        from nanometa_live.core.watchlist import watchlist_manager as wm_mod

        captured = {}
        real = wm_mod._get_taxonomy_matcher()

        def _spy_build(entries, generates_gtdb_variants=False):
            captured["gtdb"] = generates_gtdb_variants
            return real.build_entry_index(
                entries, generates_gtdb_variants=generates_gtdb_variants)

        mgr = wm_mod.WatchlistManager.__new__(wm_mod.WatchlistManager)
        mgr._match_index_cache = None
        monkeypatch.setattr(
            wm_mod.WatchlistManager, "_database_generates_gtdb_variants",
            staticmethod(lambda: True))
        monkeypatch.setattr(
            mgr, "watchlist_signature", lambda entries: "sig", raising=False)
        monkeypatch.setattr(wm_mod, "_get_taxonomy_matcher",
                            lambda: SimpleNamespace(build_entry_index=_spy_build))

        mgr._entry_match_index({1: _entry("Bacillus anthracis")})
        assert captured["gtdb"] is True
