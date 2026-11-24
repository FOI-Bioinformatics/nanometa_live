"""Callback-level tests for the Quality Control tab.

Invokes the real @app.callback bodies (modal toggles + the empty-data paths of
the figure/stat/table builders) which were previously uncovered.
"""

import os
import time
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs import qc_tab as qc_mod
from nanometa_live.app.tabs.qc_tab import register_qc_callbacks
from nanometa_live.core.testing.mock_data_generator import (
    generate_test_dataset,
    MockDataScenario,
)
from dash_test_utils import get_callback_fn, make_callback_app


def _backdate(root, seconds=30):
    old = time.time() - seconds
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                os.utime(os.path.join(dirpath, f), (old, old))
            except OSError:
                pass


@pytest.fixture(scope="module")
def populated_config(tmp_path_factory):
    d = tmp_path_factory.mktemp("qc_tab_populated")
    generate_test_dataset(str(d), scenario=MockDataScenario.PATHOGEN_DETECTED, num_samples=3)
    _backdate(str(d))
    return {"results_output_directory": str(d), "main_dir": str(d)}


@pytest.fixture(scope="module")
def qc_app():
    return make_callback_app(register_qc_callbacks)


@contextmanager
def ctx_trigger(triggered_id):
    """Patch qc_tab's module-local ctx (it does ``from dash import ctx``)."""
    fake = MagicMock(triggered_id=triggered_id,
                     triggered=[{"prop_id": f"{triggered_id}.n_clicks"}])
    with patch.object(qc_mod, "ctx", fake):
        yield


# --------------------------------------------------------------------------- #
# modal toggles
# --------------------------------------------------------------------------- #

def test_help_modal_toggles(qc_app):
    fn = get_callback_fn(qc_app, "qc-help-modal")
    assert fn(1, 0, False) is True       # help opens
    assert fn(0, 1, True) is False       # close closes
    assert fn(0, 0, True) is True        # no click -> unchanged


def test_export_modal_toggles(qc_app):
    fn = get_callback_fn(qc_app, "qc-export-modal")
    assert fn(1, 0, 0, False) is True
    assert fn(0, 1, 0, True) is False
    assert fn(None, None, None, True) is True


# --------------------------------------------------------------------------- #
# big data callbacks: empty-data paths
# --------------------------------------------------------------------------- #

def test_update_qc_stats_empty_returns_defaults(qc_app):
    fn = get_callback_fn(qc_app, "qc-reads-pre-filtering")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, {}, {}, None)
    assert isinstance(result, (list, tuple))
    # Ten stat tiles plus the Store-backed interval-backstop memo (this
    # callback is background=True, so the memo cannot be a module global).
    assert len(result) == 11
    joined = " ".join(result[:10])
    assert "passed filtering: 0" in joined
    assert "Files processed: 0" in joined


def test_update_qc_plots_empty_returns_four_figures(qc_app):
    fn = get_callback_fn(qc_app, "cumul-reads-graph")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, "qc-tab", {}, {})
    assert isinstance(result, (list, tuple))
    assert len(result) == 4                # cumul-reads, cumul-bp, reads, bp
    # each output is a plotly figure (dict-like with 'data'/'layout' or Figure)
    for fig in result:
        assert fig is not None


def test_update_per_sample_table_empty_returns_list(qc_app):
    fn = get_callback_fn(qc_app, "per-sample-table")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, "qc-tab", {}, {})
    assert isinstance(result, list)


# --------------------------------------------------------------------------- #
# big data callbacks: populated paths (the bulk of the module)
# --------------------------------------------------------------------------- #

def test_update_qc_stats_populated(qc_app, populated_config):
    fn = get_callback_fn(qc_app, "qc-reads-pre-filtering")
    with ctx_trigger("results-fingerprint"):
        # Round 3: fires from the gate-bumped due Store; the former
        # Inputs are States now.
        result = fn({"n": 1}, "fp1", "All Samples", populated_config,
                    {"running": True}, None)
    assert len(result) == 11
    # classification stats should reflect real data, not the all-zero defaults
    joined = " ".join(result[:10])
    assert "Files processed: 0" not in joined or "Classified reads: 0 (0%)" not in joined


def test_update_qc_plots_populated(qc_app, populated_config):
    fn = get_callback_fn(qc_app, "cumul-reads-graph")
    with ctx_trigger("results-fingerprint"):
        result = fn("fp1", "All Samples", 0, "qc-tab", populated_config, {"running": True})
    assert len(result) == 4
    for fig in result:
        assert fig is not None


def test_update_per_sample_table_populated(qc_app, populated_config):
    fn = get_callback_fn(qc_app, "per-sample-table")
    with ctx_trigger("results-fingerprint"):
        result = fn("fp1", "All Samples", 0, "qc-tab", populated_config, {"running": True})
    assert isinstance(result, list)
    assert len(result) > 0  # 3 samples in the dataset


# --------------------------------------------------------------------------- #
# Reads before filtering from chopper's own counts (Barcelona exercise
# feedback, 2026-11-24)
# --------------------------------------------------------------------------- #

_KREPORT = ("16.67\t20\t20\tU\t0\tunclassified\n"
            "83.33\t100\t0\tR\t1\troot\n"
            "83.33\t100\t100\tS\t562\t  Escherichia coli\n")
_SEQKIT = ("file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\n"
           "barcode01.chopped.fastq.gz\tFASTQ\tDNA\t120\t120000\t1000\t1000.0\t1000\n")


def _chopper_tree(root, with_counts=True):
    (root / "kraken2").mkdir(parents=True)
    (root / "kraken2" / "barcode01.kraken2.report.txt").write_text(_KREPORT)
    (root / "seqkit").mkdir()
    (root / "seqkit" / "barcode01.tsv").write_text(_SEQKIT)
    if with_counts:
        d = root / "chopper" / "barcode01" / "counts"
        d.mkdir(parents=True)
        (d / "barcode01.1.chopper_counts.txt").write_text(
            "Kept 120 reads out of 150 reads\n")
    _backdate(str(root))
    return {"results_output_directory": str(root), "main_dir": str(root)}


def _text(component):
    out = []

    def walk(c):
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
        elif hasattr(c, "children"):
            walk(c.children)
    walk(component)
    return " ".join(out)


@pytest.fixture
def _fresh_loaders():
    from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
    clear_all_loader_caches()
    yield
    clear_all_loader_caches()


def test_stage_strip_shows_chopper_reads_before_filtering(qc_app, tmp_path, _fresh_loaders):
    config = _chopper_tree(tmp_path)
    fn = get_callback_fn(qc_app, "qc-stage-strip")
    with ctx_trigger("results-fingerprint"):
        strip = fn("fp-chopper", "barcode01", 0, config)
    text = _text(strip)
    assert "150" in text
    assert "not recorded" not in text


def test_stage_strip_without_counts_is_unchanged(qc_app, tmp_path, _fresh_loaders):
    config = _chopper_tree(tmp_path, with_counts=False)
    fn = get_callback_fn(qc_app, "qc-stage-strip")
    with ctx_trigger("results-fingerprint"):
        strip = fn("fp-nocounts", "barcode01", 0, config)
    assert "not recorded" in _text(strip)


def test_stat_lines_use_chopper_counts(qc_app, tmp_path, _fresh_loaders):
    config = _chopper_tree(tmp_path)
    fn = get_callback_fn(qc_app, "qc-reads-pre-filtering")
    with ctx_trigger("results-fingerprint"):
        result = fn({"n": 1}, "fp-stat", "barcode01", config, {"running": False}, None)
    joined = " | ".join(result[:10])
    assert "Raw reads (before filtering): 150" in joined
    assert "Reads that passed filtering: 120 (80.0%)" in joined
    assert "Total reads removed: 30 (20.0%)" in joined
    assert "Too short: not recorded by the read filter" in joined


def test_stat_lines_without_counts_say_not_recorded(qc_app, tmp_path, _fresh_loaders):
    config = _chopper_tree(tmp_path, with_counts=False)
    fn = get_callback_fn(qc_app, "qc-reads-pre-filtering")
    with ctx_trigger("results-fingerprint"):
        result = fn({"n": 1}, "fp-stat2", "barcode01", config, {"running": False}, None)
    assert "Raw reads (before filtering): not recorded" in " | ".join(result[:10])


def test_guidance_receives_chopper_prefilter(qc_app, tmp_path, _fresh_loaders):
    config = _chopper_tree(tmp_path)
    fn = get_callback_fn(qc_app, "qc-action-guidance-container")
    seen = {}

    def spy(pre_filter, passed, classified, total_classified_input):
        seen["pre_filter"] = pre_filter
        return [], False

    with patch.object(qc_mod, "qc_guidance_issues", spy), \
            ctx_trigger("results-fingerprint"):
        fn("fp-guide", "barcode01", 0, config)
    assert seen["pre_filter"] == 150
