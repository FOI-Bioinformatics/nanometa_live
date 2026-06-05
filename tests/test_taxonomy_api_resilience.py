"""Resilience of the taxonomy API clients and circuit breaker.

Covers the local-server report where Verify Taxonomy IDs validated only 1 of N
entries: the NCBI HTTP 400 (a pseudo-taxid sent to esummary) tripped the
per-host circuit breaker, which then silently failed the rest of the run.
"""

import requests

from nanometa_live.core.taxonomy.taxonomy_api import (
    NCBIClient,
    TaxonomyAPIClient,
    _classify_request_error,
    describe_failure_reason,
)


def test_get_by_taxid_skips_pseudo_taxid_without_request(monkeypatch):
    """A synthetic pseudo-taxid (>= 2e9) must not hit NCBI esummary (HTTP 400);
    get_by_taxid returns None without making a request."""
    client = NCBIClient()

    called = {"hit": False}

    def _boom(*args, **kwargs):
        called["hit"] = True
        raise AssertionError("network call must not happen for a pseudo-taxid")

    monkeypatch.setattr(client, "_make_request", _boom)
    assert client.get_by_taxid(2_000_000_123) is None
    assert called["hit"] is False
    # taxid 0 / negative are likewise non-real and skipped.
    assert client.get_by_taxid(0) is None
    assert called["hit"] is False


def test_reset_circuit_breaker_clears_state():
    TaxonomyAPIClient._circuit_open["example.com"] = True
    TaxonomyAPIClient._circuit_failures["example.com"] = 5
    TaxonomyAPIClient._circuit_last_reason["example.com"] = "ssl_error"
    TaxonomyAPIClient.reset_circuit_breaker()
    assert TaxonomyAPIClient._circuit_open == {}
    assert TaxonomyAPIClient._circuit_failures == {}
    assert TaxonomyAPIClient._circuit_last_reason == {}


def test_circuit_failure_summary_reports_reason():
    TaxonomyAPIClient.reset_circuit_breaker()
    TaxonomyAPIClient._circuit_record_failure(
        "https://api.gtdb.ecogenomic.org/x", "ssl_error"
    )
    summary = TaxonomyAPIClient.circuit_failure_summary()
    assert summary.get("api.gtdb.ecogenomic.org") == "ssl_error"
    TaxonomyAPIClient.reset_circuit_breaker()


def test_classify_request_error_maps_http_400():
    resp = requests.Response()
    resp.status_code = 400
    err = requests.exceptions.HTTPError(response=resp)
    assert _classify_request_error(err) == "http_400"


def test_classify_request_error_maps_families():
    assert _classify_request_error(requests.exceptions.SSLError()) == "ssl_error"
    assert _classify_request_error(requests.exceptions.Timeout()) == "timeout"
    assert _classify_request_error(
        requests.exceptions.ConnectionError()
    ) == "connection_error"


def test_describe_failure_reason_is_human_readable():
    assert "SSL" in describe_failure_reason("ssl_error")
    assert describe_failure_reason("http_400")  # non-empty phrasing
