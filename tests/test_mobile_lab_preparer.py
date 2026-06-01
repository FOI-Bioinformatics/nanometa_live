"""
Unit tests for core/workflow/mobile_lab_preparer.py (was 25%).

The preparer orchestrates the offline-readiness stages (verify DB, build index,
download genomes, build BLAST DBs, cache taxonomy, check tools, readiness). These
tests cover the pure dataclasses, the progress arithmetic, the ``prepare()``
dispatch loop (ordering, cancellation, critical-vs-non-critical error handling),
and the individual stage methods with their downstream dependencies mocked. No
network, no subprocess, no real binaries.
"""

import pytest

from nanometa_live.core.workflow.mobile_lab_preparer import (
    MobileLabPreparer,
    PrepProgress,
    PrepStage,
    PreparationResult,
    STAGE_LABELS,
)

pytestmark = pytest.mark.unit


def make_preparer(tmp_path, config=None, cb=None):
    return MobileLabPreparer(
        config if config is not None else {"kraken_db": "/db"},
        nanometa_home=str(tmp_path),
        progress_callback=cb,
    )


class TestInjectedWatchlistEntries:
    """In a background worker the WatchlistManager singleton is empty, so the
    preparer must accept entries injected from the main process (the
    watchlist-entries-snapshot store). Regression for the E2E finding where
    Start Preparation generated no taxid mappings ("No watchlist entries
    found for mapping")."""

    def test_injected_entries_used_over_empty_singleton(self, tmp_path):
        snapshot = [
            {"name": "Staphylococcus aureus", "taxid": 1280, "names_alt": []},
            {"name": "Escherichia coli", "taxid": 562, "names_alt": ["E. coli"]},
        ]
        prep = MobileLabPreparer(
            {"kraken_db": "/db"},
            nanometa_home=str(tmp_path),
            watchlist_entries=snapshot,
        )
        entries = prep._get_watchlist_entries()
        taxids = sorted(e["taxid"] for e in entries)
        assert taxids == [562, 1280]
        # kraken_taxid falls back to the watchlist taxid when no mapping exists
        assert all(e["kraken_taxid"] == e["taxid"] for e in entries)

    def test_no_injection_falls_back_to_singleton(self, tmp_path):
        # No injected entries -> reads the (empty in tests) singleton; must not
        # raise and returns a list.
        prep = MobileLabPreparer({"kraken_db": "/db"}, nanometa_home=str(tmp_path))
        assert isinstance(prep._get_watchlist_entries(), list)


class TestDataclasses:
    def test_prep_progress_to_dict(self):
        p = PrepProgress(
            stage=PrepStage.VERIFY_DB,
            stage_label="Verifying",
            stage_index=0,
            stage_detail="checking",
            stage_progress=50.0,
            overall_progress=6.25,
        )
        d = p.to_dict()
        assert d["stage"] == "verify_db"  # enum value, not the member
        assert d["stage_label"] == "Verifying"
        assert d["stage_progress"] == 50.0
        assert d["total_stages"] == len(PrepStage)

    def test_preparation_result_defaults_and_to_dict(self):
        r = PreparationResult(success=True)
        assert r.stages_completed == [] and r.errors == []
        d = r.to_dict()
        assert d["success"] is True
        assert d["genomes_downloaded"] == 0
        assert d["blast_dbs_built"] == 0
        assert set(d) == {
            "success", "stages_completed", "stages_failed", "errors",
            "warnings", "genomes_downloaded", "blast_dbs_built",
        }

    def test_stage_labels_cover_every_stage(self):
        assert set(STAGE_LABELS) == set(PrepStage)


class TestReportAndCancel:
    def test_cancel_sets_flag(self, tmp_path):
        prep = make_preparer(tmp_path)
        assert prep._cancelled is False
        prep.cancel()
        assert prep._cancelled is True

    def test_report_overall_progress_math(self, tmp_path):
        captured = []
        prep = make_preparer(tmp_path, cb=captured.append)
        # Stage index 0 at 50% within an 8-stage run -> (0 + 0.5)/8 * 100 = 6.25
        prep._report(PrepStage.VERIFY_DB, 0, "detail", 50.0)
        p = captured[-1]
        assert p.overall_progress == pytest.approx(6.25)
        assert p.stage_detail == "detail"
        assert p.stage_label == STAGE_LABELS[PrepStage.VERIFY_DB]

    def test_report_overall_is_clamped_to_100(self, tmp_path):
        captured = []
        prep = make_preparer(tmp_path, cb=captured.append)
        last_idx = len(PrepStage) - 1
        prep._report(PrepStage.READINESS_CHECK, last_idx, "done", 100.0)
        assert captured[-1].overall_progress == 100.0

    def test_default_callback_is_noop(self, tmp_path):
        prep = make_preparer(tmp_path)  # no callback supplied
        # Should not raise.
        prep._report(PrepStage.VERIFY_DB, 0, "x", 0.0)


def _install_recorders(prep, calls, raising=None, cancel_after=None):
    """Replace every ``_run_<stage>`` with a recorder.

    raising: stage value whose recorder raises RuntimeError.
    cancel_after: stage value whose recorder calls prep.cancel().
    """
    def make(stage_value):
        def _rec(idx, result, skip_existing):
            calls.append(stage_value)
            if stage_value == cancel_after:
                prep.cancel()
            if stage_value == raising:
                raise RuntimeError("boom")
        return _rec

    for stage in PrepStage:
        setattr(prep, f"_run_{stage.value}", make(stage.value))


class TestPrepareOrchestration:
    def test_runs_all_stages_in_order(self, tmp_path):
        prep = make_preparer(tmp_path)
        calls = []
        _install_recorders(prep, calls)
        result = prep.prepare()
        assert result.success is True
        expected = [s.value for s in PrepStage]
        assert calls == expected
        assert result.stages_completed == expected
        assert result.stages_failed == []

    def test_cancel_before_start_runs_nothing(self, tmp_path):
        prep = make_preparer(tmp_path)
        calls = []
        _install_recorders(prep, calls)
        prep.cancel()
        result = prep.prepare()
        assert calls == []
        assert result.success is False
        assert any("cancelled" in e.lower() for e in result.errors)

    def test_cancel_midway_stops_subsequent_stages(self, tmp_path):
        prep = make_preparer(tmp_path)
        calls = []
        _install_recorders(prep, calls, cancel_after="verify_db")
        result = prep.prepare()
        # verify_db ran, then the next loop iteration sees the cancel flag.
        assert calls == ["verify_db"]
        assert result.stages_completed == ["verify_db"]
        assert result.success is False

    def test_critical_failure_aborts(self, tmp_path):
        prep = make_preparer(tmp_path)
        calls = []
        _install_recorders(prep, calls, raising="verify_db")
        result = prep.prepare()
        assert calls == ["verify_db"]  # aborted before build_index
        assert result.success is False
        assert result.stages_failed == ["verify_db"]
        assert any(STAGE_LABELS[PrepStage.VERIFY_DB] in e for e in result.errors)

    def test_non_critical_failure_continues(self, tmp_path):
        prep = make_preparer(tmp_path)
        calls = []
        _install_recorders(prep, calls, raising="download_genomes")
        result = prep.prepare()
        # download_genomes is non-critical: failure is recorded but the run
        # continues through the remaining stages and overall success stays True.
        assert "download_genomes" in result.stages_failed
        assert result.success is True
        assert calls[-1] == "readiness_check"


class TestVerifyDbStage:
    def test_missing_db_raises(self, tmp_path):
        prep = make_preparer(tmp_path, config={})
        with pytest.raises(ValueError, match="No kraken_db"):
            prep._run_verify_db(0, PreparationResult(success=True), True)

    def test_invalid_db_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.utils.kraken_utils.verify_kraken_db",
            lambda p: False,
        )
        prep = make_preparer(tmp_path, config={"kraken_db": "/nope"})
        with pytest.raises(ValueError, match="Invalid Kraken2 database"):
            prep._run_verify_db(0, PreparationResult(success=True), True)

    def test_valid_db_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.utils.kraken_utils.verify_kraken_db",
            lambda p: True,
        )
        prep = make_preparer(tmp_path, config={"kraken_db": "/db"})
        # Stub the inspect-file generation so no binary is invoked.
        monkeypatch.setattr(prep, "_ensure_inspect_file", lambda db: None)
        prep._run_verify_db(0, PreparationResult(success=True), True)  # no raise


class TestCheckToolsStage:
    def test_all_tools_missing_warns(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda tool: None)
        prep = make_preparer(tmp_path, config={"pipeline_profile": "conda"})
        result = PreparationResult(success=True)
        prep._run_check_tools(6, result, True)
        # nextflow, kraken2-inspect, datasets, makeblastdb, conda -> 5 warnings.
        assert len(result.warnings) >= 4
        assert any("nextflow" in w for w in result.warnings)
        assert any("conda" in w for w in result.warnings)

    def test_all_tools_present_no_warnings(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")
        prep = make_preparer(tmp_path, config={"pipeline_profile": "docker"})
        result = PreparationResult(success=True)
        prep._run_check_tools(6, result, True)
        assert result.warnings == []

    def test_blast_tool_checked_when_validation_enabled(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr("shutil.which", lambda tool: seen.append(tool) or "/p")
        prep = make_preparer(
            tmp_path,
            config={"pipeline_profile": "conda", "blast_validation": True},
        )
        prep._run_check_tools(6, PreparationResult(success=True), True)
        assert "blastn" in seen

    def test_singularity_profile_warns_when_absent(self, tmp_path, monkeypatch):
        # which returns a path for everything except singularity/apptainer.
        monkeypatch.setattr(
            "shutil.which",
            lambda tool: None if tool in ("singularity", "apptainer") else "/p",
        )
        prep = make_preparer(tmp_path, config={"pipeline_profile": "singularity"})
        result = PreparationResult(success=True)
        prep._run_check_tools(6, result, True)
        assert any("singularity" in w.lower() for w in result.warnings)


class TestCacheTaxonomyStage:
    def test_export_failure_becomes_warning(self, tmp_path, monkeypatch):
        class _BadCache:
            def export_snapshot(self, path):
                raise ValueError("disk full")

        monkeypatch.setattr(
            "nanometa_live.core.utils.offline_cache.OfflineTaxonomyCache",
            _BadCache,
        )
        prep = make_preparer(tmp_path)
        result = PreparationResult(success=True)
        prep._run_cache_taxonomy(5, result, True)  # must not raise
        assert any("Taxonomy cache export" in w for w in result.warnings)

    def test_export_success_no_warning(self, tmp_path, monkeypatch):
        class _OkCache:
            def export_snapshot(self, path):
                return 42

        monkeypatch.setattr(
            "nanometa_live.core.utils.offline_cache.OfflineTaxonomyCache",
            _OkCache,
        )
        prep = make_preparer(tmp_path)
        result = PreparationResult(success=True)
        prep._run_cache_taxonomy(5, result, True)
        assert result.warnings == []


class TestBuildIndexAndMappings:
    def test_build_index_skips_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            lambda p: "abc",
        )
        # A loader that would explode if called -- proves the skip branch wins.
        class _Boom:
            def load_database(self, p):
                raise AssertionError("should not load when index exists")
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.TaxidMapper", _Boom
        )
        prep = make_preparer(tmp_path, config={"kraken_db": "/db"})
        index_file = tmp_path / "mappings" / "abc_index.pkl"
        index_file.parent.mkdir(parents=True)
        index_file.write_text("cached")
        prep._run_build_index(1, PreparationResult(success=True), True)  # no raise

    def test_build_index_loads_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            lambda p: "abc",
        )
        loaded = []
        class _Mapper:
            def load_database(self, p):
                loaded.append(p)
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.TaxidMapper", _Mapper
        )
        prep = make_preparer(tmp_path, config={"kraken_db": "/db"})
        prep._run_build_index(1, PreparationResult(success=True), True)
        assert loaded == ["/db"]

    def test_generate_mappings_warns_when_no_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_mapping_cache_path",
            lambda p: tmp_path / "nope.pkl",
        )
        prep = make_preparer(tmp_path, config={"kraken_db": "/db"})
        monkeypatch.setattr(prep, "_get_watchlist_entries", lambda: [])
        result = PreparationResult(success=True)
        prep._run_generate_mappings(2, result, True)
        assert any("No watchlist entries" in w for w in result.warnings)


class TestDownloadAndBlastStages:
    def test_download_genomes_counts_new(self, tmp_path, monkeypatch):
        class _Manager:
            def has_genome(self, taxid):
                return taxid == 999  # one already present
            def download_genome(self, taxid, name):
                return f"/genomes/{taxid}.fasta"
        monkeypatch.setattr(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            lambda d: _Manager(),
        )
        prep = make_preparer(tmp_path)
        monkeypatch.setattr(prep, "_get_watchlist_entries", lambda: [
            {"taxid": 562, "name": "E. coli"},
            {"taxid": 999, "name": "cached"},
            {"taxid": 1280, "name": "S. aureus"},
        ])
        result = PreparationResult(success=True)
        prep._run_download_genomes(3, result, True)
        assert result.genomes_downloaded == 2  # 562 and 1280; 999 skipped

    def test_download_genomes_respects_cancel(self, tmp_path, monkeypatch):
        class _Manager:
            def has_genome(self, taxid):
                return False
            def download_genome(self, taxid, name):
                raise AssertionError("should not download after cancel")
        monkeypatch.setattr(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            lambda d: _Manager(),
        )
        prep = make_preparer(tmp_path)
        prep.cancel()
        monkeypatch.setattr(prep, "_get_watchlist_entries", lambda: [
            {"taxid": 562, "name": "E. coli"},
        ])
        result = PreparationResult(success=True)
        prep._run_download_genomes(3, result, True)
        assert result.genomes_downloaded == 0

    def test_build_blast_dbs_records_count(self, tmp_path, monkeypatch):
        class _Manager:
            def build_missing_blast_dbs(self):
                return 4
        monkeypatch.setattr(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            lambda d: _Manager(),
        )
        prep = make_preparer(tmp_path)
        result = PreparationResult(success=True)
        prep._run_build_blast_dbs(4, result, True)
        assert result.blast_dbs_built == 4


class TestGetWatchlistEntries:
    def test_returns_mapped_entries(self, tmp_path, monkeypatch):
        class _Entry:
            def __init__(self, taxid, name):
                self.taxid = taxid
                self.name = name
                self.names_alt = []

        class _WM:
            def get_all_entries(self):
                return [_Entry(562, "E. coli"), _Entry(1280, "S. aureus")]

        class _MC:
            def get_db_taxid(self, taxid):
                return taxid + 1  # pretend a kraken-db remap

        monkeypatch.setattr(
            "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
            lambda: _WM(),
        )
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
            lambda: _MC(),
        )
        prep = make_preparer(tmp_path)
        entries = prep._get_watchlist_entries()
        assert [e["taxid"] for e in entries] == [562, 1280]
        assert entries[0]["kraken_taxid"] == 563  # remapped
        assert entries[0]["name"] == "E. coli"

    def test_import_error_returns_empty(self, tmp_path, monkeypatch):
        def _boom():
            raise ImportError("no module")

        monkeypatch.setattr(
            "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
            _boom,
        )
        prep = make_preparer(tmp_path)
        assert prep._get_watchlist_entries() == []
