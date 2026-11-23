"""Pooled seqkit statistics must be weighted, and N50 must not be invented.

Four sites summarised several seqkit rows (one per sample in "All Samples")
with plain column means: a 10-read sample counted as much as a 1,000-read
one. Mean length is total bases over total reads; mean quality, Q20/Q30 and
GC are per-base figures and are weighted by bases (as nanometanf's seqkit
merge does). N50 of pooled reads cannot be derived from per-sample N50s:
one site reported the largest and another the mean, neither of which is an
N50, so a pooled N50 is reported as unknown.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from nanometa_live.core.utils import qc_loaders
from nanometa_live.core.utils.qc_loaders import summarize_seqkit_rows

pytestmark = pytest.mark.unit


def _row(num_seqs, avg_len, qual, n50, q20=80.0, gc=40.0):
    return {"num_seqs": num_seqs, "sum_len": num_seqs * avg_len,
            "min_len": avg_len, "max_len": avg_len, "avg_len": avg_len,
            "Q2": avg_len, "N50": n50, "AvgQual": qual,
            "Q20(%)": q20, "Q30(%)": q20 / 2, "GC(%)": gc}


TWO_SAMPLES = pd.DataFrame([
    _row(10, 1000, 14.0, 1000, q20=90.0, gc=30.0),
    _row(1000, 5000, 10.0, 9000, q20=70.0, gc=50.0),
])


def test_mean_length_is_bases_over_reads():
    s = summarize_seqkit_rows(TWO_SAMPLES)
    assert s["total_reads"] == 1010
    assert s["mean_length"] == pytest.approx(5_010_000 / 1010)


def test_per_base_figures_are_base_weighted():
    s = summarize_seqkit_rows(TWO_SAMPLES)
    w1, w2 = 10_000, 5_000_000
    assert s["mean_quality"] == pytest.approx((14 * w1 + 10 * w2) / (w1 + w2))
    assert s["q20_percent"] == pytest.approx((90 * w1 + 70 * w2) / (w1 + w2))
    assert s["gc_percent"] == pytest.approx((30 * w1 + 50 * w2) / (w1 + w2))


def test_pooled_n50_and_median_are_unknown():
    s = summarize_seqkit_rows(TWO_SAMPLES)
    assert s["n50"] is None
    assert s["median_length"] is None


def test_single_row_keeps_its_own_n50_and_median():
    s = summarize_seqkit_rows(TWO_SAMPLES.iloc[[1]])
    assert s["n50"] == 9000
    assert s["median_length"] == 5000


def test_all_samples_qc_stats_use_the_weighted_summary(tmp_path):
    with patch.object(qc_loaders, "load_seqkit_stats", return_value=TWO_SAMPLES):
        nano = qc_loaders._load_seqkit_as_nanoplot_stats(str(tmp_path))
    assert nano["mean_read_length"] == pytest.approx(5_010_000 / 1010)
    assert nano["read_length_n50"] is None


# --- Real-time batches: no invented N50 or quartiles --------------------------
#
# _aggregate_seqkit_batches (the GUI's view of a running real-time sample)
# set N50 = mean length and Q1/Q3 = 0.75x / 1.5x the mean, and nanometanf's
# SEQKIT_MERGE_STATS writes the same approximations into the session-end
# <sample>.cumulative.fastq.gz row. The QC table and Read Statistics card
# showed them as measurements; for a long-tailed nanopore length
# distribution the N50 is well above the mean.

def _batch(num_seqs, avg_len, n50):
    return pd.DataFrame([{**_row(num_seqs, avg_len, 12.0, n50),
                          "Q1": avg_len * 0.5, "Q3": avg_len * 2,
                          "file": "b.fastq.gz"}])


def test_several_batches_leave_n50_and_quartiles_unknown():
    row = qc_loaders._aggregate_seqkit_batches(
        [_batch(100, 3000, 7000), _batch(200, 4000, 9000)], "barcode01")
    for key in ("N50", "Q1", "Q2", "Q3", "N50_num"):
        assert row[key] is None, key
    assert row["avg_len"] == pytest.approx(round(1_100_000 / 300, 1))


def test_one_contributing_batch_keeps_its_measured_values():
    row = qc_loaders._aggregate_seqkit_batches(
        [_batch(100, 3000, 7000), _batch(0, 0, 0)], "barcode01")
    assert row["N50"] == 7000
    assert row["Q3"] == 6000


def test_summary_of_an_aggregated_row_reports_unknown_n50():
    row = qc_loaders._aggregate_seqkit_batches(
        [_batch(100, 3000, 7000), _batch(200, 4000, 9000)], "barcode01")
    s = summarize_seqkit_rows(pd.DataFrame([row]))
    assert s["n50"] is None
    assert s["median_length"] is None


def test_summary_of_the_pipeline_merged_row_reports_unknown_n50():
    merged = pd.DataFrame([{**_row(300, 3667, 12.0, 3666),
                            "file": "barcode01.cumulative.fastq.gz"}])
    assert summarize_seqkit_rows(merged)["n50"] is None
