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


class TestAnUnreadableSampleIsReported:
    """A sample whose report could not be read is not a negative result.

    Realtime detects a sample as soon as its output directory appears, which
    is before its first report lands, and rewrites each sample's cumulative
    report on every batch thereafter. A poll landing in either window gets an
    empty frame, and the sample silently disappeared from attribution:
    identical on screen to a sample that was measured and carries nothing.

    Observed live on 2026-09-01 at 21:14:46, one minute into a realtime run:
    barcode06 was in the sample list with no readable report while the banner
    read "Triggered by: F. tularensis (barcode05)", implying barcode06 had
    been screened and was clean.
    """

    def test_an_unparseable_sample_is_listed_as_unmeasured(self, tmp_path):
        from nanometa_live.app.tabs.dashboard_helpers import (
            _load_per_sample_organisms,
            unmeasured_samples,
        )

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)

        # barcode06 detected as a sample, no readable report yet.
        (results / "kraken2" / "barcode06" / "batch_reports").mkdir(parents=True)

        available = ["All Samples", "barcode05", "barcode06"]
        taxid_to_samples = _load_per_sample_organisms(str(results), available, {})

        assert [r["sample"] for r in taxid_to_samples[263]] == ["barcode05"]
        assert unmeasured_samples(str(results), available, {}) == ["barcode06"]

    def test_a_readable_empty_sample_is_not_unmeasured(self, tmp_path):
        """A sample that parsed and carries nothing is a negative, not a gap."""
        from nanometa_live.app.tabs.dashboard_helpers import unmeasured_samples

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)
        write_realtime_sample(results, "barcode06", 9999, "Escherichia coli", 900)

        assert unmeasured_samples(str(results), available_samples=[
            "All Samples", "barcode05", "barcode06"], config={}) == []

    def test_every_sample_readable_means_no_gap(self, realtime_snapshot):
        """The captured live snapshot has a readable report for each sample."""
        from nanometa_live.app.tabs.dashboard_helpers import unmeasured_samples
        from nanometa_live.core.utils.sample_detector import get_available_samples

        available = get_available_samples(str(realtime_snapshot))

        assert unmeasured_samples(str(realtime_snapshot), available, {}) == []

    def test_a_run_with_nothing_readable_is_not_a_partial_gap(self, tmp_path):
        """No sample readable at all is the verdict's own no-data state.

        Reporting it here would fire the note on every poll of a run that has
        not started writing yet, which trains the operator to ignore it.
        """
        from nanometa_live.app.tabs.dashboard_helpers import unmeasured_samples

        results = tmp_path / "results"
        (results / "kraken2" / "barcode05" / "batch_reports").mkdir(parents=True)
        (results / "kraken2" / "barcode06" / "batch_reports").mkdir(parents=True)

        assert unmeasured_samples(str(results), [
            "All Samples", "barcode05", "barcode06"], config={}) == []


class TestTheBannerReportsUnmeasuredSamples:
    """The verdict banner must say when a barcode was not screened."""

    def test_an_unreadable_barcode_is_named_on_the_banner(self, tmp_path, monkeypatch):
        from tests.test_verdict_banner_callback import _run_verdict_banner, _sample

        monkeypatch.setattr(
            "nanometa_live.app.tabs.dashboard_tab.unmeasured_samples",
            lambda *a, **k: ["barcode06"],
        )
        rendered = _run_verdict_banner(
            tmp_path,
            detections=[{
                "taxid": 1392, "detected_taxid": 88888,
                "name": "Bacillus anthracis", "threat_level": "critical",
                "reads": 350, "threshold": 10,
            }],
            taxid_to_samples={88888: [_sample("barcode05", 350)]},
            available_samples=["barcode05", "barcode06"],
        )

        assert "Bacillus anthracis (barcode05)" in rendered
        assert "barcode06" in rendered
        assert "not readable this poll" in rendered

    def test_no_note_when_every_sample_was_read(self, tmp_path, monkeypatch):
        from tests.test_verdict_banner_callback import _run_verdict_banner, _sample

        monkeypatch.setattr(
            "nanometa_live.app.tabs.dashboard_tab.unmeasured_samples",
            lambda *a, **k: [],
        )
        rendered = _run_verdict_banner(
            tmp_path,
            detections=[{
                "taxid": 1392, "detected_taxid": 88888,
                "name": "Bacillus anthracis", "threat_level": "critical",
                "reads": 350, "threshold": 10,
            }],
            taxid_to_samples={88888: [_sample("barcode05", 350)]},
            available_samples=["barcode05"],
        )

        assert "not readable this poll" not in rendered
