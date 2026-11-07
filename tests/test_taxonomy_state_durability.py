"""Taxonomy state files are written atomically, and get_lineage obeys the breaker.

Two items from the 2026-11-06 audit.

**Finding 34.** Three JSON state files were written with ``open(path, "w")``,
which truncates before writing: the taxid mapping collection, the database
index cache and the NCBI/GTDB taxonomy cache. A crash or a second process
reading mid-write therefore saw a truncated file -- and none of these fails
loudly. A truncated mappings file loads as None and every watchlist entry
reads UNMAPPED, which is "this organism is not in the database": a negative
result an operator may act on, produced by an I/O accident. It also carries
the operator's manual verifications, which nothing else can reconstruct.

**Finding 37 (the get_lineage item).** ``NCBIClient.get_lineage`` needs XML
and so issues its own request rather than going through ``_make_request`` --
and it did not consult the per-host circuit breaker or report to it. With NCBI
degraded, every lineage call still paid the full timeout after the breaker had
opened, which is precisely the Dash-callback pile-up the breaker exists to
prevent.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    TaxidMapping,
    TaxidMappingCollection,
)
from nanometa_live.core.taxonomy.taxonomy_api import (
    NCBIClient,
    TaxonomyAPIClient,
    TaxonomyCache,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_circuit():
    TaxonomyAPIClient.reset_circuit_breaker()
    yield
    TaxonomyAPIClient.reset_circuit_breaker()


def _collection():
    c = TaxidMappingCollection(database_path="/db", database_hash="h")
    c.mappings[1392] = TaxidMapping(
        ncbi_taxid=1392,
        canonical_name="Bacillus anthracis",
        db_taxid=4005020,
        confidence=MappingConfidence.MANUAL,
        manually_verified=True,
    )
    return c


class TestMappingCollectionSaveIsAtomic:
    def test_a_failed_write_leaves_the_previous_file_intact(self, tmp_path):
        path = tmp_path / "mappings.json"
        assert _collection().save(str(path)) is True
        before = path.read_text()

        doomed = _collection()
        doomed.mappings[1392].canonical_name = "replaced"
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.json.dumps",
            side_effect=OSError("disk full"),
        ):
            assert doomed.save(str(path)) is False

        assert path.read_text() == before, (
            "the previous mappings file was truncated by a failed write; it "
            "then loads as all-UNMAPPED, which reads as a negative result"
        )

    def test_it_does_not_truncate_before_writing(self, tmp_path):
        """No window in which a reader can see an empty file."""
        path = tmp_path / "mappings.json"
        assert _collection().save(str(path)) is True
        seen = []

        real_replace = __import__("os").replace

        def spy(src, dst):
            seen.append(path.read_text())
            return real_replace(src, dst)

        with patch("nanometa_live.core.utils.atomic_write.os.replace", spy):
            assert _collection().save(str(path)) is True

        assert seen and seen[0], (
            "the target was already empty while the new contents were being "
            "written"
        )

    def test_no_temp_file_is_left_behind(self, tmp_path):
        path = tmp_path / "mappings.json"
        assert _collection().save(str(path)) is True

        assert [p.name for p in tmp_path.iterdir()] == ["mappings.json"]

    def test_the_round_trip_still_works(self, tmp_path):
        path = tmp_path / "mappings.json"
        assert _collection().save(str(path)) is True

        reloaded = TaxidMappingCollection.load(str(path))

        assert reloaded is not None
        assert reloaded.mappings[1392].manually_verified is True
        # Still valid, indented JSON.
        assert json.loads(path.read_text())["mappings"]


class TestTaxonomyCacheSaveIsAtomic:
    def test_a_failed_write_leaves_the_previous_cache_intact(self, tmp_path):
        cache = TaxonomyCache(cache_dir=tmp_path / "cache")
        from nanometa_live.core.taxonomy.taxonomy_api import NCBIResult
        cache.set_ncbi(NCBIResult(taxid=1392, sciname="B. anthracis"))
        before = cache.cache_file.read_text()

        with patch(
            "nanometa_live.core.taxonomy.taxonomy_api.atomic_write_json",
            side_effect=OSError("disk full"),
        ):
            cache.set_ncbi(NCBIResult(taxid=562, sciname="E. coli"))

        assert cache.cache_file.read_text() == before

    def test_the_cache_still_persists(self, tmp_path):
        from nanometa_live.core.taxonomy.taxonomy_api import NCBIResult
        cache = TaxonomyCache(cache_dir=tmp_path / "cache")
        cache.set_ncbi(NCBIResult(taxid=1392, sciname="B. anthracis"))

        fresh = TaxonomyCache(cache_dir=tmp_path / "cache")

        assert fresh.get_ncbi_by_taxid(1392) is not None


class TestGetLineageHonoursTheCircuitBreaker:
    @pytest.fixture
    def client(self, tmp_path):
        c = NCBIClient(cache=TaxonomyCache(cache_dir=tmp_path / "cache"))
        c.rate_limit = 0
        return c

    def test_an_open_circuit_makes_no_request(self, client):
        url = f"{client.BASE_URL}/efetch.fcgi"
        for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD):
            TaxonomyAPIClient._circuit_record_failure(url)

        with patch.object(client._session, "get") as get:
            assert client.get_lineage(1392) == []

        get.assert_not_called(), (
            "a lineage call still paid the host timeout after the breaker "
            "had opened for that host"
        )

    def test_a_request_failure_counts_towards_the_breaker(self, client):
        host = TaxonomyAPIClient._circuit_host(
            f"{client.BASE_URL}/efetch.fcgi")

        with patch.object(
            client._session, "get",
            side_effect=requests.exceptions.ConnectionError(),
        ):
            assert client.get_lineage(1392) == []

        assert TaxonomyAPIClient._circuit_failures.get(host) == 1, (
            "lineage failures never counted towards opening the breaker, so "
            "the host stayed in use however badly it was failing"
        )

    def test_three_failures_open_it(self, client):
        url = f"{client.BASE_URL}/efetch.fcgi"
        with patch.object(
            client._session, "get",
            side_effect=requests.exceptions.ConnectionError(),
        ):
            for _ in range(TaxonomyAPIClient._CIRCUIT_FAILURE_THRESHOLD):
                client.get_lineage(1392)

        assert TaxonomyAPIClient._circuit_is_open(url) is True

    def test_a_success_clears_the_recorded_failures(self, client):
        url = f"{client.BASE_URL}/efetch.fcgi"
        TaxonomyAPIClient._circuit_record_failure(url)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = (
            "<LineageEx><Taxon><ScientificName>Bacteria</ScientificName>"
            "</Taxon></LineageEx>"
        )

        with patch.object(client._session, "get", return_value=resp):
            assert client.get_lineage(1392) == ["Bacteria"]

        assert TaxonomyAPIClient._circuit_host(url) not in (
            TaxonomyAPIClient._circuit_failures)

    def test_an_unparseable_response_is_not_a_host_failure(self, client):
        """The host answered; the breaker is about reachability."""
        host = TaxonomyAPIClient._circuit_host(
            f"{client.BASE_URL}/efetch.fcgi")
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = "not xml at all"

        with patch.object(client._session, "get", return_value=resp):
            assert client.get_lineage(1392) == []

        assert host not in TaxonomyAPIClient._circuit_failures
