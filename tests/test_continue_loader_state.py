"""Loader behaviour on a Continue into a populated outdir (round-4 audit).

Three findings, all observed live on 2026-09-01 (docs/audit/
realtime-round4-2026-09-02.md):

- H7: ``canonical/_manifest.json`` replaced disk discovery, so a barcode
  whose output appeared during the continued run never reached the sample
  selector (the manifest is written once, at session end, and describes the
  previous run).
- H6b: ``load_kraken_data(main_dir, sample)`` preferred the previous run's
  canonical JSON over a cumulative report the new run had just rewritten:
  barcode05 read 2,627 per sample while its cumulative file held 69.
- H17: the no-data mapping globbed only the flat report forms, so a sample
  whose only output so far was ``kraken2/<sample>/batch_reports/`` was marked
  as having produced nothing.
"""

import json
import os
import shutil
import time

import pytest

from nanometa_live.core.utils import classification_loaders
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
from nanometa_live.core.utils.sample_detector import (
    _sample_output_files,
    invalidate_sample_cache,
    get_available_samples,
)

pytestmark = pytest.mark.unit

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "realtime_attribution", "kraken2",
                       "barcode06.cumulative.kraken2.report.txt")


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _write_report(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copy(FIXTURE, path)
    _age(path, 30)


def _write_canonical(results_dir, sample, reads_clade):
    d = os.path.join(results_dir, "canonical", "classification")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{sample}.classification.json")
    with open(path, "w") as f:
        json.dump({"taxa": [
            {"percent": 100.0, "reads_clade": reads_clade, "reads_direct": 0,
             "rank": "R", "taxid": 1, "name": "root", "parent_taxid": 0},
            {"percent": 100.0, "reads_clade": reads_clade, "reads_direct": reads_clade,
             "rank": "S", "taxid": 562, "name": "Escherichia coli", "parent_taxid": 1},
        ]}, f)
    return path


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_all_loader_caches()
    invalidate_sample_cache()
    yield
    clear_all_loader_caches()
    invalidate_sample_cache()


class TestManifestIsUnionedWithDisk:
    def test_late_barcode_is_listed_beside_manifest_samples(self, tmp_path):
        rd = str(tmp_path)
        for s in ("barcode05", "barcode06"):
            _write_report(os.path.join(rd, "kraken2", f"{s}.cumulative.kraken2.report.txt"))
        os.makedirs(os.path.join(rd, "canonical"))
        with open(os.path.join(rd, "canonical", "_manifest.json"), "w") as f:
            json.dump({"samples": ["barcode05", "barcode06"], "failed_samples": []}, f)
        # The continued run starts writing a barcode the manifest never saw.
        _write_report(os.path.join(rd, "kraken2", "barcode91", "batch_reports",
                                   "barcode91_batch0.kraken2.report.txt"))
        samples = get_available_samples(rd)
        assert "barcode91" in samples
        assert "barcode05" in samples and "barcode06" in samples
        assert samples[0] == "All Samples"

    def test_manifest_only_sample_is_kept(self, tmp_path):
        """A sample the manifest names but whose files vanished stays listed
        (marked, never hidden -- the existing contract)."""
        rd = str(tmp_path)
        _write_report(os.path.join(rd, "kraken2", "barcode05.cumulative.kraken2.report.txt"))
        os.makedirs(os.path.join(rd, "canonical"))
        with open(os.path.join(rd, "canonical", "_manifest.json"), "w") as f:
            json.dump({"samples": ["barcode05", "barcode16"], "failed_samples": []}, f)
        assert "barcode16" in get_available_samples(rd)


class TestStaleCanonicalDoesNotOutrankALiveReport:
    def test_newer_cumulative_report_wins(self, tmp_path):
        rd = str(tmp_path)
        can = _write_canonical(rd, "barcode06", reads_clade=2627)
        _age(can, 600)
        _write_report(os.path.join(rd, "kraken2", "barcode06.cumulative.kraken2.report.txt"))
        df = load_kraken_data(rd, "barcode06")
        root = int(df.loc[df["taxid"] == 1, "cumul_reads"].iloc[0])
        assert root == 377, "the live report (377 root reads) must win over the older canonical JSON"

    def test_current_canonical_still_wins(self, tmp_path):
        rd = str(tmp_path)
        _write_report(os.path.join(rd, "kraken2", "barcode06.cumulative.kraken2.report.txt"))
        can = _write_canonical(rd, "barcode06", reads_clade=2627)
        _age(can, 5)  # newer than the 30 s old report
        df = load_kraken_data(rd, "barcode06")
        root = int(df.loc[df["taxid"] == 1, "cumul_reads"].iloc[0])
        assert root == 2627

    def test_canonical_alone_is_used(self, tmp_path):
        rd = str(tmp_path)
        _write_canonical(rd, "barcode06", reads_clade=2627)
        df = load_kraken_data(rd, "barcode06")
        assert int(df.loc[df["taxid"] == 1, "cumul_reads"].iloc[0]) == 2627


class TestNestedBatchReportsCountAsOutput:
    def test_batch_reports_only_sample_has_kraken2_files(self, tmp_path):
        rd = str(tmp_path)
        _write_report(os.path.join(rd, "kraken2", "barcode91", "batch_reports",
                                   "barcode91_batch0.kraken2.report.txt"))
        files = _sample_output_files(rd, "barcode91")
        assert files.get("kraken2"), "a sample with only per-batch reports has produced output"
