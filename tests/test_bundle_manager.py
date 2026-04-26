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


class TestWatchlistToggleStateRoundTrip:
    """GAP-3: per-entry enable/disable state must survive export and import.

    The watchlist_toggle_state.yaml file at ~/.nanometa records which
    individual pathogen entries the operator enabled. Without it the
    field machine sees default toggle state for every entry.
    """

    def _make_export_home(self, tmp_path, toggle_payload):
        home = tmp_path / "build_home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        toggle = home / "watchlist_toggle_state.yaml"
        toggle.write_text(toggle_payload)
        return home

    def test_toggle_state_round_trips(self, tmp_path):
        toggle_yaml = (
            "version: 1\n"
            "entries:\n"
            "  '1639': enabled\n"
            "  '562': disabled\n"
        )
        build_home = self._make_export_home(tmp_path, toggle_yaml)
        bundle_path = tmp_path / "bundle.tar.gz"

        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle_path),
            config={"kraken_db": "", "results_output_directory": str(tmp_path / "results")},
            nanometa_home=str(build_home),
        )

        # Confirm the bundle archive carries the file at the top level.
        with tarfile.open(str(bundle_path), "r:gz") as tar:
            names = tar.getnames()
        assert "watchlist_toggle_state.yaml" in names

        # Import on a fresh field-machine home and verify content.
        field_home = tmp_path / "field_home"
        field_home.mkdir()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(field_home),
        )
        assert result["success"] is True
        restored = field_home / "watchlist_toggle_state.yaml"
        assert restored.exists(), (
            "import_bundle must restore watchlist_toggle_state.yaml"
        )
        assert restored.read_text() == toggle_yaml

    def test_import_silently_tolerates_missing_toggle_state(self, tmp_path):
        """Older bundles do not carry this file -- import must not warn or fail."""
        bundle_path, _ = _make_minimal_bundle(tmp_path)
        field_home = tmp_path / "field_home"
        field_home.mkdir()

        mgr = BundleManager()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(field_home),
        )
        assert result["success"] is True
        assert not (field_home / "watchlist_toggle_state.yaml").exists()


class TestReadmeFieldGuidance:
    """GAP-5/GAP-7: README must surface conda-unpack and NXF_CONDA_CACHEDIR.

    These two pieces of operator guidance were missing from the bundle's
    README, leading to a confusing first-time setup on the field machine.
    """

    def test_export_bundle_readme_documents_conda_unpack(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(out),
            config={"kraken_db": "", "results_output_directory": str(tmp_path)},
            nanometa_home=str(home),
        )

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("README_FIELD.md") as fh:
                readme = fh.read().decode("utf-8")

        # GAP-5: conda-unpack invocation should reference the extracted
        # binary path, not "conda run -n nf-core conda-unpack".
        assert "bin/conda-unpack" in readme
        assert "conda run -n nf-core conda-unpack" not in readme

    def test_export_bundle_readme_documents_nxf_conda_cachedir(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(out),
            config={"kraken_db": "", "results_output_directory": str(tmp_path)},
            nanometa_home=str(home),
        )

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("README_FIELD.md") as fh:
                readme = fh.read().decode("utf-8")

        # GAP-7: NXF_CONDA_CACHEDIR must be documented.
        assert "NXF_CONDA_CACHEDIR" in readme


class TestBuildOnlyToolWarnings:
    """GAP-6: warnings for build-only tools should be informational, not errors.

    conda-pack and NCBI datasets are only used during bundle preparation
    on the build machine. Their absence on the field machine is expected
    and should not be flagged as a missing runtime dependency.
    """

    def test_conda_pack_missing_locally_is_informational(self):
        bundle = {"conda-pack": "0.7.1", "nextflow": "25.10.4"}
        local = {"conda-pack": "not found", "nextflow": "25.10.4"}
        warnings = _check_version_compatibility(bundle, local)
        # Exactly one warning, and it should be marked informational.
        conda_pack_warnings = [w for w in warnings if "conda-pack" in w]
        assert len(conda_pack_warnings) == 1
        msg = conda_pack_warnings[0].lower()
        assert "build-only" in msg or "expected" in msg
        # The legacy phrasing must not surface for build-only tools.
        assert "was 0.7.1 in bundle but is not found locally" not in conda_pack_warnings[0]

    def test_datasets_missing_locally_is_informational(self):
        bundle = {"datasets": "16.0.0"}
        local = {"datasets": "not found"}
        warnings = _check_version_compatibility(bundle, local)
        assert len(warnings) == 1
        assert "datasets" in warnings[0]
        msg = warnings[0].lower()
        assert "build-only" in msg or "expected" in msg

    def test_runtime_tool_missing_locally_still_warns_strongly(self):
        bundle = {"kraken2": "2.1.3"}
        local = {"kraken2": "not found"}
        warnings = _check_version_compatibility(bundle, local)
        # Runtime tools must keep the original strict warning shape.
        assert len(warnings) == 1
        assert "kraken2" in warnings[0]
        assert "build-only" not in warnings[0].lower()
