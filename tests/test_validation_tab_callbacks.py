"""Registered-callback tests for the Validation tab and the on-demand modal.

The pure helpers behind these callbacks are covered in
test_validation_tab_helpers.py; this module exercises the *registered* callback
functions themselves (extracted via dash_test_utils.get_callback_fn) so the
Input/Output wiring, the config gates, the fingerprint debounce, and the
batch/sample routing are verified against the Phase-0 synthetic validation tree.

ctx note (CLAUDE.md): validation_tab and main_tab do ``from dash import ctx``,
binding a module-local name, so the dash.ctx patch must target
``<module>.ctx`` rather than ``dash.ctx``.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from dash import Dash, no_update
from dash.exceptions import PreventUpdate

from tests.dash_test_utils import get_callback_fn
from tests.validation.generate_synthetic_data import generate_all_synthetic_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validation_app():
    from nanometa_live.app.tabs.validation_tab import register_validation_callbacks
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_validation_callbacks(app)
    return app


@pytest.fixture
def synth_results(tmp_path):
    """A populated results dir with the full validation tree."""
    generate_all_synthetic_data(tmp_path)
    return str(tmp_path)


@pytest.fixture
def enabled_config(synth_results):
    return {"blast_validation": True, "results_output_directory": synth_results}


@contextmanager
def _vt_ctx(triggered_id):
    """Patch validation_tab.ctx (module-local) with a given triggered_id."""
    import nanometa_live.app.tabs.validation_tab as vt
    with patch.object(vt, "ctx", MagicMock(triggered_id=triggered_id, triggered=[{"prop_id": "x"}])):
        yield


# ---------------------------------------------------------------------------
# load_validation_data
# ---------------------------------------------------------------------------

class TestLoadValidationData:
    def _fn(self, app):
        return get_callback_fn(app, "validation-data-store", input_contains="results-fingerprint")

    def test_disabled_config_returns_disabled_message(self, validation_app):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, None, 0, "cumulative", None,
                     {"blast_validation": False}, None)
        assert out["results"] == []
        assert "disabled" in out["message"].lower()
        assert out["status"]["code"] == "disabled"

    def test_no_config_returns_no_configuration(self, validation_app):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, None, 0, "cumulative", None, None, None)
        assert out["message"] == "No configuration loaded"

    def test_missing_results_dir(self, validation_app):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, None, 0, "cumulative", None,
                     {"blast_validation": True,
                      "results_output_directory": "/no/such/dir"}, None)
        assert "Results directory not found" in out["message"]
        assert out["status"]["code"] == "no_results_dir"

    def test_populated_returns_all_methods(self, validation_app, enabled_config):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, None, 0, "cumulative", None, enabled_config, None)
        assert out["message"] is None
        # 7 ValidationResults: both -> 2 (taxid 1773), blast x2 (1280, 562),
        # minimap2 x2 (1639, barcode05 TUL4 taxid 263), plus the on-disk blast.tsv
        # for barcode05/263 that the minimap2-only aggregate previously hid (now
        # merged in -- see TestAggregateWinsHidesBlast).
        assert len(out["results"]) == 7
        methods = {r["validation_method"] for r in out["results"]}
        assert {"both", "blast", "minimap2"} <= methods

    def test_sample_filter_narrows(self, validation_app, enabled_config):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, "barcode02", 0, "cumulative", None, enabled_config, None)
        assert out["results"], "barcode02 should have at least one result"
        assert all(r["sample_id"] == "barcode02" for r in out["results"])

    def test_batch_view_routes_through_batch_id(self, validation_app, enabled_config):
        fn = self._fn(validation_app)
        with _vt_ctx("results-fingerprint"):
            out = fn({"fp": "a"}, None, 0, "batch", "1", enabled_config, None)
        # batch 1 only carries taxid 1773 (blast + minimap2)
        assert out["results"]
        assert all(r["taxid"] == 1773 for r in out["results"])

    def test_redundant_interval_tick_prevented(self, validation_app, enabled_config):
        from nanometa_live.app.utils.debounce import mark_rendered, reset_debounce
        reset_debounce()
        fn = self._fn(validation_app)
        fp = {"fp": "same"}
        mark_rendered("load_validation_data", fp)
        with _vt_ctx("update-interval"):
            with pytest.raises(PreventUpdate):
                fn(fp, None, 5, "cumulative", None, enabled_config, None)


# ---------------------------------------------------------------------------
# Empty-state callbacks (BLAST + Coverage)
# ---------------------------------------------------------------------------

class TestEmptyStateCallbacks:
    def _blast_fn(self, app):
        return get_callback_fn(app, "blast-empty-message")

    def _cov_fn(self, app):
        return get_callback_fn(app, "coverage-empty-message")

    def _title(self, children):
        # EmptyStateMessage is a component; its title text is reachable via str()
        return str(children)

    def test_blast_disabled_state(self, validation_app):
        style, children, section = self._blast_fn(validation_app)(
            {"results": [], "message": "Validation is disabled. Enable it in Configuration tab."})
        assert style == {"display": "block"}
        assert "Disabled" in self._title(children)
        assert section == {"display": "none"}

    def test_blast_waiting_state(self, validation_app):
        style, children, section = self._blast_fn(validation_app)(
            {"results": [], "message": "Waiting for validation results from pipeline..."})
        assert "Awaiting" in self._title(children)

    def test_blast_has_results_hides_empty(self, validation_app):
        style, children, section = self._blast_fn(validation_app)(
            {"results": [{"validation_method": "blast", "species": "X"}]})
        assert style == {"display": "none"}
        assert section == {"display": "block"}

    def test_coverage_disabled_state(self, validation_app):
        style, children, section = self._cov_fn(validation_app)(
            {"results": [], "message": "Validation is disabled. Enable it in Configuration tab."})
        assert "Disabled" in self._title(children)

    def test_coverage_has_minimap2_results_shows_controls(self, validation_app):
        style, children, section = self._cov_fn(validation_app)(
            {"results": [{"validation_method": "minimap2", "species": "X"}]})
        assert style == {"display": "none"}
        assert section == {"display": "block"}


class TestBlastIdentityPlotEmptyStates:
    """C5: the identity plot must distinguish 'no BLAST results' from 'results
    examined but all zero-identity', so a tab full of rejected cards is not read
    as missing data."""

    def _fn(self, app):
        return get_callback_fn(app, "blast-identity-plot")

    def _msg(self, fig):
        return str(fig.layout.annotations[0].text) if fig.layout.annotations else ""

    def test_no_results_generic_message(self, validation_app):
        fig = self._fn(validation_app)({"results": []})
        assert "No identity data" in self._msg(fig)

    def test_all_zero_identity_examined_message(self, validation_app):
        # A real BLAST result that was examined but matched nothing (0 identity).
        data = {"results": [{"validation_method": "blast", "species": "E. coli",
                             "percent_identity_mean": 0.0, "status": "low_confidence"}]}
        fig = self._fn(validation_app)(data)
        assert "examined" in self._msg(fig).lower()

    def test_positive_identity_renders_bars(self, validation_app):
        data = {"results": [{"validation_method": "blast", "species": "E. coli",
                             "percent_identity_mean": 97.0}]}
        fig = self._fn(validation_app)(data)
        # A real bar trace, not the empty annotation.
        assert fig.data and len(fig.data[0].x) == 1


class TestBlastCardsStatusFilter:
    """C6: a status filter that matches nothing shows a clear message, not a
    silent blank."""

    def _fn(self, app):
        return get_callback_fn(app, "blast-results-container")

    def test_no_match_shows_message(self, validation_app):
        data = {"results": [{"validation_method": "blast", "species": "E. coli",
                             "status": "low_confidence", "percent_validated": 0}]}
        out = self._fn(validation_app)(data, "confirmed", "percent_validated", False)
        assert "No BLAST results match" in str(out)

    def test_matching_status_renders_cards(self, validation_app):
        data = {"results": [{"validation_method": "blast", "species": "E. coli",
                             "status": "confirmed", "percent_validated": 90,
                             "percent_identity_mean": 97.0}]}
        out = self._fn(validation_app)(data, "confirmed", "percent_validated", False)
        assert "No BLAST results match" not in str(out)


# ---------------------------------------------------------------------------
# update_coverage_plots
# ---------------------------------------------------------------------------

class TestCoveragePlots:
    def _fn(self, app):
        return get_callback_fn(app, "coverage-depth-plot")

    def test_no_selection_returns_empty_hidden(self, validation_app, enabled_config):
        depth, cum, hist, stats, style = self._fn(validation_app)(
            None, 0, 10, "cumulative", None, enabled_config)
        assert style == {"display": "none"}

    def test_cumulative_paf_renders_three_figures(self, validation_app, enabled_config):
        depth, cum, hist, stats, style = self._fn(validation_app)(
            "barcode01_1773", 0, 10, "cumulative", None, enabled_config)
        assert style == {"display": "block"}
        # Each figure should carry at least one trace built from the PAF.
        assert depth.data and cum.data and hist.data

    def test_batch_paf_renders(self, validation_app, enabled_config):
        depth, cum, hist, stats, style = self._fn(validation_app)(
            "barcode01_1773", 0, 10, "batch", "1", enabled_config)
        assert style == {"display": "block"}

    def test_missing_paf_shows_warning_visible(self, validation_app, enabled_config):
        # No PAF: the section must stay VISIBLE so the warning Alert (which lives
        # inside coverage-plots-section) is actually shown, not swallowed.
        depth, cum, hist, stats, style = self._fn(validation_app)(
            "barcode99_9999", 0, 10, "cumulative", None, enabled_config)
        assert style == {"display": "block"}
        assert "No PAF file" in str(stats)

    def test_negative_depth_threshold_sanitized(self, validation_app, enabled_config):
        # A negative or None threshold must not raise; it clamps internally.
        depth, cum, hist, stats, style = self._fn(validation_app)(
            "barcode01_1773", 0, -5, "cumulative", None, enabled_config)
        assert style == {"display": "block"}


# ---------------------------------------------------------------------------
# populate_validation_batch_selector
# ---------------------------------------------------------------------------

class TestBatchSelector:
    def _fn(self, app):
        return get_callback_fn(app, "validation-batch-selector")

    def test_hidden_when_no_batch_dir(self, validation_app, tmp_path):
        # A results dir with no validation/.../batch tree.
        (tmp_path / "validation").mkdir()
        fn = self._fn(validation_app)
        controls, col, options, value = fn(
            {"fp": "a"}, "cumulative",
            {"results_output_directory": str(tmp_path)}, None)
        assert controls == {"display": "none"}
        assert options == []

    def test_populated_with_numeric_labels(self, validation_app, enabled_config):
        fn = self._fn(validation_app)
        controls, col, options, value = fn(
            {"fp": "a"}, "batch", enabled_config, None)
        assert controls == {}  # visible
        labels = {o["label"] for o in options}
        assert labels == {"Batch 1", "Batch 2"}
        assert value in {"1", "2"}


# ---------------------------------------------------------------------------
# handle_view_coverage_click (pattern-matching -> tab switch)
# ---------------------------------------------------------------------------

class TestViewCoverageClick:
    def _fn(self, app):
        return get_callback_fn(app, "validation-sub-tabs")

    def test_click_switches_to_coverage_tab(self, validation_app):
        fn = self._fn(validation_app)
        with _vt_ctx({"type": "view-coverage-btn", "index": "barcode01_1773"}):
            value, active = fn([1])
        assert value == "barcode01_1773"
        assert active == "coverage-tab"

    def test_no_clicks_is_noop(self, validation_app):
        fn = self._fn(validation_app)
        with _vt_ctx({"type": "view-coverage-btn", "index": "barcode01_1773"}):
            value, active = fn([None])
        assert value is no_update and active is no_update


# ---------------------------------------------------------------------------
# On-demand validation modal (main_tab)
# ---------------------------------------------------------------------------

@contextmanager
def _mt_ctx(triggered_id):
    """Patch main_tab.ctx (module-local) with a triggered_id and a truthy
    ``triggered`` list so the ``if not ctx.triggered`` guard passes."""
    import nanometa_live.app.tabs.main_tab as mt
    with patch.object(mt, "ctx", MagicMock(triggered_id=triggered_id,
                                           triggered=[{"prop_id": "x"}])):
        yield


@pytest.fixture
def main_app():
    import dash_bootstrap_components as dbc
    from nanometa_live.app.tabs.main_tab import register_main_callbacks
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
               suppress_callback_exceptions=True)
    register_main_callbacks(app)
    return app


class TestOnDemandOpenModal:
    def _fn(self, app):
        return get_callback_fn(app, "on-demand-validation-modal")

    def test_cancel_closes_modal(self, main_app):
        fn = self._fn(main_app)
        with _mt_ctx("cancel-on-demand-validation"):
            out = fn([0], 1, None, True, None, {})
        assert out[0] is False                 # is_open

    def test_spurious_zero_click_is_noop(self, main_app):
        # When organism cards are (re)created, the pattern-matching input fires
        # with n_clicks=0/None; the modal must NOT open.
        fn = self._fn(main_app)
        trig = {"type": "on-demand-validate", "taxid": 562, "name": "E. coli"}
        with _mt_ctx(trig):
            out = fn([0], None, None, False, None, {})
        assert all(o is no_update for o in out)

    def test_real_click_opens_with_target(self, main_app):
        fn = self._fn(main_app)
        trig = {"type": "on-demand-validate", "taxid": 562, "name": "E. coli"}
        with _mt_ctx(trig):
            out = fn([1], None, None, False, "barcode01", {})
        assert out[0] is True                  # is_open
        assert out[1]["taxid"] == 562          # target store
        assert out[1]["sample"] == "barcode01"


class TestOnDemandRun:
    def _fn(self, app):
        return get_callback_fn(app, "on-demand-validation-results",
                               input_contains="start-on-demand-validation")

    def test_missing_results_dir_fails_cleanly(self, main_app):
        fn = self._fn(main_app)
        out = fn(1, {"taxid": 562, "name": "E. coli", "sample": "s"},
                 {}, {}, "blast")
        assert "no results directory" in out[1].lower()

    def test_missing_kraken_output_fails_cleanly(self, main_app, tmp_path):
        # results dir exists but has no Kraken2 per-read .output files.
        (tmp_path / "kraken2").mkdir()
        fn = self._fn(main_app)
        out = fn(1, {"taxid": 562, "name": "E. coli", "sample": "s"},
                 {"results_output_directory": str(tmp_path)}, {}, "blast")
        assert "per-read output" in out[1].lower()
        # start/cancel stay visible so the operator can retry
        assert out[5] == {"display": "inline-block"}

    def test_validator_failure_surfaces_error(self, main_app, tmp_path):
        # Pass the kraken gate, then make validate_organism return a failed
        # ValidationResult (e.g. missing pipeline_source) and assert the failure
        # is shown without raising.
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        (kraken / "barcode01.output").write_text("C\tread1\t562\n")

        fake = MagicMock(success=False,
                         error_message="pipeline_source not configured")
        import nanometa_live.core.workflow.on_demand_validator as odv
        with patch.object(odv, "OnDemandValidator") as Cls:
            Cls.return_value.validate_organism.return_value = fake
            fn = self._fn(main_app)
            out = fn(1, {"taxid": 562, "name": "E. coli", "sample": "barcode01"},
                     {"results_output_directory": str(tmp_path)}, {}, "blast")
        assert "validation failed" in out[1].lower()
        assert "pipeline_source" in out[1]
        assert out[5] == {"display": "inline-block"}   # start button visible for retry
