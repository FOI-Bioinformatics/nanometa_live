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
