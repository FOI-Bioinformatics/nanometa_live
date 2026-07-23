"""
Unit tests for app/tabs/preparation_helpers.py.

These pure helpers back the offline-deployment wizard. Tests cover the
deterministic branches that do not invoke the heavy MobileLabPreparer / network
stages: the unrecognised-file mapping table, the export directory guard, and the
wizard-step dispatcher's validation errors.
"""

from unittest.mock import MagicMock, patch

import dash_bootstrap_components as dbc
import pytest

import nanometa_live.app.tabs.preparation_helpers as prep_helpers
from nanometa_live.app.tabs.preparation_helpers import (
    _build_mapping_table,
    _execute_wizard_step,
    _regenerate_mappings,
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

    def test_step7_honors_export_opts(self):
        """The wizard export step must forward the operator's Export-card
        selections (engine, pre-warm, directory, filename) rather than
        hardcoding conda + ~/Downloads.
        """
        with patch.object(prep_helpers, "_run_export") as run:
            _execute_wizard_step(
                7,
                {"kraken_db": "/x"},
                export_opts={
                    "directory": "/tmp/out",
                    "filename": "b.tar.gz",
                    "pre_warm": True,
                    "containerization": "singularity",
                },
            )
        run.assert_called_once()
        _, kwargs = run.call_args
        assert kwargs["containerization"] == "singularity"
        assert kwargs["pre_warm"] is True
        assert kwargs["directory"] == "/tmp/out"
        assert kwargs["filename"] == "b.tar.gz"

    def test_step7_defaults_when_no_opts(self):
        """No export_opts (e.g. a caller that has not wired the card) falls
        back to conda with pre-warm off -- never the old ~5 GB default-on.
        """
        with patch.object(prep_helpers, "_run_export") as run:
            _execute_wizard_step(7, {"kraken_db": "/x"})
        _, kwargs = run.call_args
        assert kwargs["containerization"] == "conda"
        assert kwargs["pre_warm"] is False


class TestRegenerateMappings:
    """Recover from a bundle imported against a different Kraken2 DB by
    rebuilding the taxonomy index + taxid mappings for the local DB, so they
    land under {local_db_hash}_* where readiness and the run look.
    """

    def test_no_db_returns_danger(self):
        alert = _regenerate_mappings({"kraken_db": ""})
        assert isinstance(alert, dbc.Alert)
        assert alert.color == "danger"
        assert "database" in str(alert.children).lower()

    def test_missing_inspect_and_binary_fails_with_guidance(self, tmp_path):
        db = tmp_path / "kdb"
        db.mkdir()  # no inspect.txt
        with patch("shutil.which", return_value=None):
            alert = _regenerate_mappings({"kraken_db": str(db)})
        assert alert.color == "danger"
        s = str(alert.children).lower()
        assert "inspect" in s and "kraken2-inspect" in s

    def test_success_runs_prep_stages_and_forwards_entries(self, tmp_path):
        db = tmp_path / "kdb"
        db.mkdir()
        (db / "inspect.txt").write_text("# inspect\n")  # prerequisite satisfied
        snapshot = [{"name": "Francisella tularensis", "taxid": 263}]

        prep = MagicMock()
        prep_ctor = MagicMock(return_value=prep)
        pr = MagicMock(warnings=[])
        with patch(
            "nanometa_live.core.workflow.mobile_lab_preparer.MobileLabPreparer",
            prep_ctor,
        ), patch(
            "nanometa_live.core.workflow.mobile_lab_preparer.PreparationResult",
            return_value=pr,
        ):
            alert = _regenerate_mappings(
                {"kraken_db": str(db)}, watchlist_entries=snapshot
            )

        assert alert.color == "success"
        # Watchlist snapshot forwarded to the preparer (background-worker path).
        _, kwargs = prep_ctor.call_args
        assert kwargs.get("watchlist_entries") == snapshot
        # Index + mappings stages ran (force rebuild for the new hash).
        assert prep._run_build_index.called
        assert prep._run_generate_mappings.called

    def test_stage_failure_returns_danger(self, tmp_path):
        db = tmp_path / "kdb"
        db.mkdir()
        (db / "inspect.txt").write_text("# inspect\n")
        prep = MagicMock()
        prep._run_build_index.side_effect = RuntimeError("boom")
        with patch(
            "nanometa_live.core.workflow.mobile_lab_preparer.MobileLabPreparer",
            return_value=prep,
        ), patch(
            "nanometa_live.core.workflow.mobile_lab_preparer.PreparationResult",
            return_value=MagicMock(warnings=[]),
        ):
            alert = _regenerate_mappings({"kraken_db": str(db)})
        assert alert.color == "danger"
        assert "boom" in str(alert.children)
