"""A genome download must prefer an assembly of the organism that was asked for.

An NCBI taxon query returns the whole subtree, so "the reference genome for
taxon N" can be an assembly of a descendant. Measured 2026-08-20:

    datasets summary genome taxon 263 --reference
    -> GCF_000833355.1, organism tax_id 1450527,
       Francisella tularensis subsp. novicida D9876

So a species-level watchlist entry for F. tularensis was handed a novicida
genome -- the most sequence-divergent member of the group. Validation then
measures a Type A or Type B detection against the wrong reference, depressing
identity and coverage for a true detection.

`--tax-exact-match` ("Exclude sub-species when a species-level taxon is
specified") is the remedy, but it cannot be applied unconditionally: for taxon
263 it yields nothing at all under `--reference`, because the only reference
genome in that subtree IS the subspecies. The rule is therefore to prefer the
exact node and fall back to the subtree, saying so, rather than silently
accepting a different organism.

Subspecies entries are unaffected: taxon 119857 has 18 assemblies registered at
exactly that node.
"""

import json
import subprocess
from unittest.mock import patch

import pytest

from nanometa_live.core.utils.genome_manager import GenomeDownloadManager


def _summary(accession, tax_id, name):
    return json.dumps({"reports": [{
        "accession": accession,
        "organism": {"tax_id": tax_id, "organism_name": name},
    }]})


EMPTY = json.dumps({"reports": []})


@pytest.fixture
def manager(tmp_path):
    return GenomeDownloadManager(cache_dir=str(tmp_path), offline_mode=False)


class TestResolveAssemblyAccession:
    def test_exact_match_is_attempted_before_the_subtree(self, manager):
        calls = []

        def _run(cmd, *a, **kw):
            calls.append(cmd)
            if "--tax-exact-match" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, _summary("GCF_001611815.4", 263, "Francisella tularensis"), "")
            return subprocess.CompletedProcess(
                cmd, 0, _summary("GCF_000833355.1", 1450527, "F. t. novicida D9876"), "")

        with patch("subprocess.run", side_effect=_run), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            acc = manager._resolve_assembly_accession(263)

        assert acc == "GCF_001611815.4"
        assert "--tax-exact-match" in calls[0], (
            "the first attempt must constrain to the exact taxon"
        )

    def test_falls_back_to_the_subtree_when_no_exact_assembly_exists(self, manager):
        def _run(cmd, *a, **kw):
            if "--tax-exact-match" in cmd:
                return subprocess.CompletedProcess(cmd, 0, EMPTY, "")
            return subprocess.CompletedProcess(
                cmd, 0, _summary("GCF_000833355.1", 1450527, "F. t. novicida D9876"), "")

        with patch("subprocess.run", side_effect=_run), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            acc = manager._resolve_assembly_accession(263)

        assert acc == "GCF_000833355.1", (
            "a descendant assembly is better than no genome at all"
        )

    def test_the_subtree_fallback_is_reported(self, manager, caplog):
        def _run(cmd, *a, **kw):
            if "--tax-exact-match" in cmd:
                return subprocess.CompletedProcess(cmd, 0, EMPTY, "")
            return subprocess.CompletedProcess(
                cmd, 0, _summary("GCF_000833355.1", 1450527, "F. t. novicida D9876"), "")

        with patch("subprocess.run", side_effect=_run), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            with caplog.at_level("WARNING"):
                manager._resolve_assembly_accession(263)

        assert any("263" in r.message for r in caplog.records), (
            "accepting a different organism must not be silent"
        )

    def test_a_subspecies_taxon_resolves_exactly(self, manager):
        def _run(cmd, *a, **kw):
            if "--tax-exact-match" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, _summary("GCF_000009245.1", 119857, "F. t. holarctica"), "")
            return subprocess.CompletedProcess(cmd, 0, EMPTY, "")

        with patch("subprocess.run", side_effect=_run), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            acc = manager._resolve_assembly_accession(119857)

        assert acc == "GCF_000009245.1"

    def test_returns_none_when_nothing_resolves(self, manager):
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, EMPTY, "")), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            assert manager._resolve_assembly_accession(999999999) is None


class TestByTaxidDownloadCommand:
    def test_the_reference_download_constrains_to_the_exact_taxon(self, manager):
        """Otherwise `--reference` alone can return a descendant's genome."""
        calls = []

        def _run(cmd, *a, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "no reference")

        with patch("subprocess.run", side_effect=_run), \
             patch.object(manager, "_resolve_assembly_accession", return_value=None), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            manager._download_ncbi_genome_by_taxid(263, "Francisella tularensis")

        download_cmds = [c for c in calls if "download" in c]
        assert download_cmds, "no download command was issued"
        assert "--tax-exact-match" in download_cmds[0]
