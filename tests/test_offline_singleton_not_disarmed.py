"""A no-argument factory call must never take the process back online.

``get_ncbi_client``, ``get_gtdb_client`` and ``get_cache`` are shared singletons
whose ``offline_mode`` is set once at startup by ``app._init_offline_mode``.
Each factory also declares ``offline_mode: bool = False`` and *mutates* the
existing instance when the value differs -- so a caller that simply wants the
client, and passes nothing, silently re-arms the network for every later user of
that singleton.

That is not hypothetical: ``genome_manager._resolve_species_name`` calls
``get_ncbi_client()`` with no arguments, and it is reached from
``_scan_existing_genomes`` (which runs in ``__init__``),
``refresh_unknown_metadata``, ``import_genomes_from_directory`` and
``import_genome_with_taxid``. Importing genomes on a field machine therefore
both performs a live lookup and leaves offline mode disarmed afterwards.

The distinction the signature needs is between "caller did not express an
opinion" and "caller explicitly wants online". A default of False cannot express
the first.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.taxonomy import taxonomy_api
from nanometa_live.core.utils import offline_cache


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, tmp_path):
    """Each test gets fresh singletons and its own cache dir."""
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(taxonomy_api, "_ncbi_client", None, raising=False)
    monkeypatch.setattr(taxonomy_api, "_gtdb_client", None, raising=False)
    monkeypatch.setattr(taxonomy_api, "_taxonomy_cache", None, raising=False)
    monkeypatch.setattr(offline_cache, "_cache_instance", None, raising=False)
    yield


class TestNoArgCallDoesNotDisarmOffline:
    def test_ncbi_client_stays_offline(self):
        armed = taxonomy_api.get_ncbi_client(offline_mode=True)
        assert armed.offline_mode is True

        again = taxonomy_api.get_ncbi_client()

        assert again is armed
        assert again.offline_mode is True, (
            "get_ncbi_client() with no arguments reset the shared client to "
            "online. Every later caller now reaches the network on an "
            "air-gapped machine."
        )

    def test_gtdb_client_stays_offline(self):
        armed = taxonomy_api.get_gtdb_client(offline_mode=True)
        assert armed.offline_mode is True

        again = taxonomy_api.get_gtdb_client()

        assert again is armed
        assert again.offline_mode is True, (
            "get_gtdb_client() with no arguments reset the shared client to "
            "online."
        )

    def test_offline_cache_stays_offline(self):
        armed = offline_cache.get_cache(offline_mode=True)
        assert armed.offline_mode is True

        again = offline_cache.get_cache()

        assert again is armed
        assert again.offline_mode is True, (
            "get_cache() with no arguments reset the shared cache to online, "
            "which also stops it serving expired entries -- the behaviour "
            "offline deployment depends on."
        )


class TestExplicitOnlineStillWorks:
    """The guard must not make offline mode impossible to leave.

    The header toggle and ``_init_offline_mode`` pass the value explicitly in
    both directions, and that has to keep working.
    """

    def test_explicit_false_returns_to_online(self):
        client = taxonomy_api.get_ncbi_client(offline_mode=True)
        assert client.offline_mode is True

        client = taxonomy_api.get_ncbi_client(offline_mode=False)

        assert client.offline_mode is False

    def test_explicit_false_returns_cache_to_online(self):
        cache = offline_cache.get_cache(offline_mode=True)
        assert cache.offline_mode is True

        cache = offline_cache.get_cache(offline_mode=False)

        assert cache.offline_mode is False


class TestGenomeManagerCallSite:
    def test_resolve_species_name_does_not_disarm(self, monkeypatch):
        """The real call site that triggers this in the field.

        ``_resolve_species_name`` must not leave the shared client online after
        it runs, whatever it does with the lookup itself.
        """
        from nanometa_live.core.utils import genome_manager as gm

        armed = taxonomy_api.get_ncbi_client(offline_mode=True)
        assert armed.offline_mode is True

        manager = gm.GenomeDownloadManager(offline_mode=True)
        manager._resolve_species_name(562)

        # Read the instance directly. Re-fetching via the factory with
        # offline_mode=True would re-arm it and make this assertion vacuous.
        assert armed.offline_mode is True, (
            "_resolve_species_name disarmed the shared NCBI client, so every "
            "subsequent taxonomy lookup in this process goes to the network."
        )
