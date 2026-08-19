"""The taxonomy lookup must honour the operator's API selection.

``_apis_for_database`` narrowed the NCBI/GTDB checkboxes to the *detected
nomenclature of the loaded Kraken2 database*, on the reasoning that querying
the service which "cannot resolve this database's names" is wasted work and a
stall risk. The 2026-08-19 audit found the premise wrong and the effect
harmful:

- ``validate_entry_via_api`` queries the WATCHLIST ENTRY's own name and
  taxid. It never looks up a database node name, so the Kraken2 database's
  nomenclature does not determine which service can answer.
- On a GTDB-nomenclature database (Bioshield and every flextaxd field build)
  the narrowing returned ``(False, use_gtdb)`` -- disabling NCBI. But 76 of
  the 129 bioshield_agents entries are name-only, and NCBI's
  ``search_by_name`` is exactly what resolves them. It disabled the service
  that works and kept the one that cannot help.
- The stall it guarded against is already handled where it belongs: the
  per-host circuit breaker, and the pseudo-taxid refusal inside
  ``NCBIClient.get_by_taxid`` pinned below.

The lookup is not load-bearing either (it does not gate detection, feed the
confidence score, or block genome download), so a wrong service choice now
costs a missing hyperlink -- never a wrong badge.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.taxonomy.pseudo_taxid import (
    PSEUDO_TAXID_BASE,
    is_real_ncbi_taxid,
)


class TestNoNarrowingByDatabaseProfile:
    """The narrowing helper must not come back."""

    SOURCE = (
        Path(__file__).resolve().parents[1]
        / "nanometa_live" / "app" / "tabs" / "watchlist_tab.py"
    )

    def test_helper_is_gone(self):
        assert not hasattr(
            __import__(
                "nanometa_live.app.tabs.watchlist_tab", fromlist=["x"]
            ),
            "_apis_for_database",
        ), (
            "the API selection is narrowed by the Kraken2 database's "
            "nomenclature again; the lookup queries the watchlist entry, "
            "not the database, so the two are unrelated"
        )

    def test_lookup_path_does_not_consult_the_database_profile(self):
        src = self.SOURCE.read_text()
        assert "load_profile_for_db" not in src, (
            "the taxonomy lookup path reads the database profile again -- "
            "that coupling is what disabled NCBI on every flextaxd build"
        )


class TestPseudoTaxidGuardMakesRemovalSafe:
    """Why dropping the narrowing cannot trip the circuit breaker.

    Entries with no NCBI identity are keyed in the reserved pseudo band, and
    the NCBI client refuses a by-taxid call for those, falling back to a name
    search. A database graft id (Bioshield uses 4,000,000+) is therefore
    never sent to esummary, which would answer HTTP 400 and trip the shared
    per-host breaker for every other organism in the run.
    """

    def test_graft_ids_are_below_the_pseudo_band(self):
        # Documents the hazard the guard has to cover: a Bioshield graft id
        # looks like a real NCBI taxid by range alone.
        assert is_real_ncbi_taxid(4005020) is True
        assert is_real_ncbi_taxid(PSEUDO_TAXID_BASE + 57967092) is False

    def test_client_refuses_by_taxid_for_a_pseudo_taxid(self):
        from nanometa_live.core.taxonomy.taxonomy_api import NCBIClient

        client = NCBIClient()
        with patch.object(client, "_make_request") as request:
            result = client.get_by_taxid(PSEUDO_TAXID_BASE + 57967092)

        assert result is None
        assert not request.called, (
            "a pseudo-taxid reached esummary; HTTP 400 there trips the "
            "per-host circuit breaker and silently fails the rest of the run"
        )

    def test_client_still_queries_a_real_taxid(self):
        from nanometa_live.core.taxonomy.taxonomy_api import NCBIClient

        client = NCBIClient()
        # Bypass the result cache so the request path is observable; the
        # point of this test is that a real taxid is NOT refused by the
        # pseudo-taxid guard above it.
        with patch.object(client.cache, "get_ncbi_by_taxid", return_value=None), \
             patch.object(client, "_make_request", return_value=None) as request:
            client.get_by_taxid(1392)

        assert request.called, (
            "a real NCBI taxid was refused; the pseudo-taxid guard must "
            "only skip the reserved band"
        )


class TestOperatorSelectionIsHonoured:
    """Both services are queried when the operator ticks both, whatever the
    loaded database is."""

    def _entry(self):
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistEntry

        entry = WatchlistEntry(
            taxid=PSEUDO_TAXID_BASE + 57967092,   # name-only entry
            name="Bacillus anthracis",
        )
        entry.db_taxid = 4005020                  # GTDB graft node
        return entry

    def test_name_only_entry_resolves_through_ncbi_by_name(self):
        from nanometa_live.core.taxonomy import taxonomy_api
        from nanometa_live.core.watchlist import watchlist_manager as wm

        entry = self._entry()
        ncbi = MagicMock()
        ncbi.get_by_taxid.return_value = None
        ncbi.search_by_name.return_value = MagicMock(
            taxid=1392, sciname="Bacillus anthracis", commonname="anthrax",
            rank="species", lineage=["Bacteria"],
            ncbi_link="https://example.invalid/1392",
        )
        manager = wm.WatchlistManager()
        manager._entries = {entry.taxid: entry}

        # The manager imports the clients lazily from taxonomy_api, so patch
        # them at their source module.
        with patch.object(taxonomy_api, "get_ncbi_client", return_value=ncbi), \
             patch.object(taxonomy_api, "get_gtdb_client", return_value=MagicMock(
                 search_by_name=MagicMock(return_value=None))):
            result = manager.validate_entry_via_api(
                entry.taxid, use_ncbi=True, use_gtdb=True
            )

        assert result["ncbi_found"] is True, (
            "NCBI resolves this entry by name -- the narrowing used to "
            "disable NCBI entirely on the database this entry belongs to"
        )
        ncbi.search_by_name.assert_called_once_with("Bacillus anthracis")
