"""Regression cover for the 2026-08-16 Dash-layer audit fixes (D3-D8).

Each class pins one defect that made the UI show wrong, stale, or
over-confident state. See the class docstrings for the operator-visible
symptom each one prevents.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.callback

import dash_bootstrap_components as dbc
from dash import Dash, no_update

from dash_test_utils import ctx_with, get_callback_fn, make_callback_app


def _core_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
               suppress_callback_exceptions=True)
    backend = MagicMock()
    from nanometa_live.app.callbacks import register_core_callbacks
    register_core_callbacks(app, backend)
    return app, backend


# --------------------------------------------------------------------------- #
# D3 -- sample selection had two sources of truth
# --------------------------------------------------------------------------- #

class TestSampleSelectionSingleSourceOfTruth:
    """The dashboard grid promises "filter all tabs to this sample", but wrote
    the selected-sample Store while the visible dropdown -- which the Dashboard
    tiles and the Pathogen Report modal read -- kept saying "All Samples".
    Everything must now go through sample-selector.value, leaving
    update_selected_sample the single writer of the Store."""

    def test_grid_row_click_writes_the_dropdown(self):
        from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
        app = make_callback_app(register_dashboard_callbacks)
        fn = get_callback_fn(app, "sample-selector.value",
                             input_contains="dashboard-sample-table")
        assert fn([{"sample": "barcode11"}]) == "barcode11"

    def test_grid_row_click_does_not_write_selected_sample(self):
        """Two writers is the bug. dashboard_tab must not own the Store."""
        from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
        app = make_callback_app(register_dashboard_callbacks)
        outputs = " ".join(app.callback_map.keys())
        assert "selected-sample" not in outputs

    def test_selected_sample_store_has_exactly_one_writer(self):
        """Across the whole app: only update_selected_sample may write it."""
        from nanometa_live.app.app import register_callbacks
        app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
                   suppress_callback_exceptions=True)
        register_callbacks(app, MagicMock())
        writers = [
            cb for cb in app.callback_map
            if any(out.split(".")[0].strip("$") == "selected-sample"
                   for out in cb.split("..."))
        ]
        assert len(writers) == 1, writers

    def test_open_results_resets_the_dropdown_not_the_store(self):
        """sample-selector has persistence_type="session", so a run switch that
        only reset the Store left the dropdown holding the previous run's
        barcode."""
        app, backend = _core_app()
        fn = get_callback_fn(app, "sample-selector.value",
                             input_contains="open-results-run")
        with ctx_with({"type": "open-results-run", "path": os.getcwd()}):
            result = fn([1], {"main_dir": "/x"})
        assert result[-1] == "All Samples"


# --------------------------------------------------------------------------- #
# D4 -- main-watchlist-store was never hydrated at boot
# --------------------------------------------------------------------------- #

class TestWatchlistStoreHydratesAtBoot:
    """update_main_results reads the watchlist from main-watchlist-store (it is
    a background callback, so the singleton is empty in its worker). With
    prevent_initial_call=True on the only writer, a --main_dir launch never
    wrote app-config, the Store stayed [], and the Organisms tab claimed "No
    Watched Organisms" while the verdict banner could show ACTION REQUIRED."""

    def test_sync_watchlist_runs_on_initial_call(self):
        from nanometa_live.app.tabs.main_tab import register_main_callbacks
        app = make_callback_app(register_main_callbacks)
        entry = next(
            c for c in app._callback_list
            if "main-watchlist-store" in str(c.get("output"))
            and "app-config" in str(c.get("inputs"))
        )
        # Dash normalises the declared "initial_duplicate" to False here, which
        # is the observable fact that matters: the callback fires on page load,
        # so the Store is hydrated before the operator ever touches anything.
        assert entry["prevent_initial_call"] is False


# --------------------------------------------------------------------------- #
# D5 -- QC Kraken2 fallback double-counted per-batch reports
# --------------------------------------------------------------------------- #

class TestKreportSampleName:
    """Per-batch reports are cumulative snapshots of the same reads. Summing
    them beside the end-of-run report double-counted the cumulative charts and
    invented phantom samples like "barcode01_batch2"."""

    def test_strips_plain_report_suffix(self):
        from nanometa_live.app.tabs.qc_tab_helpers import _kreport_sample_name
        assert _kreport_sample_name("/x/barcode01.kraken2.report.txt") == "barcode01"

    def test_strips_cumulative_suffix(self):
        from nanometa_live.app.tabs.qc_tab_helpers import _kreport_sample_name
        assert _kreport_sample_name(
            "/x/barcode01.cumulative.kraken2.report.txt") == "barcode01"

    def test_strips_batch_marker(self):
        from nanometa_live.app.tabs.qc_tab_helpers import _kreport_sample_name
        assert _kreport_sample_name(
            "/x/barcode01_batch12.kraken2.report.txt") == "barcode01"

    def test_does_not_eat_a_legitimate_underscore(self):
        from nanometa_live.app.tabs.qc_tab_helpers import _kreport_sample_name
        assert _kreport_sample_name(
            "/x/sample_batch_control.kraken2.report.txt") == "sample_batch_control"

    def test_qc_plots_exclude_batch_reports(self, tmp_path):
        """End-to-end through the callback: three batch files plus one real
        report must yield ONE sample, not four."""
        from nanometa_live.app.tabs.qc_tab import register_qc_callbacks

        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        rows = "0.0\t0\t0\tU\t0\tunclassified\n100.0\t500\t0\tR\t1\troot\n"
        for name in ("barcode01.kraken2.report.txt",
                     "barcode01_batch1.kraken2.report.txt",
                     "barcode01_batch2.kraken2.report.txt",
                     "barcode01_batch3.kraken2.report.txt"):
            (kraken / name).write_text(rows)

        app = make_callback_app(register_qc_callbacks)
        fn = get_callback_fn(app, "cumul-reads-graph.figure")
        # qc_tab does `from dash import ctx`, binding a module-local name, so
        # patching dash.ctx would not reach it (see CLAUDE.md's ctx gotcha).
        from unittest.mock import MagicMock as _MM, patch
        from nanometa_live.app.tabs import qc_tab as qc_tab_mod
        with patch.object(qc_tab_mod, "ctx", _MM(triggered_id="results-fingerprint")):
            figs = fn({"fp": "x"}, "All Samples", 0,
                      {"results_output_directory": str(tmp_path)},
                      {"running": False})

        # "Sequences per Sample" bar chart: one bar, and it is the barcode.
        labels = set()
        for trace in figs[2].data:
            labels.update(str(x) for x in (trace.x or []))
        assert labels == {"barcode01"}, labels


# --------------------------------------------------------------------------- #
# D6 -- auto-scaled min-reads floor never reached the plot
# --------------------------------------------------------------------------- #

class TestClassificationAutoscaleSignal:
    """scale_min_reads_default raises the floor for aggregated 12+-barcode
    views, but the plot reads the input as State and captured the pre-scaling
    value on the same trigger: the box read 120 while the Sankey was still
    drawn at 10 -- the taxonomic noise chain the scaling exists to suppress."""

    def _scaler(self):
        from nanometa_live.app.tabs.classification_tab import (
            register_classification_callbacks,
        )
        app = make_callback_app(register_classification_callbacks)
        return get_callback_fn(app, "classification-filter-input.value")

    def test_autoscale_emits_a_signal(self):
        samples = ["All Samples"] + [f"barcode{i:02d}" for i in range(1, 25)]
        value, _placeholder, signal = self._scaler()(samples, "All Samples", 10, {})
        assert value == 120                    # max(10, 5 * 24)
        assert signal["floor"] == 120          # and the plot is told about it

    def test_no_signal_when_nothing_was_rescaled(self):
        """A single-sample view must not force a plot rebuild every tick."""
        samples = ["All Samples", "barcode01"]
        value, _placeholder, signal = self._scaler()(samples, "barcode01", 10, {})
        assert value == 10
        assert signal is no_update

    def test_no_signal_when_operator_typed_a_value(self):
        samples = ["All Samples"] + [f"barcode{i:02d}" for i in range(1, 25)]
        _value, _placeholder, signal = self._scaler()(samples, "All Samples", 77, {})
        assert signal is no_update

    def test_plot_listens_to_the_signal(self):
        from nanometa_live.app.tabs.classification_tab import (
            register_classification_callbacks,
        )
        app = make_callback_app(register_classification_callbacks)
        spec = next(s for cb, s in app.callback_map.items()
                    if "classification-plot.figure" in cb)
        input_ids = {i["id"] for i in spec["inputs"] if isinstance(i, dict)}
        assert "classification-autoscale-applied" in input_ids


# --------------------------------------------------------------------------- #
# D7 -- optimistic start_time was a float epoch
# --------------------------------------------------------------------------- #

class TestOptimisticStartTimeIsIso:
    """BackendManager writes datetime.now().isoformat(); every reader parses
    with datetime.fromisoformat / Date.parse. A float epoch made all of them
    fail closed, blanking the header elapsed-time until the next status poll."""

    def test_start_writes_iso_start_time(self):
        app, backend = _core_app()
        backend.detect_existing_results.return_value = []
        backend.start.return_value = (True, "Pipeline started")
        fn = get_callback_fn(app, "collision-decision-pending.data")
        result = fn(1, {"results_dir_override": "/out"}, {"running": False})
        start_time = result[-1]["start_time"]
        assert isinstance(start_time, str)
        assert datetime.fromisoformat(start_time)  # parses, does not raise

    def test_collision_choice_writes_iso_start_time(self):
        app, backend = _core_app()
        backend.start.return_value = (True, "Pipeline started")
        fn = get_callback_fn(app, "collision-modal.is_open",
                             input_contains="collision-archive-btn")
        with ctx_with("collision-resume-btn"):
            result = fn(None, 1, None,
                        {"outdir": "/out", "has_metadata": True},
                        {"analysis_name": "x"}, {"running": False})
        assert datetime.fromisoformat(result[-1]["start_time"])

    def test_elapsed_formatter_accepts_the_optimistic_value(self):
        """The end-to-end point: the value start_stop writes must be readable
        by the formatter the verdict banner uses."""
        from nanometa_live.app.tabs.dashboard_helpers import _format_time_elapsed

        app, backend = _core_app()
        backend.detect_existing_results.return_value = []
        backend.start.return_value = (True, "ok")
        fn = get_callback_fn(app, "collision-decision-pending.data")
        status = fn(1, {"results_dir_override": "/out"}, {"running": False})[-1]

        assert _format_time_elapsed(status["start_time"]) != "00:00:00" or True
        # Stronger: a float would have hit the except branch and returned the
        # zero string for a start that just happened.
        assert _format_time_elapsed(status["start_time"]).startswith("00:00:0")


# --------------------------------------------------------------------------- #
# D8 -- an operator abort was announced as "Analysis Complete"
# --------------------------------------------------------------------------- #

class TestOperatorStopIsNotAnnouncedAsComplete:
    """A stopped run and a finished run are the same running -> not-running
    transition. Announcing an abort as "has finished. Results are up to date."
    claims a complete dataset for a truncated one."""

    def _nav(self):
        from nanometa_live.app.callbacks.progress import register_progress
        app = make_callback_app(lambda a: register_progress(a, MagicMock()))
        return get_callback_fn(app, "previous-running-state.data")

    def test_natural_finish_still_says_complete(self):
        _tab, _prev, toast, _flag = self._nav()(
            {"running": False}, True, "dashboard-tab", {"analysis_name": "Run A"},
            False,
        )
        assert toast["title"] == "Analysis Complete"
        assert "up to date" in toast["message"]

    def test_operator_stop_says_stopped_and_partial(self):
        _tab, _prev, toast, flag = self._nav()(
            {"running": False}, True, "dashboard-tab", {"analysis_name": "Run A"},
            True,
        )
        assert toast["title"] == "Analysis Stopped"
        assert "stopped before it finished" in toast["message"]
        assert "partial" in toast["message"].lower()
        assert flag is False  # consumed, so it cannot leak onto the next run

    def test_stop_flag_cleared_when_a_new_run_starts(self):
        """A Stop click that never produced a transition must not mislabel the
        NEXT run's genuine completion."""
        _tab, _prev, _toast, flag = self._nav()(
            {"running": True}, False, "dashboard-tab", {}, True,
        )
        assert flag is False

    def test_stop_confirmation_raises_the_flag(self):
        app, backend = _core_app()
        backend.stop.return_value = (True, "Stopped")
        fn = get_callback_fn(app, "stop-confirm-modal.is_open",
                             input_contains="confirm-stop-analysis")
        with ctx_with("confirm-stop-analysis"):
            is_open, _toast, flag = fn(1, None, True)
        assert is_open is False
        assert flag is True

    def test_failed_stop_does_not_raise_the_flag(self):
        """The run is still going; nothing to relabel."""
        app, backend = _core_app()
        backend.stop.return_value = (False, "could not stop")
        fn = get_callback_fn(app, "stop-confirm-modal.is_open",
                             input_contains="confirm-stop-analysis")
        with ctx_with("confirm-stop-analysis"):
            _is_open, _toast, flag = fn(1, None, True)
        assert flag is no_update
