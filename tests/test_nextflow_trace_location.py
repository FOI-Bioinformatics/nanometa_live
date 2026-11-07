"""The GUI's trace lives under the run's ``pipeline_info/`` (audit finding 23).

``-with-trace`` / ``-with-report`` / ``-with-timeline`` REPLACE the targets
nanometanf's config sets, they do not copy them. Pointing all three at
``<data_dir>/logs/`` meant no GUI run ever had a Nextflow report, timeline or
trace under ``pipeline_info/``: the Reports tab's three entries were always
absent and the export never carried them. The status poller keeps reading the
trace, now from the path the launcher chose for this run.
"""

import json
import os
import time

import pytest

from nanometa_live.core.utils.reports_loader import detect_reports
from nanometa_live.core.workflow import nextflow_manager as nm

pytestmark = pytest.mark.unit


class _InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _launch(tmp_path, monkeypatch, outdir):
    """Run start() with the launch thread replaced; return the command."""
    m = nm.NextflowManager(str(tmp_path / "data"))
    params = tmp_path / "params.json"
    params.write_text(json.dumps({"outdir": str(outdir)} if outdir else {}))
    m.params_file_path = str(params)
    m.config_file_path = str(tmp_path / "custom.config")
    m._check_conda_available = lambda: (True, "ok")
    m._sweep_conda_caches = lambda: []
    m._strip_appledouble_files = lambda *a, **k: 0
    captured = []
    m._run_workflow = lambda cmd, cfg: captured.append(cmd)
    monkeypatch.setattr(nm.threading, "Thread", _InlineThread)
    ok, _ = m.start(profile="conda")
    assert ok
    return m, captured[0]


class TestTraceUnderPipelineInfo:
    def test_trace_flag_names_the_runs_pipeline_info(self, tmp_path, monkeypatch):
        outdir = tmp_path / "results"
        m, cmd = _launch(tmp_path, monkeypatch, outdir)
        trace = cmd[cmd.index("-with-trace") + 1]
        assert os.path.dirname(trace) == str(outdir / "pipeline_info")
        assert os.path.basename(trace).startswith("execution_trace_")
        assert trace.endswith(".txt")
        assert m.trace_path == trace
        assert os.path.isdir(outdir / "pipeline_info")

    def test_report_and_timeline_are_left_to_the_pipeline_config(self, tmp_path, monkeypatch):
        _, cmd = _launch(tmp_path, monkeypatch, tmp_path / "results")
        assert "-with-report" not in cmd
        assert "-with-timeline" not in cmd

    def test_poller_reads_the_chosen_path_and_the_reports_tab_finds_it(self, tmp_path, monkeypatch):
        outdir = tmp_path / "results"
        m, _ = _launch(tmp_path, monkeypatch, outdir)
        with open(m.trace_path, "w") as f:
            f.write("name\tstatus\nKRAKEN2 (a)\tCOMPLETED\nCHOPPER (b)\tRUNNING\n")
        old = time.time() - 30
        os.utime(m.trace_path, (old, old))
        status = m._parse_trace_file()
        assert status["processes_complete"] == 1
        assert status["processes_running"] == 1
        entries = {e["key"]: e["exists"] for e in detect_reports(str(outdir))}
        assert entries["exec_trace"] is True

    def test_no_outdir_falls_back_to_the_data_dir_trace(self, tmp_path, monkeypatch):
        m, cmd = _launch(tmp_path, monkeypatch, outdir=None)
        assert cmd[cmd.index("-with-trace") + 1] == os.path.join(m.log_dir, "trace.txt")

    def test_reset_clears_only_the_fixed_path(self, tmp_path):
        m = nm.NextflowManager(str(tmp_path / "data"))
        info = tmp_path / "results" / "pipeline_info"
        info.mkdir(parents=True)
        previous = info / "execution_trace_2026-01-01_00-00-00.txt"
        previous.write_text("name\tstatus\n")
        m.trace_path = str(previous)
        fixed = os.path.join(m.log_dir, "trace.txt")
        with open(fixed, "w") as f:
            f.write("stale")
        m.reset_run_artifacts()
        assert previous.exists(), "a previous run's trace is a result artifact"
        assert not os.path.exists(fixed)
        assert m.trace_path == fixed
