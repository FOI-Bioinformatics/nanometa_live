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
    writes last). An incomplete env is missing that marker, exactly
    like a build that was killed by SIGTERM partway through.
    """
    env = parent / name
    (env / "conda-meta").mkdir(parents=True)
    (env / "bin").mkdir()
    if complete:
        (env / "conda-meta" / "history").write_text("# fake history\n")
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
