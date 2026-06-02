"""Tests for the 2026-06 validation robustness/UX hardening pass.

Covers:
- On-demand validator helpers: configurable timeout, genome-file integrity
  gate, and non-numeric taxid-key sanitisation (``_validation_timeout_seconds``,
  ``_genome_file_looks_valid``, ``_is_int_str``).
- The Validation tab export callbacks now emit a toast on the
  ``notification-trigger`` channel for empty/failed exports instead of
  silently returning ``no_update``.
"""

from __future__ import annotations

import pytest
from dash import Dash, no_update

from nanometa_live.core.workflow.on_demand_validator import (
    _DEFAULT_VALIDATION_TIMEOUT_MINUTES,
    _genome_file_looks_valid,
    _is_int_str,
    _validation_timeout_seconds,
)
from nanometa_live.app.tabs.validation_tab import register_validation_callbacks
from tests.dash_test_utils import get_callback_fn


# ---------------------------------------------------------------------------
# _is_int_str
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("562", True),
    (562, True),
    ("0", True),
    ("abc", False),
    ("", False),
    (None, False),
    ("56.2", False),
])
def test_is_int_str(value, expected):
    assert _is_int_str(value) is expected


# ---------------------------------------------------------------------------
# _validation_timeout_seconds
# ---------------------------------------------------------------------------

def test_timeout_default_when_unset():
    assert _validation_timeout_seconds({}) == _DEFAULT_VALIDATION_TIMEOUT_MINUTES * 60
    assert _validation_timeout_seconds(None) == _DEFAULT_VALIDATION_TIMEOUT_MINUTES * 60


def test_timeout_reads_config_minutes():
    assert _validation_timeout_seconds({"validation_timeout_minutes": 60}) == 3600


def test_timeout_floored_at_60s():
    assert _validation_timeout_seconds({"validation_timeout_minutes": 0}) == 60


def test_timeout_bad_value_falls_back_to_default():
    assert _validation_timeout_seconds(
        {"validation_timeout_minutes": "not-a-number"}
    ) == _DEFAULT_VALIDATION_TIMEOUT_MINUTES * 60


# ---------------------------------------------------------------------------
# _genome_file_looks_valid
# ---------------------------------------------------------------------------

def test_genome_valid_fasta(tmp_path):
    g = tmp_path / "562.fasta"
    g.write_text(">seq1\nACGTACGT\n")
    assert _genome_file_looks_valid(g) is True


def test_genome_missing(tmp_path):
    assert _genome_file_looks_valid(tmp_path / "absent.fasta") is False


def test_genome_empty(tmp_path):
    g = tmp_path / "empty.fasta"
    g.write_text("")
    assert _genome_file_looks_valid(g) is False


def test_genome_not_fasta(tmp_path):
    g = tmp_path / "junk.fasta"
    g.write_text("this is not fasta\nACGT\n")
    assert _genome_file_looks_valid(g) is False


# ---------------------------------------------------------------------------
# Export callbacks emit a toast on empty/failed export (U1)
# ---------------------------------------------------------------------------

def _validation_app() -> Dash:
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_validation_callbacks(app)
    return app


def test_export_blast_empty_emits_warning_toast():
    fn = get_callback_fn(_validation_app(), "download-blast-report")
    # Only a minimap2 result present -> no BLAST rows to export.
    data = {"results": [{"species": "X", "validation_method": "minimap2"}]}
    download, toast = fn(1, data, {"analysis_name": "demo"})
    assert download is no_update
    assert toast["color"] == "warning"
    assert "BLAST" in toast["message"]


def test_export_blast_success_returns_csv_no_toast():
    fn = get_callback_fn(_validation_app(), "download-blast-report")
    data = {"results": [{
        "species": "Escherichia coli", "sample_id": "barcode01",
        "validation_method": "blast", "total_reads": 100,
        "validated_reads": 90, "percent_validated": 90.0,
    }]}
    download, toast = fn(1, data, {"analysis_name": "demo"})
    assert toast is no_update
    assert download["filename"].startswith("blast_validation_demo_")
    assert "content" in download


def test_export_coverage_empty_emits_warning_toast():
    fn = get_callback_fn(_validation_app(), "download-coverage-report")
    # Only a blast result present -> no minimap2 rows to export.
    data = {"results": [{"species": "X", "validation_method": "blast"}]}
    download, toast = fn(1, data, {"analysis_name": "demo"})
    assert download is no_update
    assert toast["color"] == "warning"


def test_export_no_clicks_is_noop():
    fn = get_callback_fn(_validation_app(), "download-blast-report")
    download, toast = fn(None, {"results": []}, {})
    assert download is no_update
    assert toast is no_update


# ---------------------------------------------------------------------------
# minimap2 individual-file fallback (Coverage sub-tab in realtime, before the
# aggregate validation_results.json is written)
# ---------------------------------------------------------------------------

import json

from nanometa_live.core.parsers.blast_validation_parser import ValidationParser


def _write_minimap2_stats(results_dir, sample, taxid, **fields):
    mm2 = results_dir / "validation" / "minimap2"
    mm2.mkdir(parents=True, exist_ok=True)
    payload = {
        "sample_id": sample, "taxid": taxid, "validation_method": "minimap2",
        "total_reads": 0, "mapped_reads": 0, "hit_rate": 0.0, "avg_mapq": 0.0,
        "avg_identity": 0.0, "avg_coverage": 0.0, "validation_status": "rejected",
        "ref_name": "unknown", "ref_length": 0,
    }
    payload.update(fields)
    (mm2 / f"{sample}_taxid{taxid}.minimap2_stats.json").write_text(json.dumps(payload))


def test_minimap2_stats_surfaced_without_aggregate(tmp_path):
    """A confirmed minimap2 stats file is surfaced as a minimap2 result even
    when no aggregate validation_results.json exists (the realtime case)."""
    _write_minimap2_stats(
        tmp_path, "barcode14", 263,
        total_reads=24, mapped_reads=24, hit_rate=1.0, avg_mapq=60.0,
        avg_identity=99.79, avg_coverage=0.9434, validation_status="confirmed",
        ref_name="NZ_CP009607.1", ref_length=1870206,
    )
    results = ValidationParser(str(tmp_path)).get_validation_results()
    mm2 = [r for r in results if r.validation_method == "minimap2"]
    assert len(mm2) == 1
    r = mm2[0]
    assert r.sample_id == "barcode14" and r.taxid == 263
    assert r.validated_reads == 24
    assert r.percent_validated == 100.0           # hit_rate fraction -> percent
    assert 0.0 <= r.coverage_breadth <= 1.0       # stored as a fraction
    assert round(r.coverage_breadth, 3) == 0.943
    assert r.avg_mapq == 60.0
    assert (r.status.value if hasattr(r.status, "value") else r.status) == "confirmed"


def test_minimap2_rejected_is_no_data(tmp_path):
    """A 0-read minimap2 stats file maps to NO_DATA, not a noisy low result."""
    _write_minimap2_stats(tmp_path, "barcode15", 263)  # all-zero defaults
    results = ValidationParser(str(tmp_path)).get_validation_results()
    mm2 = [r for r in results if r.validation_method == "minimap2"]
    assert len(mm2) == 1
    assert (mm2[0].status.value if hasattr(mm2[0].status, "value")
            else mm2[0].status) == "no_data"


def test_minimap2_and_blast_coexist_for_same_taxid(tmp_path):
    """BLAST and minimap2 results for the same (sample, taxid) both survive --
    they are distinct methods, so the minimap2 scan must not dedup against blast."""
    # one minimap2 stats file
    _write_minimap2_stats(
        tmp_path, "barcode14", 263, total_reads=24, mapped_reads=24,
        hit_rate=1.0, avg_identity=99.0, avg_coverage=0.9, validation_status="confirmed",
    )
    # one blast.tsv for the same pair (12-col outfmt 6, two hits on one read)
    blast = tmp_path / "validation" / "blast"
    blast.mkdir(parents=True, exist_ok=True)
    (blast / "barcode14_taxid263.blast.tsv").write_text(
        "read1\tNZ_CP009607.1\t98.0\t500\t0\t0\t1\t500\t1\t500\t1e-50\t900\n"
    )
    results = ValidationParser(str(tmp_path)).get_validation_results()
    pair = [r for r in results if r.sample_id == "barcode14" and r.taxid == 263]
    methods = {r.validation_method for r in pair}
    assert "minimap2" in methods and "blast" in methods
