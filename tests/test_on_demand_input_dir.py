"""On-demand validation must refuse to run without the original FASTQs.

Validation re-reads the reads that were classified. When no input directory
was configured, the Nextflow command fell back to passing the *results*
directory as ``--reads_dir`` -- a directory that contains no FASTQ files. The
pipeline then matched nothing and, before it grew its own guards, completed
successfully having validated nothing.

Two subsystems had to agree for that to be safe, and neither was checking.
This pins the caller's half: refuse before launching, where the message can
reach the operator, rather than after a silent no-op run.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator

pytestmark = pytest.mark.unit


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    (d / "kraken2").mkdir(parents=True)
    return d


def _config(tmp_path):
    return {"pipeline_source": str(tmp_path / "nanometanf")}


class TestRefusesWithoutInputDirectory:
    def test_no_input_directory_returns_none(self, tmp_path, results_dir, caplog):
        """The regression: it used to substitute the results directory."""
        validator = OnDemandValidator(str(results_dir), input_dir=None)
        with caplog.at_level("ERROR"):
            result = validator.validate_via_nanometanf(
                taxid=1392, name="Bacillus anthracis", sample="barcode01",
                config=_config(tmp_path),
            )
        assert result is None
        assert "input directory" in caplog.text.lower()

    def test_missing_input_directory_returns_none(self, tmp_path, results_dir, caplog):
        """Configured but gone -- e.g. an unmounted USB drive in the field."""
        validator = OnDemandValidator(
            str(results_dir), input_dir=str(tmp_path / "unplugged"),
        )
        with caplog.at_level("ERROR"):
            result = validator.validate_via_nanometanf(
                taxid=1392, name="Bacillus anthracis", sample="barcode01",
                config=_config(tmp_path),
            )
        assert result is None
        assert "does not exist" in caplog.text.lower()

    def test_refusal_happens_before_launching_nextflow(
        self, tmp_path, results_dir
    ):
        """Failing fast is the point: no subprocess, no -resume cache churn."""
        validator = OnDemandValidator(str(results_dir), input_dir=None)
        with patch("subprocess.run") as run:
            validator.validate_via_nanometanf(
                taxid=1392, name="Bacillus anthracis", sample="barcode01",
                config=_config(tmp_path),
            )
        run.assert_not_called()

    def test_results_dir_is_never_passed_as_reads_dir(self, tmp_path, results_dir):
        """The specific substitution that made the failure silent."""
        import inspect

        source = inspect.getsource(OnDemandValidator.validate_via_nanometanf)
        assert "str(self.results_dir)," not in source.split("--reads_dir")[1][:120], (
            "results_dir is being passed as --reads_dir again; it holds no FASTQs"
        )
