"""Regression tests for the fingerprint outdir resolution helper.

Pins the priority order that fixes the U4 waiting-banner bug observed
on 2026-05-10 during the GUI-launched pipeline pass: BackendManager's
``_setup_project`` mutates ``config["main_dir"]`` to point at a
Nextflow project directory under ``~/.nanometa/data/analysis_*/``,
which contains only ``config.json`` and never the data outputs. The
fingerprint must scan ``results_output_directory`` (where nanometanf
actually writes ``kraken2/``, ``seqkit/`` etc.) instead.
"""

from __future__ import annotations

from nanometa_live.app.utils.outdir_resolution import (
    resolve_outdir_for_fingerprint,
)


def test_returns_results_output_directory_when_both_present():
    """The bug case: BackendManager has overwritten main_dir with a
    project directory, but results_output_directory is the source of truth."""
    config = {
        "main_dir": "/Users/me/.nanometa/data/analysis_20260510_062107",
        "results_output_directory": "/Users/me/runs/scenario_1/results",
    }
    assert (
        resolve_outdir_for_fingerprint(config)
        == "/Users/me/runs/scenario_1/results"
    )


def test_falls_back_to_main_dir_when_results_unset():
    """Existing-data view (`--main_dir /path/to/results`) sets only
    main_dir; the fingerprint must still find the data."""
    config = {"main_dir": "/path/to/results"}
    assert resolve_outdir_for_fingerprint(config) == "/path/to/results"


def test_empty_string_when_neither_set():
    assert resolve_outdir_for_fingerprint({}) == ""


def test_empty_string_when_config_none():
    assert resolve_outdir_for_fingerprint(None) == ""


def test_treats_empty_results_directory_as_unset():
    """An empty string for results_output_directory should fall through
    to main_dir, not return empty."""
    config = {
        "results_output_directory": "",
        "main_dir": "/fallback",
    }
    assert resolve_outdir_for_fingerprint(config) == "/fallback"
