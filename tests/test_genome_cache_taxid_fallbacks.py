"""A genome must land under the cache taxid on every download path.

`_download_ncbi_genome_by_taxid` takes ``taxid`` (asked of NCBI) and
``cache_taxid`` (the key the file is written under). Its main path honoured
both, but its two "no reference genome" fallbacks called
``_download_ncbi_genome(acc, taxid)`` with the NCBI taxid, so the file landed
under the wrong name.

Observed on the subspecies exercise, 2026-08-20: of five F. tularensis
watchlist entries, the two whose NCBI taxon has a flagged reference genome
cached correctly under their flextaxd db_taxid, while the three without one
fell into the fallback and cached under their NCBI taxid. A genome under the
wrong key is invisible: `has_genome(db_taxid)` is False, so the readiness
check and the Preparation tab report it missing and it is re-downloaded on
every attempt.
"""

import subprocess
import zipfile
from unittest.mock import patch

import pytest

from nanometa_live.core.utils.genome_manager import GenomeDownloadManager


FETCH_TAXID = 119857   # real NCBI taxid for F. t. subsp. holarctica
CACHE_TAXID = 4007187  # flextaxd graft id it must be cached under


@pytest.fixture
def manager(tmp_path):
    return GenomeDownloadManager(cache_dir=str(tmp_path), offline_mode=False)


def _capture_download(manager):
    """Patch the accession download and record the taxid it is handed."""
    seen = {}

    def _fake(accession, taxid):
        seen["accession"] = accession
        seen["taxid"] = taxid
        path = manager.genomes_dir / f"{taxid}.fasta"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(">contig\nACGT\n")
        return path

    return seen, _fake


class TestNoReferenceGenomeFallback:
    """The CLI exits non-zero when the taxon has no flagged reference."""

    def test_fallback_caches_under_the_cache_taxid(self, manager):
        seen, fake = _capture_download(manager)
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with patch("subprocess.run", return_value=failed), \
             patch.object(manager, "_resolve_assembly_accession",
                          return_value="GCF_000009245.1"), \
             patch.object(manager, "_download_ncbi_genome", side_effect=fake), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            path, accession = manager._download_ncbi_genome_by_taxid(
                FETCH_TAXID, "F. t. holarctica", cache_taxid=CACHE_TAXID)

        assert seen["taxid"] == CACHE_TAXID, (
            f"fallback wrote under {seen['taxid']}, expected the cache taxid "
            f"{CACHE_TAXID}"
        )
        assert path.name == f"{CACHE_TAXID}.fasta"
        assert accession == "GCF_000009245.1"

    def test_accession_lookup_still_uses_the_ncbi_taxid(self, manager):
        """The fetch/cache split must hold in both directions."""
        seen, fake = _capture_download(manager)
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        resolved_with = {}

        def _resolve(taxid):
            resolved_with["taxid"] = taxid
            return "GCF_000009245.1"

        with patch("subprocess.run", return_value=failed), \
             patch.object(manager, "_resolve_assembly_accession", side_effect=_resolve), \
             patch.object(manager, "_download_ncbi_genome", side_effect=fake), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            manager._download_ncbi_genome_by_taxid(
                FETCH_TAXID, "F. t. holarctica", cache_taxid=CACHE_TAXID)

        assert resolved_with["taxid"] == FETCH_TAXID


class TestEmptyArchiveFallback:
    """The CLI can also exit 0 with an archive containing no FASTA."""

    def test_empty_archive_fallback_caches_under_the_cache_taxid(
            self, manager, tmp_path, monkeypatch):
        seen, fake = _capture_download(manager)
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        real_zipfile = zipfile.ZipFile

        class _EmptyZip:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def namelist(self):
                return ["README.md"]

        def _fake_run(cmd, *a, **kw):
            # The CLI is expected to have created the archive.
            for i, part in enumerate(cmd):
                if part == "--filename":
                    p = tmp_path / "made.zip"
                    with real_zipfile(p, "w") as zf:
                        zf.writestr("README.md", "no genome here")
                    target = cmd[i + 1]
                    import shutil as _sh
                    _sh.copy(p, target)
            return ok

        with patch("subprocess.run", side_effect=_fake_run), \
             patch("zipfile.ZipFile", _EmptyZip), \
             patch.object(manager, "_resolve_assembly_accession",
                          return_value="GCF_000009245.1"), \
             patch.object(manager, "_download_ncbi_genome", side_effect=fake), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            path, _ = manager._download_ncbi_genome_by_taxid(
                FETCH_TAXID, "F. t. holarctica", cache_taxid=CACHE_TAXID)

        assert seen["taxid"] == CACHE_TAXID
        assert path.name == f"{CACHE_TAXID}.fasta"


class TestWithoutACacheTaxid:
    """An entry with no separate database id keeps the old behaviour."""

    def test_defaults_to_the_ncbi_taxid(self, manager):
        seen, fake = _capture_download(manager)
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with patch("subprocess.run", return_value=failed), \
             patch.object(manager, "_resolve_assembly_accession",
                          return_value="GCF_000005845.2"), \
             patch.object(manager, "_download_ncbi_genome", side_effect=fake), \
             patch("shutil.which", return_value="/usr/bin/datasets"):
            manager._download_ncbi_genome_by_taxid(562, "Escherichia coli")

        assert seen["taxid"] == 562
