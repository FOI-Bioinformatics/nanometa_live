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


def test_missing_databases_flagged():
    s = _status(db_status={"present": [263], "missing": [9999], "no_genome": [123]})
    assert s.code == "missing_dbs"
    assert s.severity == "warning"
    # 2 of (3 taxids) lack a database
    assert "of" in s.headline


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
