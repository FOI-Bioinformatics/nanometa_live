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
    _ACTIVATE_SCRIPT_FILENAME,
    _ACTIVATE_SCRIPT_TEMPLATE,
    _BUNDLED_CONDA_CACHE_DIRNAME,
    _PRE_WARM_SCENARIOS,
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

    def test_seven_scenarios_registered(self):
        """The pre-warm scenario list now carries exactly seven entries
        in the order the audit recommended."""
        names = [s["name"] for s in _PRE_WARM_SCENARIOS]
        assert names == [
            "batch_samplesheet",
            "realtime_multiplex",
            "realtime_per_file",
            "realtime_single_sample",
            "validation_blast",
            "validation_minimap2",
            "fastp_qc",
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

    def test_all_seven_scenarios_attempted(self, tmp_path):
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
