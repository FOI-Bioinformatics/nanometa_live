"""On-demand validation must launch Nextflow in the main run's resume context.

``-resume`` resolves through two pieces of state that both live outside the
command line: the run history in ``<launch dir>/.nextflow/history`` and the
task cache under the ``-work-dir``. The main pipeline launches from
``data_dir`` with ``-work-dir <data_dir>/work``
(``NextflowManager.start_workflow`` / ``_run_workflow``). The on-demand
launcher passed ``-resume`` but neither of the two, so Nextflow ran from the
GUI process's arbitrary CWD with a work dir of ``./work``: it printed
"It appears you have never run this project before -- Option `-resume` is
ignored" and re-ran everything from scratch. Observed on the 2026-08-18
release-check run. The whole point of the on-demand path is that
previously-validated pairs cache-hit; without the shared context the cache
can never hit.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator


@pytest.fixture
def resume_config(tmp_path):
    pipeline = tmp_path / "pipeline_source"
    pipeline.mkdir(parents=True)
    (pipeline / "main.nf").write_text("// stub\n")
    return {
        "pipeline_source": str(pipeline),
        "pipeline_profile": "conda",
        "results_output_directory": str(tmp_path / "results"),
        "data_dir": str(tmp_path / "datadir"),
    }


def _launch(validator, config):
    mock_proc = MagicMock(pid=1234, returncode=1)  # fail fast; only the launch matters
    mock_proc.communicate.return_value = ("", "stubbed")
    with patch(
        "nanometa_live.core.workflow.on_demand_validator.subprocess.Popen",
        return_value=mock_proc,
    ) as mock_popen:
        validator.validate_via_nanometanf(
            taxid=263,
            name="Francisella tularensis",
            sample="barcode01",
            method="blast",
            config=config,
        )
    return mock_popen


class TestOnDemandResumeContext:
    def _validator(self, tmp_path):
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
        return validator

    def test_launches_with_main_runs_work_dir(self, tmp_path, resume_config):
        mock_popen = self._launch_and_check(tmp_path, resume_config)
        cmd = mock_popen.call_args.args[0]
        assert "-work-dir" in cmd, (
            "no -work-dir: Nextflow defaults to ./work relative to the "
            "launch CWD, which is not where the main run's task cache lives, "
            "so -resume can never reuse it."
        )
        work_dir = cmd[cmd.index("-work-dir") + 1]
        assert work_dir == str(Path(resume_config["data_dir"]) / "work"), (
            "the on-demand work dir must be the SAME directory "
            "NextflowManager gives the main pipeline (<data_dir>/work); any "
            f"other path defeats -resume. Got: {work_dir}"
        )

    def test_launches_from_data_dir(self, tmp_path, resume_config):
        mock_popen = self._launch_and_check(tmp_path, resume_config)
        cwd = mock_popen.call_args.kwargs.get("cwd")
        assert cwd == resume_config["data_dir"], (
            "-resume resolves the previous run through "
            "<launch dir>/.nextflow/history; the main pipeline launches from "
            "data_dir, so the on-demand run must too. Launching from the app "
            "process CWD prints 'It appears you have never run this project "
            f"before' and ignores -resume. Got cwd={cwd!r}"
        )

    def _launch_and_check(self, tmp_path, resume_config):
        validator = self._validator(tmp_path)
        mock_popen = _launch(validator, resume_config)
        assert mock_popen.called, (
            "validate_via_nanometanf did not reach subprocess.Popen; the "
            "test needs updating to match the current preconditions."
        )
        return mock_popen
