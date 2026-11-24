"""The Dashboard sample table must not present missing data as a result.

``_collect_samples_data`` graded a sample whose report held no reads -- the
``100.00 0 0 U 0 unclassified`` placeholder nanometanf publishes for a sample
that produced nothing -- as quality "Excellent", status "Complete" and 100.0%
classified, the best possible row. It also counted reads with
``kraken_df["reads"].sum()`` and derived the rate from it, where the
Dashboard tile uses ``get_classification_stats`` (root + unclassified
cumulative reads); the two disagreed on the same sample.
"""

import os
import time

import pytest

from nanometa_live.app.tabs.dashboard_helpers import _collect_samples_data
from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

pytestmark = pytest.mark.unit

_PLACEHOLDER = "100.00\t0\t0\tU\t0\tunclassified\n"

# 100 reads, 25 unclassified. Direct reads sit on several ranks so a
# reads.sum() count and the cumulative count could differ if the report
# were not self-consistent; here they agree by construction.
_REPORT = (
    "25.00\t25\t25\tU\t0\tunclassified\n"
    "75.00\t75\t5\tR\t1\troot\n"
    "70.00\t70\t0\tD\t2\t  Bacteria\n"
    "70.00\t70\t10\tG\t100\t    GenusA\n"
    "60.00\t60\t60\tS\t101\t      GenusA speciesA\n"
)


@pytest.fixture
def results(tmp_path):
    clear_all_loader_caches()
    kdir = tmp_path / "kraken2"
    kdir.mkdir()
    for sample, text in (("barcode01", _PLACEHOLDER), ("barcode02", _REPORT)):
        p = kdir / f"{sample}.kraken2.report.txt"
        p.write_text(text)
        old = time.time() - 60
        os.utime(p, (old, old))
    yield tmp_path
    clear_all_loader_caches()


def _row(results, sample):
    rows = _collect_samples_data(str(results), ["All Samples", sample])
    assert len(rows) == 1
    return rows[0]


def test_zero_read_sample_is_not_graded_as_complete(results):
    row = _row(results, "barcode01")
    assert row["reads"] == "0"
    assert row["status"] != "Complete"
    assert row["quality"] not in ("Excellent", "Good")
    assert row["class_rate"] == "--"


def test_counts_match_the_dashboard_tile_definition(results):
    row = _row(results, "barcode02")
    assert row["reads"] == "100"
    assert row["class_rate"] == "75.0%"
    assert row["status"] == "Complete"
