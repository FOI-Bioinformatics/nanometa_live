"""Regression tests for the genome-resolution fallbacks added after the
watchlist BLAST-DB audit.

The audit found that BLAST-DB building itself never failed; the failures were
genome *resolution* for taxa whose watchlist taxid is an old/no-rank node or a
serovar with no reference assembly. `datasets` then either exits 0 with an empty
archive (viruses) or exits non-zero (genomes), and the old code gave up. These
tests pin the three fallbacks that fixed it, all with mocked subprocess so no
network is touched:

  * viruses fall back from the taxid to the species name, relaxing filters;
  * a by-taxid genome download with no reference resolves a single
    complete-assembly accession instead of failing (or pulling every assembly);
  * `_resolve_assembly_accession` prefers reference -> complete -> any.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.utils.genome_manager import GenomeDownloadManager

pytestmark = pytest.mark.unit


def _mgr(tmp_path):
    mgr = GenomeDownloadManager(cache_dir=str(tmp_path))
    mgr.offline_mode = False
    return mgr


class TestVirusNameFallback:
    def test_falls_back_from_taxid_to_species_name(self, tmp_path):
        """The taxid attempt yields nothing; the species-name attempt wins."""
        mgr = _mgr(tmp_path)
        # First attempt (the taxid) returns None; second (the name) returns an
        # accession. _try_virus_download writes the FASTA in reality; here we
        # only assert the orchestration picks the name attempt.
        mgr._try_virus_download = MagicMock(side_effect=[None, "NC_001234"])

        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"):
            path, accession = mgr._download_virus_genome(12080, "Poliovirus")

        assert accession == "NC_001234"
        assert path == mgr.genomes_dir / "12080.fasta"
        # First call used the taxid, second used the species name.
        first_taxon = mgr._try_virus_download.call_args_list[0].args[0]
        second_taxon = mgr._try_virus_download.call_args_list[1].args[0]
        assert first_taxon == "12080"
        assert second_taxon == "Poliovirus"

    def test_records_error_when_every_attempt_fails(self, tmp_path):
        mgr = _mgr(tmp_path)
        mgr._try_virus_download = MagicMock(return_value=None)
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"):
            path, accession = mgr._download_virus_genome(999999, "Nonexistent virus")
        assert path is None and accession is None
        assert 999999 in mgr._last_errors


class TestResolveAssemblyAccession:
    def _fake_run_factory(self, mapping):
        """mapping: predicate(cmd)->stdout str. Returns a subprocess.run stub."""
        def fake_run(cmd, **kwargs):
            for pred, stdout in mapping:
                if pred(cmd):
                    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="no match")
        return fake_run

    def test_prefers_reference_then_complete_then_any(self, tmp_path):
        mgr = _mgr(tmp_path)
        fake = self._fake_run_factory([
            (lambda c: "--reference" in c, '{"reports":[{"accession":"GCF_REF"}]}'),
        ])
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"), \
             patch("nanometa_live.core.utils.genome_manager.subprocess.run", side_effect=fake):
            assert mgr._resolve_assembly_accession(573) == "GCF_REF"

    def test_falls_through_to_complete_when_no_reference(self, tmp_path):
        mgr = _mgr(tmp_path)
        # reference query returns empty reports; complete query returns one.
        fake = self._fake_run_factory([
            (lambda c: "--reference" in c, '{"reports":[]}'),
            (lambda c: "complete" in c, '{"reports":[{"accession":"GCF_COMPLETE"}]}'),
        ])
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"), \
             patch("nanometa_live.core.utils.genome_manager.subprocess.run", side_effect=fake):
            assert mgr._resolve_assembly_accession(90370) == "GCF_COMPLETE"

    def test_returns_none_when_nothing_found(self, tmp_path):
        mgr = _mgr(tmp_path)
        fake = self._fake_run_factory([])  # every query 'fails'
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"), \
             patch("nanometa_live.core.utils.genome_manager.subprocess.run", side_effect=fake):
            assert mgr._resolve_assembly_accession(1) is None


class TestByTaxidReferenceFallback:
    def test_no_reference_resolves_accession_and_downloads_one(self, tmp_path):
        """--reference exits non-zero -> resolve a complete accession and fetch
        just that one (never the bare without-reference download that pulls every
        assembly for the taxon)."""
        mgr = _mgr(tmp_path)
        fasta = tmp_path / "90370.fasta"
        fasta.write_text(">seq\nACGT\n")

        # --reference download fails (no reference genome for the serovar).
        fake_run = MagicMock(return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="Error: no genomes available"))
        mgr._resolve_assembly_accession = MagicMock(return_value="GCF_001048035.2")
        mgr._download_ncbi_genome = MagicMock(return_value=fasta)

        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/datasets"), \
             patch("nanometa_live.core.utils.genome_manager.subprocess.run", fake_run):
            path, accession = mgr._download_ncbi_genome_by_taxid(90370, "Salmonella enterica serovar Typhi")

        assert path == fasta
        assert accession == "GCF_001048035.2"
        mgr._download_ncbi_genome.assert_called_once_with("GCF_001048035.2", 90370)
        # The dangerous bare without-reference retry must not run: exactly one
        # `datasets download` subprocess call (the --reference attempt).
        assert fake_run.call_count == 1


class TestBlastBuildIdempotent:
    def test_existing_db_skips_makeblastdb(self, tmp_path):
        """The per-taxid build lock re-checks has_blast_db inside the lock, so a
        second builder (auto-build-on-scan racing the prep batch) is a no-op
        instead of a redundant makeblastdb on the same output."""
        mgr = _mgr(tmp_path)
        genome = tmp_path / "562.fasta"
        genome.write_text(">s\nACGT\n")
        mgr.get_genome_path = MagicMock(return_value=genome)
        mgr.has_blast_db = MagicMock(return_value=True)  # already built by the other path
        run = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/makeblastdb"), \
             patch("nanometa_live.core.utils.genome_manager.subprocess.run", run):
            ok, reason = mgr._build_blast_db_with_reason(562)
        assert ok is True and reason is None
        run.assert_not_called()  # no second makeblastdb on the same DB


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
