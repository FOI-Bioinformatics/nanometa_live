"""``save_reads_assignment`` / ``save_output_fastqs`` follow the config
(audit finding 4, GUI side).

They were sent only when watchlist validation ran, so a config that asked
for them explicitly -- the on-demand check reads exactly these files --
produced neither.
"""

import pytest

from nanometa_live.core.config.parameter_mapping import create_nextflow_params

pytestmark = pytest.mark.unit


@pytest.fixture
def config(tmp_path):
    nanopore_dir = tmp_path / "input"
    nanopore_dir.mkdir()
    (nanopore_dir / "sample1.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return {
        "nanopore_output_directory": str(nanopore_dir),
        "results_output_directory": str(results_dir),
        "kraken_db": str(tmp_path / "kraken2_db"),
        "processing_mode": "batch",
        "sample_handling": "single_sample",
        "sample_name": "test_sample",
        "analysis_name": "TestRun",
        "blast_validation": False,
    }


def test_explicit_config_values_are_honoured_without_validation(config):
    config["save_reads_assignment"] = True
    config["save_output_fastqs"] = True
    params = create_nextflow_params(config)
    assert params["run_validation"] is False
    assert params["save_reads_assignment"] is True
    assert params["save_output_fastqs"] is True


def test_default_without_validation_stays_off(config):
    params = create_nextflow_params(config)
    assert params["save_reads_assignment"] is False
    assert params["save_output_fastqs"] is False


def test_one_can_be_requested_alone(config):
    config["save_reads_assignment"] = True
    params = create_nextflow_params(config)
    assert params["save_reads_assignment"] is True
    assert params["save_output_fastqs"] is False
