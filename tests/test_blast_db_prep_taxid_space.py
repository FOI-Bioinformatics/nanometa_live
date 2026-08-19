"""BLAST-DB preparation must look in the taxid space the genomes live in.

A watchlist entry with no NCBI identity -- every bacterial Bioshield agent,
76 of 129 -- is keyed by a synthetic pseudo-taxid (>= 2e9), while its
reference genome is cached under the DATABASE taxid the reads are extracted
for (``4005020.fasta`` for Bacillus anthracis). ``get_genome_path`` already
knows this: ``get_validation_species_from_watchlist`` resolves genomes by
``kraken_taxid`` first.

The launch-time BLAST preparation did not. ``create_nextflow_config`` passed
``ncbi_taxids`` -- the pseudo-taxids -- to ``_ensure_blast_dbs_for_validation``
and ``_warn_on_reference_mismatch``. Measured against the real
bioshield_agents watchlist on the Bioshield database:

    blast_db_status(pseudo taxids) -> {'present': 0, 'missing': 0, 'no_genome': 129}
    blast_db_status(db taxids)     -> {'present': 2, 'missing': 0, 'no_genome': 127}

So for the entire Bioshield bacterial set the builder saw "no genome",
which is NOT the ``missing`` bucket it builds from and NOT the bucket it
warns about. A genome placed under the documented ``{db_taxid}.fasta`` name
therefore reached the pipeline with no BLAST database and no diagnostic:
minimap2 coverage appeared, the Sequence Matching sub-tab stayed empty, and
nothing in the log said why. The reference-mismatch guard was dead for the
same reason.

The fix passes the taxid each genome is actually keyed by (kraken/db taxid
when it differs, else the NCBI taxid).
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.config.parameter_mapping import (
    _ensure_blast_dbs_for_validation,
    _genome_lookup_taxids,
)


PSEUDO = 2_057_967_092      # Bacillus anthracis, name-only entry
DB_TAXID = 4_005_020        # Bacillus_A anthracis in the Bioshield database
NCBI_ONLY = 11292           # Lyssavirus rabies: a real NCBI taxid, no mapping

SPECIES = [
    {"taxid": PSEUDO, "kraken_taxid": DB_TAXID, "name": "Bacillus anthracis"},
    {"taxid": NCBI_ONLY, "kraken_taxid": NCBI_ONLY, "name": "Lyssavirus rabies"},
]


class TestGenomeLookupTaxids:
    def test_prefers_the_db_taxid_when_it_differs(self):
        assert _genome_lookup_taxids(SPECIES) == [DB_TAXID, NCBI_ONLY]

    def test_keeps_ncbi_taxid_when_there_is_no_mapping(self):
        assert _genome_lookup_taxids(
            [{"taxid": NCBI_ONLY, "kraken_taxid": NCBI_ONLY}]) == [NCBI_ONLY]

    def test_falls_back_to_ncbi_taxid_when_kraken_taxid_absent(self):
        assert _genome_lookup_taxids([{"taxid": NCBI_ONLY}]) == [NCBI_ONLY]

    def test_skips_entries_with_no_identifier_and_dedupes(self):
        out = _genome_lookup_taxids([
            {"taxid": 0, "kraken_taxid": 0},
            {"taxid": PSEUDO, "kraken_taxid": DB_TAXID},
            {"taxid": PSEUDO, "kraken_taxid": DB_TAXID},
        ])
        assert out == [DB_TAXID]


class TestEnsureBlastDbsUsesGenomeTaxids:
    def _manager(self, genome_taxids):
        """Genome manager double: genomes exist only under ``genome_taxids``."""
        mgr = MagicMock()

        def status(taxids):
            present, missing, no_genome = [], [], []
            for t in taxids:
                if t in genome_taxids:
                    missing.append(t)     # genome present, DB not built yet
                else:
                    no_genome.append(t)
            return {"present": present, "missing": missing,
                    "no_genome": no_genome}

        mgr.blast_db_status.side_effect = status
        return mgr

    def test_builds_the_db_for_a_genome_cached_under_its_db_taxid(self):
        mgr = self._manager({DB_TAXID})
        _ensure_blast_dbs_for_validation(mgr, _genome_lookup_taxids(SPECIES))
        built = [c.args[0] for c in mgr.build_blast_db.call_args_list]
        assert DB_TAXID in built, (
            "the whole Bioshield bacterial set reached the pipeline with no "
            "BLAST database and no warning: BLAST sub-tab silently empty"
        )

    def test_pseudo_taxid_alone_builds_nothing(self):
        # Documents the defect this test pins: with the pseudo taxid the
        # status call reports no_genome, so nothing is built.
        mgr = self._manager({DB_TAXID})
        _ensure_blast_dbs_for_validation(mgr, [PSEUDO])
        assert not mgr.build_blast_db.called

    def test_ncbi_keyed_genome_still_builds(self):
        mgr = self._manager({NCBI_ONLY})
        _ensure_blast_dbs_for_validation(mgr, _genome_lookup_taxids(SPECIES))
        built = [c.args[0] for c in mgr.build_blast_db.call_args_list]
        assert NCBI_ONLY in built

    def test_empty_list_is_a_noop(self):
        mgr = self._manager(set())
        _ensure_blast_dbs_for_validation(mgr, [])
        assert not mgr.blast_db_status.called


class TestCallSiteWiring:
    """The two guards must be called with genome-space taxids, not the
    pseudo-taxid list."""

    SOURCE = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "nanometa_live" / "core" / "config" / "parameter_mapping.py"
    )

    def test_call_site_uses_the_lookup_helper(self):
        src = self.SOURCE.read_text()
        assert "_warn_on_reference_mismatch(genome_manager, ncbi_taxids" not in src, (
            "reference-mismatch guard is back on the pseudo-taxid list, where "
            "it can never see a Bioshield genome"
        )
        assert "_ensure_blast_dbs_for_validation(genome_manager, ncbi_taxids)" not in src
        assert "_genome_lookup_taxids(" in src


class TestReferenceMismatchNameLookup:
    """The mismatch guard must find the expected organism NAME in the same
    taxid space it iterates.

    Fixing the loop to walk genome taxids is only half the repair: the
    ``name_by_taxid`` map was still keyed by the watchlist ENTRY taxid, so
    every Bioshield lookup returned ``""``. ``check_reference_organism``
    treats an empty expected name as "cannot tell" and returns None, so the
    guard could still never warn -- a wrong reference genome would attribute
    coverage to the wrong organism in silence.
    """

    def test_expected_name_is_found_by_genome_taxid(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import (
            _warn_on_reference_mismatch,
        )

        genome = tmp_path / f"{DB_TAXID}.fasta"
        # A genuinely wrong reference: Yersinia sequence filed under the
        # Bacillus anthracis entry.
        genome.write_text(">NZ_TEST.1 Yersinia pestis CO92\nACGT\n")

        mgr = MagicMock()
        mgr.has_genome.side_effect = lambda t: t == DB_TAXID
        mgr.get_genome_path.side_effect = (
            lambda t: str(genome) if t == DB_TAXID else None
        )

        import logging as _logging
        records = []

        class _Cap(_logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        root = _logging.getLogger()
        handler = _Cap()
        root.addHandler(handler)
        prior = root.level
        root.setLevel(_logging.WARNING)
        try:
            _warn_on_reference_mismatch(
                mgr, _genome_lookup_taxids(SPECIES), SPECIES)
        finally:
            root.removeHandler(handler)
            root.setLevel(prior)

        assert any("mismatch" in m.lower() for m in records), (
            "a reference genome from the wrong genus was accepted silently; "
            "the expected-name lookup is still keyed by the entry taxid"
        )
