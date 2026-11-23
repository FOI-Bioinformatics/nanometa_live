"""An aggregated report's ``%`` column must mean what Kraken2's does.

Kraken2's ``%`` is the clade share: reads at the node and below
(``cumul_reads``) over all reads, classified and unclassified. A single-sample
load returns the parsed report and therefore that definition. The
multi-report aggregate ("All Samples", and a sample whose incremental batch
deltas are summed) recomputed the column as DIRECT reads over all reads, so
in the aggregate a genus carried only its unresolved reads, root and domain
read 0.0%, and the Organisms tab's minimum-abundance filter dropped rows in
"All Samples" that it kept for the same data viewed one sample at a time.
"""

import os
import time

import pytest

from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
from nanometa_live.core.utils.classification_loaders import load_kraken_data

pytestmark = pytest.mark.unit

# 100 reads: 20 unclassified, 80 classified under one genus (10 direct)
# and one species (70 direct).
_REPORT = (
    "20.00\t20\t20\tU\t0\tunclassified\n"
    "80.00\t80\t0\tR\t1\troot\n"
    "80.00\t80\t0\tD\t2\t  Bacteria\n"
    "80.00\t80\t10\tG\t100\t    GenusA\n"
    "70.00\t70\t70\tS\t101\t      GenusA speciesA\n"
)


def _write(kraken_dir, sample):
    path = kraken_dir / f"{sample}.kraken2.report.txt"
    path.write_text(_REPORT)
    old = time.time() - 60
    os.utime(path, (old, old))


@pytest.fixture
def two_identical_samples(tmp_path):
    clear_all_loader_caches()
    kraken_dir = tmp_path / "kraken2"
    kraken_dir.mkdir()
    _write(kraken_dir, "barcode01")
    _write(kraken_dir, "barcode02")
    yield tmp_path
    clear_all_loader_caches()


def _pct(df, taxid):
    return float(df.loc[df["taxid"] == taxid, "%"].iloc[0])


@pytest.mark.parametrize("taxid,expected", [
    (0, 20.0),    # unclassified
    (1, 80.0),    # root
    (2, 80.0),    # domain
    (100, 80.0),  # genus: clade share, not its 10 direct reads
    (101, 70.0),  # species (leaf: direct == clade)
])
def test_aggregate_percent_is_clade_share(two_identical_samples, taxid, expected):
    agg = load_kraken_data(str(two_identical_samples), sample="All Samples")
    assert _pct(agg, taxid) == pytest.approx(expected)


def test_aggregate_matches_single_sample_percent(two_identical_samples):
    single = load_kraken_data(str(two_identical_samples), sample="barcode01")
    agg = load_kraken_data(str(two_identical_samples), sample="All Samples")
    for taxid in (0, 1, 2, 100, 101):
        assert _pct(agg, taxid) == pytest.approx(_pct(single, taxid))
