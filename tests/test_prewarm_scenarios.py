"""Pre-warm scenarios must drive parameters nanometanf actually has.

The 2026-08-27 audit found the scenario registry passing nanometa_live
CONFIG keys (``processing_mode``, ``sample_handling``) straight to
``nextflow run`` -- nanometanf has neither parameter, so all "realtime"
scenarios were byte-identical to batch and the realtime-only envs were
never built. The validation scenarios passed no ``kraken2_db``, and in
nanometanf the VALIDATION subworkflow is nested inside the
``if (params.kraken2_db && !params.skip_kraken2)`` branch -- so the
BLAST/minimap2 envs were never built either, while the scenario exited 0.

Contract pinned here:

- no scenario carries a key the pipeline schema does not define
  (``processing_mode`` / ``sample_handling`` are the offenders);
- the realtime scenario passes ``realtime_mode`` with a termination bound
  (``max_files``), and the runner supplies ``--nanopore_output_dir``
  pointing at a watch directory that already holds a FASTQ, WITHOUT
  ``--input`` (realtime discovers files, it does not take a samplesheet);
- every scenario gets a Kraken2 database: a locally written stub directory
  holding the three ``.k2d`` files, so the classification (and therefore
  validation) branch instantiates under ``-stub``;
- the untar scenario references a locally built ``tar.gz`` of that stub
  DB, never a network URL (export must work on an offline build machine).
"""

import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.utils.kraken_utils import KRAKEN_REQUIRED_FILES
from nanometa_live.core.workflow.bundle_manager import (
    _LOCAL_STUB_DB_ARCHIVE,
    _PRE_WARM_SCENARIOS,
    BundleManager,
)

pytestmark = pytest.mark.unit

# Keys that exist only in nanometa_live's config vocabulary. nf-schema
# merely WARNS on unknown params, so passing these succeeds while doing
# nothing -- the worst failure shape.
_NON_PIPELINE_KEYS = {"processing_mode", "sample_handling"}


def _scenario(name):
    matches = [s for s in _PRE_WARM_SCENARIOS if s["name"] == name]
    assert matches, f"scenario '{name}' missing from _PRE_WARM_SCENARIOS"
    return matches[0]


class TestScenarioRegistry:
    def test_no_scenario_uses_config_vocabulary_keys(self):
        for scenario in _PRE_WARM_SCENARIOS:
            offending = _NON_PIPELINE_KEYS & set(scenario.get("params", {}))
            assert not offending, (
                f"scenario '{scenario['name']}' passes {sorted(offending)} "
                "which nanometanf does not define; nf-schema warns and "
                "ignores them, so the scenario silently degenerates"
            )

    def test_realtime_scenario_terminates_via_max_files(self):
        rt = _scenario("realtime")
        params = rt["params"]
        # Real JSON types: params travel via -params-file because the
        # strict parser + nf-schema reject string-typed CLI booleans/ints.
        assert params.get("realtime_mode") is True
        assert params.get("max_files") == 1, (
            "an unbounded realtime watch never exits and burns the whole "
            "pre-warm timeout"
        )

    def test_validation_scenarios_present(self):
        for name in ("validation_blast", "validation_minimap2"):
            params = _scenario(name)["params"]
            assert params.get("run_validation") is True

    def test_untar_scenario_uses_local_archive_not_url(self):
        params = _scenario("untar_kraken2_db")["params"]
        value = str(params.get("kraken2_db", ""))
        assert value == _LOCAL_STUB_DB_ARCHIVE
        for scenario in _PRE_WARM_SCENARIOS:
            for v in scenario.get("params", {}).values():
                assert "http://" not in str(v) and "https://" not in str(v), (
                    f"scenario '{scenario['name']}' depends on the network "
                    "at export time"
                )


class TestScenarioRunnerCommands:
    """Drive _run_pre_warm_scenario with a mocked subprocess and inspect
    the exact command line it would hand to Nextflow."""

    def _run(self, tmp_path, scenario):
        pipeline = tmp_path / "pipeline"
        pipeline.mkdir(exist_ok=True)
        (pipeline / "main.nf").write_text("workflow {}\n")
        staging = tmp_path / "staging"
        staging.mkdir(exist_ok=True)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch(
            "subprocess.run",
            side_effect=fake_run,
        ):
            ok, msg = BundleManager._run_pre_warm_scenario(
                scenario=scenario,
                pipeline_dir=pipeline,
                staging=staging,
                env={"NXF_CONDA_CACHEDIR": str(tmp_path / "cache")},
            )
        assert ok, msg
        return captured["cmd"]

    @staticmethod
    def _params(cmd):
        import json as _json

        assert "-params-file" in cmd, (
            "params must travel as a typed -params-file: strict-parser CLI "
            "params arrive as strings and fail nf-schema type validation"
        )
        params_path = cmd[cmd.index("-params-file") + 1]
        return _json.loads(Path(params_path).read_text())

    def test_batch_scenario_gets_stub_kraken_db_and_samplesheet(self, tmp_path):
        cmd = self._run(tmp_path, _scenario("batch_default"))
        params = self._params(cmd)
        db_dir = Path(params["kraken2_db"])
        assert db_dir.is_dir()
        for required in KRAKEN_REQUIRED_FILES:
            assert (db_dir / required).exists()
        assert "input" in params

    def test_realtime_scenario_watches_a_prepared_dir_without_input(
        self, tmp_path
    ):
        cmd = self._run(tmp_path, _scenario("realtime"))
        params = self._params(cmd)
        assert "input" not in params, (
            "realtime mode discovers files from nanopore_output_dir; a "
            "samplesheet param contradicts it"
        )
        watch_dir = Path(params["nanopore_output_dir"])
        assert watch_dir.is_dir()
        assert list(watch_dir.glob("*.fastq.gz")), (
            "the watch dir must be pre-seeded or max_files=1 never fires"
        )
        assert params["max_files"] == 1
        assert params["realtime_mode"] is True
        # Realtime classification is also gated on kraken2_db.
        assert "kraken2_db" in params

    def test_validation_scenario_gets_stub_db(self, tmp_path):
        cmd = self._run(tmp_path, _scenario("validation_blast"))
        params = self._params(cmd)
        db_dir = Path(params["kraken2_db"])
        for required in KRAKEN_REQUIRED_FILES:
            assert (db_dir / required).exists()
        assert "pathogen_genomes" in params
        assert params["run_validation"] is True

    def test_untar_scenario_builds_local_archive(self, tmp_path):
        cmd = self._run(tmp_path, _scenario("untar_kraken2_db"))
        archive = Path(self._params(cmd)["kraken2_db"])
        assert archive.name.endswith(".tar.gz")
        assert archive.is_file()
        with tarfile.open(str(archive), "r:gz") as tar:
            names = tar.getnames()
        for required in KRAKEN_REQUIRED_FILES:
            assert any(n.endswith(required) for n in names)
