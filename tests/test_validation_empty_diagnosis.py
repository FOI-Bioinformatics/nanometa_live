"""A validation run that confirmed nothing must say why.

Found auditing the Validation tab (2026-08-18) against a real run whose
watched organisms had no reference genomes: the pipeline wrote
``validation/validation_results.json`` with ``"results": {}``, so
``has_validation_data()`` was true, the diagnostic path was skipped, and the
callback returned a bare empty payload. The BLAST panel then showed the
generic "No BLAST validation results available" -- which reads as "BLAST ran
and confirmed nothing" when the truth is "BLAST had nothing to run against".

The diagnostic machinery already distinguishes these (codes ``disabled``,
``no_species``, ``missing_dbs``, ``running_batch`` ...); the empty-after-parse
path simply never consulted it. Same doctrine as the verdict banner: a
missing measurement must not render as a negative result.
"""

import json

import pytest
from dash import Dash
from unittest.mock import MagicMock, patch

from tests.dash_test_utils import get_callback_fn

pytestmark = pytest.mark.callback


@pytest.fixture
def app():
    from nanometa_live.app.tabs.validation_tab import register_validation_callbacks
    a = Dash(__name__, suppress_callback_exceptions=True)
    register_validation_callbacks(a)
    return a


@pytest.fixture
def ran_but_empty(tmp_path):
    """A results tree where validation executed and confirmed nothing."""
    vdir = tmp_path / "validation"
    vdir.mkdir(parents=True)
    (vdir / "validation_results.json").write_text(json.dumps({
        "pipeline_version": "1.6.1",
        "validation_method": "both",
        "results": {},
        "summary": {"total_samples": 0, "total_taxids_validated": 0},
    }))
    (vdir / "validation_summary.tsv").write_text(
        "sample_id\ttaxid\tspecies\tmethod\tstatus\n")
    return tmp_path


def _load(app, config):
    import nanometa_live.app.tabs.validation_tab as vt
    fn = get_callback_fn(app, "validation-data-store",
                         input_contains="results-fingerprint")
    with patch.object(vt, "ctx", MagicMock(triggered_id="results-fingerprint",
                                           triggered=[{"prop_id": "x"}])):
        return fn({"fp": "1"}, None, 0, "cumulative", None, config, None)


class TestEmptyAfterParseIsDiagnosed:
    def test_store_carries_a_diagnostic_status(self, app, ran_but_empty):
        store = _load(app, {
            "blast_validation": True,
            "validation_method": "both",
            "results_output_directory": str(ran_but_empty),
        })
        assert store["results"] == []
        assert store.get("status"), (
            "an empty parse must still carry the diagnostic payload -- "
            "without it the panel cannot say why nothing was confirmed")
        assert store["status"].get("code"), "diagnostic code missing"

    def test_panel_does_not_imply_blast_ran(self, app, ran_but_empty):
        store = _load(app, {
            "blast_validation": True,
            "validation_method": "both",
            "results_output_directory": str(ran_but_empty),
        })
        _style, message, _sec = get_callback_fn(app, "blast-empty-message")(
            store, {"blast_validation": True, "validation_method": "both",
                    "results_output_directory": str(ran_but_empty)})
        text = str(message)
        # The generic wording is what made "could not run" look like
        # "ran and found nothing".
        assert "No BLAST validation results available." not in text, (
            "empty-after-parse still shows the undiagnosed generic message")

    def test_disabled_still_diagnosed(self, app, ran_but_empty):
        # Regression guard for the path that already worked.
        store = _load(app, {
            "blast_validation": False,
            "validation_method": "minimap2",
            "results_output_directory": str(ran_but_empty),
        })
        assert store["status"]["code"] == "disabled"

    def test_populated_run_is_untouched(self, app, tmp_path):
        # A tree with real results must not acquire an empty-state payload.
        vdir = tmp_path / "validation" / "blast"
        vdir.mkdir(parents=True)
        (vdir / "bc01_taxid263.blast.tsv").write_text(
            "read1\tNZ_CP009607.1\t99.0\t500\t2\t0\t1\t500\t10\t510\t1e-50\t900\n")
        store = _load(app, {
            "blast_validation": True,
            "validation_method": "both",
            "results_output_directory": str(tmp_path),
        })
        assert store["results"], "real blast.tsv results must still load"
        assert store.get("message") is None
