"""Unit tests for the Validation tab diagnostic logic.

Covers every branch of ``compute_validation_status`` so the operator-facing
explanation for an empty Validation tab stays correct.
"""

import pytest

from nanometa_live.app.tabs.validation_status_helpers import (
    compute_validation_status,
    ValidationStatus,
)


def _status(**over):
    base = dict(
        blast_enabled=True,
        results_dir_ok=True,
        validation_taxids=["263"],
        db_status={"present": [263], "missing": [], "no_genome": []},
        has_results=False,
        pipeline_running=False,
        realtime=False,
        results_count=0,
    )
    base.update(over)
    return compute_validation_status(**base)


def test_disabled_wins_over_everything():
    s = _status(blast_enabled=False, has_results=True, pipeline_running=True)
    assert s.code == "disabled"
    assert s.severity == "secondary"
    assert "Configuration" in s.detail


def test_missing_results_dir():
    s = _status(results_dir_ok=False)
    assert s.code == "no_results_dir"


def test_no_species_enabled():
    s = _status(validation_taxids=[])
    assert s.code == "no_species"
    assert "Watchlist" in s.detail


def test_missing_databases_only_no_db():
    # genome present but BLAST DB missing -> buildable, counted distinctly
    s = _status(
        validation_taxids=["263", "9999"],
        db_status={"present": [263], "missing": [9999], "no_genome": []},
    )
    assert s.code == "missing_dbs"
    assert s.severity == "warning"
    assert s.headline == "1 of 2 organism(s) have a reference genome but no BLAST database."
    assert "Build the missing databases" in s.detail


def test_missing_databases_only_no_genome():
    # no genome at all -> not buildable, reported separately
    s = _status(
        validation_taxids=["263", "123"],
        db_status={"present": [263], "missing": [], "no_genome": [123]},
    )
    assert s.code == "missing_dbs"
    assert s.severity == "warning"
    assert s.headline == "1 of 2 organism(s) have no reference genome."
    assert "cannot be BLAST" in s.detail
    assert "Build the missing databases" not in s.detail


def test_missing_databases_both():
    s = _status(
        validation_taxids=["263", "9999", "123"],
        db_status={"present": [263], "missing": [9999], "no_genome": [123]},
    )
    assert s.code == "missing_dbs"
    assert s.severity == "warning"
    assert s.headline == "1 organism(s) have no BLAST database and 1 have no reference genome."
    assert "Build the missing databases" in s.detail
    assert "cannot be BLAST" in s.detail


def test_results_present_summary():
    s = _status(has_results=True, results_count=4)
    assert s.code == "results"
    assert s.severity == "success"
    assert "4" in s.headline


def test_running_realtime_mentions_per_batch_refresh():
    s = _status(pipeline_running=True, realtime=True)
    assert s.code == "running_realtime"
    assert "each batch" in s.detail


def test_running_batch():
    s = _status(pipeline_running=True, realtime=False)
    assert s.code == "running_batch"
    assert "complete" in s.detail.lower()


def test_waiting_when_idle_and_ready():
    s = _status(pipeline_running=False)
    assert s.code == "waiting"


def test_message_joins_headline_and_detail():
    s = ValidationStatus("x", "info", "Head.", "Tail.")
    assert s.message == "Head. Tail."
    assert ValidationStatus("x", "info", "Head.", "").message == "Head."


def test_db_status_none_does_not_crash():
    s = _status(db_status=None)
    # no missing info available -> falls through to running/waiting branches
    assert s.code in {"waiting", "running_realtime", "running_batch"}


# --- Visualization-only mode and the default ---------------------------------
#
# Live walk (2026-11-23 bug hunt): opened with --main_dir, the Validation tab
# said "Validation is disabled. Enable it in the Configuration tab" while the
# Configuration tab showed "Enable confirmation testing" switched on. The tab
# read blast_validation with a False default, the form and default_config()
# with True, and the visualization config carries no such key. In
# visualization-only mode the setting describes the NEXT run in any case;
# what the folder holds is the answer.

def test_visualization_mode_without_results_says_the_folder_has_none():
    s = _status(blast_enabled=False, visualization_only=True, has_results=False)
    assert s.code == "no_results_viz"
    assert "Configuration" not in s.detail


def test_visualization_mode_with_results_shows_them():
    s = _status(blast_enabled=False, visualization_only=True,
                has_results=True, results_count=3)
    assert s.code == "results"


def test_payload_takes_the_default_when_the_key_is_absent():
    from nanometa_live.app.tabs.validation_status_helpers import (
        build_validation_status_payload,
    )
    from nanometa_live.core.config.config_loader import default_config

    assert default_config()["blast_validation"] is True
    payload = build_validation_status_payload(
        {"processing_mode": "batch"}, results_dir_ok=True,
        backend_status={}, has_results=False, results_count=0)
    assert payload["code"] != "disabled"
