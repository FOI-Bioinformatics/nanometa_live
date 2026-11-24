"""How many input files a finished real-time run did not classify.

The header and the report said "N input files ... were not processed
(arrived after the run ended)" with N = every FASTQ in the watched folder
minus files_processed. That counts files the start-up age filter skipped on
purpose and files an earlier run already classified, and the "arrived after"
clause was then false. nanometanf's ledger
(pipeline_info/processed_inputs.tsv) lists every input a run finished
classifying, so the unprocessed files are the ones absent from it.
"""

import os
import time

import pytest

from nanometa_live.app.callbacks.status import _unprocessed_input_note
from nanometa_live.core.export.run_status import count_unprocessed_inputs

pytestmark = pytest.mark.unit


def _fastq(path, age_s=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@r\nA\n+\nI\n")
    t = time.time() - age_s
    os.utime(path, (t, t))
    return path


@pytest.fixture
def run(tmp_path):
    inbox, outdir = tmp_path / "inbox", tmp_path / "out"
    done = [_fastq(inbox / "barcode01" / f"r{i}.fastq.gz") for i in range(3)]
    old = _fastq(inbox / "barcode01" / "old.fastq.gz", age_s=3 * 3600)
    late = [_fastq(inbox / "barcode02" / f"late{i}.fastq.gz") for i in range(2)]
    (outdir / "pipeline_info").mkdir(parents=True)
    (outdir / "pipeline_info" / "processed_inputs.tsv").write_text(
        "sample_id\tbatch_id\tsource_file\tcompleted_at\n" + "".join(
            f"barcode01\t{i}\t{p}\t2026-11-23T10:00:00\n" for i, p in enumerate(done)))
    started = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 600))
    return inbox, outdir, started, old, late


def test_counts_files_absent_from_the_ledger(run):
    inbox, outdir, started, _old, _late = run
    # old.fastq.gz is unprocessed too when no age filter applies.
    assert count_unprocessed_inputs(str(outdir), str(inbox), started, None) == 3


def test_files_skipped_by_the_age_filter_are_not_counted(run):
    inbox, outdir, started, _old, _late = run
    assert count_unprocessed_inputs(str(outdir), str(inbox), started, 60) == 2


def test_no_ledger_means_unknown(run, tmp_path):
    inbox, _outdir, started, _old, _late = run
    assert count_unprocessed_inputs(str(tmp_path / "nowhere"), str(inbox), started, None) is None


def test_header_prefers_the_ledger_count_and_states_no_cause():
    status = {"files_waiting": 47, "files_processed": 10,
              "unprocessed_input_files": 2}
    note = _unprocessed_input_note(status, {"processing_mode": "realtime"})
    assert "2 input files" in note
    assert "arrived after" not in note


def test_header_fallback_does_not_claim_a_cause():
    status = {"files_waiting": 47, "files_processed": 33}
    note = _unprocessed_input_note(status, {"processing_mode": "realtime"})
    assert "14" in note
    assert "arrived after" not in note


def test_report_reads_the_recorded_count(tmp_path):
    import json
    from nanometa_live.core.export.run_status import read_final_run_status
    (tmp_path / ".nanometa.run.json").write_text(json.dumps({
        "final_status": "completed", "files_processed": 33,
        "input_files_at_end": 47, "unprocessed_input_files": 2}))
    assert read_final_run_status(str(tmp_path))["unprocessed_input_files"] == 2
