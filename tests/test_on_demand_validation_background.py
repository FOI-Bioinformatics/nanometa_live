"""Tests for the on-demand validation callback after its conversion to a
background callback (P1 background-callback audit finding).

The Organisms-tab "Validate" button shells out to BLAST/minimap2/nextflow for
minutes; it now runs in a DiskcacheManager worker. It has no Python-singleton
side effect -- its only state output is the results dcc.Store, which crosses
back to the main process fine -- so it is a plain background callback (no
separate finalize). These tests cover the pure result helpers, that the
callback is registered background, and its success/failure/no-data branches.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash_test_utils import get_callback_fn, make_callback_app
from nanometa_live.app.tabs.main_tab import register_main_callbacks
from nanometa_live.app.tabs.main_tab_helpers import (
    render_validation_results_card,
    validation_store_entry,
)


def _result(rate=92.0):
    return SimpleNamespace(
        success=True, validation_rate=rate, validated_reads=100,
        extracted_reads=110, avg_identity=98.5, total_classified_reads=1000,
        error_message="",
    )


@pytest.fixture
def app():
    return make_callback_app(register_main_callbacks)


def _spec(app):
    for cb_id, spec in app.callback_map.items():
        if "on-demand-validation-results" in cb_id and \
                "start-on-demand-validation" in str(spec.get("inputs")):
            return spec
    raise AssertionError("validation callback not found")


class TestValidationResultHelpers:
    def test_card_shows_rate_and_verified_badge(self):
        card = render_validation_results_card(_result(rate=92.0))
        s = str(card)
        assert "92.0%" in s and "Validation Results" in s and "BLAST Verified" in s

    def test_card_badge_degrades_with_rate(self):
        assert "Partial Match" in str(render_validation_results_card(_result(rate=60.0)))
        assert "Low Match" in str(render_validation_results_card(_result(rate=10.0)))

    def test_store_entry_is_plain_dict(self):
        entry = validation_store_entry(_result(rate=88.0), 562, "E. coli")
        assert entry == {
            "taxid": 562, "name": "E. coli", "validation_rate": 88.0,
            "validated_reads": 100, "extracted_reads": 110,
            "avg_identity": 98.5, "success": True,
        }


class TestOnDemandValidationCallback:
    def _fn(self, app):
        return get_callback_fn(
            app, "on-demand-validation-results.data",
            input_contains="start-on-demand-validation",
        )

    def _results_dir(self, tmp_path):
        r = tmp_path / "results"
        (r / "kraken2").mkdir(parents=True)
        (r / "kraken2" / "sample.kraken2").write_text("x")
        return r

    def test_registered_as_background(self, app):
        assert _spec(app).get("background"), \
            "run_on_demand_validation must be a background callback"

    def test_success_renders_card_and_writes_store(self, app, tmp_path):
        results = self._results_dir(tmp_path)
        validator = MagicMock()
        validator.validate_organism.return_value = _result(rate=92.0)
        set_progress = MagicMock()
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.OnDemandValidator",
            return_value=validator,
        ):
            out = self._fn(app)(
                set_progress, 1,
                {"taxid": 562, "name": "E. coli", "sample": "all"},
                {"results_output_directory": str(results)}, {}, "blast",
            )
        # 9-tuple; [8]=results store, [3]=results card, [4]=section style
        assert out[8]["562"]["validation_rate"] == 92.0
        assert "Validation Results" in str(out[3])
        assert out[4] == {"display": "block"}
        assert set_progress.called   # streamed a status line while running

    def test_missing_kraken_output_reports_error(self, app, tmp_path):
        results = tmp_path / "results"
        results.mkdir()  # no kraken2/ dir -> no per-read output
        out = self._fn(app)(
            MagicMock(), 1,
            {"taxid": 562, "name": "x", "sample": "all"},
            {"results_output_directory": str(results)}, {}, "blast",
        )
        assert "not found" in str(out[1]).lower()

    def test_validation_failure_reports_error(self, app, tmp_path):
        results = self._results_dir(tmp_path)
        validator = MagicMock()
        validator.validate_organism.return_value = SimpleNamespace(
            success=False, error_message="boom")
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.OnDemandValidator",
            return_value=validator,
        ):
            out = self._fn(app)(
                MagicMock(), 1,
                {"taxid": 562, "name": "x", "sample": "all"},
                {"results_output_directory": str(results)}, {}, "blast",
            )
        assert "boom" in str(out[1])
