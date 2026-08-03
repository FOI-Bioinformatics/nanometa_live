"""On-demand validation must launch Nextflow with the offline environment.

``NextflowManager._build_nextflow_env`` is where every offline guarantee for a
pipeline run lives: ``NXF_OFFLINE``, ``NXF_PLUGINS_PATH`` (the variable that
actually suppresses the plugin-registry probe), ``NXF_CONDA_CACHEDIR`` and
``NXF_SINGULARITY_CACHEDIR``.

``OnDemandValidator.validate_via_nanometanf`` launched its own
``nextflow run`` with ``subprocess.run(cmd, ...)`` and no ``env=`` at all, so it
inherited the bare app environment and none of those variables. On an
air-gapped field machine that run reaches for the plugin registry and the
container registry and fails -- while the main pipeline, launched through
``NextflowManager``, works. Clicking "validate" is a normal operator action, so
this is a live path, not a corner.

The test drives the real method with a stubbed ``subprocess.run`` and asserts on
the environment it was handed.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator


@pytest.fixture
def offline_config(tmp_path):
    plugins = tmp_path / "nextflow_plugins"
    (plugins / "nf-schema-2.6.1").mkdir(parents=True)
    sing = tmp_path / "pipeline_containers"
    sing.mkdir(parents=True)
    pipeline = tmp_path / "pipeline_source"
    pipeline.mkdir(parents=True)
    (pipeline / "main.nf").write_text("// stub\n")
    return {
        "offline_mode": True,
        "nxf_plugins_dir": str(plugins),
        "nxf_singularity_cachedir": str(sing),
        "pipeline_source": str(pipeline),
        "pipeline_profile": "singularity",
        "results_output_directory": str(tmp_path / "results"),
    }


class _Completed:
    returncode = 1  # fail fast; we only care about the env handed to Popen
    stdout = ""
    stderr = "stubbed"


def _run_validation(validator, config):
    """Drive the launcher far enough to reach subprocess.run."""
    with patch(
        "nanometa_live.core.workflow.on_demand_validator.subprocess.run",
        return_value=_Completed(),
    ) as mock_run:
        validator.validate_via_nanometanf(
            taxid=263,
            name="Francisella tularensis",
            sample="barcode01",
            method="blast",
            config=config,
        )
    return mock_run


class TestOnDemandValidationOfflineEnv:
    def test_subprocess_receives_offline_env(self, tmp_path, offline_config):
        # Preconditions the launcher checks before it will run: the original
        # FASTQ directory must exist, and the genome for the taxid must be a
        # readable FASTA (existence alone is deliberately not enough).
        input_dir = tmp_path / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "barcode01.fastq").write_text("@r1\nACGT\n+\nIIII\n")

        validator = OnDemandValidator(
            results_dir=str(tmp_path / "results"),
            input_dir=str(input_dir),
        )
        validator.genomes_dir.mkdir(parents=True, exist_ok=True)
        (validator.genomes_dir / "263.fasta").write_text(
            ">NC_000000.1 Francisella tularensis\nACGTACGTACGTACGTACGT\n"
        )
        mock_run = _run_validation(validator, offline_config)

        assert mock_run.called, (
            "validate_via_nanometanf did not reach subprocess.run; the test "
            "needs updating to match the current preconditions."
        )
        env = mock_run.call_args.kwargs.get("env")
        assert env is not None, (
            "nextflow was launched with no env=, so it inherited the bare app "
            "environment: no NXF_OFFLINE, no plugin path, no container cache. "
            "Air-gapped, this run reaches for the plugin registry."
        )
        assert env.get("NXF_OFFLINE") == "true", (
            "NXF_OFFLINE must be the literal string 'true' -- the Nextflow "
            f"bash launcher compares it by string equality. Got: {env.get('NXF_OFFLINE')!r}"
        )
        assert "NXF_PLUGINS_PATH" in env, (
            "NXF_PLUGINS_PATH is the variable that suppresses the registry "
            "probe; without it an offline run still tries to reach it."
        )
        assert "NXF_SINGULARITY_CACHEDIR" in env, (
            "Without the singularity cachedir Nextflow re-pulls images it was "
            "shipped, which cannot work with no network."
        )
