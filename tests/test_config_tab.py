"""
Unit tests for the path-validation callbacks in app/tabs/config_tab.py.

These callbacks give the operator real-time feedback on the directories and
database paths entered in the Configuration tab. They are pure filesystem
checks returning Bootstrap-icon components, so tests drive them against
tmp_path and assert on the returned icon's className (success / warning /
danger), including the Kraken2 required-files rule.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.callback
from dash import Dash

from dash_test_utils import get_callback_fn as _callback_fn
from nanometa_live.app.tabs.config_tab import register_config_callbacks


@pytest.fixture
def cfg_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_config_callbacks(app, MagicMock())
    return app


def _class(component):
    """Extract the className from a returned html.I (or '' for empty string)."""
    return getattr(component, "className", "") or ""


class TestValidateNanoporeDirectory:
    def test_empty_is_blank(self, cfg_app):
        fn = _callback_fn(cfg_app, "nanopore-dir-status.children")
        assert fn("") == ("", "")

    def test_missing_path_is_danger(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "nanopore-dir-status.children")
        icon, _ = fn(str(tmp_path / "nope"))
        assert "text-danger" in _class(icon)

    def test_file_is_not_a_directory(self, cfg_app, tmp_path):
        f = tmp_path / "a_file.txt"
        f.write_text("x")
        fn = _callback_fn(cfg_app, "nanopore-dir-status.children")
        icon, _ = fn(str(f))
        assert "text-danger" in _class(icon)

    def test_existing_dir_is_success(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "nanopore-dir-status.children")
        icon, _ = fn(str(tmp_path))
        assert "text-success" in _class(icon)


class TestValidateKrakenDatabase:
    def test_missing_required_files_warns(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "kraken-db-status.children")
        icon, feedback = fn(str(tmp_path))  # empty dir, no .k2d files
        assert "text-warning" in _class(icon)

    def test_complete_db_is_success(self, cfg_app, tmp_path):
        for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (tmp_path / name).write_text("x")
        fn = _callback_fn(cfg_app, "kraken-db-status.children")
        icon, _ = fn(str(tmp_path))
        assert "text-success" in _class(icon)

    def test_nonexistent_is_danger(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "kraken-db-status.children")
        icon, _ = fn(str(tmp_path / "nope"))
        assert "text-danger" in _class(icon)


class TestValidateResultsDirectory:
    # The callback now returns (status_icon, existing-results-feedback);
    # assert on the icon element (index 0).
    def test_empty_is_info(self, cfg_app):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        assert "text-muted" in _class(fn("")[0])

    def test_existing_writable_is_success(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        assert "text-success" in _class(fn(str(tmp_path))[0])

    def test_nonexistent_with_writable_parent_is_info(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        icon = fn(str(tmp_path / "to_be_created"))[0]
        assert "text-info" in _class(icon)


class TestValidatePipelinePath:
    def test_empty_is_blank(self, cfg_app):
        fn = _callback_fn(cfg_app, "pipeline-path-status.children")
        assert fn("") == ""

    def test_dir_without_main_nf_warns(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "pipeline-path-status.children")
        assert "text-warning" in _class(fn(str(tmp_path)))

    def test_dir_with_main_nf_is_success(self, cfg_app, tmp_path):
        (tmp_path / "main.nf").write_text("// pipeline")
        fn = _callback_fn(cfg_app, "pipeline-path-status.children")
        assert "text-success" in _class(fn(str(tmp_path)))

    def test_nonexistent_is_danger(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "pipeline-path-status.children")
        assert "text-danger" in _class(fn(str(tmp_path / "nope")))


class TestModifiedBadgeClearsOnApply:
    """Apply Settings must clear the "Modified" badge.

    Apply persists the config (autosave_session_config writes
    last-session.yaml), so after it the form matches BOTH the applied state
    and what is on disk -- there is nothing left for the operator to save.
    The badge nevertheless stayed lit forever: update_snapshot_on_apply
    returned no_update for both outputs, on the reasoning (in a comment
    that outlived the design it described) that Apply was session-only and
    a separate Save wrote the file. A badge that never clears cannot be
    read as a signal, and it tells the operator they have unsaved work when
    they do not (2026-08-19 config audit).
    """

    def _fn(self, cfg_app):
        return _callback_fn(
            cfg_app, "saved-config-snapshot",
            input_contains="apply-config-button",
        )

    def test_apply_clears_modified_and_updates_snapshot(self, cfg_app):
        applied = {"analysis_name": "run A", "kraken_db": "/db"}
        snapshot, modified = self._fn(cfg_app)(1, applied)

        assert modified is False, (
            "the Modified badge must clear on Apply: the config has been "
            "applied AND autosaved, so nothing is pending"
        )
        assert snapshot == applied, (
            "the dirty-check baseline must become the applied config, else "
            "the next edit is compared against a stale snapshot"
        )

    def test_no_clicks_is_a_noop(self, cfg_app):
        from dash import no_update
        snapshot, modified = self._fn(cfg_app)(None, {"a": 1})
        assert snapshot is no_update and modified is no_update


class TestApplyDuringARun:
    """Apply Settings must not move a running run's folders (round-4, H11).

    build_config_from_form recomputes results_output_directory from the
    analysis name on every Apply and the callback had no view of the backend:
    renaming the analysis mid-run pointed the viewer at an empty folder while
    the pipeline kept writing to the old one.
    """

    def _apply(self, cfg_app):
        from nanometa_live.app.tabs.config_field_registry import CONFIG_FORM_FIELDS
        fn = _callback_fn(cfg_app, "app-config", input_contains="apply-config-button")

        def invoke(current_config, backend_status, **overrides):
            by_name = {kw: None for _, kw in CONFIG_FORM_FIELDS}
            by_name.update(overrides)
            values = [by_name[kw] for _, kw in CONFIG_FORM_FIELDS]
            return fn(1, *values, current_config, backend_status)
        return invoke

    def _live(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        db = tmp_path / "db"
        db.mkdir()
        for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (db / name).write_bytes(b"x")
        return {
            "data_dir": str(tmp_path),
            "analysis_name": "run A",
            "nanopore_output_directory": str(inbox),
            "kraken_db": str(db),
            "results_output_directory": str(tmp_path / "results" / "run_a"),
        }

    def test_running_run_keeps_its_folders(self, cfg_app, tmp_path):
        live = self._live(tmp_path)
        invoke = self._apply(cfg_app)
        config, _label, toast, _open = invoke(
            live, {"running": True}, analysis_name="run B",
            nanopore_dir=live["nanopore_output_directory"], kraken_db=live["kraken_db"],
        )
        assert config["results_output_directory"] == live["results_output_directory"]
        assert config["nanopore_output_directory"] == live["nanopore_output_directory"]
        assert config["analysis_name"] == "run B"
        assert toast["color"] == "warning"
        assert "next Start" in toast["message"]

    def test_idle_apply_recomputes_the_results_folder(self, cfg_app, tmp_path):
        live = self._live(tmp_path)
        invoke = self._apply(cfg_app)
        config, _label, toast, _open = invoke(
            live, {"running": False}, analysis_name="run B",
            nanopore_dir=live["nanopore_output_directory"], kraken_db=live["kraken_db"],
        )
        assert config["results_output_directory"] != live["results_output_directory"]
        assert toast["color"] == "success"

