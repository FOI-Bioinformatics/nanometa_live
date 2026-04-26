"""Tests for BundleManager hardening: checksum abort, disk space, version checks."""

import hashlib
import json
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    _check_version_compatibility,
    _extract_major_version,
    _file_md5,
    _resolve_builtin_watchlist_dir,
)


def _make_minimal_bundle(tmp_path, tamper_file=None):
    """Create a minimal valid bundle tar.gz for testing.

    Args:
        tmp_path: Directory to create the bundle in.
        tamper_file: If set, corrupt this relative path after checksumming.

    Returns:
        Tuple of (bundle_path, manifest).
    """
    staging = tmp_path / "staging"
    staging.mkdir()

    genomes = staging / "genomes"
    genomes.mkdir()
    genome_file = genomes / "12345.fasta"
    genome_file.write_text(">seq1\nATCG\n")

    checksums = {}
    for f in staging.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(staging))
            checksums[rel] = _file_md5(f)

    manifest = {
        "version": "1.1",
        "created": "2026-01-01T00:00:00",
        "creation_date": "2026-01-01 00:00",
        "creator": "test",
        "nanometa_home": str(tmp_path / "home"),
        "checksums": checksums,
        "tool_versions": {
            "nextflow": "nextflow version 23.10.1.5891",
            "kraken2": "Kraken version 2.1.3",
            "makeblastdb": "makeblastdb: 2.14.0+",
            "datasets": "not found",
        },
        "container_runtime": None,
    }

    # Tamper with a file after computing checksums
    if tamper_file:
        target = staging / tamper_file
        if target.exists():
            target.write_text("CORRUPTED DATA")

    manifest_path = staging / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    bundle_path = tmp_path / "test_bundle.tar.gz"
    with tarfile.open(str(bundle_path), "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(str(item), arcname=item.name)

    return bundle_path, manifest


class TestChecksumAbort:
    """Fix 1: Import should abort on checksum mismatch unless force=True."""

    def test_import_succeeds_with_valid_checksums(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(tmp_path)
        home = tmp_path / "import_home"
        home.mkdir()

        mgr = BundleManager()
        result = mgr.import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(home)
        )
        assert result["success"] is True

    def test_import_aborts_on_checksum_mismatch(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(
            tmp_path, tamper_file="genomes/12345.fasta"
        )
        home = tmp_path / "import_home"
        home.mkdir()

        mgr = BundleManager()
        result = mgr.import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(home)
        )
        assert result["success"] is False
        assert any("checksum" in w.lower() for w in result["warnings"])
        # The genomes directory should NOT have been copied
        assert not (home / "genomes").exists()

    def test_import_continues_with_force_on_mismatch(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(
            tmp_path, tamper_file="genomes/12345.fasta"
        )
        home = tmp_path / "import_home"
        home.mkdir()

        mgr = BundleManager()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(home),
            force=True,
        )
        assert result["success"] is True
        assert any("force=True" in w for w in result["warnings"])
        # Files should have been copied despite mismatch
        assert (home / "genomes").exists()

    def test_mismatch_warning_lists_files(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(
            tmp_path, tamper_file="genomes/12345.fasta"
        )
        home = tmp_path / "import_home"
        home.mkdir()

        mgr = BundleManager()
        result = mgr.import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(home)
        )
        warnings_text = " ".join(result["warnings"])
        assert "genomes/12345.fasta" in warnings_text


class TestVersionCompatibility:
    """Fix 3: Tool version validation on bundle import."""

    def test_extract_major_version_standard(self):
        assert _extract_major_version("23.10.1") == "23"

    def test_extract_major_version_with_prefix(self):
        assert _extract_major_version("nextflow version 23.10.1.5891") == "23"

    def test_extract_major_version_blast(self):
        assert _extract_major_version("makeblastdb: 2.14.0+") == "2"

    def test_extract_major_version_none(self):
        assert _extract_major_version("not found") is None
        assert _extract_major_version("unknown") is None

    def test_no_warnings_same_versions(self):
        bundle = {"nextflow": "23.10.1", "kraken2": "2.1.3"}
        local = {"nextflow": "23.04.0", "kraken2": "2.1.2"}
        warnings = _check_version_compatibility(bundle, local)
        assert warnings == []

    def test_warns_on_major_mismatch(self):
        bundle = {"nextflow": "23.10.1"}
        local = {"nextflow": "25.04.0"}
        warnings = _check_version_compatibility(bundle, local)
        assert len(warnings) == 1
        assert "nextflow" in warnings[0]
        assert "23" in warnings[0]
        assert "25" in warnings[0]

    def test_warns_on_missing_local_tool(self):
        bundle = {"kraken2": "2.1.3"}
        local = {"kraken2": "not found"}
        warnings = _check_version_compatibility(bundle, local)
        assert len(warnings) == 1
        assert "not found" in warnings[0]

    def test_skips_not_found_bundle_tool(self):
        bundle = {"datasets": "not found"}
        local = {"datasets": "16.0.0"}
        warnings = _check_version_compatibility(bundle, local)
        assert warnings == []

    def test_version_warnings_appear_in_import_result(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(tmp_path)
        home = tmp_path / "import_home"
        home.mkdir()

        # Mock _collect_tool_versions to return a major version mismatch
        mgr = BundleManager()
        with patch.object(
            mgr,
            "_collect_tool_versions",
            return_value={
                "nextflow": "25.04.0",
                "kraken2": "2.1.3",
                "makeblastdb": "2.14.0+",
                "datasets": "not found",
            },
        ):
            result = mgr.import_bundle(
                str(bundle_path), kraken_db_path="", nanometa_home=str(home)
            )
        assert result["success"] is True
        # Should have a warning about nextflow 23 vs 25
        assert any("nextflow" in w.lower() for w in result["warnings"])


class TestBuiltinWatchlistResolution:
    """GAP-2: Resolve built-in watchlist directory under editable installs.

    The previous implementation called ``Path(wl_pkg.__file__).parent`` on
    the namespace package, which raises TypeError because ``__file__`` is
    None for namespace packages produced by editable installs. The fix
    moves the lookup to ``importlib.resources.files`` with a fallback to
    the package's ``__path__`` entries.
    """

    def test_resolve_returns_existing_directory(self):
        """Resolution returns a directory containing watchlist YAMLs."""
        wl_dir = _resolve_builtin_watchlist_dir()
        assert wl_dir is not None
        assert wl_dir.is_dir()
        # The built-in watchlists ship with at least one YAML file.
        assert any(wl_dir.glob("*.yaml")), (
            f"Expected at least one *.yaml under {wl_dir}"
        )

    def test_resolve_handles_namespace_package_file_none(self):
        """Resolution works when wl_pkg.__file__ is None (editable install).

        Simulate the editable-install condition by importing the
        watchlists package and confirming its ``__file__`` is None on
        this checkout. The fix must still return a usable directory.
        """
        from nanometa_live.core.config.data import watchlists as wl_pkg

        # Sanity: this checkout is an editable install, so __file__ is None.
        # If a future package layout adds an __init__.py the assertion
        # changes shape but the resolver must still succeed.
        if wl_pkg.__file__ is not None:
            pytest.skip(
                "watchlists package is a regular package on this install; "
                "the namespace-package crash path cannot be exercised here."
            )

        wl_dir = _resolve_builtin_watchlist_dir()
        assert wl_dir is not None
        assert wl_dir.is_dir()

    def test_copy_builtin_watchlists_succeeds_on_editable_install(self, tmp_path):
        """End-to-end: BundleManager._copy_builtin_watchlists() does not raise.

        Before the fix, this call failed with TypeError on editable
        installs because ``Path(None).parent`` is invalid.
        """
        mgr = BundleManager()
        dst = tmp_path / "watchlists"
        # Should not raise.
        mgr._copy_builtin_watchlists(dst)
        # At least one YAML should be copied across.
        assert dst.exists()
        copied = list(dst.glob("*.yaml"))
        assert len(copied) > 0, (
            "Expected built-in watchlist YAMLs to be copied to the bundle"
        )

    def test_export_bundle_runs_under_editable_install(self, tmp_path):
        """End-to-end: full export_bundle() succeeds on an editable install."""
        home = tmp_path / "home"
        home.mkdir()
        # Create a tiny placeholder genome so export has something to walk.
        genomes = home / "genomes"
        genomes.mkdir()
        (genomes / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        config = {
            "kraken_db": "",  # skip db_hash branch
            "results_output_directory": str(tmp_path / "results"),
        }
        result_path = mgr.export_bundle(
            str(out), config=config, nanometa_home=str(home)
        )
        assert result_path == out
        assert out.exists() and out.stat().st_size > 0
        # Confirm the archive contains a watchlists/ entry.
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
        assert any(n.startswith("watchlists/") for n in names), (
            "export_bundle should embed built-in watchlists"
        )
