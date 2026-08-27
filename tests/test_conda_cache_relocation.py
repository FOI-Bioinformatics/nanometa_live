"""Pre-warmed conda cache: relocation across machines (2026-08-27 audit).

Conda envs embed the absolute build prefix in shebangs, conda-meta JSON and
NUL-terminated strings inside binaries. The pre-warm step builds the cache
under a staging directory that no longer exists at import time, so without a
relocation pass every env ships dead-on-arrival -- even when re-imported on
the build machine itself (audit 2026-08-27, conda finding 1).

The contract pinned here:

- export builds the cache under a deliberately PADDED prefix (>= 160 chars)
  and records it as ``manifest["pre_warm_conda_envs"]["build_prefix"]``, so
  any realistic field path is shorter and binary patching always has room;
- import rewrites the recorded prefix to the restored cache path in text
  files (length may change) and binaries (NUL-padded, length preserved), and
  retargets symlinks that point into the old prefix;
- symlinks survive the restore as symlinks (copytree must not dereference);
- an env directory failing the completeness predicate (conda-meta/history +
  non-empty bin/) is pruned at export, never shipped;
- pre-warm failures are folded into ``manifest["export_warnings"]`` so
  verify/import replay them to the operator.
"""

import json
import os
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    _BUNDLED_CONDA_CACHE_DIRNAME,
    BundleManager,
)

pytestmark = pytest.mark.unit

ENV_NAME = "env-1234abcd5678efgh"


def _fake_runner_building_real_shaped_env(scenario, pipeline_dir, staging, env):
    """Mimic Nextflow's CondaCache: build an env under NXF_CONDA_CACHEDIR
    with the three artefact kinds relocation must handle."""
    cache = Path(env["NXF_CONDA_CACHEDIR"])
    env_dir = cache / ENV_NAME
    if env_dir.exists():
        return True, "ok"
    (env_dir / "conda-meta").mkdir(parents=True)
    (env_dir / "conda-meta" / "history").write_text("==> done <==\n")
    bindir = env_dir / "bin"
    bindir.mkdir()
    (bindir / "python3.12").write_text("fake interpreter\n")
    # Text file with embedded prefix: a console-script shebang.
    (bindir / "pip").write_text(f"#!{env_dir}/bin/python3.12\nprint('x')\n")
    # Binary file with a NUL-terminated prefix string.
    libdir = env_dir / "lib"
    libdir.mkdir()
    blob = (
        b"\x7fELF\x00\x00"
        + str(env_dir).encode() + b"/lib/python3.12/site-packages\x00"
        + b"TRAILER"
    )
    (libdir / "config.so").write_bytes(blob)
    # Absolute symlink pointing inside the build prefix.
    os.symlink(str(env_dir / "bin" / "python3.12"), str(bindir / "python"))
    # Relative symlink (the common conda case) -- must survive verbatim.
    os.symlink("python3.12", str(bindir / "python3"))
    return True, "ok"


def _export_prewarmed(tmp_path, runner, home_name="build_home"):
    home = tmp_path / home_name
    (home / "genomes").mkdir(parents=True)
    (home / "genomes" / "1.fasta").write_text(">x\nA\n")
    pipeline = tmp_path / "pipeline"
    if not pipeline.exists():
        pipeline.mkdir()
        (pipeline / "main.nf").write_text("workflow {}\n")
    out = tmp_path / "bundle.tar.gz"
    mgr = BundleManager()
    with patch.object(mgr, "_run_pre_warm_scenario", side_effect=runner):
        with patch(
            "nanometa_live.core.workflow.bundle_manager.shutil.which",
            return_value="/usr/bin/nextflow",
        ):
            mgr.export_bundle(
                str(out),
                config={"kraken_db": "", "pipeline_source": str(pipeline)},
                nanometa_home=str(home),
                pre_warm_conda_envs=True,
                pipeline_path=str(pipeline),
            )
    return mgr, out


def _read_manifest(bundle_path):
    with tarfile.open(str(bundle_path), "r:gz") as tar:
        return json.loads(tar.extractfile("manifest.json").read())


class TestPaddedBuildPrefix:
    def test_manifest_records_padded_build_prefix(self, tmp_path):
        _, out = _export_prewarmed(
            tmp_path, _fake_runner_building_real_shaped_env
        )
        pwc = _read_manifest(out)["pre_warm_conda_envs"]
        assert pwc["success"] is True
        build_prefix = pwc.get("build_prefix")
        assert build_prefix, "manifest must record the build prefix"
        # Padding guarantees binary patching has room on any realistic
        # field path.
        assert len(build_prefix) >= 160
        # The cache still ships under the canonical dirname.
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
        assert any(
            n.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/{ENV_NAME}")
            for n in names
        )


class TestImportRelocation:
    @pytest.fixture()
    def imported(self, tmp_path):
        mgr, out = _export_prewarmed(
            tmp_path, _fake_runner_building_real_shaped_env
        )
        field_home = tmp_path / "field_home"
        field_home.mkdir()
        result = mgr.import_bundle(
            str(out), kraken_db_path=None, nanometa_home=str(field_home)
        )
        assert result["success"] is True, result.get("warnings")
        return field_home, result

    def test_shebang_points_at_restored_cache(self, imported):
        field_home, _ = imported
        env_dir = field_home / _BUNDLED_CONDA_CACHE_DIRNAME / ENV_NAME
        first_line = (env_dir / "bin" / "pip").read_text().splitlines()[0]
        assert first_line == f"#!{env_dir}/bin/python3.12"

    def test_binary_patched_nul_padded_same_length(self, imported):
        field_home, result = imported
        env_dir = field_home / _BUNDLED_CONDA_CACHE_DIRNAME / ENV_NAME
        blob = (env_dir / "lib" / "config.so").read_bytes()
        new_prefix = str(env_dir).encode()
        assert new_prefix + b"/lib/python3.12/site-packages" in blob
        # Length preserved: the string was re-NUL-padded in place, so the
        # trailer bytes still sit at their original offset.
        assert blob.endswith(b"TRAILER")
        build_prefix = result["manifest"]["pre_warm_conda_envs"]["build_prefix"]
        old_env_dir = f"{build_prefix}/{ENV_NAME}".encode()
        original = (
            b"\x7fELF\x00\x00"
            + old_env_dir + b"/lib/python3.12/site-packages\x00"
            + b"TRAILER"
        )
        assert len(blob) == len(original)

    def test_no_file_still_contains_build_prefix(self, imported, tmp_path):
        field_home, result = imported
        build_prefix = result["manifest"]["pre_warm_conda_envs"][
            "build_prefix"
        ].encode()
        cache = field_home / _BUNDLED_CONDA_CACHE_DIRNAME
        offenders = []
        for path in cache.rglob("*"):
            if path.is_file() and not path.is_symlink():
                if build_prefix in path.read_bytes():
                    offenders.append(str(path))
        assert offenders == []

    def test_absolute_internal_symlink_resolves_in_field_home(self, imported):
        field_home, _ = imported
        env_dir = field_home / _BUNDLED_CONDA_CACHE_DIRNAME / ENV_NAME
        link = env_dir / "bin" / "python"
        assert link.is_symlink()
        assert link.resolve() == (env_dir / "bin" / "python3.12").resolve()

    def test_relative_symlink_preserved_as_symlink(self, imported):
        field_home, _ = imported
        link = (
            field_home
            / _BUNDLED_CONDA_CACHE_DIRNAME
            / ENV_NAME
            / "bin"
            / "python3"
        )
        assert link.is_symlink(), (
            "copytree must not dereference symlinks in the conda cache"
        )
        assert os.readlink(str(link)) == "python3.12"

    def test_import_reports_relocation(self, imported):
        _, result = imported
        stats = result.get("conda_relocation")
        assert stats, "import result must report the relocation pass"
        assert stats["text_rewritten"] >= 1
        assert stats["binary_patched"] >= 1
        assert stats["failures"] == []


class TestBrokenEnvPruning:
    def test_incomplete_env_pruned_at_export(self, tmp_path):
        def runner(scenario, pipeline_dir, staging, env):
            cache = Path(env["NXF_CONDA_CACHEDIR"])
            good = cache / "env-good1111"
            if not good.exists():
                (good / "conda-meta").mkdir(parents=True)
                (good / "conda-meta" / "history").write_text("done\n")
                (good / "bin").mkdir()
                (good / "bin" / "tool").write_text("#!/bin/sh\n")
                # A SIGTERM-truncated env: no conda-meta/history.
                stub = cache / "env-stub2222"
                (stub / "bin").mkdir(parents=True)
                (stub / "bin" / "tool").write_text("#!/bin/sh\n")
            return True, "ok"

        _, out = _export_prewarmed(tmp_path, runner)
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
        assert any("env-good1111" in n for n in names)
        assert not any("env-stub2222" in n for n in names), (
            "a half-built env must never ship in the bundle"
        )
        pwc = _read_manifest(out)["pre_warm_conda_envs"]
        assert pwc["env_count"] == 1
        assert any("env-stub2222" in w for w in pwc["warnings"])


class TestPreWarmWarningsSurface:
    def test_scenario_failure_folded_into_export_warnings(self, tmp_path):
        calls = {"n": 0}

        def runner(scenario, pipeline_dir, staging, env):
            calls["n"] += 1
            if calls["n"] == 1:
                cache = Path(env["NXF_CONDA_CACHEDIR"])
                env_dir = cache / "env-ok"
                (env_dir / "conda-meta").mkdir(parents=True)
                (env_dir / "conda-meta" / "history").write_text("done\n")
                (env_dir / "bin").mkdir()
                (env_dir / "bin" / "t").write_text("#!/bin/sh\n")
                return True, "ok"
            return False, "solver blew up"

        _, out = _export_prewarmed(tmp_path, runner)
        manifest = _read_manifest(out)
        assert any(
            "pre-warm" in w and "solver blew up" in w
            for w in manifest["export_warnings"]
        ), "pre-warm failures must reach export_warnings so verify/import replay them"


class TestEnvCountCrossCheck:
    def test_import_flags_missing_envs(self, tmp_path):
        mgr, out = _export_prewarmed(
            tmp_path, _fake_runner_building_real_shaped_env
        )
        # Tamper: repack the bundle without the env directory, keeping the
        # manifest's env_count claim -- models a truncated/hand-edited
        # transfer of the largest tree in the bundle.
        workdir = tmp_path / "repack"
        workdir.mkdir()
        with tarfile.open(str(out), "r:gz") as tar:
            tar.extractall(workdir, filter="data")
        cache = workdir / _BUNDLED_CONDA_CACHE_DIRNAME
        import shutil as _sh

        _sh.rmtree(cache / ENV_NAME)
        manifest = json.loads((workdir / "manifest.json").read_text())
        # Drop the now-missing files from checksums so the cross-check being
        # tested (env count), not the checksum pass, is what fires.
        manifest["checksums"] = {
            k: v
            for k, v in manifest["checksums"].items()
            if not k.startswith(f"{_BUNDLED_CONDA_CACHE_DIRNAME}/{ENV_NAME}")
        }
        (workdir / "manifest.json").write_text(json.dumps(manifest))
        tampered = tmp_path / "tampered.tar.gz"
        with tarfile.open(str(tampered), "w:gz") as tar:
            for item in workdir.iterdir():
                tar.add(str(item), arcname=item.name)

        field_home = tmp_path / "field2"
        field_home.mkdir()
        result = mgr.import_bundle(
            str(tampered), kraken_db_path=None, nanometa_home=str(field_home)
        )
        assert result.get("incomplete_conda_cache") is True
        assert any(
            "conda" in w.lower() and "env" in w.lower()
            for w in result["warnings"]
        )
