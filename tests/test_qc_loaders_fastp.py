"""Value-asserting tests for the fastp loaders in core/utils/qc_loaders.py.

Drives the parsers with a generated dataset and checks real relationships
(before >= after, passed_filter == after, per-sample fan-out) rather than just
that a non-empty object is returned.
"""

import os
import time

import pytest

from nanometa_live.core.utils.qc_loaders import (
    load_fastp_data,
    load_fastp_per_sample,
    get_qc_stats,
    _empty_fastp_stats,
)
from nanometa_live.core.testing.mock_data_generator import (
    generate_test_dataset,
    MockDataScenario,
)


@pytest.fixture(scope="module")
def qc_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("qc_loaders_fastp")
    generate_test_dataset(str(d), scenario=MockDataScenario.PATHOGEN_DETECTED, num_samples=3)
    old = time.time() - 30
    for dp, _dirs, files in os.walk(str(d)):
        for f in files:
            try:
                os.utime(os.path.join(dp, f), (old, old))
            except OSError:
                pass
    return str(d)


def test_load_fastp_data_aggregate_relationships(qc_dir):
    stats = load_fastp_data(qc_dir)
    assert stats["total_reads_before"] > 0
    # filtering can only remove reads
    assert stats["total_reads_after"] <= stats["total_reads_before"]
    assert stats["total_bases_after"] <= stats["total_bases_before"]
    # reads passing the filter == reads remaining after
    assert stats["passed_filter"] == stats["total_reads_after"]
    # removed buckets are non-negative and bounded by what was removed
    removed = stats["total_reads_before"] - stats["total_reads_after"]
    assert stats["low_quality"] >= 0 and stats["too_short"] >= 0
    assert stats["low_quality"] + stats["too_short"] <= removed + 1


def test_load_fastp_per_sample_fans_out(qc_dir):
    rows = load_fastp_per_sample(qc_dir)
    assert len(rows) == 3                       # three barcodes
    names = {r["sample"] for r in rows}
    assert names == {"barcode01", "barcode02", "barcode03"}
    for r in rows:
        assert r["reads_after"] > 0
        assert r["bases_after"] > 0
    # per-sample reads sum to the aggregate
    agg = load_fastp_data(qc_dir)
    assert sum(r["reads_after"] for r in rows) == agg["total_reads_after"]


def test_get_qc_stats_reports_fastp_source(qc_dir):
    qs = get_qc_stats(qc_dir)
    assert qs["source"] == "fastp"
    assert qs["total_reads"] > 0
    assert qs["total_reads_after"] <= qs["total_reads_before"]


def test_empty_dir_yields_empty_stats(tmp_path):
    stats = load_fastp_data(str(tmp_path))
    assert stats == _empty_fastp_stats()
    assert stats["total_reads_before"] == 0
    assert load_fastp_per_sample(str(tmp_path)) == []
