"""On-demand validation launches under the machine's ceilings and saves its
result atomically under the key it reads back (audit findings 32 and 35).
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.config import parameter_mapping as pm
from nanometa_live.core.workflow import on_demand_validator as odv
from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator
from nanometa_live.core.workflow.validation_models import ValidationJob

pytestmark = pytest.mark.unit


@pytest.fixture
def launch_config(tmp_path):
    pipeline = tmp_path / "pipeline_source"
    pipeline.mkdir(parents=True)
    (pipeline / "main.nf").write_text("// stub\n")
    return {
        "pipeline_source": str(pipeline),
        "pipeline_profile": "conda",
        "results_output_directory": str(tmp_path / "results"),
        "data_dir": str(tmp_path / "datadir"),
        "max_cpus": 6,
    }


def _validator(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "barcode01.fastq").write_text("@r1\nACGT\n+\nIIII\n")
    v = OnDemandValidator(
        results_dir=str(tmp_path / "results"),
        input_dir=str(input_dir),
        cache_dir=str(tmp_path / "cache"),
    )
    v.genomes_dir.mkdir(parents=True, exist_ok=True)
    (v.genomes_dir / "263.fasta").write_text(">NC_1 F. tularensis\nACGTACGTACGTACGTACGT\n")
    return v


def _launch(validator, config):
    proc = MagicMock(pid=1234, returncode=1)
    proc.communicate.return_value = ("", "stubbed")
    with patch.object(odv.subprocess, "Popen", return_value=proc) as popen:
        validator.validate_via_nanometanf(
            taxid=263, name="Francisella tularensis", sample="barcode01",
            method="blast", config=config,
        )
    assert popen.called
    return popen.call_args.args[0]


class TestResourceCeilingsTravel:
    def test_command_carries_the_main_launch_ceilings(self, tmp_path, launch_config):
        cmd = _launch(_validator(tmp_path), launch_config)
        expected = pm.resource_ceiling_params(launch_config)
        assert "max_memory" in expected, "the host ceiling must resolve on this machine"
        assert cmd[cmd.index("--max_cpus") + 1] == "6"
        assert cmd[cmd.index("--max_memory") + 1] == expected["max_memory"]

    def test_main_launch_sends_the_same_pair(self, tmp_path, launch_config):
        # One resolver for both launches: the main params and the on-demand
        # command cannot disagree about the ceiling.
        ceilings = pm.resource_ceiling_params(launch_config)
        assert ceilings["max_cpus"] == 6
        assert ceilings["max_memory"].endswith(".GB") or ceilings["max_memory"].endswith("GB")
        explicit = pm.resource_ceiling_params({"max_memory": "24.GB"})
        assert explicit == {"max_memory": "24.GB"}

    def test_no_cpu_setting_sends_no_max_cpus(self, tmp_path, launch_config):
        launch_config.pop("max_cpus")
        cmd = _launch(_validator(tmp_path), launch_config)
        assert "--max_cpus" not in cmd
        assert "--max_memory" in cmd


class TestSaveResultsAtomicAndReadable:
    def _job(self):
        job = ValidationJob(taxid=562, name="E. coli", sample="bc01")
        job.total_reads = 100
        job.extracted_reads = 90
        job.validated_reads = 80
        job.validation_rate = 88.9
        job.avg_identity = 97.5
        job.completed_at = datetime(2026, 11, 7, 12, 0, 0)
        return job

    def test_round_trip_keeps_the_rate(self, tmp_path):
        v = _validator(tmp_path)
        v._save_results(self._job(), method="blast")
        loaded = v.load_validation_result(562, "bc01")
        assert loaded is not None
        assert loaded.validation_rate == pytest.approx(88.9)
        data = json.loads((v.validation_dir / "bc01_562_validation.json").read_text())
        assert data["validation_rate"] == data["percent_validated"] == pytest.approx(88.9)

    def test_legacy_file_without_the_key_still_loads(self, tmp_path):
        v = _validator(tmp_path)
        v.validation_dir.mkdir(parents=True, exist_ok=True)
        (v.validation_dir / "bc01_562_validation.json").write_text(json.dumps({
            "taxid": 562, "name": "E. coli", "sample": "bc01",
            "percent_validated": 42.0,
        }))
        assert v.load_validation_result(562, "bc01").validation_rate == pytest.approx(42.0)

    def test_write_is_atomic(self, tmp_path, monkeypatch):
        v = _validator(tmp_path)
        calls = []
        real = odv.atomic_write_json

        def _spy(path, data, **kw):
            calls.append(Path(path))
            real(path, data, **kw)
        monkeypatch.setattr(odv, "atomic_write_json", _spy)
        v._save_results(self._job(), method="blast")
        assert calls == [v.validation_dir / "bc01_562_validation.json"]
        leftovers = [p for p in v.validation_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []
