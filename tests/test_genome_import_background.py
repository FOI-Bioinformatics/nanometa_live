"""Tests for the genome import callbacks after their conversion to the
background worker -> Store -> main-process finalize split (P2 audit findings).

The directory/archive/mapped imports copy files AND mutate the get_genome_manager
singleton's in-memory metadata. Run in a worker, the singleton mutation happens
in a separate process and is invisible to the live app -- so the main-process
finalize must reload the singleton (reload_metadata) after the worker's on-disk
import. These tests cover reload_metadata, the pure renderer, the workers (wrap
result, no singleton reload in the worker), and the finalize (reloads + renders).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn, make_callback_app
from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks
from nanometa_live.app.tabs.preparation_helpers import _render_genome_import_result


@pytest.fixture
def app():
    return make_callback_app(register_preparation_callbacks)


class TestReloadMetadata:
    def test_clears_in_memory_then_rereads_disk(self, tmp_path):
        from nanometa_live.core.utils.genome_manager import GenomeDownloadManager
        mgr = GenomeDownloadManager(cache_dir=str(tmp_path))
        mgr._metadata = {999: "stale"}
        with patch.object(mgr, "_load_metadata") as load:
            mgr.reload_metadata()
        assert mgr._metadata == {}      # stale in-memory copy cleared
        load.assert_called_once()       # then re-read from disk


class TestRenderGenomeImportResult:
    def test_early_error_uses_color(self):
        alert, unrec, style, table = _render_genome_import_result(
            {"source": "dir", "early": {"message": "Please provide a directory path.",
                                        "color": "warning"}})
        assert alert.color == "warning"
        assert "directory path" in str(alert.children)
        assert style == {"display": "none"} and unrec == [] and table == []

    def test_error(self):
        out = _render_genome_import_result({"source": "dir", "error": "boom"})
        assert out[0].color == "danger" and "boom" in str(out[0].children)

    def test_mapped(self):
        out = _render_genome_import_result({"source": "mapped", "imported": 3, "skipped": 1})
        s = str(out[0].children)
        assert "3 mapped" in s and "1 skipped" in s

    def test_dir_all_recognized(self):
        out = _render_genome_import_result({"source": "dir", "imported": 5, "unrecognized": []})
        s = str(out[0].children)
        assert "5 genome" in s and "All files recognized" in s
        assert out[2] == {"display": "none"}

    def test_dir_with_unrecognized_reveals_mapping(self):
        out = _render_genome_import_result({
            "source": "dir", "imported": 2,
            "unrecognized": [{"filename": "x.fasta", "path": "/x.fasta"}]})
        assert out[1] == [{"filename": "x.fasta", "path": "/x.fasta"}]
        assert out[2] == {"display": "block"}
        assert out[3]   # mapping-table rows built


class TestGenomeImportWorkers:
    def _worker(self, app, in_sub):
        return get_callback_fn(app, "genome-import-result-store.data", input_contains=in_sub)

    def _bg(self, app, in_sub):
        for cb, spec in app.callback_map.items():
            if "genome-import-result-store" in cb and in_sub in str(spec.get("inputs")):
                return bool(spec.get("background"))
        return None

    def test_all_three_workers_are_background(self, app):
        assert self._bg(app, "genome-import-dir-btn")
        assert self._bg(app, "genome-import-archive-btn")
        assert self._bg(app, "genome-import-mapped-btn")

    def test_dir_worker_wraps_result_and_does_not_reload(self, app, tmp_path):
        d = tmp_path / "g"
        d.mkdir()
        mgr = MagicMock()
        mgr.import_genomes_from_directory.return_value = (3, [])
        set_progress = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            out = self._worker(app, "genome-import-dir-btn")(
                set_progress, 1, str(d), {})
        assert out["result"] == {"source": "dir", "imported": 3, "unrecognized": []}
        assert out["_click"] == 1
        assert not mgr.reload_metadata.called   # reload belongs in finalize, not worker
        assert set_progress.called

    def test_dir_worker_missing_path_is_early_error(self, app):
        out = self._worker(app, "genome-import-dir-btn")(MagicMock(), 1, "", {})
        assert "directory path" in out["result"]["early"]["message"].lower()

    def test_mapped_worker_counts_imports_and_skips(self, app):
        mgr = MagicMock()
        mgr.import_genome_with_taxid.return_value = True
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            out = self._worker(app, "genome-import-mapped-btn")(
                MagicMock(), 1,
                [{"path": "/a.fasta", "filename": "a"}, {"path": "/b.fasta", "filename": "b"}],
                ["562", ""], [{"index": 0}, {"index": 1}], {})
        assert out["result"] == {"source": "mapped", "imported": 1, "skipped": 1}


class TestFinalizeGenomeImport:
    def _fn(self, app):
        return get_callback_fn(app, "genome-import-result.children",
                               input_contains="genome-import-result-store")

    def test_reloads_singleton_and_renders(self, app):
        mgr = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            out = self._fn(app)(
                {"_click": 1, "result": {"source": "dir", "imported": 3, "unrecognized": []}},
                {})
        mgr.reload_metadata.assert_called_once()   # the P2 core: main-process refresh
        assert "3 genome" in str(out[0])

    def test_no_reload_when_nothing_imported(self, app):
        mgr = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            out = self._fn(app)(
                {"_click": 1, "result": {"source": "dir",
                 "early": {"message": "Please provide a directory path.", "color": "warning"}}},
                {})
        assert not mgr.reload_metadata.called

    def test_empty_store_prevents_update(self, app):
        with pytest.raises(PreventUpdate):
            self._fn(app)(None, {})
