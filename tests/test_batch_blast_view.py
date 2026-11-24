"""The single-batch BLAST view must read each batch's stats sidecar.

collect_batch_results parsed <sample>_taxid<tid>_<batch>.blast.tsv with no
read count and never applied the batch's blast_stats.json, so every BLAST
result in "Single batch" view read "Unknown | Low Confidence | 40 of 0
(0.0%)" while the Cumulative view of the same data was correct (live test
2026-11-24). The species name is filled from the sidecar or, failing that,
from the cumulative results for the same taxid.
"""

import json
import os
import time
from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

pytestmark = pytest.mark.unit


def _row(i):
    return f"read{i}\tref1\t98.5\t1500\t2\t0\t1\t1500\t1\t1500\t1e-80\t2700\n"


@pytest.fixture
def tree(tmp_path):
    vb = tmp_path / "validation" / "blast"
    batch = vb / "batch"
    batch.mkdir(parents=True)
    # Cumulative pair, carrying the species name.
    (vb / "barcode01_taxid263.blast.tsv").write_text("".join(_row(i) for i in range(90)))
    (vb / "barcode01_taxid263.blast_stats.json").write_text(json.dumps({
        "sample_id": "barcode01", "taxid": 263, "species": "Francisella tularensis",
        "total_reads": 100, "avg_identity": 98.5}))
    # Batch 3 of the same pair: 40 hits of 42 reads.
    (batch / "barcode01_taxid263_3.blast.tsv").write_text("".join(_row(i) for i in range(40)))
    (batch / "barcode01_taxid263_3.blast_stats.json").write_text(json.dumps({
        "sample_id": "barcode01", "taxid": 263, "total_reads": 42, "avg_identity": 98.5}))
    old = time.time() - 120
    for root, _d, files in os.walk(tmp_path):
        for f in files:
            os.utime(os.path.join(root, f), (old, old))
    return tmp_path


def test_batch_blast_result_has_its_denominator_and_status(tree):
    results = ValidationParser(Path(tree)).get_validation_results(batch_id="3")
    blast = [r for r in results if "blast" in str(getattr(r, "validation_method", "blast")).lower()
             or r.validated_reads == 40]
    r = next(r for r in blast if r.taxid == 263)
    assert r.validated_reads == 40
    assert r.total_reads == 42
    assert r.percent_validated == pytest.approx(40 / 42 * 100)
    assert r.status.value == "confirmed"


def test_batch_blast_result_is_named(tree):
    results = ValidationParser(Path(tree)).get_validation_results(batch_id="3")
    r = next(r for r in results if r.taxid == 263 and r.validated_reads == 40)
    assert r.species == "Francisella tularensis"
