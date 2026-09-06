"""Batch-mode progress: which barcodes are preliminary and which complete.

A chunked batch run writes pipeline_info/batch_chunk_plan.json (planned chunks
per sample) and one per-batch report per finished chunk. The progress helper
reads both so the header, the sample selector and the verdict subtitle can say
"preliminary" while a barcode has more chunks to come.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dash import Dash

from nanometa_live.app.utils.batch_progress import batch_progress, read_chunk_plan

pytestmark = pytest.mark.unit


def _tree(tmp_path, plan, reports):
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "batch_chunk_plan.json").write_text(json.dumps(
        {s: {"files": n * 3, "chunks": n} for s, n in plan.items()}))
    for sample, ids in reports.items():
        d = tmp_path / "kraken2" / sample / "batch_reports"
        d.mkdir(parents=True)
        for k in ids:
            (d / f"batch_{k}.kraken2.report.txt").write_text("100.00\t1\t1\tU\t0\tunclassified\n")
            (d / f"{sample}_batch{k}.kraken2.report.txt").write_text("100.00\t1\t1\tU\t0\tunclassified\n")
    return str(tmp_path)


def test_no_plan_means_no_progress(tmp_path):
    p = batch_progress(str(tmp_path))
    assert p.planned == {} and p.summary_line() is None


def test_read_chunk_plan(tmp_path):
    root = _tree(tmp_path, {"barcode01": 4, "barcode02": 1}, {})
    assert read_chunk_plan(root) == {"barcode01": 4, "barcode02": 1}


def test_states_and_summary(tmp_path):
    root = _tree(tmp_path, {"barcode01": 4, "barcode02": 1, "barcode03": 3},
                 {"barcode01": [0, 1], "barcode02": [0]})
    p = batch_progress(root)
    assert p.done == {"barcode01": 2, "barcode02": 1, "barcode03": 0}
    assert p.preliminary == ["barcode01"]
    assert p.complete == ["barcode02"]
    assert p.pending == ["barcode03"]
    assert p.summary_line() == "Preliminary: 2 of 3 barcodes; complete: 1 of 3"


def test_duplicate_copies_count_once(tmp_path):
    root = _tree(tmp_path, {"barcode01": 2}, {"barcode01": [0]})
    assert batch_progress(root).done["barcode01"] == 1


def test_malformed_plan_is_ignored(tmp_path):
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "batch_chunk_plan.json").write_text("{not json")
    assert read_chunk_plan(str(tmp_path)) == {}


# -- Surface tests --------------------------------------------------------
#
# One preliminary sample (barcode01: 2 of 4 chunks) and one complete sample
# (barcode02: 1 of 1 chunk) -- summary_line() is
# "Preliminary: 2 of 2 barcodes; complete: 1 of 2".


def _progress_tree(tmp_path):
    return _tree(
        tmp_path,
        {"barcode01": 4, "barcode02": 1},
        {"barcode01": [0, 1], "barcode02": [0]},
    )


class TestHeaderNamesProgress:
    def test_running_header_includes_summary_line(self, tmp_path):
        from dash import Dash
        from nanometa_live.app.callbacks.status import register_status
        from tests.dash_test_utils import get_callback_fn

        root = _progress_tree(tmp_path)
        app = Dash(__name__)
        register_status(app, MagicMock())
        fn = get_callback_fn(app, "status-indicator", input_contains="backend-status")

        color, text, detail = fn(
            {"running": True, "files_waiting": 6, "files_processed": 3},
            {"processing_mode": "batch", "results_output_directory": root},
        )
        assert text == "RUNNING"
        assert "Preliminary: 2 of 2 barcodes; complete: 1 of 2" in detail


class TestSelectorNamesProgress:
    def test_preliminary_sample_carries_the_badge(self, tmp_path):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.callbacks.samples import register_samples

        root = _progress_tree(tmp_path)
        app = make_callback_app(lambda a: register_samples(a, MagicMock()))
        fn = get_callback_fn(app, "sample-selector", input_contains="available-samples")

        options, _value = fn(
            ["All Samples", "barcode01", "barcode02"],
            {},
            "All Samples",
            {"barcode01": {"kraken2": ["x"]}, "barcode02": {"kraken2": ["y"]}},
            {"results_output_directory": root},
        )
        assert "preliminary 2 of 4" in str(options)

    def test_re_renders_when_progress_advances_under_unchanged_freshness(self, tmp_path):
        """The signature gate must not freeze a preliminary badge stale.

        ``_selector_signature`` used to hash only (sample, freshness bucket,
        dataless); a barcode's freshness bucket can stay in the same band
        across polls while a new chunk lands, so the unchanged signature
        raised PreventUpdate before "preliminary 2 of 4" ever advanced to
        "3 of 4" (or disappeared on completion). Same freshness/config/value
        on both calls -- only the batch_reports/ directory changes between
        them.
        """
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.callbacks.samples import register_samples

        root = _progress_tree(tmp_path)  # barcode01: 2 of 4 chunks done
        app = make_callback_app(lambda a: register_samples(a, MagicMock()))
        fn = get_callback_fn(app, "sample-selector", input_contains="available-samples")

        samples = ["All Samples", "barcode01", "barcode02"]
        mapping = {"barcode01": {"kraken2": ["x"]}, "barcode02": {"kraken2": ["y"]}}
        config = {"results_output_directory": root}
        freshness: dict = {}
        current_value = "All Samples"

        options, _value = fn(samples, freshness, current_value, mapping, config)
        assert "preliminary 2 of 4" in str(options)

        # A third batch lands for barcode01 (now 3 of 4 chunks); nothing else
        # about the inputs changes.
        d = Path(root) / "kraken2" / "barcode01" / "batch_reports"
        (d / "batch_2.kraken2.report.txt").write_text(
            "100.00\t1\t1\tU\t0\tunclassified\n")
        (d / "barcode01_batch2.kraken2.report.txt").write_text(
            "100.00\t1\t1\tU\t0\tunclassified\n")

        options2, _value2 = fn(samples, freshness, current_value, mapping, config)
        assert "preliminary 3 of 4" in str(options2)


class TestVerdictSubtitleNamesProgress:
    def test_clause_appended_when_set(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict

        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=[], n_watched=5, validation_has_results=False,
            total_reads=1000,
            batch_progress_clause="preliminary: 1 of 2 barcodes still classifying",
        )
        assert "still classifying" in d.subtitle

    def test_no_clause_when_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict

        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=[], n_watched=5, validation_has_results=False,
            total_reads=1000, batch_progress_clause=None,
        )
        assert "still classifying" not in d.subtitle

    def test_detection_still_wins(self):
        """A clause never demotes the state -- ACTION REQUIRED still renders."""
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict

        hits = [{"name": "Bacillus anthracis", "threat_level": "critical",
                 "alert_threshold": 10, "taxid": 1392}]
        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=hits, n_watched=1, validation_has_results=False,
            total_reads=1000,
            batch_progress_clause="preliminary: 1 of 2 barcodes still classifying",
        )
        assert d.state == "ACTION_REQUIRED"
        assert "still classifying" in d.subtitle

    def test_real_callback_names_it_in_the_rendered_subtitle(self, tmp_path):
        """Drives update_verdict_banner end to end, not just select_verdict().

        A hand-supplied ``batch_progress_clause`` above would pass even if
        ``_batch_progress_verdict_clause`` (dashboard_tab.py) resolved the
        wrong directory, was never called, or ``main_dir`` at the
        ``select_verdict(`` call site were wrong. This drives the real
        registered callback against a results tree with one preliminary and
        one pending sample (mirrors the fixture in
        tests/test_verdict_banner_callback.py), so the whole chain --
        resolve_outdir_for_fingerprint -> batch_progress -> select_verdict ->
        with_failure_clauses -- is exercised.
        """
        from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks

        results_dir = tmp_path / "results"
        (results_dir / "kraken2").mkdir(parents=True, exist_ok=True)
        # barcode01: preliminary (2 of 4); barcode02: pending (0 of 2).
        root = _tree(results_dir, {"barcode01": 4, "barcode02": 2},
                     {"barcode01": [0, 1]})
        assert root == str(results_dir)

        app = Dash(__name__, suppress_callback_exceptions=True)
        register_dashboard_callbacks(app)
        callback_fn = None
        for cb_id, spec in app.callback_map.items():
            if "dashboard-verdict-banner" in cb_id:
                callback_fn = getattr(spec["callback"], "__wrapped__", spec["callback"])
                break
        assert callback_fn is not None, "Verdict-banner callback was not registered"

        config = {
            "results_output_directory": str(results_dir),
            "main_dir": str(results_dir),
        }
        status = {"running": True, "completed": False, "start_time": None}

        # No watchlist hits -- reaches the all-clear/subthreshold branch of
        # _data_verdict, where the batch-progress clause is appended. root /
        # unclassified rows give get_classification_stats() a depth above
        # the low-read floor, so the branch is ALL CLEAR rather than
        # INSUFFICIENT READS (which skips the failure-clause wrapper
        # entirely).
        kraken_df = pd.DataFrame([
            {
                "perc": 100.0, "cumul_reads": 1000, "reads": 0,
                "rank": "R", "taxid": 1, "name": "root", "parent_taxid": 0,
            },
            {
                "perc": 0.0, "cumul_reads": 0, "reads": 0,
                "rank": "U", "taxid": 0, "name": "unclassified", "parent_taxid": 0,
            },
        ])

        with patch(
            "nanometa_live.app.tabs.dashboard_tab.load_kraken_data",
            return_value=kraken_df,
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._species_df_to_organisms",
            return_value=[],
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._get_active_watchlist_entries",
            return_value=[{"taxid": 1392, "name": "Bacillus anthracis"}],
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._check_pathogens_both",
            return_value=([], []),
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab.interval_tick_is_redundant",
            return_value=False,
        ):
            outputs = callback_fn(
                "fp1", None, 0,
                config, status, {"status": "ok"}, {"results": []},
                ["All Samples", "barcode01", "barcode02"],
            )

        assert outputs is not None
        rendered = json.dumps(outputs, default=str)
        assert "still classifying" in rendered
