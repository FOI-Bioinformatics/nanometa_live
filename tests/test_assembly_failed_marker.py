"""A failed assembly task reaches the Reports panel.

``_assembly_failed_tasks`` matched the lost-input marker's ``process`` key,
but ``run_status.read_lost_inputs`` returns the process under ``stage``, so
an isolated FLYE exit was never named and the panel said "Assembly not
enabled" or "Not produced" (live test 2026-11-24). The panel also checked
"not enabled" before "failed", so a failure read as "not enabled" when the
caller could not tell whether assembly was on.
"""

import json

import pytest

from nanometa_live.app.tabs.reports_helpers import build_assembly_panel
from nanometa_live.app.tabs.reports_tab import _assembly_failed_tasks

pytestmark = pytest.mark.unit


def _text(node):
    if isinstance(node, (str, int, float)):
        return str(node)
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if not isinstance(children, (list, tuple)):
        children = [children]
    return " ".join(_text(c) for c in children)


def _marker(results, stage, sample):
    d = results / "pipeline_info" / "lost_inputs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.{sample}.abc.json").write_text(json.dumps({
        "stage": stage, "sample": sample, "exit_status": 1,
        "input_files": [f"/w/{sample}.fastq.gz"]}))


def test_a_flye_marker_names_the_sample(tmp_path):
    _marker(tmp_path, "FLYE", "barcode04")
    _marker(tmp_path, "CHOPPER", "barcode06")
    assert _assembly_failed_tasks(str(tmp_path)) == ["barcode04"]


def test_failure_outranks_not_enabled(tmp_path):
    out = _text(build_assembly_panel([], enabled=False, failed_samples=["barcode04"]))
    assert "failed" in out.lower()
    assert "not enabled" not in out.lower()
