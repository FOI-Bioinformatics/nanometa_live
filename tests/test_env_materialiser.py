"""The module-env materialiser: every environment.yml gets an env.

Split from test_prewarm_scenarios.py because the other export tests mock
the materialiser (autouse fixture) -- these tests exercise it directly.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestModuleEnvMaterialisation:
    """Scenario stub runs cannot reach every process: nanometanf filters
    empty (stub-touched) files, so processes downstream of a content
    filter -- kraken2 and nanoplot in the 2026-08-27 field rehearsal --
    never fire and their envs never land in the cache. The materialiser
    generates a one-process-per-environment.yml stub workflow so Nextflow
    itself builds every module env, with the exact hash the runtime will
    look up."""

    def test_generated_workflow_covers_every_module_env(self, tmp_path):
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        pipeline = tmp_path / "pipeline"
        for mod in ("modules/nf-core/toola", "modules/local/toolb"):
            d = pipeline / mod
            d.mkdir(parents=True)
            (d / "environment.yml").write_text(
                f"channels: [bioconda]\ndependencies: [{mod.split('/')[-1]}]\n"
            )
        (pipeline / "main.nf").write_text("workflow {}\n")
        staging = tmp_path / "staging"
        staging.mkdir()
        captured = {}

        def fake_run(cmd, **kwargs):
            import subprocess as sp

            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        from unittest.mock import patch as _patch

        with _patch("subprocess.run", side_effect=fake_run):
            ok, msg, count = BundleManager._materialise_all_module_envs(
                pipeline_dir=pipeline,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(tmp_path / "cache")},
            )
        assert ok, msg
        assert count == 2
        cmd = captured["cmd"]
        assert "-stub" in cmd
        nf_path = Path(cmd[cmd.index("run") + 1])
        nf_text = nf_path.read_text()
        for mod in ("toola", "toolb"):
            assert f"{mod}/environment.yml" in nf_text

        # conda must be enabled for the generated run.
        config_text = (nf_path.parent / "nextflow.config").read_text()
        assert "conda.enabled = true" in config_text

    def test_no_module_envs_is_a_noop(self, tmp_path):
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        pipeline = tmp_path / "pipeline"
        pipeline.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        ok, msg, count = BundleManager._materialise_all_module_envs(
            pipeline_dir=pipeline,
            staging=staging,
            env={},
        )
        assert ok
        assert count == 0


class TestPerEnvFallback:
    """An env-creation failure aborts the whole Nextflow session --
    errorStrategy cannot contain it (CondaCache runs outside task error
    handling; verified live: porechop has no osx-arm64 build and its
    PackagesNotFoundError killed the batch sweep at 10/42). On batch
    failure the materialiser retries each env in its own run, so one
    platform hole costs one env, and the failures are NAMED."""

    def _pipeline(self, tmp_path, mods):
        pipeline = tmp_path / "pipeline"
        for mod in mods:
            d = pipeline / "modules" / mod
            d.mkdir(parents=True)
            (d / "environment.yml").write_text(
                f"channels: [bioconda]\ndependencies: [{mod}]\n"
            )
        (pipeline / "main.nf").write_text("workflow {}\n")
        return pipeline

    def test_batch_failure_falls_back_per_env_and_names_failures(self, tmp_path):
        import subprocess as sp
        from unittest.mock import patch as _patch

        from nanometa_live.core.workflow.bundle_manager import BundleManager

        pipeline = self._pipeline(tmp_path, ["gooda", "badb", "goodc"])
        staging = tmp_path / "staging"
        staging.mkdir()
        calls = []

        def fake_run(cmd, **kwargs):
            nf = Path(cmd[cmd.index("run") + 1]).read_text()
            calls.append(nf)
            if len(calls) == 1:
                # batch run: session aborts on the unsolvable env
                return sp.CompletedProcess(
                    cmd, 1, stdout="", stderr="Failed to create Conda environment"
                )
            rc = 1 if "badb" in nf else 0
            return sp.CompletedProcess(
                cmd, rc, stdout="",
                stderr="PackagesNotFoundError: badb" if rc else "",
            )

        with _patch("subprocess.run", side_effect=fake_run):
            ok, msg, count = BundleManager._materialise_all_module_envs(
                pipeline_dir=pipeline,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(tmp_path / "cache")},
            )
        assert count == 3
        assert ok is False
        assert "badb" in msg, "the unbuildable env must be NAMED"
        assert "gooda" not in msg and "goodc" not in msg
        # batch attempt + one isolated run per env
        assert len(calls) == 4

    def test_batch_success_skips_fallback(self, tmp_path):
        import subprocess as sp
        from unittest.mock import patch as _patch

        from nanometa_live.core.workflow.bundle_manager import BundleManager

        pipeline = self._pipeline(tmp_path, ["gooda"])
        staging = tmp_path / "staging"
        staging.mkdir()
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        with _patch("subprocess.run", side_effect=fake_run):
            ok, msg, count = BundleManager._materialise_all_module_envs(
                pipeline_dir=pipeline,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(tmp_path / "cache")},
            )
        assert ok and count == 1
        assert len(calls) == 1
