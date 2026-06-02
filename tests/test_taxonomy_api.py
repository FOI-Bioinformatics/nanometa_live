"""
Unit tests for core/taxonomy/taxonomy_api.py.

The headline behaviour is the per-host circuit breaker documented in CLAUDE.md:
after _CIRCUIT_FAILURE_THRESHOLD consecutive failures a host is short-circuited
for the rest of the process, so a degraded GTDB/NCBI endpoint cannot pile up
5-second timeouts on the synchronous Dash callback thread. The breaker is
in-memory and per-process, so the class-level state is reset around each test.

All HTTP is mocked; no real network call is made.
"""

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.taxonomy.taxonomy_api import (
    GTDBResult,
    NCBIClient,
    NCBIResult,
    TaxonomyAPIClient,
    TaxonomyCache,
)

URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
HOST = "eutils.ncbi.nlm.nih.gov"


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
    c.rate_limit = 0  # disable rate-limit sleeps in tests
    return c


class TestCircuitBreaker:
    def test_host_extraction(self):
        assert TaxonomyAPIClient._circuit_host(URL) == HOST

    def test_host_extraction_falls_back_and_logs_on_parse_failure(self, caplog):
        # A URL that cannot be parsed must not be swallowed silently: the
        # raw URL is used as the breaker key and the failure is logged so a
        # malformed endpoint is diagnosable rather than retried in silence.
        with patch("urllib.parse.urlparse", side_effect=ValueError("bad url")):
            with caplog.at_level("WARNING"):
                result = TaxonomyAPIClient._circuit_host(URL)
        assert result == URL
        assert any("circuit-breaker host" in rec.message for rec in caplog.records)

    def test_opens_after_threshold_failures(self):
        for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD):
            TaxonomyAPIClient._circuit_record_failure(URL)
        assert TaxonomyAPIClient._circuit_is_open(URL) is True

    def test_stays_closed_below_threshold(self):
        for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD - 1):
            TaxonomyAPIClient._circuit_record_failure(URL)
        assert TaxonomyAPIClient._circuit_is_open(URL) is False

    def test_success_resets_failure_count(self):
        TaxonomyAPIClient._circuit_record_failure(URL)
        TaxonomyAPIClient._circuit_record_failure(URL)
        TaxonomyAPIClient._circuit_record_success(URL)
        # After a reset it takes a fresh full threshold to open again.
        TaxonomyAPIClient._circuit_record_failure(URL)
        assert TaxonomyAPIClient._circuit_is_open(URL) is False

    def test_breaker_is_per_host(self):
        other = "https://gtdb.example.org/api"
        for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD):
            TaxonomyAPIClient._circuit_record_failure(URL)
        assert TaxonomyAPIClient._circuit_is_open(URL) is True
        assert TaxonomyAPIClient._circuit_is_open(other) is False


class TestMakeRequest:
    def test_open_circuit_short_circuits_without_http(self, client):
        for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD):
            TaxonomyAPIClient._circuit_record_failure(URL)
        with patch.object(client._session, "get") as get:
            assert client._make_request(URL) is None
        get.assert_not_called()

    def test_offline_mode_short_circuits_without_http(self, client):
        client.offline_mode = True
        with patch.object(client._session, "get") as get:
            assert client._make_request(URL) is None
        get.assert_not_called()

    def test_success_returns_json_and_resets_breaker(self, client):
        TaxonomyAPIClient._circuit_record_failure(URL)  # one prior failure
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"ok": True}
        with patch.object(client._session, "get", return_value=resp):
            result = client._make_request(URL)
        assert result == {"ok": True}
        # A success clears the recorded failure for the host.
        assert TaxonomyAPIClient._circuit_host(URL) not in TaxonomyAPIClient._circuit_failures

    def test_request_failure_records_breaker_failure(self, client):
        import requests

        with patch.object(
            client._session, "get", side_effect=requests.exceptions.ConnectionError()
        ):
            assert client._make_request(URL) is None
        assert TaxonomyAPIClient._circuit_failures.get(HOST) == 1


class TestTaxonomyCache:
    def test_ncbi_round_trip_by_taxid_and_name(self, tmp_path):
        cache = TaxonomyCache(cache_dir=tmp_path / "c")
        cache.set_ncbi(NCBIResult(taxid=562, sciname="Escherichia coli"))
        assert cache.get_ncbi_by_taxid(562).sciname == "Escherichia coli"
        assert cache.get_ncbi_by_name("escherichia coli").taxid == 562

    def test_gtdb_round_trip(self, tmp_path):
        cache = TaxonomyCache(cache_dir=tmp_path / "c")
        cache.set_gtdb(GTDBResult(gtdb_taxonomy="d__Bacteria;s__E coli", species="Escherichia coli"))
        assert cache.get_gtdb("Escherichia coli").species == "Escherichia coli"

    def test_persists_across_instances(self, tmp_path):
        cache_dir = tmp_path / "c"
        TaxonomyCache(cache_dir=cache_dir).set_ncbi(
            NCBIResult(taxid=1280, sciname="Staphylococcus aureus")
        )
        reopened = TaxonomyCache(cache_dir=cache_dir)
        assert reopened.get_ncbi_by_taxid(1280) is not None

    def test_clear_and_stats(self, tmp_path):
        cache = TaxonomyCache(cache_dir=tmp_path / "c")
        cache.set_ncbi(NCBIResult(taxid=562, sciname="Escherichia coli"))
        assert cache.get_stats()["ncbi_entries"] == 1
        cache.clear()
        assert cache.get_stats()["ncbi_entries"] == 0


class TestResultDataclasses:
    def test_ncbi_result_auto_link_and_round_trip(self):
        r = NCBIResult(taxid=562, sciname="Escherichia coli")
        assert "id=562" in r.ncbi_link
        assert r.cached_at
        assert NCBIResult.from_dict(r.to_dict()) == r

    def test_gtdb_result_round_trip(self):
        r = GTDBResult(gtdb_taxonomy="d__Bacteria;s__E coli", species="E coli")
        assert GTDBResult.from_dict(r.to_dict()) == r

    def test_from_dict_ignores_unknown_keys(self):
        r = NCBIResult.from_dict({"taxid": 1, "sciname": "x", "bogus": "drop me"})
        assert r.taxid == 1
        assert not hasattr(r, "bogus")
