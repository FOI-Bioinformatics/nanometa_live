"""Chunked batch classification must be switchable from the Configuration tab.

``batch_chunking`` defaults on and is a measured trade-off, not a universal
win: the 2026-09-06 audit found it faster to all-first-report on MinKNOW-sized
files (86.9 s against the unchunked control's 156.6 s) and a 130% regression on
barcode spread with 500-read files. Until this field existed the only way to
turn it off was to hand-edit ``config.yaml``.

A field is only real when it is wired into all four places CLAUDE.md's "save /
load / dirty-state symmetry" names, so each is asserted here: the saved config,
the repopulated form, the "Modified" badge and the session draft. The
component id follows the registry's ``<name>-input`` convention, which
``tests/test_config_field_registry.py`` enforces for every form widget.
"""

from __future__ import annotations

import pytest

from nanometa_live.app.tabs.config_field_registry import (
    CONFIG_FORM_FIELDS,
    FORM_FIELD_KWARGS,
)
from nanometa_live.app.tabs.config_tab_helpers import (
    build_config_from_form,
    config_form_dirty,
)
from nanometa_live.core.config.config_loader import default_config
from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


@pytest.fixture
def valid_paths(tmp_path):
    """The form refuses to save unless the required paths resolve."""
    nanopore = tmp_path / "in"
    nanopore.mkdir()
    db = tmp_path / "db"
    db.mkdir()
    for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (db / name).write_bytes(b"x")
    return str(nanopore), str(db)


def _saved(valid_paths, **kw):
    nanopore, db = valid_paths
    form = {kw_name: None for kw_name in FORM_FIELD_KWARGS}
    form.update({"nanopore_dir": nanopore, "kraken_db": db})
    form.update(kw)
    config, errors = build_config_from_form({}, **form)
    assert config is not None, f"the form refused to save: {errors}"
    return config


@pytest.fixture
def cfg_app():
    from unittest.mock import MagicMock

    from nanometa_live.app.tabs.config_tab import register_config_callbacks

    return make_callback_app(
        lambda app: register_config_callbacks(app, MagicMock()))


class TestTheFieldIsInTheRegistry:
    def test_the_switch_is_a_registered_form_widget(self):
        assert ("batch-chunking-input", "batch_chunking") in CONFIG_FORM_FIELDS

    def test_the_switch_is_rendered_in_the_analysis_options_card(self):
        """A registered id whose widget is not in the layout is unreachable.

        The registry guard checks the callbacks, and the app registers with
        suppress_callback_exceptions, so a missing widget would fail only in
        a browser.
        """
        from nanometa_live.app.components.config_form import _analysis_options_item

        def walk(component, out):
            cid = getattr(component, "id", None)
            if cid is not None:
                out.add(str(cid))
            children = getattr(component, "children", None)
            if children is None:
                return
            for child in (children if isinstance(children, (list, tuple)) else [children]):
                if hasattr(child, "children") or hasattr(child, "id"):
                    walk(child, out)

        rendered: set = set()
        walk(_analysis_options_item(), rendered)
        assert "batch-chunking-input" in rendered
        assert "batch-chunking-help" in rendered


class TestApplyWritesIt:
    def test_off_is_saved_as_false(self, valid_paths):
        assert _saved(valid_paths, batch_chunking=False)["batch_chunking"] is False

    def test_on_is_saved_as_true(self, valid_paths):
        assert _saved(valid_paths, batch_chunking=True)["batch_chunking"] is True

    def test_an_untouched_form_leaves_the_existing_value_alone(self, valid_paths):
        """None means "no widget value", not "off" -- the config keeps its own."""
        nanopore, db = valid_paths
        form = {kw_name: None for kw_name in FORM_FIELD_KWARGS}
        form.update({"nanopore_dir": nanopore, "kraken_db": db})
        config, errors = build_config_from_form({"batch_chunking": False}, **form)
        assert errors == []
        assert config["batch_chunking"] is False


class TestInitialiseReadsItBack:
    def _values(self, cfg_app, config):
        fn = get_callback_fn(
            cfg_app, "config-form-initialized", input_contains="refresh-form-trigger")
        outputs = fn(1, config, None)
        index = [cid for cid, _ in CONFIG_FORM_FIELDS].index("batch-chunking-input")
        return outputs[index]

    def test_a_saved_false_repopulates_the_switch_off(self, cfg_app):
        assert self._values(cfg_app, {"batch_chunking": False}) is False

    def test_a_config_without_the_key_shows_the_shipped_default(self, cfg_app):
        """The form fallback must be the value the app will actually use."""
        assert self._values(cfg_app, {"analysis_name": "run"}) is (
            default_config()["batch_chunking"])


class TestTheDirtyCheckSeesIt:
    def test_flipping_the_switch_marks_the_form_modified(self):
        snapshot = {"batch_chunking": True}
        assert config_form_dirty(snapshot, form={"batch_chunking": False})
        assert not config_form_dirty(snapshot, form={"batch_chunking": True})

    def test_a_string_in_a_hand_edited_config_compares_as_a_boolean(self):
        """``batch_chunking`` is in the dirty check's bool_keys set."""
        assert not config_form_dirty(
            {"batch_chunking": "true"}, form={"batch_chunking": True})


class TestTheSessionDraftCarriesIt:
    def test_the_draft_written_on_edit_holds_the_new_value(self, cfg_app):
        # detect_form_changes lists its Inputs in its own order (the registry
        # fixes the set, not the order), so the positional values are built
        # from the registered spec rather than from CONFIG_FORM_FIELDS.
        spec = next(
            s for cb_id, s in cfg_app.callback_map.items()
            if "config-form-draft.data" in cb_id and "config-modified.data" in cb_id
        )
        input_ids = [
            i["id"] if isinstance(i, dict) else i.component_id
            for i in spec["inputs"]
        ]
        by_id = {cid: None for cid in input_ids}
        by_id["batch-chunking-input"] = False
        values = [by_id[cid] for cid in input_ids]

        fn = get_callback_fn(
            cfg_app, "config-form-draft", input_contains="batch-chunking-input")
        # The third State is config-form-initialized: True means the values
        # arrived from a form (re)initialisation, which the callback skips.
        outputs = fn(*values, {"batch_chunking": True}, False, False)
        draft = next(o for o in outputs if isinstance(o, dict) and "batch_chunking" in o)
        assert draft["batch_chunking"] is False
        # Outputs are (config-modified, config-form-initialized, draft).
        assert outputs[0] is True, "flipping the switch must flag the form modified"
