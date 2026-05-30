"""
Tests for NCBIClient response parsing in core/taxonomy/taxonomy_api.py
(was 51% covered; the transport + cache + circuit breaker are in
test_taxonomy_api.py, this covers search_by_name / get_by_taxid parsing).

All HTTP is mocked at _make_request; get_lineage is stubbed so each test drives a
single parse path. A fresh TaxonomyCache(tmp) avoids cross-test cache hits.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.taxonomy.taxonomy_api import (
    NCBIClient,
    TaxonomyAPIClient,
    TaxonomyCache,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_circuit():
    TaxonomyAPIClient._circuit_failures.clear()
    TaxonomyAPIClient._circuit_open.clear()
    yield
    TaxonomyAPIClient._circuit_failures.clear()
    TaxonomyAPIClient._circuit_open.clear()


@pytest.fixture
def client(tmp_path):
    c = NCBIClient(cache=TaxonomyCache(cache_dir=tmp_path / "cache"))
    c.rate_limit = 0
    return c


ESUMMARY = {"result": {"562": {
    "scientificname": "Escherichia coli", "rank": "species", "division": "bacteria",
}}}


class TestGetByTaxid:
    def test_parses_summary(self, client):
        with patch.object(client, "_make_request", return_value=ESUMMARY), \
             patch.object(client, "get_lineage", return_value=[]):
            result = client.get_by_taxid(562)
        assert result is not None
        assert result.taxid == 562
        assert result.sciname == "Escherichia coli"
        assert result.rank == "species"

    def test_error_doc_returns_none(self, client):
        with patch.object(client, "_make_request",
                          return_value={"result": {"562": {"error": "not found"}}}), \
             patch.object(client, "get_lineage", return_value=[]):
            assert client.get_by_taxid(562) is None

    def test_no_response_returns_none(self, client):
        with patch.object(client, "_make_request", return_value=None):
            assert client.get_by_taxid(562) is None

    def test_result_is_cached(self, client):
        with patch.object(client, "_make_request", return_value=ESUMMARY), \
             patch.object(client, "get_lineage", return_value=[]):
            client.get_by_taxid(562)
        # Second call hits the cache; _make_request must not fire again.
        with patch.object(client, "_make_request", side_effect=AssertionError("network")):
            cached = client.get_by_taxid(562)
        assert cached.sciname == "Escherichia coli"


class TestSearchByName:
    def test_resolves_name_to_taxid_then_summary(self, client):
        esearch = {"esearchresult": {"idlist": ["562"]}}
        with patch.object(client, "_make_request", side_effect=[esearch, ESUMMARY]), \
             patch.object(client, "get_lineage", return_value=[]):
            result = client.search_by_name("Escherichia coli")
        assert result is not None
        assert result.taxid == 562

    def test_no_hits_returns_none(self, client):
        empty = {"esearchresult": {"idlist": []}}
        with patch.object(client, "_make_request", side_effect=[empty, empty]):
            assert client.search_by_name("Imaginary species") is None

    def test_cache_hit_skips_network(self, client):
        # Seed the cache via a first lookup, then assert no network on repeat.
        esearch = {"esearchresult": {"idlist": ["562"]}}
        with patch.object(client, "_make_request", side_effect=[esearch, ESUMMARY]), \
             patch.object(client, "get_lineage", return_value=[]):
            client.search_by_name("Escherichia coli")
        with patch.object(client, "_make_request", side_effect=AssertionError("network")):
            again = client.search_by_name("Escherichia coli")
        assert again.taxid == 562


class TestOfflineMode:
    def test_offline_get_by_taxid_no_network(self, tmp_path):
        c = NCBIClient(cache=TaxonomyCache(cache_dir=tmp_path / "c"))
        c.offline_mode = True
        with patch.object(c, "_make_request", side_effect=AssertionError("network")):
            # Empty offline cache -> None, but crucially no network call.
            assert c.get_by_taxid(562) is None
