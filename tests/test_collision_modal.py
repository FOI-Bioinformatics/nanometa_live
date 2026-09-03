"""Tests for the output-collision modal component.

Pinned behaviours:
  * create_collision_modal returns a Modal with the three expected
    button ids and the body Div.
  * render_collision_body shows the outdir path, lists the found
    subdirs, and explains the three actions in plain language.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc

from nanometa_live.app.components.collision_modal import (
    create_collision_modal,
    render_collision_body,
)


def _walk(component):
    """Yield every Dash component in the tree (BFS)."""
    if component is None:
        return
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        yield from _walk(c)


def _flatten_text(component) -> str:
    parts = []
    for node in _walk(component):
        if isinstance(node, str):
            parts.append(node)
            continue
        text = getattr(node, "children", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts)


def _ids(component) -> set:
    return {
        getattr(node, "id", None)
        for node in _walk(component)
        if getattr(node, "id", None)
    }


class TestCreateCollisionModal:
    def test_returns_a_modal(self):
        modal = create_collision_modal()
        assert isinstance(modal, dbc.Modal)

    def test_has_expected_ids(self):
        ids = _ids(create_collision_modal())
        assert "collision-modal" in ids
        assert "collision-modal-body" in ids
        assert "collision-archive-btn" in ids
        assert "collision-resume-btn" in ids
        assert "collision-cancel-btn" in ids

    def test_modal_starts_closed(self):
        modal = create_collision_modal()
        assert modal.is_open is False


class TestRenderCollisionBody:
    def test_shows_outdir_path(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2", "fastp"]
        )
        text = _flatten_text(body)
        assert "/tmp/results" in text

    def test_lists_found_subdirs(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2", "fastp", "validation"]
        )
        text = _flatten_text(body)
        assert "kraken2" in text
        assert "fastp" in text
        assert "validation" in text

    def test_explains_three_actions(self):
        body = render_collision_body("/tmp/results", ["kraken2"])
        text = _flatten_text(body).lower()
        assert "move existing" in text
        assert "continue" in text
        assert "cancel" in text

    def test_recommends_move_action(self):
        # The body should signal which option is the safe default.
        body = render_collision_body("/tmp/results", ["kraken2"])
        text = _flatten_text(body).lower()
        assert "recommended" in text

    def test_empty_found_falls_back(self):
        # Defensive: should not raise when called with an empty list,
        # even though the callback is supposed to gate this case.
        body = render_collision_body("/tmp/results", [])
        text = _flatten_text(body).lower()
        assert "no existing results" in text

    def test_no_mismatch_banner_when_input_unknown(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=None
        )
        text = _flatten_text(body).lower()
        assert "input differs" not in text

    def test_no_mismatch_banner_when_input_matches(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=True
        )
        text = _flatten_text(body).lower()
        assert "input differs" not in text

    def test_mismatch_banner_when_input_differs(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=False
        )
        text = _flatten_text(body).lower()
        assert "input differs" in text
        assert "mix" in text


class TestSettingsMismatchBanner:
    """Continuing into a folder whose results were produced under different
    analysis settings must say so.

    Measured live: a mid-run Apply raised the Kraken2 confidence from 0.05 to
    0.3, the next Start offered Continue, and the modal's three options
    described archiving, resuming and cancelling without a word about the
    change. The batches then appended to cumulative reports built at the old
    threshold, with nothing recording which rows came from which (round-5
    drills, C11).
    """

    DIFF = [("Kraken2 confidence", 0.05, 0.3), ("Minimum read length", 1000, 500)]

    def test_changed_settings_are_named(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=True, settings_diff=self.DIFF
        )
        text = _flatten_text(body).lower()
        assert "analysis settings differ" in text
        assert "kraken2 confidence" in text
        assert "0.05" in text and "0.3" in text

    def test_no_banner_when_settings_agree(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=True, settings_diff=[]
        )
        assert "analysis settings differ" not in _flatten_text(body).lower()

    def test_no_banner_when_the_prior_run_recorded_none(self):
        body = render_collision_body(
            "/tmp/results", ["kraken2"], input_match=True, settings_diff=None
        )
        assert "analysis settings differ" not in _flatten_text(body).lower()

    def test_silent_for_foreign_data(self):
        """No run record means no settings to compare against."""
        body = render_collision_body(
            "/tmp/results", ["kraken2"], has_metadata=False, settings_diff=self.DIFF
        )
        assert "analysis settings differ" not in _flatten_text(body).lower()


class TestAnalysisSettingsDiff:
    def _outdir(self, tmp_path, settings):
        import json
        from nanometa_live.core.workflow.backend_manager import BackendManager
        d = tmp_path / "out"
        d.mkdir()
        (d / BackendManager.RUN_METADATA_FILENAME).write_text(
            json.dumps({"analysis_settings": settings})
        )
        return str(d)

    def test_changed_keys_are_reported_with_both_values(self, tmp_path):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        out = self._outdir(tmp_path, {"kraken2_confidence": 0.05, "qc_tool": "chopper"})
        diff = BackendManager.analysis_settings_diff(
            out, {"kraken2_confidence": 0.3, "qc_tool": "chopper"}
        )
        assert diff == [("Kraken2 confidence", 0.05, 0.3)]

    def test_identical_settings_report_nothing(self, tmp_path):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        out = self._outdir(tmp_path, {"kraken2_confidence": 0.05})
        assert BackendManager.analysis_settings_diff(out, {"kraken2_confidence": 0.05}) == []

    def test_a_run_that_recorded_nothing_returns_none(self, tmp_path):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        out = self._outdir(tmp_path, {})
        assert BackendManager.analysis_settings_diff(out, {"kraken2_confidence": 0.3}) is None

    def test_a_key_added_since_that_run_is_not_a_change(self, tmp_path):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        out = self._outdir(tmp_path, {"kraken2_confidence": 0.05})
        diff = BackendManager.analysis_settings_diff(
            out, {"kraken2_confidence": 0.05, "minimap2_min_mapq": 30}
        )
        assert diff == []

    def test_write_run_metadata_records_the_settings(self, tmp_path):
        import json
        from nanometa_live.core.workflow.backend_manager import BackendManager
        d = tmp_path / "out"; d.mkdir()
        BackendManager.write_run_metadata(str(d), {"kraken2_confidence": 0.2, "qc_tool": "chopper"})
        meta = json.loads((d / BackendManager.RUN_METADATA_FILENAME).read_text())
        assert meta["analysis_settings"]["kraken2_confidence"] == 0.2
        assert meta["analysis_settings"]["qc_tool"] == "chopper"
