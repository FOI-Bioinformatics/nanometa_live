"""Tests for offline_mode enforcement in watchlist API validation."""

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager, WatchlistEntry, ThreatLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager_with_entry(taxid: int = 562) -> WatchlistManager:
    """Return a fresh WatchlistManager with a single minimal entry."""
    manager = WatchlistManager()
    entry = WatchlistEntry(
        taxid=taxid,
        name="Escherichia coli",
        source="user",
        threat_level=ThreatLevel.MODERATE,
    )
    manager._entries[taxid] = entry
    manager._name_index["escherichia coli"] = taxid
    manager._loaded = True
    return manager


# ---------------------------------------------------------------------------
# validate_entry_via_api -- offline_mode=True
# ---------------------------------------------------------------------------

class TestValidateEntryOfflineMode:
    """When offline_mode=True the validate button must not make HTTP requests."""

    def test_no_http_requests_when_offline(self):
        """requests.get must not be called when offline_mode is True."""
        manager = _make_manager_with_entry(taxid=562)

        with patch("requests.Session.get") as mock_get, \
             patch("requests.Session.post") as mock_post:
            manager.validate_entry_via_api(562, offline_mode=True)

        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_offline_cache_miss_returns_failure_shape(self):
        """A cache miss in offline mode must return a well-formed failure dict."""
        manager = _make_manager_with_entry(taxid=562)

        # Patch both taxonomy clients to return None (simulating empty cache)
        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_ncbi_client"
        ) as mock_ncbi_factory, patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_gtdb_client"
        ) as mock_gtdb_factory:
            ncbi_client = MagicMock()
            ncbi_client.get_by_taxid.return_value = None
            ncbi_client.search_by_name.return_value = None
            mock_ncbi_factory.return_value = ncbi_client

            gtdb_client = MagicMock()
            gtdb_client.search_by_name.return_value = None
            mock_gtdb_factory.return_value = gtdb_client

            result = manager.validate_entry_via_api(562, offline_mode=True)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["ncbi_found"] is False
        assert result["gtdb_found"] is False
        # Clients must have been created with offline_mode forwarded
        mock_ncbi_factory.assert_called_once_with(offline_mode=True)
        mock_gtdb_factory.assert_called_once_with(offline_mode=True)

    def test_offline_mode_forwarded_to_clients(self):
        """offline_mode=True must be passed to both get_ncbi_client and get_gtdb_client."""
        manager = _make_manager_with_entry(taxid=562)

        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_ncbi_client"
        ) as mock_ncbi, patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_gtdb_client"
        ) as mock_gtdb:
            ncbi_inst = MagicMock()
            ncbi_inst.get_by_taxid.return_value = None
            ncbi_inst.search_by_name.return_value = None
            mock_ncbi.return_value = ncbi_inst

            gtdb_inst = MagicMock()
            gtdb_inst.search_by_name.return_value = None
            mock_gtdb.return_value = gtdb_inst

            manager.validate_entry_via_api(562, offline_mode=True)

        _ncbi_kwargs = mock_ncbi.call_args[1] if mock_ncbi.call_args else {}
        _gtdb_kwargs = mock_gtdb.call_args[1] if mock_gtdb.call_args else {}
        assert _ncbi_kwargs.get("offline_mode") is True
        assert _gtdb_kwargs.get("offline_mode") is True


# ---------------------------------------------------------------------------
# validate_entry_via_api -- offline_mode=False (regression)
# ---------------------------------------------------------------------------

class TestValidateEntryOnlineMode:
    """When offline_mode=False the clients must be created without offline restriction."""

    def test_online_mode_forwarded_to_clients(self):
        """offline_mode=False must be passed to both API client factories."""
        manager = _make_manager_with_entry(taxid=562)

        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_ncbi_client"
        ) as mock_ncbi, patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_gtdb_client"
        ) as mock_gtdb:
            ncbi_inst = MagicMock()
            ncbi_inst.get_by_taxid.return_value = None
            ncbi_inst.search_by_name.return_value = None
            mock_ncbi.return_value = ncbi_inst

            gtdb_inst = MagicMock()
            gtdb_inst.search_by_name.return_value = None
            mock_gtdb.return_value = gtdb_inst

            manager.validate_entry_via_api(562, offline_mode=False)

        _ncbi_kwargs = mock_ncbi.call_args[1] if mock_ncbi.call_args else {}
        _gtdb_kwargs = mock_gtdb.call_args[1] if mock_gtdb.call_args else {}
        assert _ncbi_kwargs.get("offline_mode") is False
        assert _gtdb_kwargs.get("offline_mode") is False

    def test_default_offline_mode_is_false(self):
        """The default value of offline_mode must be False (no breaking change)."""
        manager = _make_manager_with_entry(taxid=562)

        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_ncbi_client"
        ) as mock_ncbi, patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_gtdb_client"
        ) as mock_gtdb:
            ncbi_inst = MagicMock()
            ncbi_inst.get_by_taxid.return_value = None
            ncbi_inst.search_by_name.return_value = None
            mock_ncbi.return_value = ncbi_inst

            gtdb_inst = MagicMock()
            gtdb_inst.search_by_name.return_value = None
            mock_gtdb.return_value = gtdb_inst

            # Call without offline_mode keyword -- must default to False
            manager.validate_entry_via_api(562)

        _ncbi_kwargs = mock_ncbi.call_args[1] if mock_ncbi.call_args else {}
        _gtdb_kwargs = mock_gtdb.call_args[1] if mock_gtdb.call_args else {}
        assert _ncbi_kwargs.get("offline_mode") is False
        assert _gtdb_kwargs.get("offline_mode") is False


# ---------------------------------------------------------------------------
# bulk_validate_entries -- offline_mode propagation
# ---------------------------------------------------------------------------

class TestBulkValidateOfflineMode:
    """bulk_validate_entries must forward offline_mode to every per-entry call."""

    def test_bulk_offline_mode_propagates(self):
        """offline_mode=True must reach get_ncbi_client / get_gtdb_client for every entry."""
        manager = _make_manager_with_entry(taxid=562)

        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_ncbi_client"
        ) as mock_ncbi, patch(
            "nanometa_live.core.taxonomy.taxonomy_api.get_gtdb_client"
        ) as mock_gtdb:
            ncbi_inst = MagicMock()
            ncbi_inst.get_by_taxid.return_value = None
            ncbi_inst.search_by_name.return_value = None
            mock_ncbi.return_value = ncbi_inst

            gtdb_inst = MagicMock()
            gtdb_inst.search_by_name.return_value = None
            mock_gtdb.return_value = gtdb_inst

            results = manager.bulk_validate_entries(
                taxids=[562], offline_mode=True
            )

        assert results["failed"] == 1  # cache miss -> not validated
        assert results["validated"] == 0
        for call in mock_ncbi.call_args_list:
            assert call[1].get("offline_mode") is True
        for call in mock_gtdb.call_args_list:
            assert call[1].get("offline_mode") is True

    def test_bulk_no_http_when_offline(self):
        """No real HTTP requests must be issued during bulk offline validation."""
        manager = _make_manager_with_entry(taxid=562)

        with patch("requests.Session.get") as mock_get, \
             patch("requests.Session.post") as mock_post:
            manager.bulk_validate_entries(taxids=[562], offline_mode=True)

        mock_get.assert_not_called()
        mock_post.assert_not_called()
