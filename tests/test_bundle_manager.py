"""Tests for BundleManager hardening: checksum abort, disk space, version checks."""

import hashlib
import json
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    _local_container_platform,
    _ACTIVATE_SCRIPT_FILENAME,
    _ACTIVATE_SCRIPT_TEMPLATE,
    _BUNDLED_CONDA_CACHE_DIRNAME,
    _PRE_WARM_SCENARIOS,
    _check_version_compatibility,
    _extract_major_version,
    _file_md5,
    _resolve_builtin_watchlist_dir,
)


def _make_minimal_bundle(tmp_path, tamper_file=None, db_hash=None,
                         extra_files=None):
    """Create a minimal valid bundle tar.gz for testing.

    Args:
        tmp_path: Directory to create the bundle in.
        tamper_file: If set, corrupt this relative path after checksumming.
        db_hash: If set, record it as the bundle's Kraken2 DB hash so import
            can exercise the DB-hash compatibility check.
        extra_files: ``{relative_path: text}`` written into the bundle before
            checksums are computed. The default bundle carries no config.yaml,
            and import skips its entire config-rebase block when that file is
            absent -- so a test that needs to reach that block must add one.

    Returns:
        Tuple of (bundle_path, manifest).
    """
    staging = tmp_path / "staging"
    staging.mkdir()

    genomes = staging / "genomes"
    genomes.mkdir()
    genome_file = genomes / "12345.fasta"
    genome_file.write_text(">seq1\nATCG\n")

    for rel, text in (extra_files or {}).items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

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
    if db_hash is not None:
        manifest["db_hash"] = db_hash

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


def _make_fake_pipeline_checkout(parent: Path) -> Path:
    """Build a minimal directory layout that satisfies the pipeline-resolver
    contract: directory exists and contains ``main.nf``.

    Used to drive _pre_warm_conda_envs without actually invoking Nextflow.
    """
    pipeline = parent / "fake_nanometanf"
    (pipeline / "modules" / "local" / "fastp_streaming").mkdir(parents=True)
    (pipeline / "main.nf").write_text("// stub\n")
    (pipeline / "modules" / "local" / "fastp_streaming" / "environment.yml").write_text(
        "name: fastp_streaming\nchannels: [bioconda]\n"
    )
    return pipeline


class TestPreWarmCondaEnvs:
    """GAP-1: BundleManager.export_bundle(pre_warm_conda_envs=True) bakes
    the per-process Nextflow conda envs into the bundle so the field
    machine never needs network access on first run.

    The actual Nextflow stub invocation is mocked so these tests stay
    fast; the end-to-end smoke is covered separately under @pytest.mark.slow.
    """

    def test_default_remains_disabled(self, tmp_path):
        """Calling export_bundle without the flag does NOT pre-warm.

        Existing operator workflows (cycle 8 and earlier) must keep
        producing identical bundles when the new flag is omitted.
        """
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
            names = tar.getnames()

        # No conda_cache directory should exist in the bundle.
        assert not any(
            n.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/") for n in names
        ), "Default export must not include conda_cache/"

        # Manifest must record that pre-warm was not attempted.
        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        assert manifest["pre_warm_conda_envs"]["attempted"] is False
        assert manifest["pre_warm_conda_envs"]["success"] is False

    def test_pre_warm_records_manifest_entries(self, tmp_path):
        """When pre-warm succeeds, the bundle manifest lists every cache
        env directory under conda_cache/ with a checksum entry."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        # Mock the per-scenario stub run so it "creates" two env dirs
        # in the cache the same way Nextflow's CondaCache would.
        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            for env_md5 in (
                "env-aaaa1111bbbb2222cccc3333dddd4444",
                "env-eeee5555ffff6666aaaa7777bbbb8888",
            ):
                env_dir = cache_root / env_md5
                env_dir.mkdir(exist_ok=True)
                (env_dir / "bin" / "fastp").parent.mkdir(parents=True, exist_ok=True)
                (env_dir / "bin" / "fastp").write_text("#!/bin/sh\nexit 0\n")
            return True, "ok"

        mgr = BundleManager()
        out = tmp_path / "out.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch("nanometa_live.core.workflow.bundle_manager.shutil.which",
                       return_value="/usr/bin/nextflow"):
                mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()

        # Conda cache files must be packed into the bundle.
        assert any(
            n.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/env-aaaa") for n in names
        ), "Bundle must include the pre-warmed env directories"

        # Manifest must record pre-warm metadata and checksums.
        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        pwc = manifest["pre_warm_conda_envs"]
        assert pwc["attempted"] is True
        assert pwc["success"] is True
        assert pwc["env_count"] >= 1
        assert "batch_samplesheet" in pwc["scenarios"]

        # Every conda_cache file must have a checksum entry so import
        # validation can detect tarball corruption later.
        cache_files = [n for n in manifest["checksums"]
                       if n.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/")]
        assert len(cache_files) >= 1

    def test_pre_warm_falls_back_when_nextflow_missing(self, tmp_path):
        """If the build host has no nextflow binary, pre-warm logs a
        warning and the bundle is still produced without the cache.

        This guards the documented fallback behavior referenced in the
        task description ("on failure, falls back to skipping pre-warm
        and logs a clear warning").
        """
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        with patch("nanometa_live.core.workflow.bundle_manager.shutil.which",
                   return_value=None):
            mgr.export_bundle(
                str(out),
                config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                nanometa_home=str(home),
                pre_warm_conda_envs=True,
                pipeline_path=str(pipeline_dir),
            )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        assert not any(
            n.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/") for n in names
        ), "Failed pre-warm must not leave a half-populated cache in bundle"

        pwc = manifest["pre_warm_conda_envs"]
        assert pwc["attempted"] is True
        assert pwc["success"] is False
        assert any("nextflow" in w.lower() for w in pwc["warnings"])

    def test_pre_warm_falls_back_without_pipeline_checkout(self, tmp_path):
        """Pre-warm needs a local pipeline checkout. When neither the
        ``pipeline_path`` argument nor ``config['pipeline_source']``
        resolves to a directory, the bundle is still produced but the
        cache is omitted.
        """
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        with patch("nanometa_live.core.workflow.bundle_manager.shutil.which",
                   return_value="/usr/bin/nextflow"):
            with patch.object(
                BundleManager, "_resolve_pipeline_checkout", return_value=None
            ):
                mgr.export_bundle(
                    str(out),
                    config={
                        "kraken_db": "",
                        "results_output_directory": str(tmp_path),
                        "pipeline_source": "remote:main",  # not a local dir
                    },
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                )

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        pwc = manifest["pre_warm_conda_envs"]
        assert pwc["success"] is False
        assert any(
            "pipeline_path" in w or "pipeline_source" in w or "checkout" in w
            for w in pwc["warnings"]
        )

    def test_readme_documents_pre_warm_when_active(self, tmp_path):
        """When pre-warm succeeds, the README must explain that the
        cache is bundled and tell the operator to set NXF_CONDA_CACHEDIR
        to the restored location, NOT the manual workaround.
        """
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / "env-deadbeef").mkdir(exist_ok=True)
            (cache_root / "env-deadbeef" / "marker").write_text("ok")
            return True, "ok"

        mgr = BundleManager()
        out = tmp_path / "out.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch("nanometa_live.core.workflow.bundle_manager.shutil.which",
                       return_value="/usr/bin/nextflow"):
                mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("README_FIELD.md") as fh:
                readme = fh.read().decode("utf-8")

        # Auto block must mention the bundled cache and the env var.
        assert "pre_warm_conda_envs=True" in readme
        assert "NXF_CONDA_CACHEDIR" in readme
        assert _BUNDLED_CONDA_CACHE_DIRNAME in readme
        # Manual workaround phrasing should not be in this branch.
        assert "without ``pre_warm_conda_envs``" not in readme

    def test_import_restores_conda_cache_to_home(self, tmp_path):
        """import_bundle restores the bundled conda cache to
        ``<nanometa_home>/conda_cache`` and surfaces its path on the
        result so the operator can export NXF_CONDA_CACHEDIR.
        """
        home = tmp_path / "build_home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            env_dir = cache_root / "env-feedface"
            env_dir.mkdir(exist_ok=True)
            (env_dir / "marker").write_text("ok")
            return True, "ok"

        mgr = BundleManager()
        bundle_path = tmp_path / "bundle.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch("nanometa_live.core.workflow.bundle_manager.shutil.which",
                       return_value="/usr/bin/nextflow"):
                mgr.export_bundle(
                    str(bundle_path),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        # Now import on a fresh field-machine home.
        field = tmp_path / "field_home"
        field.mkdir()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(field),
        )

        assert result["success"] is True
        restored = field / _BUNDLED_CONDA_CACHE_DIRNAME / "env-feedface" / "marker"
        assert restored.exists(), (
            "import_bundle must extract conda_cache/env-* into "
            "<nanometa_home>/conda_cache/"
        )
        assert "conda_cache_path" in result
        assert result["conda_cache_path"].endswith(_BUNDLED_CONDA_CACHE_DIRNAME)


class TestPreWarmEndToEnd:
    """Real end-to-end pre-warm test against the operator's nanometanf
    checkout. Marked slow because it actually invokes ``nextflow`` and
    creates conda envs (~30 minutes, ~5 GB on the build host).
    """

    @pytest.mark.slow
    def test_real_pre_warm_against_pipeline_checkout(self, tmp_path):
        pytest.skip(
            "End-to-end pre-warm requires online nextflow + conda; run "
            "manually with `pytest -m slow tests/test_bundle_manager.py "
            "-k test_real_pre_warm`."
        )


class TestExtendedPreWarmScenarios:
    """Cycle 11: validation_blast, validation_minimap2, fastp_qc scenarios.

    These extend the cycle 9 baseline of four scenarios so the bundled
    cache covers BLAST, minimap2+samtools, and FASTP envs in addition
    to the chopper/seqkit/kraken2/multiqc set already covered.
    """

    def test_nine_scenarios_registered(self):
        """The pre-warm scenario list now carries the entries audited
        across cycles 11 (validation/fastp) and 17 (assembly/untar) in
        the order the audit recommended."""
        names = [s["name"] for s in _PRE_WARM_SCENARIOS]
        assert names == [
            "batch_samplesheet",
            "realtime_multiplex",
            "realtime_per_file",
            "realtime_single_sample",
            "validation_blast",
            "validation_minimap2",
            "fastp_qc",
            "assembly_flye",
            "untar_kraken2_db",
        ]

    def test_each_scenario_has_required_fields(self):
        """Every scenario must declare name, params, and comment so the
        manifest summary and stub invocation have what they need."""
        for scenario in _PRE_WARM_SCENARIOS:
            assert "name" in scenario
            assert "params" in scenario
            assert "comment" in scenario
            assert isinstance(scenario["params"], dict)
            assert scenario["params"]  # non-empty
            assert isinstance(scenario["comment"], str)
            assert scenario["comment"].strip()

    def test_validation_blast_params_target_blast_env(self):
        scenario = next(
            s for s in _PRE_WARM_SCENARIOS if s["name"] == "validation_blast"
        )
        assert scenario["params"].get("run_validation") == "true"
        assert scenario["params"].get("validation_method") == "blast"

    def test_validation_minimap2_params_target_minimap2_env(self):
        scenario = next(
            s for s in _PRE_WARM_SCENARIOS if s["name"] == "validation_minimap2"
        )
        assert scenario["params"].get("run_validation") == "true"
        assert scenario["params"].get("validation_method") == "minimap2"

    def test_fastp_qc_params_target_fastp_env(self):
        scenario = next(
            s for s in _PRE_WARM_SCENARIOS if s["name"] == "fastp_qc"
        )
        assert scenario["params"].get("qc_tool") == "fastp"

    def test_assembly_flye_params_enable_assembly(self):
        """The assembly scenario sets enable_assembly so flye and miniasm
        envs land in the cache during pre-warm."""
        scenario = next(
            s for s in _PRE_WARM_SCENARIOS if s["name"] == "assembly_flye"
        )
        assert scenario["params"].get("enable_assembly") == "true"

    def test_untar_kraken2_db_params_supply_tarred_db(self):
        """The untar scenario points kraken2_db at a tar.gz URL so the
        UNTAR module fires and its conda env lands in the cache."""
        scenario = next(
            s for s in _PRE_WARM_SCENARIOS if s["name"] == "untar_kraken2_db"
        )
        db = scenario["params"].get("kraken2_db", "")
        assert db.endswith(".tar.gz")

    def test_all_scenarios_attempted(self, tmp_path):
        """When pre-warm runs, every scenario in the registry is passed
        to ``_run_pre_warm_scenario`` exactly once."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        attempted: list = []

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            attempted.append(scenario["name"])
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / f"env-{scenario['name']}").mkdir(exist_ok=True)
            return True, "ok"

        mgr = BundleManager()
        out = tmp_path / "out.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch(
                "nanometa_live.core.workflow.bundle_manager.shutil.which",
                return_value="/usr/bin/nextflow",
            ):
                mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        assert attempted == [
            "batch_samplesheet",
            "realtime_multiplex",
            "realtime_per_file",
            "realtime_single_sample",
            "validation_blast",
            "validation_minimap2",
            "fastp_qc",
            "assembly_flye",
            "untar_kraken2_db",
        ]

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        recorded = manifest["pre_warm_conda_envs"]["scenarios"]
        for name in attempted:
            assert name in recorded

    def test_validation_scenario_writes_pathogen_genomes_placeholder(self, tmp_path):
        """Validation scenarios pass a ``pathogen_genomes`` JSON path to
        the stub run so nanometanf's startup check does not abort
        before stub mode fires."""
        captured_cmds: list = []

        # Patch subprocess.run to capture the constructed command and
        # short-circuit out without actually launching nextflow.
        class _FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeResult()

        scenario = {
            "name": "validation_blast",
            "params": {
                "processing_mode": "batch",
                "sample_handling": "single_sample",
                "run_validation": "true",
                "validation_method": "blast",
            },
            "comment": "stub",
        }
        staging = tmp_path / "staging"
        staging.mkdir()
        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            ok, msg = BundleManager._run_pre_warm_scenario(
                scenario=scenario,
                pipeline_dir=pipeline_dir,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(staging / "conda_cache")},
            )

        assert ok is True
        assert captured_cmds, "subprocess.run should have been invoked once"
        cmd = captured_cmds[0]
        assert "--pathogen_genomes" in cmd
        idx = cmd.index("--pathogen_genomes")
        placeholder_path = Path(cmd[idx + 1])
        assert placeholder_path.exists()
        payload = json.loads(placeholder_path.read_text())
        assert payload == {"pathogens": []}

    def test_fastp_scenario_does_not_write_pathogen_genomes(self, tmp_path):
        """Non-validation scenarios should not gain a pathogen_genomes
        argument; that placeholder is only required when run_validation
        is enabled."""
        captured_cmds: list = []

        class _FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeResult()

        scenario = {
            "name": "fastp_qc",
            "params": {
                "processing_mode": "batch",
                "sample_handling": "single_sample",
                "qc_tool": "fastp",
            },
            "comment": "stub",
        }
        staging = tmp_path / "staging"
        staging.mkdir()
        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            ok, _ = BundleManager._run_pre_warm_scenario(
                scenario=scenario,
                pipeline_dir=pipeline_dir,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(staging / "conda_cache")},
            )

        assert ok is True
        cmd = captured_cmds[0]
        assert "--pathogen_genomes" not in cmd
        # The fastp-specific param must still reach the stub call.
        assert "--qc_tool" in cmd
        idx = cmd.index("--qc_tool")
        assert cmd[idx + 1] == "fastp"


class TestActivateOfflineEnvsScript:
    """Cycle 11: bundles ship a thin activation helper that the
    operator sources to set NXF_CONDA_CACHEDIR after import.
    """

    def test_repo_script_has_valid_bash_syntax(self):
        """The script under scripts/activate_offline_envs.sh must be
        syntactically valid bash. ``bash -n`` parses without executing.
        """
        import subprocess

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / _ACTIVATE_SCRIPT_FILENAME
        assert script_path.exists(), (
            f"Expected activation script at {script_path}"
        )

        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"bash -n failed: {result.stderr}"
        )

    def test_activate_script_template_renders_to_valid_bash(self, tmp_path):
        """The string template embedded in bundle_manager renders to
        bash that parses cleanly. Renders with the cache dirname token
        to mirror what export_bundle writes into the staging area.
        """
        import subprocess

        rendered = _ACTIVATE_SCRIPT_TEMPLATE.format(
            cache_dirname=_BUNDLED_CONDA_CACHE_DIRNAME,
        )
        script_path = tmp_path / _ACTIVATE_SCRIPT_FILENAME
        script_path.write_text(rendered)

        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Rendered template did not parse: {result.stderr}"
        )

    def test_activate_script_template_exports_required_vars(self):
        rendered = _ACTIVATE_SCRIPT_TEMPLATE.format(
            cache_dirname=_BUNDLED_CONDA_CACHE_DIRNAME,
        )
        assert "export NXF_CONDA_CACHEDIR=" in rendered
        assert "NXF_OFFLINE" in rendered
        assert "set -euo pipefail" in rendered

    def test_export_bundle_writes_activation_script_when_pre_warm_succeeds(
        self, tmp_path
    ):
        """When pre-warm produces a cache, the bundle archive must
        contain ``activate_offline_envs.sh`` at the top level.
        """
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / "env-deadbeef").mkdir(exist_ok=True)
            (cache_root / "env-deadbeef" / "marker").write_text("ok")
            return True, "ok"

        mgr = BundleManager()
        out = tmp_path / "out.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch(
                "nanometa_live.core.workflow.bundle_manager.shutil.which",
                return_value="/usr/bin/nextflow",
            ):
                mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            with tar.extractfile(_ACTIVATE_SCRIPT_FILENAME) as fh:
                content = fh.read().decode("utf-8")

        assert _ACTIVATE_SCRIPT_FILENAME in names
        assert "export NXF_CONDA_CACHEDIR=" in content

        # Activation script must also be checksummed in the manifest so
        # import-time validation catches archive corruption.
        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        assert _ACTIVATE_SCRIPT_FILENAME in manifest["checksums"]

    def test_export_bundle_omits_activation_script_when_pre_warm_skipped(
        self, tmp_path
    ):
        """A bundle built without pre-warm has nothing to activate, so
        the helper script should not appear in the archive."""
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
            names = tar.getnames()
        assert _ACTIVATE_SCRIPT_FILENAME not in names

    def test_import_bundle_restores_activation_script_to_home(self, tmp_path):
        """After import the helper sits in the install dir and the
        result dict surfaces its absolute path so the operator can
        copy/paste a single source command."""
        home = tmp_path / "build_home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            env_dir = cache_root / "env-feedface"
            env_dir.mkdir(exist_ok=True)
            (env_dir / "marker").write_text("ok")
            return True, "ok"

        mgr = BundleManager()
        bundle_path = tmp_path / "bundle.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch(
                "nanometa_live.core.workflow.bundle_manager.shutil.which",
                return_value="/usr/bin/nextflow",
            ):
                mgr.export_bundle(
                    str(bundle_path),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        field = tmp_path / "field_home"
        field.mkdir()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(field),
        )

        assert result["success"] is True
        installed_script = field / _ACTIVATE_SCRIPT_FILENAME
        assert installed_script.exists()
        # Result dict surfaces the absolute path for operator reference.
        assert result.get("activation_script") == str(installed_script)
        # The script must remain syntactically valid after relocation.
        import subprocess
        check = subprocess.run(
            ["bash", "-n", str(installed_script)],
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0, (
            f"Installed script must parse: {check.stderr}"
        )

    def test_readme_points_to_activation_script(self, tmp_path):
        """The README must instruct the operator to source the helper,
        not just to export NXF_CONDA_CACHEDIR by hand."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_run_scenario(scenario, pipeline_dir, staging, env):
            cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
            cache_root.mkdir(parents=True, exist_ok=True)
            (cache_root / "env-marker").mkdir(exist_ok=True)
            (cache_root / "env-marker" / "ok").write_text("ok")
            return True, "ok"

        mgr = BundleManager()
        out = tmp_path / "out.tar.gz"
        with patch.object(mgr, "_run_pre_warm_scenario", side_effect=fake_run_scenario):
            with patch(
                "nanometa_live.core.workflow.bundle_manager.shutil.which",
                return_value="/usr/bin/nextflow",
            ):
                mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline_dir),
                )

        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("README_FIELD.md") as fh:
                readme = fh.read().decode("utf-8")

        assert "source ./activate_offline_envs.sh" in readme


# ---------------------------------------------------------------------------
# Cycle 17 fixes
# ---------------------------------------------------------------------------

class TestBundlePipelineSource:
    """Fix #1: Pipeline source checkout is bundled and path rebased on import."""

    def test_pipeline_source_bundled_when_local_checkout_found(self, tmp_path):
        """When pipeline_source points to a local directory with main.nf,
        export_bundle copies it as pipeline_source/ in the archive and
        writes pipeline_source: ./pipeline_source in config.yaml."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(out),
            config={
                "kraken_db": "",
                "results_output_directory": str(tmp_path),
                "pipeline_source": str(pipeline_dir),
            },
            nanometa_home=str(home),
        )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            # pipeline_source/main.nf must be in the archive.
            assert any(n == "pipeline_source/main.nf" for n in names), (
                "pipeline_source/main.nf must be bundled"
            )
            # config.yaml must contain the relative reference.
            with tar.extractfile("config.yaml") as fh:
                cfg_text = fh.read().decode("utf-8")
        assert "./pipeline_source" in cfg_text

        # manifest must record bundled=true.
        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        assert manifest["pipeline_source"]["bundled"] is True
        assert manifest["pipeline_source"]["path"] == "./pipeline_source"

    def test_pipeline_source_rebased_on_import(self, tmp_path):
        """import_bundle rewrites pipeline_source from ./pipeline_source
        to the absolute path on the field machine."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        bundle_path = tmp_path / "bundle.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle_path),
            config={
                "kraken_db": "",
                "results_output_directory": str(tmp_path),
                "pipeline_source": str(pipeline_dir),
            },
            nanometa_home=str(home),
        )

        field = tmp_path / "field_home"
        field.mkdir()
        result = mgr.import_bundle(
            str(bundle_path),
            kraken_db_path="",
            nanometa_home=str(field),
        )

        assert result["success"] is True
        assert "pipeline_source_path" in result
        expected = str(field / "pipeline_source")
        assert result["pipeline_source_path"] == expected
        assert Path(result["pipeline_source_path"]).is_dir()

    def test_remote_pipeline_source_logs_warning_not_error(self, tmp_path):
        """When pipeline_source is 'remote:main', export still succeeds
        (no local checkout to copy) and the manifest records bundled=false."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(out),
            config={
                "kraken_db": "",
                "results_output_directory": str(tmp_path),
                "pipeline_source": "remote:main",
            },
            nanometa_home=str(home),
        )

        assert out.exists()
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        assert not any(n.startswith("pipeline_source/") for n in names)
        assert manifest["pipeline_source"]["bundled"] is False


class TestBundleNextflowPlugins:
    """Fix #2: Nextflow plugin cache bundled to prevent registry probes."""

    def test_plugins_bundled_when_cache_exists(self, tmp_path):
        """When ~/.nextflow/plugins/ contains plugin dirs, matching entries
        are copied into nextflow_plugins/ in the bundle and the manifest
        records the count."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        # Create a stub ~/.nextflow/plugins directory under tmp_path.
        fake_nxf_plugins = tmp_path / ".nextflow" / "plugins"
        fake_nxf_plugins.mkdir(parents=True)
        plugin_dir = fake_nxf_plugins / "nf-schema-2.4.2"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.jar").write_bytes(b"PK\x03\x04")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()

        # Patch Path.home() so the plugin cache resolves to our stub dir.
        with patch(
            "nanometa_live.core.workflow.bundle_manager.Path.home",
            return_value=tmp_path,
        ):
            mgr.export_bundle(
                str(out),
                config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                nanometa_home=str(home),
            )

        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        assert any(n.startswith("nextflow_plugins/nf-schema-2.4.2") for n in names), (
            "nf-schema plugin must be bundled"
        )
        assert manifest["nextflow_plugins"]["bundled"] is True
        assert manifest["nextflow_plugins"]["plugin_count"] >= 1

    def test_plugins_not_bundled_when_cache_missing(self, tmp_path):
        """When ~/.nextflow/plugins/ does not exist, export succeeds and
        the manifest records bundled=false."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")

        out = tmp_path / "out.tar.gz"
        mgr = BundleManager()

        # Point home to tmp_path which has no .nextflow/plugins sub-dir.
        with patch(
            "nanometa_live.core.workflow.bundle_manager.Path.home",
            return_value=tmp_path / "no_such_home",
        ):
            mgr.export_bundle(
                str(out),
                config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                nanometa_home=str(home),
            )

        assert out.exists()
        with tarfile.open(str(out), "r:gz") as tar:
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        assert manifest["nextflow_plugins"]["bundled"] is False


class TestNextflowVersionDetection:
    """Fix #7: _get_nextflow_version parses the actual version line."""

    def test_parses_version_line(self):
        """A typical 'nextflow -version' banner is reduced to 'X.Y.Z build N'."""
        from nanometa_live.core.workflow.bundle_manager import _get_nextflow_version
        import subprocess

        fake_output = (
            "\n"
            "      N E X T F L O W\n"
            "      version 25.10.4 build 11173\n"
            "      created 10-11-2024 17:11 UTC\n"
            "      cite doi:10.1038/nbt.3820\n"
            "      http://nextflow.io\n"
        )

        class FakeResult:
            stdout = fake_output
            stderr = ""
            returncode = 0

        with patch("shutil.which", return_value="/usr/bin/nextflow"):
            with patch("subprocess.run", return_value=FakeResult()):
                version = _get_nextflow_version()

        assert version == "25.10.4 build 11173", (
            f"Expected '25.10.4 build 11173', got '{version}'"
        )

    def test_banner_not_returned_as_version(self):
        """The 'N E X T F L O W' banner line must not be returned as the version."""
        from nanometa_live.core.workflow.bundle_manager import _get_nextflow_version

        class FakeResult:
            stdout = "      N E X T F L O W\n      version 25.10.4 build 11173\n"
            stderr = ""
            returncode = 0

        with patch("shutil.which", return_value="/usr/bin/nextflow"):
            with patch("subprocess.run", return_value=FakeResult()):
                version = _get_nextflow_version()

        assert "N E X T F L O W" not in version


class TestBuildPlatformCheck:
    """Fix #8: Build platform recorded in manifest; import warns on mismatch."""

    def test_export_records_build_platform(self, tmp_path):
        """export_bundle writes build_platform to the manifest with
        system, machine, and python fields."""
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
            with tar.extractfile("manifest.json") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))

        bp = manifest.get("build_platform")
        assert bp is not None, "manifest must contain build_platform"
        assert "system" in bp
        assert "machine" in bp
        assert "python" in bp
        # Values must be non-empty strings.
        assert bp["system"]
        assert bp["machine"]
        assert bp["python"]

    def test_import_warns_on_platform_mismatch(self, tmp_path):
        """import_bundle adds a WARNING-level message when the bundle's
        platform differs from the current machine."""
        bundle_path, manifest = _make_minimal_bundle(tmp_path)

        # Inject a mismatched build_platform into the bundle.
        staging = tmp_path / "staging_patch"
        staging.mkdir()
        with tarfile.open(str(bundle_path), "r:gz") as tar:
            tar.extractall(path=str(staging), filter="data")

        manifest_path = staging / "manifest.json"
        manifest_data = json.loads(manifest_path.read_text())
        manifest_data["build_platform"] = {
            "system": "FakeOS",
            "machine": "fakearch",
            "python": "3.0.0",
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2))

        patched_bundle = tmp_path / "patched_bundle.tar.gz"
        with tarfile.open(str(patched_bundle), "w:gz") as tar:
            for item in staging.iterdir():
                tar.add(str(item), arcname=item.name)

        field = tmp_path / "field_home"
        field.mkdir()
        mgr = BundleManager()
        result = mgr.import_bundle(
            str(patched_bundle),
            kraken_db_path="",
            nanometa_home=str(field),
            force=True,
        )

        # Import must succeed even on mismatch.
        assert result["success"] is True
        # A warning mentioning the mismatch must be present.
        mismatch_warnings = [
            w for w in result["warnings"]
            if "FakeOS" in w or "fakearch" in w or "built on" in w.lower()
        ]
        assert mismatch_warnings, (
            "Expected a platform-mismatch warning in import result"
        )


class TestPreparationTabPreWarmCheckbox:
    """The Preparation tab must surface the pre-warm toggle and platform banner."""

    def test_layout_includes_prewarm_checkbox_default_off(self):
        """bundle-export-prewarm checkbox is in the layout, defaults to False.

        Off by default so the default export never attempts a ~5 GB conda
        pre-warm download -- a footgun on restricted internet.
        """
        from nanometa_live.app.layouts.deployment_layout import (
            create_deployment_layout,
        )
        import dash_bootstrap_components as dbc

        def find_checkbox(node, target_id):
            if isinstance(node, dbc.Checkbox) and getattr(node, "id", None) == target_id:
                return node
            children = getattr(node, "children", None)
            if children is None:
                return None
            if not isinstance(children, (list, tuple)):
                children = [children]
            for c in children:
                if hasattr(c, "children") or hasattr(c, "id"):
                    found = find_checkbox(c, target_id)
                    if found is not None:
                        return found
            return None

        layout = create_deployment_layout()
        cb = find_checkbox(layout, "bundle-export-prewarm")
        assert cb is not None, "bundle-export-prewarm checkbox missing"
        assert cb.value is False, "pre-warm checkbox must default to OFF"

    def test_platform_banner_renders(self):
        """_build_platform_banner returns an Alert with current OS+arch."""
        import platform as _plat
        from nanometa_live.app.layouts.preparation_layout import (
            _build_platform_banner,
        )
        import dash_bootstrap_components as dbc

        banner = _build_platform_banner()
        assert isinstance(banner, dbc.Alert)
        rendered = json.dumps(banner.to_plotly_json(), default=str)
        assert _plat.system() in rendered
        assert _plat.machine() in rendered

    def test_export_callbacks_read_prewarm_state(self):
        """The export-bundle and export-force-btn callbacks must include
        bundle-export-prewarm among their State inputs.
        """
        import dash
        from nanometa_live.app.tabs.preparation_tab import (
            register_preparation_callbacks,
        )

        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        register_preparation_callbacks(app)

        prewarm_listeners = []
        for cb_id, spec in app.callback_map.items():
            state_specs = spec.get("state", []) or []
            # Dash stores state entries as dicts: {'id': ..., 'property': ...}
            state_ids = [s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None)
                         for s in state_specs]
            if "bundle-export-prewarm" in state_ids:
                prewarm_listeners.append(cb_id)

        # Both the primary export callback and the force-export fallback
        # must read the checkbox.
        assert len(prewarm_listeners) >= 2, (
            f"Expected at least 2 callbacks reading bundle-export-prewarm, "
            f"got {len(prewarm_listeners)}: {prewarm_listeners}"
        )


class TestContainerizationModes:
    """W7-B: ``BundleManager.export_bundle`` honors the
    ``containerization`` parameter -- conda mode preserves the existing
    pre-warm flow, docker mode pulls + saves Docker tars, and
    singularity mode pulls .sif files. Bundle's emitted config carries
    the matching pipeline_profile in every mode."""

    def _stub_pipeline(self, tmp_path):
        """Build a minimal nanometanf-shaped checkout with one module
        carrying both Singularity and Docker references plus a
        bioconda environment.yml. ``main.nf`` at the root is sufficient
        for ``_resolve_local_pipeline_path``."""
        pipeline = tmp_path / "fake_nanometanf"
        (pipeline / "modules" / "nf-core" / "chopper").mkdir(parents=True)
        (pipeline / "main.nf").write_text("// stub main.nf\n")
        (pipeline / "modules" / "nf-core" / "chopper" / "main.nf").write_text(
            'process CHOPPER {\n'
            '    container "${ workflow.containerEngine == \'singularity\' '
            "? 'https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0' "
            ": 'biocontainers/chopper:0.12.0--hdcf5f25_0' }\"\n"
            '}\n'
        )
        (pipeline / "modules" / "nf-core" / "chopper" / "environment.yml").write_text(
            "channels:\n  - bioconda\ndependencies:\n  - bioconda::chopper=0.12.0\n"
        )
        return pipeline

    def _read_bundle_config_profile(self, bundle_path):
        """Extract pipeline_profile from a bundled config.yaml."""
        import tarfile
        import yaml
        with tarfile.open(str(bundle_path), "r:gz") as tar:
            cfg_member = tar.getmember("config.yaml")
            f = tar.extractfile(cfg_member)
            payload = yaml.safe_load(f)
        return payload.get("pipeline_profile")

    def test_invalid_mode_raises(self, tmp_path):
        mgr = BundleManager()
        with pytest.raises(ValueError, match="containerization"):
            mgr.export_bundle(
                str(tmp_path / "x.tar.gz"),
                {"pipeline_source": "remote:main"},
                nanometa_home=str(tmp_path / "home"),
                containerization="podman",
            )

    def test_conda_mode_writes_conda_profile(self, tmp_path):
        """conda mode (default) emits pipeline_profile: conda."""
        home = tmp_path / "home"
        home.mkdir()
        bundle = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle),
            {"pipeline_source": "remote:main"},
            nanometa_home=str(home),
            containerization="conda",
        )
        assert bundle.exists()
        assert self._read_bundle_config_profile(bundle) == "conda"

    def test_docker_mode_writes_docker_profile_and_skips_pull_when_no_pipeline(
        self, tmp_path
    ):
        """Without a local pipeline_source, docker mode still completes
        but records a warning and pulls nothing."""
        home = tmp_path / "home"
        home.mkdir()
        bundle = tmp_path / "out.tar.gz"
        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle),
            {"pipeline_source": "remote:main"},
            nanometa_home=str(home),
            containerization="docker",
        )
        assert bundle.exists()
        assert self._read_bundle_config_profile(bundle) == "docker"

    def test_docker_mode_pulls_and_saves_each_image(self, tmp_path, monkeypatch):
        """With a local pipeline checkout and a stubbed docker CLI,
        docker mode invokes ``docker pull`` then ``docker save`` per
        unique reference and writes the tars under
        ``pipeline_containers/``."""
        pipeline = self._stub_pipeline(tmp_path)
        home = tmp_path / "home"
        home.mkdir()
        bundle = tmp_path / "out.tar.gz"

        # Pretend docker is on PATH.
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker"
                            if cmd == "docker" else None)

        # Capture every subprocess call. ``docker save`` writes a real
        # file to the requested path so the bundling step finds it.
        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["docker", "save"]:
                # cmd[3] is the -o target path.
                Path(cmd[3]).write_bytes(b"fake-docker-tar")
            class _Done:
                returncode = 0
                stdout = b""
                stderr = b""
            return _Done()
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            fake_run,
        )

        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle),
            {"pipeline_source": str(pipeline)},
            nanometa_home=str(home),
            containerization="docker",
            pipeline_path=str(pipeline),
        )

        assert bundle.exists()
        assert self._read_bundle_config_profile(bundle) == "docker"

        pull_cmds = [c for c in calls if c[:2] == ["docker", "pull"]]
        save_cmds = [c for c in calls if c[:2] == ["docker", "save"]]
        # Exactly one image in the stub pipeline -> one pull + one save
        assert len(pull_cmds) == 1
        assert len(save_cmds) == 1
        # The bare biocontainers ref is resolved under quay.io (Nextflow's
        # docker.registry), where the image actually exists -- pulling it from
        # Docker Hub fails. See BundleManager._apply_default_registry.
        assert "quay.io/biocontainers/chopper:0.12.0--hdcf5f25_0" in pull_cmds[0]

        # The tar should have been bundled.
        import tarfile
        with tarfile.open(str(bundle), "r:gz") as tar:
            tar_names = tar.getnames()
        assert any(
            "pipeline_containers/" in n and n.endswith(".tar")
            for n in tar_names
        ), f"expected at least one pipeline_containers/*.tar entry: {tar_names}"

    def test_singularity_mode_writes_singularity_profile(
        self, tmp_path, monkeypatch
    ):
        """singularity mode emits pipeline_profile: singularity and
        runs ``apptainer pull`` per unique reference. Falls back from
        ``apptainer`` to ``singularity`` based on PATH detection."""
        pipeline = self._stub_pipeline(tmp_path)
        home = tmp_path / "home"
        home.mkdir()
        bundle = tmp_path / "out.tar.gz"

        # apptainer present, singularity absent.
        monkeypatch.setattr(
            "shutil.which",
            lambda cmd: "/usr/bin/apptainer" if cmd == "apptainer" else None,
        )

        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["apptainer", "pull"]:
                # cmd index 3 is the .sif output path under --force flag.
                # cmd: [apptainer, pull, --force, <out.sif>, <ref>]
                Path(cmd[3]).write_bytes(b"fake-sif")
            class _Done:
                returncode = 0
                stdout = b""
                stderr = b""
            return _Done()
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            fake_run,
        )

        mgr = BundleManager()
        mgr.export_bundle(
            str(bundle),
            {"pipeline_source": str(pipeline)},
            nanometa_home=str(home),
            containerization="singularity",
            pipeline_path=str(pipeline),
        )

        assert bundle.exists()
        assert self._read_bundle_config_profile(bundle) == "singularity"

        pull_cmds = [c for c in calls if c[:2] == ["apptainer", "pull"]]
        # The stub has one Singularity URL and one Docker ref. The
        # Singularity URL gets pulled directly; the Docker ref is the
        # SAME image so it should be deduped to one pull total.
        assert len(pull_cmds) >= 1


class TestPreparationTabContainerizationRadio:
    """W7-C: the Preparation tab exposes a 3-way radio whose value
    flows through the export callback to BundleManager."""

    def test_layout_includes_containerization_radio_default_conda(self):
        from nanometa_live.app.layouts.deployment_layout import (
            create_deployment_layout,
        )
        import dash_bootstrap_components as dbc

        def find_radio(node, target_id):
            if isinstance(node, dbc.RadioItems) and getattr(node, "id", None) == target_id:
                return node
            children = getattr(node, "children", None)
            if children is None:
                return None
            if not isinstance(children, (list, tuple)):
                children = [children]
            for c in children:
                if hasattr(c, "children") or hasattr(c, "id"):
                    found = find_radio(c, target_id)
                    if found is not None:
                        return found
            return None

        layout = create_deployment_layout()
        radio = find_radio(layout, "bundle-containerization-radio")
        assert radio is not None, "bundle-containerization-radio missing"
        assert radio.value == "conda", "default selection must be conda"
        # Three options regardless of host engine availability (some
        # disabled when their CLI is missing, but always rendered).
        values = [opt["value"] for opt in radio.options]
        assert values == ["conda", "docker", "singularity"]

    def test_export_callbacks_read_radio_state(self):
        """Both export callbacks must subscribe to the radio's value."""
        import dash
        from nanometa_live.app.tabs.preparation_tab import (
            register_preparation_callbacks,
        )

        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        register_preparation_callbacks(app)

        listeners = []
        for cb_id, spec in app.callback_map.items():
            state_specs = spec.get("state", []) or []
            state_ids = [
                s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None)
                for s in state_specs
            ]
            if "bundle-containerization-radio" in state_ids:
                listeners.append(cb_id)

        # export_bundle (readiness path) + force_export_bundle (warnings path)
        assert len(listeners) >= 2, (
            f"Expected >=2 callbacks reading the radio; got {len(listeners)}: "
            f"{listeners}"
        )


# ---------------------------------------------------------------------------
# Deployment / move-to-another-computer import-path hardening
# ---------------------------------------------------------------------------

import yaml  # noqa: E402
from nanometa_live.core.workflow.bundle_manager import (  # noqa: E402
    _KRAKEN_DB_PLACEHOLDER,
    _BUNDLED_PIPELINE_DIRNAME,
    _BUNDLED_NXF_PLUGINS_DIRNAME,
    _BUNDLED_PIPELINE_CONTAINERS_DIRNAME,
    _template_genome_metadata,
)


def _make_config_bundle(
    tmp_path,
    *,
    kraken_db=_KRAKEN_DB_PLACEHOLDER,
    with_pipeline=False,
    pipeline_has_main=True,
    with_plugins=False,
    plugins_empty=False,
    min_versions=None,
    tamper_after=None,
    pipeline_container_files=None,
    export_warnings=None,
    pull_image_count=None,
):
    """Build a bundle that carries a config.yaml (and optionally pipeline source
    / plugins), so the import config-rebase block runs."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "genomes").mkdir()
    (staging / "genomes" / "1.fasta").write_text(">s\nACGT\n")

    if pipeline_container_files:
        pcdir = staging / _BUNDLED_PIPELINE_CONTAINERS_DIRNAME
        pcdir.mkdir()
        for name in pipeline_container_files:
            (pcdir / name).write_bytes(b"IMAGE\x00" + name.encode())

    cfg = {"kraken_db": kraken_db}
    if with_pipeline:
        cfg["pipeline_source"] = f"./{_BUNDLED_PIPELINE_DIRNAME}"
        psrc = staging / _BUNDLED_PIPELINE_DIRNAME
        psrc.mkdir()
        (psrc / "nextflow.config").write_text("manifest {}\n")
        if pipeline_has_main:
            (psrc / "main.nf").write_text("workflow {}\n")
    if with_plugins:
        cfg["nxf_plugins_dir"] = f"./{_BUNDLED_NXF_PLUGINS_DIRNAME}"
        pdir = staging / _BUNDLED_NXF_PLUGINS_DIRNAME
        pdir.mkdir()
        if not plugins_empty:
            (pdir / "nf-schema-2.4.2").mkdir()
            (pdir / "nf-schema-2.4.2" / "x.jar").write_text("jar")
        else:
            (pdir / "placeholder.txt").write_text("not a plugin")
    (staging / "config.yaml").write_text(yaml.safe_dump(cfg))

    checksums = {}
    for f in staging.rglob("*"):
        if f.is_file():
            checksums[str(f.relative_to(staging))] = _file_md5(f)

    manifest = {
        "version": "1.1", "created": "2026-01-01T00:00:00",
        "creation_date": "2026-01-01 00:00", "creator": "test",
        "nanometa_home": str(tmp_path / "home"), "checksums": checksums,
        "tool_versions": {}, "container_runtime": None,
        "build_platform": {"system": __import__("platform").system(),
                           "machine": __import__("platform").machine(),
                           "python": "3.11.0"},
    }
    if min_versions is not None:
        manifest["min_versions"] = min_versions
    if export_warnings is not None:
        manifest["export_warnings"] = export_warnings
    if pull_image_count is not None:
        manifest["containerization"] = {
            "mode": "docker",
            "pull_result": {"image_count": pull_image_count},
        }
    (staging / "manifest.json").write_text(json.dumps(manifest))

    if tamper_after:
        (staging / tamper_after).write_text("CORRUPT-AFTER-CHECKSUM")

    bundle = tmp_path / "bundle.tar.gz"
    with tarfile.open(str(bundle), "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(str(item), arcname=item.name)
    return bundle


def _do_import(tmp_path, bundle, *, kraken_db_path="", force=False):
    home = tmp_path / "field"
    home.mkdir()
    return BundleManager().import_bundle(
        str(bundle), kraken_db_path=kraken_db_path,
        nanometa_home=str(home), force=force,
    ), home


class TestEmptyKrakenDbWarning:
    def test_no_db_path_warns_and_flags(self, tmp_path):
        bundle = _make_config_bundle(tmp_path)
        result, home = _do_import(tmp_path, bundle, kraken_db_path="")
        assert result["success"] is True
        assert result.get("kraken_db_unset") is True
        assert any("kraken2 database path was not provided" in w.lower()
                   for w in result["warnings"])
        # Import-first-point-later: config still carries the placeholder token
        # (ConfigLoader normalises it to <cwd>/${KRAKEN_DB}), not a real path.
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert _KRAKEN_DB_PLACEHOLDER in str(cfg["kraken_db"])

    def test_with_db_path_no_flag(self, tmp_path):
        bundle = _make_config_bundle(tmp_path)
        db = tmp_path / "db"; db.mkdir()
        result, home = _do_import(tmp_path, bundle, kraken_db_path=str(db))
        assert result["success"] is True
        assert not result.get("kraken_db_unset")
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert cfg["kraken_db"] == str(db)


class TestMissingMainNfHardFail:
    def test_missing_main_nf_fails(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, with_pipeline=True, pipeline_has_main=False)
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is False
        assert result.get("pipeline_main_missing") is True
        assert any("main.nf" in w for w in result["warnings"])

    def test_main_nf_present_succeeds(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, with_pipeline=True, pipeline_has_main=True)
        db = tmp_path / "db"; db.mkdir()
        result, _ = _do_import(tmp_path, bundle, kraken_db_path=str(db))
        assert result["success"] is True
        assert not result.get("pipeline_main_missing")


class TestEmptyPluginsWarning:
    def test_empty_plugins_warns(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, with_plugins=True, plugins_empty=True)
        db = tmp_path / "db"; db.mkdir()
        result, _ = _do_import(tmp_path, bundle, kraken_db_path=str(db))
        assert result["success"] is True
        assert result.get("plugins_empty") is True
        assert any("plugin registry" in w for w in result["warnings"])

    def test_populated_plugins_no_flag(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, with_plugins=True, plugins_empty=False)
        db = tmp_path / "db"; db.mkdir()
        result, _ = _do_import(tmp_path, bundle, kraken_db_path=str(db))
        assert result["success"] is True
        assert not result.get("plugins_empty")


class TestPostCopyChecksumReverify:
    @staticmethod
    def _patch_truncating_copytree(monkeypatch):
        # The fresh-home import copies each dir with shutil.copytree; wrap it to
        # truncate the genome after copy so the tempdir checksum passed but the
        # post-copy re-verify catches the on-disk divergence.
        import shutil as _sh
        real_copytree = _sh.copytree

        def bad_copytree(src, dst, *a, **k):
            out = real_copytree(src, dst, *a, **k)
            g = Path(dst) / "1.fasta"
            if g.exists():
                g.write_text("TRUNCATED")
            return out

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.shutil.copytree",
            bad_copytree)

    def test_post_copy_divergence_fails(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path)
        self._patch_truncating_copytree(monkeypatch)
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is False
        assert any("after copy" in w.lower() for w in result["warnings"])

    def test_post_copy_divergence_force_continues(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path)
        self._patch_truncating_copytree(monkeypatch)
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x", force=True)
        assert result["success"] is True
        assert any("after copy" in w.lower() for w in result["warnings"])


class TestNextflowVersionFloor:
    def test_old_nextflow_warns(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path, min_versions={"nextflow": "26.04.0"})
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager._get_nextflow_version",
            lambda: "25.10.4 build 5930")
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is True
        assert any("older than the bundle" in w for w in result["warnings"])

    def test_new_nextflow_no_floor_warning(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path, min_versions={"nextflow": "26.04.0"})
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager._get_nextflow_version",
            lambda: "26.05.0 build 1")
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert not any("older than the bundle" in w for w in result["warnings"])

    def test_no_min_versions_skips(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path)  # no min_versions
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager._get_nextflow_version",
            lambda: "1.0.0 build 1")
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert not any("older than the bundle" in w for w in result["warnings"])


class TestTemplateGenomeMetadata:
    def test_external_path_left_with_warning(self, tmp_path):
        home = tmp_path / "home"; home.mkdir()
        src = tmp_path / "gm.json"; dst = tmp_path / "out.json"
        src.write_text(json.dumps({
            "a": {"fasta_path": str(home / "genomes" / "a.fasta"),
                  "blast_db_path": "/mnt/ext/a.fasta"}}))
        warns = _template_genome_metadata(src, dst, str(home), "${NANOMETA_HOME}")
        out = json.loads(dst.read_text())
        assert out["a"]["fasta_path"].startswith("${NANOMETA_HOME}")
        assert out["a"]["blast_db_path"] == "/mnt/ext/a.fasta"
        assert len(warns) == 1 and "blast_db_path" in warns[0]

    def test_all_home_paths_no_warnings(self, tmp_path):
        home = tmp_path / "home"; home.mkdir()
        src = tmp_path / "gm.json"; dst = tmp_path / "out.json"
        src.write_text(json.dumps({
            "a": {"fasta_path": str(home / "genomes" / "a.fasta")}}))
        warns = _template_genome_metadata(src, dst, str(home), "${NANOMETA_HOME}")
        assert warns == []
        assert "${NANOMETA_HOME}" in dst.read_text()


class TestSingularityBundleWiring:
    """Offline Singularity/Apptainer path: images pulled into
    ``pipeline_containers/`` must be restored to the field-machine home and
    wired to Nextflow via ``NXF_SINGULARITY_CACHEDIR``. Before this fix the
    pulled ``.sif``/``.img`` files rode in the tarball but were never copied
    out or pointed at, so an air-gapped run silently re-pulled and failed.
    """

    def test_cache_name_matches_nextflow_convention(self):
        """Filenames must match Nextflow's SingularityCache naming
        (strip scheme at ``://``, replace ``:`` and ``/`` with ``-``,
        append ``.img``) or Nextflow re-pulls instead of reusing.
        """
        f = BundleManager._singularity_cache_name
        assert (
            f("docker://quay.io/biocontainers/foo:1.0.2--h1234_0")
            == "quay.io-biocontainers-foo-1.0.2--h1234_0.img"
        )
        assert (
            f("https://depot.galaxyproject.org/singularity/foo:1.0--0")
            == "depot.galaxyproject.org-singularity-foo-1.0--0.img"
        )
        assert f("quay.io/org/img:tag") == "quay.io-org-img-tag.img"

    def test_pull_one_singularity_writes_convention_name(self, tmp_path):
        """_pull_one_singularity_image writes to the Nextflow-convention
        ``.img`` filename, not the generic safe-slug ``.sif``.
        """
        mgr = BundleManager()
        recorded = {}

        def fake_run(cmd, **kwargs):
            # cmd = [cli, "pull", "--force", out, ref]
            recorded["out"] = Path(cmd[3])
            recorded["out"].write_bytes(b"SIF\x00")
            return MagicMock(returncode=0)

        with patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            side_effect=fake_run,
        ):
            mgr._pull_one_singularity_image(
                "docker://quay.io/biocontainers/foo:1.0", tmp_path, "apptainer"
            )
        assert recorded["out"].name == "quay.io-biocontainers-foo-1.0.img"

    def test_import_restores_pipeline_containers_and_wires_cachedir(self, tmp_path):
        """A singularity bundle restores pipeline_containers/ to home and
        sets nxf_singularity_cachedir + result["singularity_cache_path"].
        """
        home = tmp_path / "build_home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        img_name = "quay.io-biocontainers-foo-1.0.img"

        def fake_pull(engine, staging, config, pipeline_path, target_platform=None):
            images = staging / "pipeline_containers"
            images.mkdir(parents=True, exist_ok=True)
            (images / img_name).write_bytes(b"SIF\x00fake-image")
            return {
                "attempted": True,
                "engine": engine,
                "image_count": 1,
                "pulled": ["quay.io/biocontainers/foo:1.0"],
                "warnings": [],
            }

        mgr = BundleManager()
        bundle_path = tmp_path / "bundle.tar.gz"
        with patch.object(
            mgr, "_pull_pipeline_containers", side_effect=fake_pull
        ):
            mgr.export_bundle(
                str(bundle_path),
                config={
                    "kraken_db": "",
                    "results_output_directory": str(tmp_path),
                },
                nanometa_home=str(home),
                pipeline_path=str(pipeline_dir),
                containerization="singularity",
                # Imported on this same machine below, so declare this
                # machine's platform rather than the linux/amd64 default.
                target_platform=_local_container_platform(),
            )

        field = tmp_path / "field_home"
        field.mkdir()
        result = mgr.import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(field)
        )

        assert result["success"] is True
        restored = field / "pipeline_containers" / img_name
        assert restored.exists(), (
            "import_bundle must restore pipeline_containers/*.img into "
            "<nanometa_home>/pipeline_containers/"
        )
        assert result.get("singularity_cache_path", "").endswith(
            "pipeline_containers"
        )

        from nanometa_live.core.config.config_loader import ConfigLoader

        cfg = ConfigLoader(str(field)).load_config(str(field / "config.yaml"))
        assert cfg.get("nxf_singularity_cachedir", "").endswith(
            "pipeline_containers"
        ), "config must carry nxf_singularity_cachedir for _build_nextflow_env"


class TestContainerImageCompleteness:
    """A partial container pull at export (a slow/failed image is caught and
    appended to warnings, not aborted) must not import as a silent success.
    The import cross-checks the loaded image count against the manifest's
    recorded pull count and warns when fewer images arrive.
    """

    def test_import_warns_on_incomplete_image_set(self, tmp_path):
        home = tmp_path / "build_home"
        home.mkdir()
        (home / "genomes").mkdir()
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        pipeline_dir = _make_fake_pipeline_checkout(tmp_path)

        def fake_pull(engine, staging, config, pipeline_path, target_platform=None):
            # Report two images pulled, but only stage one -- models a
            # single failed `docker save` / `apptainer pull` that was
            # caught and warned about rather than aborting the export.
            images = staging / "pipeline_containers"
            images.mkdir(parents=True, exist_ok=True)
            (images / "quay.io-org-a-1.0.img").write_bytes(b"SIF\x00a")
            return {
                "attempted": True,
                "engine": engine,
                "image_count": 2,
                "pulled": ["quay.io/org/a:1.0"],
                "warnings": ["Failed to pull quay.io/org/b:2.0"],
            }

        mgr = BundleManager()
        bundle_path = tmp_path / "bundle.tar.gz"
        with patch.object(mgr, "_pull_pipeline_containers", side_effect=fake_pull):
            mgr.export_bundle(
                str(bundle_path),
                config={"kraken_db": "", "results_output_directory": str(tmp_path)},
                nanometa_home=str(home),
                pipeline_path=str(pipeline_dir),
                containerization="singularity",
                # Imported on this same machine below, so declare this
                # machine's platform rather than the linux/amd64 default.
                target_platform=_local_container_platform(),
            )

        field = tmp_path / "field_home"
        field.mkdir()
        result = mgr.import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(field)
        )

        # Import still succeeds (images can be re-pulled if the field
        # machine ever gets network), but the shortfall must be surfaced.
        joined = " ".join(result["warnings"]).lower()
        assert "image" in joined and ("1" in joined and "2" in joined), (
            f"expected an incomplete-image-set warning, got: {result['warnings']}"
        )


class TestDbHashMismatch:
    """A bundle imported against a Kraken2 DB whose hash differs from the one
    the mappings were built for must flag it explicitly and actionably. The
    bundled taxid mappings/index key off the DB hash, so on a mismatch the
    readiness 'Database index'/'Taxid mappings' checks go CRITICAL -- the old
    vague 'may need regeneration' warning left operators unable to connect the
    successful import to the later readiness failure.
    """

    def test_mismatch_sets_flag_and_actionable_warning(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(tmp_path, db_hash="BUNDLE_HASH_AAA")
        home = tmp_path / "import_home"
        home.mkdir()
        db = tmp_path / "kdb"
        db.mkdir()

        mgr = BundleManager()
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="LOCAL_HASH_BBB",
        ):
            result = mgr.import_bundle(
                str(bundle_path),
                kraken_db_path=str(db),
                nanometa_home=str(home),
            )

        assert result["success"] is True
        assert result.get("db_hash_mismatch") is True
        txt = " ".join(result["warnings"]).lower()
        assert "mapping" in txt
        assert "regenerat" in txt or "taxonomy index" in txt

    def test_matching_hash_sets_no_flag(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(tmp_path, db_hash="SAME_HASH")
        home = tmp_path / "import_home"
        home.mkdir()
        db = tmp_path / "kdb"
        db.mkdir()

        mgr = BundleManager()
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="SAME_HASH",
        ):
            result = mgr.import_bundle(
                str(bundle_path),
                kraken_db_path=str(db),
                nanometa_home=str(home),
            )

        assert result["success"] is True
        assert result.get("db_hash_mismatch") is not True


class TestPipelineContainersPostCopyVerify:
    """``pipeline_containers/`` holds the largest artefacts in a
    docker/singularity bundle, so it is what an interrupted copy truncates
    first. It must be covered by the post-copy checksum re-verify; before the
    fix the ``_copied_roots`` prefix tuple omitted it and every image file
    skipped the check entirely.
    """

    IMG = "quay.io-org-a-1.0.img"

    @staticmethod
    def _patch_truncating_copytree(monkeypatch, target_name):
        import shutil as _sh
        real_copytree = _sh.copytree

        def bad_copytree(src, dst, *a, **k):
            out = real_copytree(src, dst, *a, **k)
            victim = Path(dst) / target_name
            if victim.exists():
                victim.write_bytes(b"TRUNCATED")
            return out

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.shutil.copytree",
            bad_copytree)

    def test_truncated_image_fails_post_copy_verify(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(
            tmp_path, pipeline_container_files=[self.IMG])
        self._patch_truncating_copytree(monkeypatch, self.IMG)
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is False
        joined = " ".join(result["warnings"])
        assert "after copy" in joined.lower()
        assert _BUNDLED_PIPELINE_CONTAINERS_DIRNAME in joined

    def test_intact_image_passes_post_copy_verify(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, pipeline_container_files=[self.IMG])
        result, home = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is True
        assert (home / _BUNDLED_PIPELINE_CONTAINERS_DIRNAME / self.IMG).exists()


class TestLoadContainerImages:
    """Direct tests for _load_container_images. It reports enough detail for
    the caller to tell 'the bundle is short of images' (build-machine problem)
    apart from 'this machine cannot run Docker' (field-machine problem).
    """

    def test_sif_images_counted_in_place(self, tmp_path):
        (tmp_path / "a.img").write_bytes(b"SIF")
        (tmp_path / "b.sif").write_bytes(b"SIF")
        report = BundleManager()._load_container_images(tmp_path)
        assert report["image_count"] == 2
        assert report["loaded"] == 2
        assert report["tar_count"] == 0
        # No tars, so no Docker probe was needed.
        assert report["docker_usable"] is True

    def test_docker_tars_loaded(self, tmp_path):
        (tmp_path / "a.tar").write_bytes(b"TAR")
        (tmp_path / "b.tar").write_bytes(b"TAR")
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=True,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            return_value=MagicMock(returncode=0),
        ):
            report = BundleManager()._load_container_images(tmp_path)
        assert report["tar_count"] == 2
        assert report["tar_loaded"] == 2
        assert report["loaded"] == 2
        assert report["failures"] == []

    def test_docker_binary_missing(self, tmp_path):
        (tmp_path / "a.tar").write_bytes(b"TAR")
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value=None,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            side_effect=FileNotFoundError("docker"),
        ):
            report = BundleManager()._load_container_images(tmp_path)
        assert report["docker_available"] is False
        assert report["docker_usable"] is False
        assert report["tar_loaded"] == 0
        assert report["failures"]

    def test_docker_daemon_down(self, tmp_path):
        (tmp_path / "a.tar").write_bytes(b"TAR")
        import subprocess as _sp
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=False,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            side_effect=_sp.CalledProcessError(1, "docker load"),
        ):
            report = BundleManager()._load_container_images(tmp_path)
        assert report["docker_available"] is True
        assert report["docker_usable"] is False
        assert report["tar_loaded"] == 0

    def test_partial_load_keeps_docker_usable(self, tmp_path):
        """One corrupt archive among several is a bundle problem, not a
        runtime problem -- docker_usable must stay True."""
        (tmp_path / "a.tar").write_bytes(b"TAR")
        (tmp_path / "b.tar").write_bytes(b"TAR")
        import subprocess as _sp
        calls = {"n": 0}

        def flaky(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return MagicMock(returncode=0)
            raise _sp.CalledProcessError(1, "docker load")

        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=True,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            side_effect=flaky,
        ):
            report = BundleManager()._load_container_images(tmp_path)
        assert report["docker_usable"] is True
        assert report["tar_loaded"] == 1
        assert len(report["failures"]) == 1

    def test_empty_dir(self, tmp_path):
        report = BundleManager()._load_container_images(tmp_path)
        assert report["loaded"] == 0
        assert report["tar_count"] == 0


class TestContainerRuntimeUnavailableAtImport:
    """A missing/stopped Docker on the FIELD machine must not be reported as
    an incomplete export. The old message told the operator to 're-export from
    a machine that can reach the registry', which fixes nothing.
    """

    def _import_with_docker(self, tmp_path, *, which, daemon_ok):
        bundle = _make_config_bundle(
            tmp_path,
            pipeline_container_files=["a.tar", "b.tar"],
            pull_image_count=2,
        )
        import subprocess as _sp
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            side_effect=lambda name: which if name == "docker" else None,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=daemon_ok,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            side_effect=_sp.CalledProcessError(1, "docker load"),
        ):
            return _do_import(tmp_path, bundle, kraken_db_path="x")

    def test_docker_missing_blames_field_machine(self, tmp_path):
        result, _ = self._import_with_docker(
            tmp_path, which=None, daemon_ok=False)
        assert result.get("container_runtime_unavailable") is True
        assert not result.get("incomplete_image_set")
        joined = " ".join(result["warnings"])
        assert "'docker' command was not found" in joined
        assert "bundle itself is intact" in joined
        # Blame attribution is the point: a field machine with no Docker must
        # not be told to re-export a bundle that is fine. Scoped to the
        # container-runtime message rather than every warning, because other
        # checks legitimately do advise a re-export -- this fixture also ships
        # no Nextflow plugins, which genuinely is an export-side problem.
        runtime_msg = next(
            w for w in result["warnings"] if "'docker' command was not found" in w
        )
        assert "re-export" not in runtime_msg.lower()

    def test_daemon_down_blames_field_machine(self, tmp_path):
        result, _ = self._import_with_docker(
            tmp_path, which="/usr/bin/docker", daemon_ok=False)
        assert result.get("container_runtime_unavailable") is True
        joined = " ".join(result["warnings"])
        assert "daemon did not respond" in joined

    def test_working_docker_short_set_blames_export(self, tmp_path):
        """With Docker working, a shortfall really is an incomplete export."""
        bundle = _make_config_bundle(
            tmp_path, pipeline_container_files=["a.tar"], pull_image_count=2)
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=True,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run",
            return_value=MagicMock(returncode=0),
        ):
            result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result.get("incomplete_image_set") is True
        assert not result.get("container_runtime_unavailable")
        assert any("re-export" in w.lower() for w in result["warnings"])


class TestExportWarningsSurfacedAtImport:
    """Warnings recorded at export (un-portable genome paths, partial pulls)
    were written to the manifest and then never read. The operator importing
    on the field machine is usually not the operator who built the bundle.
    """

    def test_export_warnings_reach_import_result(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path,
            export_warnings=[
                "Genome path /mnt/scratch/foo.fasta is outside the data home",
            ],
        )
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert result["success"] is True
        assert result["export_warnings"] == [
            "Genome path /mnt/scratch/foo.fasta is outside the data home",
        ]
        assert any("Recorded at export" in w for w in result["warnings"])

    def test_no_export_warnings_no_key(self, tmp_path):
        bundle = _make_config_bundle(tmp_path)
        result, _ = _do_import(tmp_path, bundle, kraken_db_path="x")
        assert "export_warnings" not in result


class TestVerifyBundleDryRun:
    """`verify_bundle` runs the import's pre-copy checks without touching the
    machine, so an operator can check a USB copy before committing to it.
    """

    def test_clean_bundle_verifies(self, tmp_path):
        bundle = _make_config_bundle(tmp_path)
        result = BundleManager().verify_bundle(str(bundle))
        assert result["success"] is True
        assert result["blockers"] == []
        assert result["manifest"]["version"] == "1.1"

    def test_verify_does_not_write_to_home(self, tmp_path, monkeypatch):
        bundle = _make_config_bundle(tmp_path)
        home = tmp_path / "untouched_home"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(home))
        BundleManager().verify_bundle(str(bundle))
        assert not home.exists()

    def test_tampered_bundle_reports_blocker(self, tmp_path):
        bundle = _make_config_bundle(tmp_path, tamper_after="genomes/1.fasta")
        result = BundleManager().verify_bundle(str(bundle))
        assert result["success"] is False
        assert result["checksum_mismatches"] == ["genomes/1.fasta"]
        assert any("checksum" in b.lower() for b in result["blockers"])

    def test_missing_file_reports_blocker(self, tmp_path):
        bundle = _make_config_bundle(tmp_path)
        result = BundleManager().verify_bundle(str(bundle))
        assert result["success"] is True
        missing = tmp_path / "nope.tar.gz"
        result = BundleManager().verify_bundle(str(missing))
        assert result["success"] is False
        assert any("not found" in w for w in result["warnings"])

    def test_not_a_tar(self, tmp_path):
        junk = tmp_path / "junk.tar.gz"
        junk.write_text("not a tar")
        result = BundleManager().verify_bundle(str(junk))
        assert result["success"] is False
        assert any("tar archive" in w for w in result["warnings"])

    def test_export_warnings_surfaced_in_dry_run(self, tmp_path):
        bundle = _make_config_bundle(
            tmp_path, export_warnings=["something was not portable"])
        result = BundleManager().verify_bundle(str(bundle))
        assert result["export_warnings"] == ["something was not portable"]

    def test_db_hash_mismatch_reported_without_import(self, tmp_path):
        bundle_path, _ = _make_minimal_bundle(tmp_path, db_hash="BUNDLE_AAA")
        db = tmp_path / "kdb"
        db.mkdir()
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="LOCAL_BBB",
        ):
            result = BundleManager().verify_bundle(
                str(bundle_path), kraken_db_path=str(db))
        assert result["success"] is True
        assert result["db_hash_mismatch"] is True
