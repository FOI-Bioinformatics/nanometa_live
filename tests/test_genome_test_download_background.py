"""Tests for the 'Test genome download' callback after its conversion to a
background callback (P1 background-callback audit finding).

The button runs an NCBI `datasets` download (network + subprocess). It now runs
in a worker; the genome lands on disk and the callback only reports a path, so
there is no in-process side effect to return -- a plain background callback.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash_test_utils import get_callback_fn, make_callback_app
from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks


@pytest.fixture
def app():
    return make_callback_app(register_preparation_callbacks)


def _spec(app):
    for cb_id, spec in app.callback_map.items():
        if "genome-test-result" in cb_id and \
                "test-genome-download-btn" in str(spec.get("inputs")):
            return spec
    raise AssertionError("test_genome_download callback not found")


def _fn(app):
    return get_callback_fn(
        app, "genome-test-result.children",
        input_contains="test-genome-download-btn",
    )


def test_registered_as_background(app):
    assert _spec(app).get("background"), \
        "test_genome_download must be a background callback"


def test_missing_datasets_cli_reports_error(app):
    with patch("shutil.which", return_value=None):
        out = _fn(app)(MagicMock(), 1, {})
    assert out.color == "danger"
    assert "datasets" in str(out.children).lower()


def test_success_reports_path_and_shows_spinner(app, tmp_path):
    mgr = MagicMock()
    mgr.cache_dir = str(tmp_path)
    mgr.download_genome.return_value = str(tmp_path / "562.fasta")
    set_progress = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/datasets"), \
         patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
               return_value=mgr):
        out = _fn(app)(set_progress, 1, {"genome_cache_dir": str(tmp_path)})
    assert out.color == "success"
    assert "562.fasta" in str(out.children)
    assert set_progress.called   # spinner shown while downloading


def test_download_failure_reports_error(app, tmp_path):
    mgr = MagicMock()
    mgr.cache_dir = str(tmp_path)
    mgr.download_genome.return_value = None
    with patch("shutil.which", return_value="/usr/bin/datasets"), \
         patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
               return_value=mgr):
        out = _fn(app)(MagicMock(), 1, {"genome_cache_dir": str(tmp_path)})
    assert out.color == "danger"
    assert "failed" in str(out.children).lower()
