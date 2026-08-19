"""One rule for which taxid a genome is keyed by, used by every consumer.

A watchlist entry with no NCBI identity -- every bacterial Bioshield agent --
is keyed by a synthetic pseudo-taxid, while its reference genome belongs
under the DATABASE taxid the reads are extracted for. Two call sites already
knew this (`preparation_tab._genome_taxid_for_entry`,
`parameter_mapping._genome_lookup_taxids`); four did not, so on a Bioshield
deployment they all reported nothing:

- `GenomeDownloadManager.get_missing_genomes`
- `GenomeDownloadManager.get_all_genome_status`
- `readiness_checker` "Watchlist Genomes" and "BLAST Databases"

And the download path had the mirror-image problem: it fetched by the entry
taxid, which NCBI cannot resolve, and would have written the result under
that same unusable name. With the watchlist now carrying a real
``taxid_ncbi`` alongside ``db_taxid``, the two roles separate cleanly:

- **fetch** by the NCBI taxid (what a public database can answer), and
- **cache** under the database taxid (what every consumer looks up).
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils.genome_manager import (
    genome_cache_taxid,
    genome_fetch_taxid,
)

PSEUDO = 2_057_967_092
DB = 4_005_020
NCBI = 1392


class TestCacheTaxid:
    def test_prefers_the_database_taxid(self):
        assert genome_cache_taxid(
            {"taxid": PSEUDO, "db_taxid": DB, "taxid_ncbi": NCBI}) == DB

    def test_falls_back_to_the_entry_taxid(self):
        assert genome_cache_taxid({"taxid": NCBI}) == NCBI

    def test_missing_identifiers_yield_zero(self):
        assert genome_cache_taxid({}) == 0
        assert genome_cache_taxid({"taxid": 0, "db_taxid": None}) == 0


class TestFetchTaxid:
    def test_prefers_a_real_ncbi_taxid(self):
        assert genome_fetch_taxid(
            {"taxid": PSEUDO, "db_taxid": DB, "taxid_ncbi": NCBI}) == NCBI

    def test_falls_back_to_the_entry_taxid_when_real(self):
        assert genome_fetch_taxid({"taxid": NCBI}) == NCBI

    def test_never_returns_a_pseudo_taxid(self):
        # A pseudo-taxid cannot be resolved by NCBI; returning it would send
        # a request that answers HTTP 400 and trips the shared circuit
        # breaker for every other organism in the run.
        assert genome_fetch_taxid({"taxid": PSEUDO, "db_taxid": DB}) == 0

    def test_database_taxid_is_not_offered_to_ncbi(self):
        # A flextaxd graft id looks like a real taxid by range alone but
        # names a different organism at NCBI.
        assert genome_fetch_taxid({"taxid": PSEUDO, "db_taxid": DB}) != DB


class TestConsumersUseTheCacheTaxid:
    def _mgr(self, present):
        from nanometa_live.core.utils.genome_manager import GenomeDownloadManager

        mgr = GenomeDownloadManager.__new__(GenomeDownloadManager)
        mgr.has_genome = lambda t: t in present
        mgr.has_blast_db = lambda t: t in present
        return mgr

    ENTRIES = [
        {"taxid": PSEUDO, "db_taxid": DB, "name": "Bacillus anthracis"},
        {"taxid": 11292, "name": "Lyssavirus rabies"},
    ]

    def test_missing_genomes_looks_under_the_database_taxid(self):
        mgr = self._mgr({DB})
        missing = mgr.get_missing_genomes(self.ENTRIES)
        names = [e["name"] for e in missing]
        assert "Bacillus anthracis" not in names, (
            "a genome cached under its database taxid was reported missing; "
            "this is the '0 downloaded / 129 missing' state operators saw"
        )
        assert "Lyssavirus rabies" in names

    def test_status_map_is_keyed_by_the_cache_taxid(self):
        mgr = self._mgr({DB})
        status = mgr.get_all_genome_status(self.ENTRIES)
        assert status[DB]["genome"] is True
        assert status[11292]["genome"] is False
        assert PSEUDO not in status


class TestReadinessUsesTheCacheTaxid:
    SOURCE = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "nanometa_live" / "core" / "workflow" / "readiness_checker.py"
    )

    def test_readiness_no_longer_keys_on_the_entry_taxid(self):
        src = self.SOURCE.read_text()
        assert 'not gm.has_genome(e["taxid"])' not in src, (
            "the readiness checklist reports every Bioshield genome missing"
        )
        assert 'not gm.has_blast_db(e["taxid"])' not in src
        assert "genome_cache_taxid" in src
