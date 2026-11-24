"""Per-sample QC table: quality is measured or blank, never invented.

Live test 2026-11-24:
- A zero-read sample's "Avg. Q score" read "Invalid Number": the loader put
  the string "N/A" in a column AG Grid types as numeric.
- On a fastp run the score was ``10 + 25 * q30_rate`` -- a formula, shown in
  green as "Mean Phred quality per read. Source: SeqKit". fastp reports no
  mean read quality, so the cell is blank there.
"""

import json
import os
import time

import pytest

from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
from nanometa_live.core.utils.qc_loaders import get_sample_statistics_summary

pytestmark = pytest.mark.unit


def _fastp(dirpath, sample, reads):
    d = dirpath / "fastp"
    d.mkdir(exist_ok=True)
    (d / f"{sample}.fastp.json").write_text(json.dumps({"summary": {
        "before_filtering": {"total_reads": reads, "total_bases": reads * 1000},
        "after_filtering": {"total_reads": reads, "total_bases": reads * 1000,
                            "q30_rate": 0.8, "q30_bases": reads * 800,
                            "gc_content": 0.5},
    }}))


@pytest.fixture
def run(tmp_path):
    clear_all_loader_caches()
    _fastp(tmp_path, "barcode01", 100)
    k = tmp_path / "kraken2"
    k.mkdir()
    (k / "barcode01.kraken2.report.txt").write_text(
        "10.00\t10\t10\tU\t0\tunclassified\n90.00\t90\t90\tR\t1\troot\n")
    (k / "barcode02.kraken2.report.txt").write_text("100.00\t0\t0\tU\t0\tunclassified\n")
    old = time.time() - 60
    for root, _d, files in os.walk(tmp_path):
        for f in files:
            os.utime(os.path.join(root, f), (old, old))
    yield tmp_path
    clear_all_loader_caches()


def test_missing_quality_is_null_not_a_string(run):
    df = get_sample_statistics_summary(str(run))
    for value in df["mean_quality"]:
        assert value is None or isinstance(value, (int, float)), value


def test_fastp_quality_is_not_invented(run):
    df = get_sample_statistics_summary(str(run))
    row = df[df["sample"] == "barcode01"].iloc[0]
    assert row["mean_quality"] is None or row["mean_quality"] != pytest.approx(30.0)


def test_grid_column_shows_a_dash_for_missing_and_names_its_sources():
    from nanometa_live.app.layouts.qc_layout import create_qc_layout

    def walk(n):
        yield n
        ch = getattr(n, "children", None)
        for c in (ch if isinstance(ch, (list, tuple)) else [ch] if ch is not None else []):
            yield from walk(c)

    def coldefs(defs):
        for d in defs:
            yield d
            yield from coldefs(d.get("children", []))

    grid = next(n for n in walk(create_qc_layout()) if getattr(n, "columnDefs", None))
    col = next(c for c in coldefs(grid.columnDefs) if c.get("field") == "mean_quality")
    assert "valueFormatter" in col
    assert "Source: SeqKit" not in col["headerTooltip"]
