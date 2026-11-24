"""Triage of a field run's counts, failures and lost inputs.

Two questions from the Barcelona exercise (2026-11-24 feedback) need the
run's own files: why the SeqKit statistics and the Kraken2 counts described
different reads, and what the pipeline did while the header said STANDBY.
``scripts/field_run_triage.py`` puts every per-sample count the GUI could
show side by side, with the run's failures, so the files can be read in one
pass when they arrive.
"""

import json
import os
import time

import pytest

from scripts.field_run_triage import main, triage

pytestmark = pytest.mark.unit

_SEQKIT_HEADER = "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\n"


def _seqkit_row(n):
    return f"x.fastq.gz\tFASTQ\tDNA\t{n}\t{n * 1000}\t1000\t1000.0\t1000\n"


@pytest.fixture
def run_dir(tmp_path):
    from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
    clear_all_loader_caches()
    root = tmp_path / "results"
    (root / "kraken2").mkdir(parents=True)
    (root / "kraken2" / "barcode01.kraken2.report.txt").write_text(
        "16.67\t20\t20\tU\t0\tunclassified\n"
        "83.33\t100\t0\tR\t1\troot\n"
        "83.33\t100\t100\tS\t562\t  Escherichia coli\n")
    seqkit = root / "seqkit"
    (seqkit / "barcode01" / "batch_stats").mkdir(parents=True)
    (seqkit / "barcode01.tsv").write_text(_SEQKIT_HEADER + _seqkit_row(80))
    for i in (1, 2):
        (seqkit / "barcode01" / "batch_stats" / f"barcode01.{i}.tsv").write_text(
            _SEQKIT_HEADER + _seqkit_row(60))
    counts = root / "chopper" / "barcode01" / "counts"
    counts.mkdir(parents=True)
    (counts / "barcode01.1.chopper_counts.txt").write_text(
        "Kept 120 reads out of 150 reads\n")
    lost = root / "pipeline_info" / "lost_inputs"
    lost.mkdir(parents=True)
    (lost / "CHOPPER.barcode01.abc.json").write_text(json.dumps(
        {"stage": "CHOPPER", "sample": "barcode01", "exit_status": 1,
         "input_files": ["a.fastq.gz"]}))
    (root / "realtime_stats").mkdir()
    (root / "realtime_stats" / "cumulative_stats.json").write_text(json.dumps(
        {"totals": {"total_estimated_reads": 1000}}))
    (root / ".nanometa.run.json").write_text(json.dumps(
        {"final_status": "completed", "failed_tasks": ["CHOPPER (a.fastq.gz)"]}))
    old = time.time() - 60
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            os.utime(os.path.join(dirpath, f), (old, old))
    yield root
    clear_all_loader_caches()


def test_triage_puts_every_count_side_by_side(run_dir):
    report = triage(str(run_dir))
    assert report["samples"] == [{
        "sample": "barcode01",
        "kraken_reads": 120,
        "seqkit_merged_reads": 80,
        "seqkit_batch_reads": 120,
        "chopper_in": 150,
        "chopper_kept": 120,
    }]
    run = report["run"]
    assert run["run_state"] == "completed"
    assert run["failed_tasks"] == ["CHOPPER (a.fastq.gz)"]
    assert run["lost_inputs"] == 1
    assert run["estimated_reads"] == 1000


def test_cli_names_the_mismatched_sample(run_dir, capsys):
    assert main([str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "barcode01" in out
    assert "SeqKit merged 80 vs Kraken2 120" in out


def test_cli_json(run_dir, capsys):
    assert main([str(run_dir), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["samples"][0]["chopper_in"] == 150


def test_missing_directory_is_an_error(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2
