"""
Unit tests for app/tabs/preparation_helpers.py.

These pure helpers back the offline-deployment wizard. Tests cover the
deterministic branches that do not invoke the heavy MobileLabPreparer / network
stages: the unrecognised-file mapping table, the export directory guard, and the
wizard-step dispatcher's validation errors.
"""

import dash_bootstrap_components as dbc
import pytest

from nanometa_live.app.tabs.preparation_helpers import (
    _build_mapping_table,
    _execute_wizard_step,
    _run_export,
)


class TestBuildMappingTable:
    def test_one_row_per_entry(self):
        rows = _build_mapping_table([
            {"filename": "genome_a.fasta"},
            {"filename": "genome_b.fasta"},
        ])
        assert len(rows) == 2
        assert all(isinstance(r, dbc.Row) for r in rows)

    def test_empty_input_yields_no_rows(self):
        assert _build_mapping_table([]) == []


class TestRunExport:
    def test_missing_directory_returns_danger_alert(self, tmp_path):
        alert = _run_export({}, directory=str(tmp_path / "does_not_exist"))
        assert isinstance(alert, dbc.Alert)
        assert alert.color == "danger"
        assert "does not exist" in alert.children


class TestExecuteWizardStep:
    def test_unknown_step_raises(self):
        with pytest.raises(ValueError, match="Unknown wizard step"):
            _execute_wizard_step(99, {})

    def test_verify_db_without_path_raises(self):
        with pytest.raises(ValueError, match="No kraken_db path configured"):
            _execute_wizard_step(1, {"kraken_db": ""})
