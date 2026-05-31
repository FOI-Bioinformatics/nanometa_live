"""Tests for WatchlistManager.apply_validation_results.

Validation runs in a background worker whose WatchlistManager is a separate
process-local instance; its results are serialized as WatchlistEntry.to_dict()
payloads and copied back onto the main-process singleton via this method.
"""

from __future__ import annotations

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    WatchlistEntry,
    ThreatLevel,
)


def _manager_with_entry(taxid: int = 1280) -> WatchlistManager:
    manager = WatchlistManager()
    manager._entries[taxid] = WatchlistEntry(
        taxid=taxid,
        name="Staphylococcus aureus",
        source="user",
        threat_level=ThreatLevel.HIGH,
    )
    manager._loaded = True
    return manager


class TestApplyValidationResults:
    def test_applies_validation_fields(self):
        manager = _manager_with_entry(1280)
        payload = [{
            "taxid": 1280,
            "validated": True,
            "validation_date": "2026-05-31T00:00:00Z",
            "ncbi_link": "https://www.ncbi.nlm.nih.gov/taxonomy/1280",
            "gtdb_link": "https://gtdb.ecogenomic.org/x",
            "gtdb_taxonomy": "d__Bacteria;...;s__Staphylococcus aureus",
            "api_sciname": "Staphylococcus aureus",
            "api_commonname": None,
            "api_rank": "species",
            "lineage": "Bacteria; Firmicutes; ...",
        }]
        applied = manager.apply_validation_results(payload)
        assert applied == 1
        e = manager._entries[1280]
        assert e.validated is True
        assert e.ncbi_link.endswith("/1280")
        assert e.gtdb_taxonomy.startswith("d__Bacteria")
        assert e.api_sciname == "Staphylococcus aureus"
        assert e.validation_date == "2026-05-31T00:00:00Z"

    def test_string_taxid_payload_matches_int_entry(self):
        manager = _manager_with_entry(1280)
        applied = manager.apply_validation_results(
            [{"taxid": "1280", "validated": True}]
        )
        assert applied == 1
        assert manager._entries[1280].validated is True

    def test_unknown_taxid_skipped(self):
        manager = _manager_with_entry(1280)
        applied = manager.apply_validation_results(
            [{"taxid": 99999, "validated": True}]
        )
        assert applied == 0
        assert manager._entries[1280].validated is False

    def test_bad_payloads_ignored(self):
        manager = _manager_with_entry(1280)
        assert manager.apply_validation_results([]) == 0
        assert manager.apply_validation_results(None) == 0
        assert manager.apply_validation_results([{"no_taxid": 1}]) == 0
        assert manager.apply_validation_results([{"taxid": None}]) == 0
