"""The runtime half of C13: what arrived versus what was declared.

The Configuration tab rejects by_barcode over a folder that already holds
flat FASTQ files, but in real time the watched folder is legitimately empty
at Apply, so that check cannot fire. The run then groups reads by what it
finds -- one sample per file under a by_barcode selection -- and nothing
said so on any surface (round-5 live drills, RT5). These pin the shared
helper and the four surfaces that now carry it: the per-poll backend status,
the verdict subtitle, the header, and the readiness check.
"""

import os
import time
from unittest.mock import MagicMock

import pytest

from nanometa_live.core.utils.auto_detect import (
    describe_layout_mismatch,
    input_layout_mismatch,
)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"@r\nACGT\n+\n!!!!\n")


class TestDescribeLayoutMismatch:
    def test_flat_folder_under_by_barcode_is_named(self):
        text = describe_layout_mismatch("by_barcode", 6, 0)
        assert text and "each file is being treated as its own sample" in text

    def test_subfolders_under_single_sample_are_named(self):
        text = describe_layout_mismatch("single_sample", 0, 3)
        assert text and "Single sample" in text and "subfolder" in text

    @pytest.mark.parametrize("mode,root,dirs", [
        ("by_barcode", 0, 3),        # agrees
        ("per_file", 4, 0),          # agrees
        ("by_barcode", 0, 0),        # nothing arrived yet
        ("by_barcode", 2, 2),        # mixed: not called a mismatch
        (None, 6, 0),                # nothing declared
        ("", 6, 0),
    ])
    def test_agreement_and_silence(self, mode, root, dirs):
        assert describe_layout_mismatch(mode, root, dirs) is None

    def test_directory_form(self, tmp_path):
        _touch(tmp_path / "a.fastq.gz")
        assert input_layout_mismatch(str(tmp_path), "by_barcode")
        assert input_layout_mismatch(str(tmp_path), "per_file") is None
        assert input_layout_mismatch(str(tmp_path / "missing"), "by_barcode") is None


class TestBackendStatusCarriesIt:
    def _manager(self, tmp_path, inbox, mode):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        m = BackendManager(str(tmp_path / "data"))
        m.config = {"nanopore_output_directory": str(inbox), "sample_handling": mode}
        m._file_count_cached_at = 0.0
        return m

    def test_flat_inbox_under_by_barcode_sets_the_key(self, tmp_path):
        inbox = tmp_path / "inbox"
        _touch(inbox / "x.fastq.gz")
        m = self._manager(tmp_path, inbox, "by_barcode")
        m._update_file_counts()
        assert m.status["files_waiting"] == 1
        assert m.status["input_layout_mismatch"]
        assert "own sample" in m.status["input_layout_mismatch"]

    def test_barcode_layout_under_by_barcode_is_clean(self, tmp_path):
        inbox = tmp_path / "inbox"
        _touch(inbox / "barcode01" / "x.fastq.gz")
        m = self._manager(tmp_path, inbox, "by_barcode")
        m._update_file_counts()
        assert m.status["files_waiting"] == 1
        assert m.status["input_layout_mismatch"] is None

    def test_empty_inbox_is_not_a_mismatch(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        m = self._manager(tmp_path, inbox, "by_barcode")
        m._update_file_counts()
        assert m.status["input_layout_mismatch"] is None

    def test_the_key_reaches_get_status(self, tmp_path):
        inbox = tmp_path / "inbox"
        _touch(inbox / "x.fastq.gz")
        m = self._manager(tmp_path, inbox, "by_barcode")
        m._update_file_counts()
        assert m.get_status().get("input_layout_mismatch")


class TestVerdictSubtitleCarriesIt:
    def test_clause_is_appended_to_a_detection(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        hits = [{"name": "Francisella tularensis", "reads": 500, "threshold": 10,
                 "alert_threshold": 10, "taxid": 263, "threat_level": "critical"}]
        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=hits, n_watched=1, validation_has_results=False,
            total_reads=1000,
            input_layout_mismatch="the watched folder holds FASTQ files directly but "
                                  "By barcode is selected, so each file is being "
                                  "treated as its own sample",
        )
        assert "own sample" in d.subtitle, d.subtitle

    def test_no_clause_when_none(self):
        from nanometa_live.app.tabs.dashboard_helpers import select_verdict
        d = select_verdict(
            has_config=True, pipeline_running=True, overall_status_starting=False,
            main_dir_available=True, kraken_has_data=True,
            dangerous=[], n_watched=5, validation_has_results=False,
            total_reads=1000, input_layout_mismatch=None,
        )
        assert "own sample" not in d.subtitle


class TestHeaderCarriesIt:
    def _fn(self):
        from dash import Dash
        from nanometa_live.app.callbacks.status import register_status
        from tests.dash_test_utils import get_callback_fn
        app = Dash(__name__)
        register_status(app, MagicMock())
        return get_callback_fn(app, "status-indicator", input_contains="backend-status")

    def test_running_header_names_it(self):
        _c, text, detail = self._fn()(
            {"running": True, "files_waiting": 6, "files_processed": 3,
             "input_layout_mismatch": "the watched folder holds FASTQ files directly "
                                      "but By barcode is selected, so each file is "
                                      "being treated as its own sample"},
            {"processing_mode": "realtime"},
        )
        assert text == "RUNNING"
        assert "own sample" in detail

    def test_completed_header_names_it(self):
        _c, text, detail = self._fn()(
            {"running": False, "pipeline_status": "completed",
             "input_layout_mismatch": "the watched folder holds FASTQ files directly "
                                      "but By barcode is selected, so each file is "
                                      "being treated as its own sample"},
            {"processing_mode": "realtime"},
        )
        assert text == "Complete"
        assert "own sample" in detail


class TestReadinessCheckFailsOnMismatch:
    @pytest.fixture
    def checker(self):
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker
        return ReadinessChecker()

    def test_flat_folder_under_by_barcode_fails_with_a_remedy(self, checker, tmp_path):
        _touch(tmp_path / "reads.fastq.gz")
        r = checker._check_input_directory(
            {"nanopore_output_directory": str(tmp_path), "sample_handling": "by_barcode"})
        assert r.passed is False
        assert "Sample handling" in r.message
        assert "Single sample or Per file" in (r.details or "")

    def test_matching_layout_passes(self, checker, tmp_path):
        _touch(tmp_path / "barcode01" / "reads.fastq.gz")
        r = checker._check_input_directory(
            {"nanopore_output_directory": str(tmp_path), "sample_handling": "by_barcode"})
        assert r.passed is True

    def test_undeclared_mode_keeps_the_old_pass(self, checker, tmp_path):
        _touch(tmp_path / "reads.fastq.gz")
        r = checker._check_input_directory({"nanopore_output_directory": str(tmp_path)})
        assert r.passed is True
