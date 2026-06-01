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

import os

from nanometa_live.app.utils.outdir_resolution import (
    resolve_outdir_for_fingerprint,
    resolve_run_outdir,
    slugify_run_name,
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


# --------------------------------------------------------------------------
# Run-name slug + per-run outdir derivation (named runs under the project).
# --------------------------------------------------------------------------

class TestSlugifyRunName:
    def test_spaces_to_underscore(self):
        assert slugify_run_name("Patient 0042 blood") == "Patient_0042_blood"

    def test_strips_path_separators(self):
        # Cannot escape the results/ container.
        assert "/" not in slugify_run_name("../etc/passwd")
        assert slugify_run_name("../etc/passwd") == "etc_passwd"

    def test_empty_falls_back_to_run(self):
        assert slugify_run_name("") == "run"
        assert slugify_run_name(None) == "run"
        assert slugify_run_name("///") == "run"

    def test_keeps_safe_chars(self):
        assert slugify_run_name("run-1.2_v3") == "run-1.2_v3"


class TestResolveRunOutdir:
    def test_derives_project_results_run(self):
        cfg = {"project_dir": "/proj", "analysis_name": "Patient 0042 blood",
               "results_output_directory": ""}
        assert resolve_run_outdir(cfg) == "/proj/results/Patient_0042_blood"

    def test_explicit_override_returned_verbatim(self):
        cfg = {"project_dir": "/proj", "analysis_name": "x",
               "results_output_directory": "/scratch/out"}
        assert resolve_run_outdir(cfg) == "/scratch/out"

    def test_no_project_falls_back_to_home(self):
        cfg = {"analysis_name": "run1", "results_output_directory": ""}
        assert resolve_run_outdir(cfg) == os.path.join(
            os.path.expanduser("~/nanometa_results"), "run1"
        )

    def test_none_config_empty(self):
        assert resolve_run_outdir(None) == ""
