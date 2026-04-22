"""Round-trip tests for the realtime_timeout_minutes config key.

Covers the four layers the key touches:
- ConfigLoader.create_default_config() ensures a default value
- config_validator coerces invalid values back to the default, keeps None
- create_nextflow_params forwards the value to Nextflow
- Validator accepts None (= run indefinitely) without overwriting

Follows up on audit item F12 (nanometanf default landed in 2026-04-21). The
GUI-side field was the remaining gap; these tests pin the integration so a
future callback refactor does not silently drop the key.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.config.config_validator import validate_config
from nanometa_live.core.config.parameter_mapping import create_nextflow_params


@pytest.fixture
def realtime_config(tmp_path):
    nanopore_dir = tmp_path / "watch"
    nanopore_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return {
        "nanopore_output_directory": str(nanopore_dir),
        "results_output_directory": str(results_dir),
        "kraken_db": str(tmp_path / "kraken_db"),
        "processing_mode": "realtime",
        "sample_handling": "by_barcode",
        "pipeline_profile": "conda",
        "pipeline_source": "remote:dev",
    }


class TestDefaultIncludesKey:
    def test_default_config_contains_realtime_timeout_minutes(self, tmp_path):
        loader = ConfigLoader(config_dir=str(tmp_path))
        defaults = loader.create_default_config()
        assert defaults["realtime_timeout_minutes"] == 60


class TestValidator:
    # validate_config raises on a completely empty dict, so seed each case with
    # a minimal-but-valid baseline and only vary realtime_timeout_minutes.
    @staticmethod
    def _run(extra):
        base = {"analysis_name": "TestRun"}
        base.update(extra)
        return validate_config(base)

    def test_validator_adds_default_when_missing(self):
        validated = self._run({})
        assert validated["realtime_timeout_minutes"] == 60

    def test_validator_preserves_none(self):
        validated = self._run({"realtime_timeout_minutes": None})
        assert validated["realtime_timeout_minutes"] is None

    def test_validator_preserves_valid_values(self):
        for value in (1, 30, 60, 1440, 10080):
            validated = self._run({"realtime_timeout_minutes": value})
            assert validated["realtime_timeout_minutes"] == value

    def test_validator_rejects_out_of_range_below(self):
        validated = self._run({"realtime_timeout_minutes": 0})
        assert validated["realtime_timeout_minutes"] == 60

    def test_validator_rejects_out_of_range_above(self):
        validated = self._run({"realtime_timeout_minutes": 10081})
        assert validated["realtime_timeout_minutes"] == 60

    def test_validator_rejects_non_integer(self):
        validated = self._run({"realtime_timeout_minutes": "sixty"})
        assert validated["realtime_timeout_minutes"] == 60

    def test_validator_rejects_bool(self):
        # True is an int subclass; make sure we guard against it.
        validated = self._run({"realtime_timeout_minutes": True})
        assert validated["realtime_timeout_minutes"] == 60


class TestParameterMappingPassthrough:
    def test_positive_value_reaches_nextflow_params(self, realtime_config):
        realtime_config["realtime_timeout_minutes"] = 30
        params = create_nextflow_params(realtime_config)
        assert params.get("realtime_timeout_minutes") == 30

    def test_large_value_reaches_nextflow_params(self, realtime_config):
        realtime_config["realtime_timeout_minutes"] = 1440
        params = create_nextflow_params(realtime_config)
        assert params["realtime_timeout_minutes"] == 1440

    def test_none_is_not_forwarded(self, realtime_config):
        # parameter_mapping guards with `if realtime_timeout:` so None/0 drop out.
        # None means "run indefinitely", which is nanometanf's default when the
        # param is absent.
        realtime_config["realtime_timeout_minutes"] = None
        params = create_nextflow_params(realtime_config)
        assert "realtime_timeout_minutes" not in params
