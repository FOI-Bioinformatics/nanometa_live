"""Lifecycle tests for core/utils/genome_manager.py.

Complements the accessor / singleton / pool-sizing suites by exercising:

  * metadata cache round-trip and the merge-not-clobber behaviour of the
    atomic, file-locked ``_save_metadata`` read-modify-write,
  * cache hit/miss detection (``has_genome`` / ``get_genome_path``),
  * kingdom-based source routing inside ``download_genome`` -- bacteria /
    archaea route through GTDB first, eukaryotes / viruses do not,
  * the per-host circuit breaker short-circuit in ``fetch_gtdb_accession`` /
    ``fetch_ncbi_accession`` after CIRCUIT_THRESHOLD failures.

No network calls and no NCBI Datasets CLI / makeblastdb subprocesses are
performed -- every external boundary is monkeypatched. All state lives under a
tmp cache_dir; the real ~/.nanometa is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanometa_live.core.utils.genome_manager import (
    GenomeDownloadManager,
    GenomeMetadata,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset the class-level circuit breaker around each test.

    The breaker maps are class attributes shared across all manager
    instances and the whole process, so a failure recorded in one test
    would otherwise leak into the next.
    """
    GenomeDownloadManager._host_failures = {}
    GenomeDownloadManager._host_open = {}
    yield
    GenomeDownloadManager._host_failures = {}
    GenomeDownloadManager._host_open = {}


@pytest.fixture
def manager(tmp_path):
    """A manager rooted at a fresh tmp cache, offline by default.

    ``offline_mode=True`` keeps __init__'s _scan_existing_genomes from
    reaching the network when resolving species names, and stops the
    auto-build of BLAST databases from shelling out.
    """
    cache = tmp_path / "cache"
    return GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)


# ---------------------------------------------------------------------------
# 1. Cache metadata round-trip + merge-not-clobber
# ---------------------------------------------------------------------------


class TestMetadataRoundTrip:
    def _make_meta(self, taxid: int, cache: Path, **kw) -> GenomeMetadata:
        defaults = dict(
            taxid=taxid,
            species_name=f"Species {taxid}",
            accession=f"GCF_{taxid}.1",
            source="ncbi",
            kingdom="Bacteria",
            fasta_path=str(cache / "genomes" / f"{taxid}.fasta"),
            file_size=42,
        )
        defaults.update(kw)
        return GenomeMetadata(**defaults)

    def test_save_then_reload_round_trips(self, manager, tmp_path):
        cache = tmp_path / "cache"
        manager._metadata[562] = self._make_meta(562, cache)
        manager._save_metadata()

        # A fresh manager over the same cache_dir must read it back.
        reloaded = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
        assert 562 in reloaded._metadata
        assert reloaded._metadata[562].species_name == "Species 562"
        assert reloaded._metadata[562].accession == "GCF_562.1"

    def test_second_write_merges_rather_than_clobbers(self, manager, tmp_path):
        """A concurrent writer's disk additions survive our save.

        _save_metadata re-reads inside the file lock and merges disk
        entries it does not know about, so an out-of-band write by a
        second process is preserved.
        """
        cache = tmp_path / "cache"
        # First manager records taxid 562.
        manager._metadata[562] = self._make_meta(562, cache)
        manager._save_metadata()

        # A second manager (simulating another process) loads, adds 1280,
        # and saves -- without ever having seen 562 dropped.
        other = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
        assert 562 in other._metadata  # loaded from disk

        # Now simulate an out-of-band addition to disk that `manager` is
        # unaware of, then have `manager` save its own (stale) view.
        out_of_band = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
        out_of_band._metadata.clear()
        out_of_band._metadata[1280] = self._make_meta(1280, cache, species_name="Staph")
        out_of_band._save_metadata()

        # `manager` only knows 562; saving must NOT erase 1280 from disk.
        manager._save_metadata()

        final = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
        assert 562 in final._metadata
        assert 1280 in final._metadata
        assert final._metadata[1280].species_name == "Staph"

    def test_atomic_write_leaves_no_partial_file(self, manager, tmp_path):
        cache = tmp_path / "cache"
        manager._metadata[562] = self._make_meta(562, cache)
        manager._save_metadata()
        # The metadata file exists and is valid JSON with no temp siblings.
        # The `.lock` file used by file_lock is an expected, persistent
        # companion -- it is not a partial-write artifact.
        assert manager.metadata_file.exists()
        leftovers = [
            p for p in manager.metadata_file.parent.iterdir()
            if p.name.startswith(manager.metadata_file.name)
            and p != manager.metadata_file
            and p.suffix != ".lock"
        ]
        assert leftovers == [], f"unexpected temp leftovers: {leftovers}"


# ---------------------------------------------------------------------------
# 2. Cache hit / miss detection
# ---------------------------------------------------------------------------


class TestCacheHitMiss:
    def test_hit_when_fasta_on_disk(self, tmp_path):
        cache = tmp_path / "cache"
        (cache / "genomes").mkdir(parents=True)
        (cache / "blast").mkdir(parents=True)
        # A genome present on disk with the canonical {taxid}.fasta name.
        fasta = cache / "genomes" / "562.fasta"
        fasta.write_text(">seq\nACGTACGT\n")

        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
        assert mgr.has_genome(562) is True
        assert mgr.get_genome_path(562) == fasta

    def test_miss_when_absent(self, manager):
        assert manager.has_genome(99999) is False
        assert manager.get_genome_path(99999) is None

    def test_download_returns_cached_without_network(self, tmp_path, monkeypatch):
        """An already-present genome short-circuits download_genome.

        In online mode, download_genome must return the cached path
        without ever resolving a kingdom or hitting the network.
        """
        cache = tmp_path / "cache"
        (cache / "genomes").mkdir(parents=True)
        (cache / "blast").mkdir(parents=True)
        fasta = cache / "genomes" / "562.fasta"
        fasta.write_text(">seq\nACGTACGT\n")

        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=False)

        # Any network/CLI access would call these; make them explode.
        def _boom(*a, **k):  # pragma: no cover - must not be called
            raise AssertionError("network/CLI should not be touched on cache hit")

        monkeypatch.setattr(mgr, "get_kingdom", _boom)
        monkeypatch.setattr(mgr, "fetch_gtdb_accession", _boom)
        monkeypatch.setattr(mgr, "fetch_ncbi_accession", _boom)

        result = mgr.download_genome(562, "Escherichia coli")
        assert result == fasta


# ---------------------------------------------------------------------------
# 3. Kingdom-based source routing
# ---------------------------------------------------------------------------


class TestKingdomRouting:
    def test_bacteria_routes_to_gtdb_first(self, tmp_path, monkeypatch):
        """Bacteria/Archaea try GTDB before NCBI."""
        cache = tmp_path / "cache"
        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=False)

        calls = {"gtdb": 0, "ncbi": 0, "dl_accession": None}

        monkeypatch.setattr(mgr, "get_kingdom", lambda t: "Bacteria")

        def fake_gtdb(name):
            calls["gtdb"] += 1
            return ("GCF_000005845.2", {"gtdbTaxonomy": "d__Bacteria"})

        def fake_ncbi(taxid):  # pragma: no cover - GTDB should win
            calls["ncbi"] += 1
            return ("GCF_xxx", {})

        def fake_dl(accession, taxid):
            calls["dl_accession"] = accession
            out = mgr.genomes_dir / f"{taxid}.fasta"
            out.write_text(">seq\nACGT\n")
            return out

        monkeypatch.setattr(mgr, "fetch_gtdb_accession", fake_gtdb)
        monkeypatch.setattr(mgr, "fetch_ncbi_accession", fake_ncbi)
        monkeypatch.setattr(mgr, "_download_ncbi_genome", fake_dl)

        path = mgr.download_genome(562, "Escherichia coli")

        assert path is not None
        assert calls["gtdb"] == 1
        assert calls["ncbi"] == 0  # NCBI not consulted -- GTDB matched
        assert calls["dl_accession"] == "GCF_000005845.2"
        # Source recorded as gtdb.
        assert mgr._metadata[562].source == "gtdb"
        assert mgr._metadata[562].gtdb_taxonomy == "d__Bacteria"

    def test_bacteria_falls_back_to_ncbi_when_gtdb_misses(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=False)

        calls = {"gtdb": 0, "ncbi": 0}

        monkeypatch.setattr(mgr, "get_kingdom", lambda t: "Archaea")

        def fake_gtdb(name):
            calls["gtdb"] += 1
            return None  # GTDB miss

        def fake_ncbi(taxid):
            calls["ncbi"] += 1
            return ("GCF_ncbi.1", {"organism": {"organism_name": "Some archaeon"}})

        def fake_dl(accession, taxid):
            out = mgr.genomes_dir / f"{taxid}.fasta"
            out.write_text(">seq\nACGT\n")
            return out

        monkeypatch.setattr(mgr, "fetch_gtdb_accession", fake_gtdb)
        monkeypatch.setattr(mgr, "fetch_ncbi_accession", fake_ncbi)
        monkeypatch.setattr(mgr, "_download_ncbi_genome", fake_dl)

        path = mgr.download_genome(2157, "Some archaeon")

        assert path is not None
        assert calls["gtdb"] == 1
        assert calls["ncbi"] == 1
        assert mgr._metadata[2157].source == "ncbi"

    def test_eukaryote_skips_gtdb_uses_ncbi(self, tmp_path, monkeypatch):
        """A eukaryote never queries GTDB; it routes straight to NCBI."""
        cache = tmp_path / "cache"
        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=False)

        calls = {"gtdb": 0, "ncbi": 0}

        monkeypatch.setattr(mgr, "get_kingdom", lambda t: "Eukaryota")

        def fake_gtdb(name):  # pragma: no cover - must not run for eukaryotes
            calls["gtdb"] += 1
            return ("should_not_be_used", {})

        def fake_ncbi(taxid):
            calls["ncbi"] += 1
            return ("GCF_euk.1", {})

        def fake_dl(accession, taxid):
            out = mgr.genomes_dir / f"{taxid}.fasta"
            out.write_text(">seq\nACGT\n")
            return out

        monkeypatch.setattr(mgr, "fetch_gtdb_accession", fake_gtdb)
        monkeypatch.setattr(mgr, "fetch_ncbi_accession", fake_ncbi)
        monkeypatch.setattr(mgr, "_download_ncbi_genome", fake_dl)

        path = mgr.download_genome(5476, "Candida albicans")

        assert path is not None
        assert calls["gtdb"] == 0  # GTDB branch skipped for eukaryotes
        assert calls["ncbi"] == 1
        assert mgr._metadata[5476].source == "ncbi"

    def test_virus_routes_to_virus_download(self, tmp_path, monkeypatch):
        """Viruses route to the dedicated virus download path."""
        cache = tmp_path / "cache"
        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=False)

        calls = {"virus": 0, "gtdb": 0, "ncbi": 0}

        monkeypatch.setattr(mgr, "get_kingdom", lambda t: "Viruses")

        def fake_virus(taxid, name):
            calls["virus"] += 1
            out = mgr.genomes_dir / f"{taxid}.fasta"
            out.write_text(">seq\nACGT\n")
            return out, "NC_001.1"

        def fake_gtdb(name):  # pragma: no cover
            calls["gtdb"] += 1
            return None

        def fake_ncbi(taxid):  # pragma: no cover
            calls["ncbi"] += 1
            return None

        monkeypatch.setattr(mgr, "_download_virus_genome", fake_virus)
        monkeypatch.setattr(mgr, "fetch_gtdb_accession", fake_gtdb)
        monkeypatch.setattr(mgr, "fetch_ncbi_accession", fake_ncbi)

        path = mgr.download_genome(11320, "Influenza A virus")

        assert path is not None
        assert calls["virus"] == 1
        assert calls["gtdb"] == 0
        assert calls["ncbi"] == 0
        assert mgr._metadata[11320].source == "ncbi_virus"
        assert mgr._metadata[11320].accession == "NC_001.1"


# ---------------------------------------------------------------------------
# 4. Circuit-breaker short-circuit
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_gtdb_opens_after_threshold_and_short_circuits(self, manager, monkeypatch):
        """After CIRCUIT_THRESHOLD failures, GTDB requests stop firing."""
        import nanometa_live.core.utils.genome_manager as gm

        manager.offline_mode = False  # so the fetch path is reached
        call_count = {"n": 0}

        def boom_get(*a, **k):
            call_count["n"] += 1
            raise gm.requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(gm.requests, "get", boom_get)

        threshold = GenomeDownloadManager.CIRCUIT_THRESHOLD
        # Drive exactly CIRCUIT_THRESHOLD failures -- each fires one request.
        for _ in range(threshold):
            assert manager.fetch_gtdb_accession("Escherichia coli") is None

        assert call_count["n"] == threshold
        assert GenomeDownloadManager._circuit_is_open("gtdb") is True

        # Further calls must return None WITHOUT firing another request.
        assert manager.fetch_gtdb_accession("Escherichia coli") is None
        assert call_count["n"] == threshold, "breaker must short-circuit the call"

    def test_ncbi_opens_after_threshold_and_short_circuits(self, manager, monkeypatch):
        import nanometa_live.core.utils.genome_manager as gm

        manager.offline_mode = False
        call_count = {"n": 0}

        def boom_get(*a, **k):
            call_count["n"] += 1
            raise gm.requests.exceptions.Timeout("slow")

        monkeypatch.setattr(gm.requests, "get", boom_get)

        threshold = GenomeDownloadManager.CIRCUIT_THRESHOLD
        for _ in range(threshold):
            assert manager.fetch_ncbi_accession(562) is None

        assert call_count["n"] == threshold
        assert GenomeDownloadManager._circuit_is_open("ncbi") is True

        assert manager.fetch_ncbi_accession(562) is None
        assert call_count["n"] == threshold

    def test_breaker_is_per_host(self, manager, monkeypatch):
        """Opening GTDB must not short-circuit NCBI (independent hosts)."""
        import nanometa_live.core.utils.genome_manager as gm

        manager.offline_mode = False

        # Force the gtdb host open directly.
        GenomeDownloadManager._host_open["gtdb"] = True

        ncbi_calls = {"n": 0}

        def fake_ncbi_get(*a, **k):
            ncbi_calls["n"] += 1
            raise gm.requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(gm.requests, "get", fake_ncbi_get)

        # GTDB short-circuits (no request).
        assert manager.fetch_gtdb_accession("Escherichia coli") is None
        # NCBI is still allowed to try (its breaker is closed).
        assert manager.fetch_ncbi_accession(562) is None
        assert ncbi_calls["n"] == 1

    def test_success_resets_failure_counter(self, manager):
        """A recorded success zeroes the failure tally for that host."""
        GenomeDownloadManager._circuit_record_failure(
            "gtdb", "GTDB API", RuntimeError("x")
        )
        assert GenomeDownloadManager._host_failures["gtdb"] == 1
        GenomeDownloadManager._circuit_record_success("gtdb")
        assert GenomeDownloadManager._host_failures["gtdb"] == 0
