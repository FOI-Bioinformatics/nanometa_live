"""Round-2 per-tick loader fixes (barcode axis).

Each test pins one of the audit's ungated/uncached per-tick S-scans:
- `load_nanoplot_stats` was the only loader without an mtime cache and is
  called several times per tick (`_estimate_quality_score` alone calls it
  twice).
- `freshness_map`'s flat-layout fallback scanned the whole kraken2/ dir
  once PER SAMPLE (O(S x F)).
- `_count_processed_samples` ran one glob per sample to derive one integer.
- The QC base-quality/read-stats cards json.load'ed every fastp file inline
  per tick, bypassing the cached `load_fastp_per_sample`.
"""

import os
import time
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def _backdate(path, seconds=60):
    back = time.time() - seconds
    os.utime(path, (back, back))


@pytest.fixture
def nanoplot_tree(tmp_path):
    nd = tmp_path / "nanoplot"
    for sample in ("barcode01", "barcode02"):
        d = nd / sample
        d.mkdir(parents=True)
        f = d / "NanoStats.txt"
        f.write_text(
            "Mean read length: 1,000.0\nMean read quality: 12.0\n"
            "Median read length: 900.0\nMedian read quality: 12.5\n"
            "Number of reads: 100\nRead length N50: 1,200\n"
            "Total bases: 100,000\n"
        )
        _backdate(f)
    return tmp_path


class TestNanoplotMtimeCache:
    @pytest.fixture(autouse=True)
    def _epoch_zero(self):
        """Another test in the process may have bumped the freshness epoch;
        with an epoch set, the mtime cache answers within-epoch lookups
        without re-checking paths (by design for non-polling callers).
        These tests exercise the path check itself, so force epoch 0."""
        from nanometa_live.core.utils import loader_utils
        before = loader_utils._freshness_epoch
        loader_utils._freshness_epoch = 0
        yield
        loader_utils._freshness_epoch = before

    def test_second_load_parses_nothing(self, nanoplot_tree):
        from nanometa_live.core.utils import qc_loaders
        calls = {"n": 0}
        orig = qc_loaders._parse_nanostats_file

        def counting(path):
            calls["n"] += 1
            return orig(path)

        with patch.object(qc_loaders, "_parse_nanostats_file", counting):
            first = qc_loaders.load_nanoplot_stats(str(nanoplot_tree))
            second = qc_loaders.load_nanoplot_stats(str(nanoplot_tree))
        assert first["number_of_reads"] == 200
        assert second == first
        assert calls["n"] == 2, (
            f"expected one parse per file on the first load only; "
            f"got {calls['n']} parses across two loads"
        )

    def test_new_file_invalidates(self, nanoplot_tree):
        from nanometa_live.core.utils import qc_loaders
        qc_loaders.load_nanoplot_stats(str(nanoplot_tree))
        d = nanoplot_tree / "nanoplot" / "barcode03"
        d.mkdir()
        f = d / "NanoStats.txt"
        f.write_text("Number of reads: 50\nTotal bases: 5,000\n")
        _backdate(f, 45)
        result = qc_loaders.load_nanoplot_stats(str(nanoplot_tree))
        assert result["number_of_reads"] == 250


class TestFreshnessMapSingleScan:
    def test_flat_layout_scans_kraken_dir_once(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        samples = [f"barcode{i:02d}" for i in range(20)]
        for s in samples:
            (kraken / f"{s}.kraken2.report.txt").write_text("x")

        from nanometa_live.app.utils import freshness
        calls = {"n": 0}
        orig = os.scandir

        def counting(path="."):
            calls["n"] += 1
            return orig(path)

        with patch.object(freshness.os, "scandir", counting):
            result = freshness.freshness_map(str(tmp_path), samples)
        assert set(result) == set(samples)
        assert calls["n"] <= 3, (
            f"{calls['n']} scandir calls for 20 flat-layout samples; the "
            f"fallback must scan kraken2/ once, not once per sample"
        )


class TestCountProcessedSamplesSingleScan:
    def test_no_per_sample_globs(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        samples = [f"barcode{i:02d}" for i in range(20)]
        for s in samples[:15]:
            (kraken / f"{s}.kraken2.report.txt").write_text("x")

        import glob as glob_module
        from nanometa_live.app.tabs import dashboard_helpers
        calls = {"n": 0}
        orig = glob_module.glob

        def counting(pattern, **kw):
            calls["n"] += 1
            return orig(pattern, **kw)

        with patch.object(dashboard_helpers.glob, "glob", counting):
            count = dashboard_helpers._count_processed_samples(
                str(tmp_path), samples)
        assert count == 15
        assert calls["n"] == 0, (
            f"{calls['n']} glob calls; one scandir must answer for all "
            f"samples"
        )


class TestSampleFileMappingCache:
    def test_second_call_does_no_globs(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        for i in range(10):
            (kraken / f"barcode{i:02d}.kraken2.report.txt").write_text("x")

        import glob as glob_module
        from nanometa_live.core.utils import sample_detector
        sample_detector.get_sample_file_mapping(str(tmp_path))  # warm

        calls = {"n": 0}
        orig = glob_module.glob

        def counting(pattern, **kw):
            calls["n"] += 1
            return orig(pattern, **kw)

        with patch.object(sample_detector.glob, "glob", counting):
            mapping = sample_detector.get_sample_file_mapping(str(tmp_path))
        assert len(mapping) == 10
        assert calls["n"] == 0, (
            f"{calls['n']} globs on an unchanged tree; the mapping must be "
            f"served from the mtime cache (was 6 globs x S per tick)"
        )

    def test_new_file_invalidates(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        (kraken / "barcode00.kraken2.report.txt").write_text("x")
        from nanometa_live.core.utils import sample_detector
        first = sample_detector.get_sample_file_mapping(str(tmp_path))
        assert set(first) == {"barcode00"}
        time.sleep(0.01)
        (kraken / "barcode01.kraken2.report.txt").write_text("x")
        os.utime(kraken)
        second = sample_detector.get_sample_file_mapping(str(tmp_path))
        assert set(second) == {"barcode00", "barcode01"}


class TestSlimFileMappingStore:
    def test_slim_keeps_presence_only(self):
        from nanometa_live.app.callbacks.samples import slim_file_mapping
        full = {
            "barcode01": {"kraken2": ["/a/b1.txt", "/a/b2.txt"],
                          "fastp": ["/f/x.json"]},
            "barcode02": {},
        }
        slim = slim_file_mapping(full)
        assert slim == {"barcode01": True}

    def test_dataless_detection_works_on_the_slim_form(self):
        from nanometa_live.app.callbacks.samples import (
            _dataless_samples, slim_file_mapping,
        )
        full = {"barcode01": {"kraken2": ["/a/b.txt"]}}
        slim = slim_file_mapping(full)
        dataless = _dataless_samples(
            ["All Samples", "barcode01", "barcode02"], slim, None)
        assert dataless == {"barcode02"}


class TestOnDemandReloadGate:
    def _fn(self):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs.main_tab import register_main_callbacks
        app = make_callback_app(register_main_callbacks)
        return get_callback_fn(app, "on-demand-validation-results")

    def test_unchanged_dir_prevents_update_without_parsing(self, tmp_path):
        import json as json_module
        od = tmp_path / "on_demand_validation"
        od.mkdir()
        (od / "666_validation.json").write_text('{"taxid": 666}')
        from dash.exceptions import PreventUpdate
        from nanometa_live.app.tabs import main_tab
        main_tab._od_results_fp.clear()
        fn = self._fn()
        config = {"results_dir_override": str(tmp_path)}
        results, _notif = fn(1, config, None)
        assert "666" in results

        calls = {"n": 0}
        orig = json_module.load

        def counting(fh, **kw):
            calls["n"] += 1
            return orig(fh, **kw)

        with patch.object(main_tab.json, "load", counting):
            with pytest.raises(PreventUpdate):
                fn(2, config, results)
        assert calls["n"] == 0

    def test_new_result_file_reloads(self, tmp_path):
        od = tmp_path / "on_demand_validation"
        od.mkdir()
        (od / "666_validation.json").write_text('{"taxid": 666}')
        from nanometa_live.app.tabs import main_tab
        main_tab._od_results_fp.clear()
        fn = self._fn()
        config = {"results_dir_override": str(tmp_path)}
        results, _ = fn(1, config, None)
        time.sleep(0.01)
        (od / "777_validation.json").write_text('{"taxid": 777}')
        results2, _ = fn(2, config, results)
        assert set(results2) == {"666", "777"}


class TestFastpCardPayloadsCache:
    PAYLOAD = (
        '{"summary": {"after_filtering": {"total_reads": 100, '
        '"total_bases": 10000, "q20_bases": 9000, "q30_bases": 8000}}, '
        '"read1_after_filtering": {"quality_curves": {"mean": [30, 31]}}}'
    )

    def _tree(self, tmp_path, names):
        fastp = tmp_path / "fastp"
        fastp.mkdir(exist_ok=True)
        for name in names:
            f = fastp / f"{name}.fastp.json"
            f.write_text(self.PAYLOAD)
            _backdate(f)

    def test_second_load_parses_nothing(self, tmp_path):
        self._tree(tmp_path, [f"barcode{i:02d}" for i in range(5)])
        from nanometa_live.core.utils import qc_loaders
        calls = {"n": 0}
        orig = qc_loaders.json.load

        def counting(fh, **kw):
            calls["n"] += 1
            return orig(fh, **kw)

        with patch.object(qc_loaders.json, "load", counting):
            first = qc_loaders.load_fastp_card_payloads(str(tmp_path))
            second = qc_loaders.load_fastp_card_payloads(str(tmp_path))
        assert len(first) == 5 and len(second) == 5
        assert calls["n"] == 5, (
            f"{calls['n']} json.load calls across two loads; the second "
            f"must be a cache hit"
        )
        curve = first[0]["read1_after_filtering"]["quality_curves"]["mean"]
        assert curve == [30, 31]

    def test_sample_scoping_is_exact(self, tmp_path):
        """barcode1 must not pick up barcode10's report (the historical
        prefix-match defect the old helper fixed; the loader keeps it)."""
        self._tree(tmp_path, ["barcode1", "barcode10"])
        from nanometa_live.core.utils import qc_loaders
        scoped = qc_loaders.load_fastp_card_payloads(str(tmp_path), "barcode1")
        assert len(scoped) == 1


class TestRealtimeOutputsCountAsData:
    """The dataless marker must not fire on a sample whose only artifacts
    are the realtime-primary files.

    Live find (2026-08-25 verify run): early in a realtime run a sample has
    only <sample>.cumulative.kraken2.report.txt (written first) and seqkit
    batch stats -- no standard-named report, no fastp. _sample_output_files
    matched neither, so the selector showed "produced no output files.
    ... nothing was written" for four samples whose cumulative reports were
    on disk and rendering in the Organisms tab at that moment."""

    def test_cumulative_only_sample_is_mapped(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        (kraken / "barcode05.cumulative.kraken2.report.txt").write_text("x")
        from nanometa_live.core.utils import sample_detector
        mapping = sample_detector.get_sample_file_mapping(str(tmp_path))
        assert "barcode05" in mapping
        assert mapping["barcode05"]["kraken2"]

    def test_seqkit_only_sample_is_mapped(self, tmp_path):
        seqkit = tmp_path / "seqkit"
        seqkit.mkdir()
        (seqkit / "barcode06.tsv").write_text("x")
        batch = seqkit / "barcode07" / "batch_stats"
        batch.mkdir(parents=True)
        (batch / "barcode07_batch0.tsv").write_text("x")
        from nanometa_live.core.utils import sample_detector
        mapping = sample_detector.get_sample_file_mapping(str(tmp_path))
        assert "barcode06" in mapping and mapping["barcode06"]["seqkit"]
        assert "barcode07" in mapping and mapping["barcode07"]["seqkit"]
