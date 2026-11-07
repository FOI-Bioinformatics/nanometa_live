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

@pytest.fixture(autouse=True)
def _mock_env_materialiser():
    """The completing env sweep spawns a real nextflow run; export tests
    mock it (its own coverage lives in test_env_materialiser.py)."""
    from unittest.mock import patch as _patch

    from nanometa_live.core.workflow.bundle_manager import BundleManager

    with _patch.object(
        BundleManager,
        "_materialise_all_module_envs",
        return_value=(True, "ok", 0),
    ):
        yield


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


class TestMachOResigning:
    """Binary-patching a Mach-O invalidates its code signature, and Apple
    Silicon SIGKILLs invalidly-signed binaries at exec (observed live:
    every python process in the field run died exit-137 while unpatched C
    tools ran). Every patched Mach-O must be ad-hoc re-signed, the way
    conda-pack does on macOS."""

    # Padded like production: the patch needs the old prefix to be at
    # least as long as the destination.
    OLD = "/build/prefix_" + "x" * 200

    def _cache_with(self, tmp_path, name, blob):
        cache = tmp_path / "cache"
        env = cache / "env-x" / "bin"
        env.mkdir(parents=True)
        (env / name).write_bytes(blob)
        return cache

    def test_patched_macho_is_resigned(self, tmp_path):
        from unittest.mock import patch as _patch

        from nanometa_live.core.workflow import conda_cache_utils as ccu

        old = self.OLD
        blob = b"\xcf\xfa\xed\xfe" + b"\x00" * 4 + old.encode() + b"/lib\x00PAD"
        cache = self._cache_with(tmp_path, "python3.12", blob)
        resigned = []
        with _patch.object(
            ccu, "_resign_macho", side_effect=lambda p: resigned.append(p) or True
        ):
            stats = ccu.relocate_conda_cache(cache, old)
        assert stats["binary_patched"] == 1
        assert len(resigned) == 1
        assert resigned[0].name == "python3.12"

    def test_patched_non_macho_is_not_resigned(self, tmp_path):
        from unittest.mock import patch as _patch

        from nanometa_live.core.workflow import conda_cache_utils as ccu

        old = self.OLD
        blob = b"\x7fELF" + b"\x00" * 4 + old.encode() + b"/lib\x00PAD"
        cache = self._cache_with(tmp_path, "tool", blob)
        resigned = []
        with _patch.object(
            ccu, "_resign_macho", side_effect=lambda p: resigned.append(p) or True
        ):
            ccu.relocate_conda_cache(cache, old)
        assert resigned == []

    def test_resign_failure_is_reported(self, tmp_path):
        from unittest.mock import patch as _patch

        from nanometa_live.core.workflow import conda_cache_utils as ccu

        old = self.OLD
        blob = b"\xcf\xfa\xed\xfe" + b"\x00" * 4 + old.encode() + b"/lib\x00PAD"
        cache = self._cache_with(tmp_path, "python3.12", blob)
        with _patch.object(ccu, "_resign_macho", return_value=False):
            stats = ccu.relocate_conda_cache(cache, old)
        assert stats["failures"], (
            "an unsigned patched Mach-O will be SIGKILLed at exec; the "
            "operator must be told"
        )


class TestByteCompiledModules:
    """A .pyc is marshal data, not a C string table (field audit 2026-10-28, C1).

    Conda byte-compiles every noarch package with the env's absolute prefix,
    so each .pyc carries the padded build path in ``co_filename``. The
    NUL-padded binary rewrite shifted the bytes after the path and broke the
    marshal stream while ``relocate_conda_cache`` reported zero failures; on
    an air-gapped machine every Python-based pipeline process then failed at
    first import. The contract: a .pyc carrying the old prefix is removed, the
    module still imports (Python regenerates the file from source), and the
    removal is counted.
    """

    OLD_ROOT_NAME = "conda_cache_build_" + "p" * 180

    def _env_with_compiled_module(self, tmp_path):
        import py_compile

        old_root = tmp_path / self.OLD_ROOT_NAME
        site = old_root / "env-abc" / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        src = site / "relocmod.py"
        src.write_text("def hello():\n    return 'relocated'\n")
        pyc = site / "__pycache__" / "relocmod.cpython-312.pyc"
        # dfile is what conda records: the absolute install-time path.
        py_compile.compile(str(src), cfile=str(pyc), dfile=str(src))
        assert str(old_root).encode() in pyc.read_bytes()
        return old_root, site, pyc

    def test_pyc_carrying_build_prefix_is_removed_not_patched(self, tmp_path):
        import shutil

        from nanometa_live.core.workflow import conda_cache_utils as ccu

        old_root, _site, _pyc = self._env_with_compiled_module(tmp_path)
        new_root = tmp_path / "restored"
        shutil.move(str(old_root), str(new_root))
        stats = ccu.relocate_conda_cache(new_root, str(old_root))

        pyc = (new_root / "env-abc" / "lib" / "python3.12" / "site-packages"
               / "__pycache__" / "relocmod.cpython-312.pyc")
        assert not pyc.exists(), "a prefix-bearing .pyc must be deleted"
        assert stats["pyc_removed"] == 1
        assert stats["binary_patched"] == 0, (
            "the NUL-padded rewrite corrupts marshal data; it must not run on .pyc"
        )
        assert stats["failures"] == []

    def test_module_imports_after_relocation(self, tmp_path):
        import shutil
        import subprocess
        import sys

        from nanometa_live.core.workflow import conda_cache_utils as ccu

        old_root, _site, _pyc = self._env_with_compiled_module(tmp_path)
        new_root = tmp_path / "restored"
        shutil.move(str(old_root), str(new_root))
        ccu.relocate_conda_cache(new_root, str(old_root))

        site = new_root / "env-abc" / "lib" / "python3.12" / "site-packages"
        # A fresh interpreter, as the pipeline's tools would start: the only
        # thing on the path is the relocated site-packages.
        proc = subprocess.run(
            [sys.executable, "-I", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "import relocmod; print(relocmod.hello())", str(site)],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "relocated"

    def test_pyc_without_build_prefix_is_left_alone(self, tmp_path):
        from nanometa_live.core.workflow import conda_cache_utils as ccu

        cache = tmp_path / "cache"
        pycache = cache / "env-abc" / "lib" / "__pycache__"
        pycache.mkdir(parents=True)
        pyc = pycache / "clean.cpython-312.pyc"
        pyc.write_bytes(b"\xcb\r\r\n" + b"\x00" * 12 + b"no prefix here")
        stats = ccu.relocate_conda_cache(cache, "/some/old/prefix_" + "x" * 160)
        assert pyc.exists()
        assert stats["pyc_removed"] == 0
