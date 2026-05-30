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
    def test_empty_is_info(self, cfg_app):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        assert "text-muted" in _class(fn(""))

    def test_existing_writable_is_success(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        assert "text-success" in _class(fn(str(tmp_path)))

    def test_nonexistent_with_writable_parent_is_info(self, cfg_app, tmp_path):
        fn = _callback_fn(cfg_app, "results-dir-status.children")
        icon = fn(str(tmp_path / "to_be_created"))
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
