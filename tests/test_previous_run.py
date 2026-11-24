"""A results folder reopened after its run ended shows that run.

At the Barcelona exercise (2026-11-24 feedback) a restarted app opened on a
finished run's results said STANDBY, "Click 'Start Analysis' to begin
processing" and a run time of 00:00:00 above a page of detections: nothing
on screen said which run produced them or how it ended.
"""

import json
from unittest.mock import MagicMock

import pytest
from dash import Dash

from nanometa_live.app.utils.previous_run import (
    PreviousRun,
    format_duration,
    previous_run_header,
    previous_run_status,
)

pytestmark = pytest.mark.unit


def _results(tmp_path, **meta):
    d = tmp_path / "results"
    d.mkdir()
    (d / ".nanometa.run.json").write_text(json.dumps(meta))
    return d


COMPLETED = dict(final_status="completed", written_at="2026-10-05T09:00:00",
                 ended_at="2026-10-05T12:12:00")


def test_completed_run_is_read(tmp_path):
    prev = previous_run_status(str(_results(tmp_path, **COMPLETED)))
    assert prev == PreviousRun(run_state="completed",
                               started_at="2026-10-05T09:00:00",
                               ended_at="2026-10-05T12:12:00",
                               duration_s=11520, stop_reason=None)


def test_header_names_the_run(tmp_path):
    prev = previous_run_status(str(_results(tmp_path, **COMPLETED)))
    color, text, details = previous_run_header(prev)
    assert color == "blue" and text == "LAST RUN"
    assert "Completed at 12:12" in details
    assert "ran 3 h 12 min" in details
    assert "Start Analysis begins a new one" in details


def test_stopped_and_error_runs(tmp_path):
    stopped = previous_run_status(str(_results(
        tmp_path, final_status="stopped", stop_reason="operator",
        written_at="2026-10-05T09:00:00", ended_at="2026-10-05T09:30:00")))
    color, _text, details = previous_run_header(stopped)
    assert color == "orange" and "Stopped (operator) at 09:30" in details


def test_error_run(tmp_path):
    err = previous_run_status(str(_results(
        tmp_path, final_status="error", written_at="2026-10-05T09:00:00",
        ended_at="2026-10-05T09:05:00")))
    color, _text, details = previous_run_header(err)
    assert color == "red" and "Ended with an error at 09:05" in details


def test_no_metadata_is_none(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    assert previous_run_status(str(d)) is None
    assert previous_run_status(None) is None
    assert previous_run_status(str(tmp_path / "missing")) is None


def test_run_without_terminal_status_is_none(tmp_path):
    assert previous_run_status(str(_results(
        tmp_path, written_at="2026-10-05T09:00:00"))) is None


def test_missing_start_gives_no_duration(tmp_path):
    prev = previous_run_status(str(_results(
        tmp_path, final_status="completed", ended_at="2026-10-05T12:12:00")))
    assert prev.duration_s is None
    _c, _t, details = previous_run_header(prev)
    assert "ran" not in details


def test_format_duration():
    assert format_duration(11520) == "03:12:00"
    assert format_duration(None) == "--:--:--"


def _status_fn():
    from nanometa_live.app.callbacks.status import register_status
    from tests.dash_test_utils import get_callback_fn
    app = Dash(__name__)
    register_status(app, MagicMock())
    return get_callback_fn(app, "status-indicator", input_contains="backend-status")


def _config(d):
    return {"results_output_directory": str(d), "results_dir_override": str(d)}


def test_status_header_shows_last_run_when_idle(tmp_path):
    d = _results(tmp_path, **COMPLETED)
    color, text, details = _status_fn()({"running": False}, _config(d))
    assert text == "LAST RUN" and "Completed at 12:12" in details


def test_running_status_is_never_a_previous_run(tmp_path):
    d = _results(tmp_path, **COMPLETED)
    _color, text, _details = _status_fn()(
        {"running": True, "files_processed": 1, "files_waiting": 0}, _config(d))
    assert text != "LAST RUN"


def test_idle_without_metadata_stays_standby(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    _color, text, _details = _status_fn()({"running": False}, _config(d))
    assert text == "STANDBY"


def test_verdict_tile_shows_the_last_runs_duration(tmp_path):
    from test_verdict_banner_callback import _run_verdict_banner

    results = tmp_path / "results"
    (results / "kraken2").mkdir(parents=True)
    (results / ".nanometa.run.json").write_text(json.dumps(COMPLETED))
    out = json.loads(_run_verdict_banner(
        tmp_path, detections=[], taxid_to_samples={}, available_samples=[],
        status={"running": False, "completed": False, "start_time": None},
        make_results_dir=False,
    ))
    # outputs: banner children, banner style, time elapsed, badge text, badge color
    assert out[2] == "03:12:00"
    assert out[3] == "COMPLETE"
    assert out[4] == "info"
