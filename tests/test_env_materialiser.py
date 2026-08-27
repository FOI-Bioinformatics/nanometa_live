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
