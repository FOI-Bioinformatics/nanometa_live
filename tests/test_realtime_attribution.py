"""The attribution chain over a real-time-shaped results tree.

Every existing attribution test writes a flat ``<sample>.kraken2.report.txt``.
Real-time mode writes a progressive ``<sample>.cumulative.kraken2.report.txt``
that is rewritten every batch, plus per-batch reports under
``kraken2/<sample>/batch_reports/`` and the incremental-layout marker under
``kraken2/<sample>/stats/``. The loader resolves a different report tier for
that tree, so the layout needs its own coverage.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _backdate(path: Path, seconds: int = 5) -> None:
    """Age a file past the loader's 1 s stability window."""
    old = time.time() - seconds
    os.utime(path, (old, old))


def _kreport(rows: list[tuple[float, int, int, str, int, str]]) -> str:
    return "".join(
        f"{pct:.2f}\t{cumul}\t{reads}\t{rank}\t{taxid}\t{name}\n"
        for pct, cumul, reads, rank, taxid, name in rows
    )


def write_realtime_sample(
    results_dir: Path,
    sample: str,
    species_taxid: int,
    species_name: str,
    cumul_reads: int,
    direct_reads: int | None = None,
    n_batches: int = 3,
) -> None:
    """Write one sample in the real-time layout.

    Produces the progressive cumulative report the head process writes, the
    per-batch reports KRAKEN2_REPORT_GENERATOR publishes, and the
    ``stats/batch_N_report_stats.json`` marker that makes
    ``_is_incremental_layout`` return True.
    """
    direct = cumul_reads if direct_reads is None else direct_reads
    kraken = results_dir / "kraken2"
    kraken.mkdir(parents=True, exist_ok=True)

    total = cumul_reads + 10
    rows = [
        (0.0, 10, 10, "U", 0, "unclassified"),
        (100.0, cumul_reads, 0, "R", 1, "root"),
        (100.0, cumul_reads, 0, "D", 2, "  Bacteria"),
        (
            round(direct / total * 100, 2),
            cumul_reads,
            direct,
            "S",
            species_taxid,
            f"    {species_name}",
        ),
    ]
    cumulative = kraken / f"{sample}.cumulative.kraken2.report.txt"
    cumulative.write_text(_kreport(rows))
    _backdate(cumulative)

    batch_dir = kraken / sample / "batch_reports"
    batch_dir.mkdir(parents=True, exist_ok=True)
    stats_dir = kraken / sample / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    per_batch = max(1, cumul_reads // n_batches)
    for b in range(n_batches):
        batch_rows = [
            (0.0, 3, 3, "U", 0, "unclassified"),
            (100.0, per_batch, 0, "R", 1, "root"),
            (100.0, per_batch, 0, "D", 2, "  Bacteria"),
            (100.0, per_batch, per_batch, "S", species_taxid, f"    {species_name}"),
        ]
        report = batch_dir / f"{sample}_batch{b}.kraken2.report.txt"
        report.write_text(_kreport(batch_rows))
        _backdate(report)
        stats = stats_dir / f"batch_{b}_report_stats.json"
        stats.write_text('{"total_reads": %d}' % per_batch)
        _backdate(stats)


@pytest.fixture(autouse=True)
def _clean_loader_caches():
    """Loader caches are module-level; a leaked entry crosses tmp_path dirs."""
    from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

    clear_all_loader_caches()
    yield
    clear_all_loader_caches()


class TestProbeReadsTheRealtimeLayout:
    def test_probe_resolves_every_sample_and_its_tier(self, tmp_path):
        from scripts.audit_realtime_attribution import probe_results_dir

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)
        write_realtime_sample(results, "barcode06", 263, "Francisella tularensis", 40)

        report = probe_results_dir(str(results), config={})

        assert sorted(report["samples"]) == ["barcode05", "barcode06"]
        assert report["tiers"]["barcode05"] == "cumulative"
        assert 263 in report["aggregate_taxids"]
        assert sorted(report["per_sample_taxids"][263]) == ["barcode05", "barcode06"]


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "realtime_attribution"


@pytest.fixture
def realtime_snapshot(tmp_path):
    """A copy of the captured realtime snapshot, mtimes aged past the gate.

    Captured live on 2026-09-01 from a nanorunner-fed realtime run of the
    Bioshield demo (five barcodes, incremental Kraken2). Carries the
    progressive cumulative report, the per-batch reports under both
    ``reports/`` and ``batch_reports/``, and the ``stats/`` markers that make
    the loader treat the layout as incremental.
    """
    import shutil

    dest = tmp_path / "results"
    shutil.copytree(FIXTURE_DIR, dest)
    for path in dest.rglob("*"):
        if path.is_file():
            _backdate(path)
    return dest


class TestCapturedSnapshotResolvesItsSamples:
    def test_the_detection_resolves_at_least_one_sample(self, realtime_snapshot):
        """The captured tree must attribute its detections to named samples."""
        from scripts.audit_realtime_attribution import probe_results_dir

        report = probe_results_dir(str(realtime_snapshot), config={})

        assert report["per_sample_taxids"], (
            "no taxid resolved to any sample on a realtime tree that has "
            "per-sample reports on disk"
        )

    def test_francisella_is_carried_by_several_barcodes(self, realtime_snapshot):
        """F. tularensis (db taxid 4007169) is in every barcode of this run."""
        from scripts.audit_realtime_attribution import probe_results_dir

        report = probe_results_dir(str(realtime_snapshot), config={})

        carriers = report["per_sample_taxids"].get(4007169, [])
        assert len(carriers) >= 3, (
            f"expected the detection in at least 3 barcodes, got {carriers}"
        )
