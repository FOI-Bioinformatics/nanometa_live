"""The run verdict must survive closing the dashboard (2026-08-17 storage audit).

- R1: nothing generated the operator HTML report automatically -- an operator
  who closed the app without clicking Export Results kept the raw pipeline
  output but no human-readable summary. BackendManager._auto_generate_report
  now writes <outdir>/report/report.html on run completion and on Stop.
- R2: the post-hoc `nanometa-report` CLI could not know which watchlists
  screened the run (the run record held only a fingerprint), so omitting
  --watchlist produced a NOT SCREENED report. The run metadata now records
  the enabled watchlist ids and the CLI defaults to them.
- R3: the Reports tab did not list the operator report.
"""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.cli.report import _resolve_watchlist_ids
from nanometa_live.core.utils.reports_loader import REPORT_SPECS, detect_reports
from nanometa_live.core.workflow.backend_manager import BackendManager


def _populated_results(tmp_path):
    from nanometa_live.core.testing.mock_data_generator import (
        MockDataScenario,
        generate_test_dataset,
    )

    outdir = tmp_path / "results"
    generate_test_dataset(
        str(outdir), scenario=MockDataScenario.PATHOGEN_DETECTED, num_samples=2
    )
    old = time.time() - 60
    for root, _dirs, files in os.walk(outdir):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))
    return outdir


class TestAutoGenerateReport:
    def test_report_written_into_outdir(self, tmp_path):
        outdir = _populated_results(tmp_path)
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {"results_output_directory": str(outdir)}
        report_path = manager._auto_generate_report()
        assert report_path is not None
        assert (outdir / "report" / "report.html").exists()
        html = (outdir / "report" / "report.html").read_text()
        assert "barcode01" in html

    def test_raw_files_never_copied_into_the_outdir(self, tmp_path):
        """The report lands INSIDE the results dir; copying raw/ would
        duplicate the whole tree into itself."""
        outdir = _populated_results(tmp_path)
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {"results_output_directory": str(outdir)}
        manager._auto_generate_report()
        assert not (outdir / "report" / "raw").exists()

    def test_disabled_by_auto_report_false(self, tmp_path):
        outdir = _populated_results(tmp_path)
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {
            "results_output_directory": str(outdir),
            "auto_report": False,
        }
        assert manager._auto_generate_report() is None
        assert not (outdir / "report").exists()

    def test_missing_outdir_is_a_silent_no(self, tmp_path):
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {"results_output_directory": str(tmp_path / "gone")}
        assert manager._auto_generate_report() is None

    def test_generator_failure_never_raises(self, tmp_path):
        outdir = _populated_results(tmp_path)
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {"results_output_directory": str(outdir)}
        with patch(
            "nanometa_live.core.export.report_generator.ReportGenerator",
            side_effect=RuntimeError("boom"),
        ):
            assert manager._auto_generate_report() is None

    def test_stop_generates_the_report(self, tmp_path):
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {"results_output_directory": str(tmp_path)}
        manager.status["running"] = True
        manager.workflow_manager = MagicMock()
        manager.workflow_manager.stop.return_value = (True, "stopped")
        with patch.object(manager, "_auto_generate_report") as auto:
            ok, _msg = manager.stop()
        assert ok
        auto.assert_called_once()

    def test_failed_stop_does_not_generate(self, tmp_path):
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.status["running"] = True
        manager.workflow_manager = MagicMock()
        manager.workflow_manager.stop.return_value = (False, "no")
        with patch.object(manager, "_auto_generate_report") as auto:
            ok, _msg = manager.stop()
        assert not ok
        auto.assert_not_called()


class TestReportCarriesActionGuidance:
    def test_detected_entry_action_required_in_html(self, tmp_path):
        """The per-organism action_required guidance (W5) must survive into
        the archived report -- the artifact that leaves the building."""
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )

        outdir = _populated_results(tmp_path)
        manager = WatchlistManager()
        manager.enable_watchlist("cdc_bioterrorism")
        with patch(
            "nanometa_live.core.watchlist.watchlist_manager"
            ".get_watchlist_manager",
            return_value=manager,
        ):
            bm = BackendManager(data_dir=str(tmp_path / "data"))
            bm.config = {"results_output_directory": str(outdir)}
            report_path = bm._auto_generate_report()
        assert report_path is not None
        html = (outdir / "report" / "report.html").read_text()
        # The mock dataset seeds B. anthracis / Y. pestis / C. botulinum;
        # their cdc_bioterrorism guidance must appear beside the detection.
        assert "Action:" in html


class TestRunMetadataRecordsWatchlists:
    def test_ids_recorded(self, tmp_path):
        manager_mock = MagicMock()
        manager_mock.enabled_watchlist_ids.return_value = [
            "cdc_bioterrorism", "foodborne",
        ]
        with patch(
            "nanometa_live.core.watchlist.watchlist_manager"
            ".get_watchlist_manager",
            return_value=manager_mock,
        ):
            BackendManager.write_run_metadata(str(tmp_path), {"kraken_db": "x"})
        meta = json.loads((tmp_path / ".nanometa.run.json").read_text())
        assert meta["watchlists"] == ["cdc_bioterrorism", "foodborne"]


class TestCliWatchlistDefaulting:
    def test_explicit_argument_wins(self, tmp_path):
        assert _resolve_watchlist_ids("a, b", str(tmp_path)) == ["a", "b"]

    def test_none_forces_unscreened(self, tmp_path):
        (tmp_path / ".nanometa.run.json").write_text(
            json.dumps({"watchlists": ["cdc_bioterrorism"]})
        )
        assert _resolve_watchlist_ids("none", str(tmp_path)) == []

    def test_falls_back_to_run_record(self, tmp_path):
        (tmp_path / ".nanometa.run.json").write_text(
            json.dumps({"watchlists": ["cdc_bioterrorism"]})
        )
        assert _resolve_watchlist_ids(None, str(tmp_path)) == [
            "cdc_bioterrorism"
        ]

    def test_no_record_means_no_watchlists(self, tmp_path):
        assert _resolve_watchlist_ids(None, str(tmp_path)) == []


class TestReportsTabListsOperatorReport:
    def test_spec_exists_and_leads_the_list(self):
        assert REPORT_SPECS[0]["key"] == "operator_report"

    def test_detected_when_present(self, tmp_path):
        (tmp_path / "report").mkdir()
        (tmp_path / "report" / "report.html").write_text("<html></html>")
        entries = {e["key"]: e for e in detect_reports(str(tmp_path))}
        assert entries["operator_report"]["exists"] is True

    def test_report_dir_is_archived_between_runs(self):
        assert "report" in BackendManager.RESULT_SUBDIRS
