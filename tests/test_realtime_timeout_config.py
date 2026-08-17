"""Round-trip tests for the realtime_timeout_minutes config key.

Covers the two live layers the key touches:
- ConfigLoader.create_default_config() ensures a default value
- create_nextflow_params forwards the value to Nextflow, with an explicit
  None reaching the params file as JSON null (= run indefinitely)

Follows up on audit item F12 (nanometanf default landed in 2026-04-21). The
GUI-side field was the remaining gap; these tests pin the integration so a
future callback refactor does not silently drop the key.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.config.config_loader import ConfigLoader
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


# The former TestValidator class exercised core/config/config_validator.py,
# which was dead code in the live app (never called outside its own tests)
# with already-drifted defaults; it was deleted in the 2026-08-16 audit
# remediation. The live null-means-indefinite contract is pinned by
# TestParameterMappingPassthrough below and by create_default_config.


class TestParameterMappingPassthrough:
    def test_positive_value_reaches_nextflow_params(self, realtime_config):
        realtime_config["realtime_timeout_minutes"] = 30
        params = create_nextflow_params(realtime_config)
        assert params.get("realtime_timeout_minutes") == 30

    def test_large_value_reaches_nextflow_params(self, realtime_config):
        realtime_config["realtime_timeout_minutes"] = 1440
        params = create_nextflow_params(realtime_config)
        assert params["realtime_timeout_minutes"] == 1440

    def test_none_is_forwarded_as_null(self, realtime_config):
        # The old comment here claimed nanometanf defaults to indefinite when
        # the param is absent -- it does not: its default is 60 minutes, so
        # OMITTING the key silently reinstated a one-hour cutoff on a run the
        # operator configured to watch forever. An explicit None must reach
        # the params file as JSON null, which nanometanf documents and
        # handles as "run indefinitely" (audit 2026-08-16, finding L8).
        realtime_config["realtime_timeout_minutes"] = None
        params = create_nextflow_params(realtime_config)
        assert "realtime_timeout_minutes" in params
        assert params["realtime_timeout_minutes"] is None
