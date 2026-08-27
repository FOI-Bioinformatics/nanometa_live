"""Regression test for the half-built-conda-env issue surfaced by the
2026-05-06 audit.

Symptom: scenario 2 was killed mid-conda-build by `pkill`, leaving
`<work>/conda/env-<hash>/` with only `conda-meta/` and no `history`
file. Subsequent runs of nanometa-live found the directory already
present, told Nextflow to skip the build, activated the empty env,
and the MULTIQC process failed with `multiqc: command not found`
(exit 127) -- silently breaking three of five test scenarios.

The defensive sweep removes half-built env dirs at the start of
every conda-profile run so Nextflow rebuilds them.
"""

from __future__ import annotations

from pathlib import Path

from nanometa_live.core.workflow.nextflow_manager import NextflowManager


def _make_env(parent: Path, name: str, *, complete: bool) -> Path:
    """Build a fake conda env directory under parent.

    A complete env carries a `conda-meta/history` file (which conda
    writes last) AND at least one executable under `bin/`. An incomplete
    env is missing the marker (build killed by SIGTERM partway through)
    or has an empty `bin/` (build that wrote history but installed no
    binaries, e.g. conda aborting on an AppleDouble-corrupted file).
    """
    env = parent / name
    (env / "conda-meta").mkdir(parents=True)
    (env / "bin").mkdir()
    if complete:
        (env / "conda-meta" / "history").write_text("# fake history\n")
        (env / "bin" / "tool").write_text("#!/bin/sh\n")
    return env


class TestPurgeBrokenCondaEnvs:
    def test_no_op_when_no_conda_cache(self, tmp_path):
        # Fresh data_dir without any conda subdirectory yet.
        assert NextflowManager._purge_broken_conda_envs(str(tmp_path)) == []

    def test_no_op_when_conda_cache_empty(self, tmp_path):
        (tmp_path / "conda").mkdir()
        assert NextflowManager._purge_broken_conda_envs(str(tmp_path)) == []

    def test_complete_env_preserved(self, tmp_path):
        cache = tmp_path / "conda"
        cache.mkdir()
        env = _make_env(cache, "env-abc123", complete=True)

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == []
        assert env.exists()
        assert (env / "conda-meta" / "history").exists()

    def test_broken_env_removed(self, tmp_path):
        cache = tmp_path / "conda"
        cache.mkdir()
        env = _make_env(cache, "env-broken", complete=False)

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == [str(env)]
        assert not env.exists()

    def test_mixed_envs_only_broken_removed(self, tmp_path):
        cache = tmp_path / "conda"
        cache.mkdir()
        good = _make_env(cache, "env-good", complete=True)
        bad = _make_env(cache, "env-bad", complete=False)

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == [str(bad)]
        assert good.exists()
        assert (good / "conda-meta" / "history").exists()
        assert not bad.exists()

    def test_non_env_subdirs_are_skipped(self, tmp_path):
        # Anything that isn't an env-* subdir should be left alone --
        # users may stash custom data alongside Nextflow's cache.
        cache = tmp_path / "conda"
        cache.mkdir()
        unrelated = cache / "user_notes.txt"
        unrelated.write_text("keep me")
        custom_dir = cache / "my_custom_dir"
        custom_dir.mkdir()
        (custom_dir / "important").write_text("data")

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == []
        assert unrelated.exists()
        assert (custom_dir / "important").exists()

    def test_empty_env_dir_is_treated_as_broken(self, tmp_path):
        # The exact failure mode observed in the 2026-05-06 audit:
        # only `conda-meta/` exists, no `history`, `bin/` empty.
        cache = tmp_path / "conda"
        cache.mkdir()
        env = cache / "env-2654238d16ef23fd95a83c884a662977"
        (env / "conda-meta").mkdir(parents=True)

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == [str(env)]
        assert not env.exists()

    def test_history_but_empty_bin_is_broken(self, tmp_path):
        # A build that wrote the history marker but installed no binaries
        # (e.g. conda aborting on an AppleDouble-corrupted conda-meta file):
        # the env activates but every tool is "command not found" (exit 127).
        cache = tmp_path / "conda"
        cache.mkdir()
        env = cache / "env-deadbeef"
        (env / "conda-meta").mkdir(parents=True)
        (env / "bin").mkdir()
        (env / "conda-meta" / "history").write_text("# fake history\n")

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == [str(env)]
        assert not env.exists()


class TestStripAppleDoubleFiles:
    def test_no_op_when_no_conda_cache(self, tmp_path):
        assert NextflowManager._strip_appledouble_files(str(tmp_path)) == 0

    def test_strips_appledouble_from_conda_meta(self, tmp_path):
        cache = tmp_path / "conda"
        env = cache / "env-abc" / "conda-meta"
        env.mkdir(parents=True)
        (env / "gzip-1.13.json").write_text("{}")
        (env / "._gzip-1.13.json").write_text("appledouble")
        (cache / "env-abc" / "._conda-meta").write_text("appledouble")

        count = NextflowManager._strip_appledouble_files(str(tmp_path))

        assert count == 2
        assert (env / "gzip-1.13.json").exists()  # real file untouched
        assert not (env / "._gzip-1.13.json").exists()


class TestSweepCoversBundledCache:
    """2026-08-27 audit, conda finding 5: the launch-time sweep only ever
    looked at <work_dir>/conda, but with NXF_CONDA_CACHEDIR pointing at a
    restored bundle cache Nextflow never uses work_dir/conda -- so the one
    cache actually in play was the one never swept."""

    def test_direct_conda_dir_form(self, tmp_path):
        cache = tmp_path / "bundle_cache"
        cache.mkdir()
        good = _make_env(cache, "env-good", complete=True)
        bad = _make_env(cache, "env-bad", complete=False)

        removed = NextflowManager._purge_broken_conda_envs(conda_dir=str(cache))

        assert removed == [str(bad)]
        assert good.exists()

    def test_named_env_with_conda_meta_is_swept(self, tmp_path):
        # Nextflow names an env from environment.yml's `name:` key when one
        # is declared; four nanometanf local modules do. A broken NAMED env
        # must be swept even though it lacks the env- prefix. A plain custom
        # directory (no conda-meta/) stays untouched.
        cache = tmp_path / "conda"
        cache.mkdir()
        named_broken = _make_env(cache, "seqkit_merge_stats-abc123", complete=False)
        custom = cache / "my_custom_dir"
        custom.mkdir()
        (custom / "important").write_text("data")

        removed = NextflowManager._purge_broken_conda_envs(str(tmp_path))

        assert removed == [str(named_broken)]
        assert (custom / "important").exists()

    def test_sweep_conda_caches_covers_both(self, tmp_path):
        work = tmp_path / "work"
        (work / "conda").mkdir(parents=True)
        work_bad = _make_env(work / "conda", "env-workbad", complete=False)
        bundle_cache = tmp_path / "conda_cache"
        bundle_cache.mkdir()
        bundle_bad = _make_env(bundle_cache, "env-bundlebad", complete=False)

        mgr = NextflowManager.__new__(NextflowManager)
        mgr.work_dir = str(work)
        mgr._run_config = {"nxf_conda_cachedir": str(bundle_cache)}

        removed = mgr._sweep_conda_caches()

        assert not work_bad.exists()
        assert not bundle_bad.exists()
        assert sorted(removed) == sorted([str(work_bad), str(bundle_bad)])
