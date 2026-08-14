"""Declaring a negative control must be possible from the GUI.

``negative_control_samples`` was read by attribution, absent from every form,
and (until recently) undocumented. Under by_barcode input the sample name is
``barcode16`` and carries no marker, so the name-pattern fallback cannot help
and declaring it was the only route -- by hand-editing YAML an operator had no
way to know existed.

A multi-select rather than free text: ``is_negative_control`` matches the name
exactly, so ``Barcode16`` or a trailing space would look declared and silently
do nothing. Picking from real sample names removes that class of mistake, and
the saved values are unioned into the options so a control declared before any
data exists is not dropped.
"""

from __future__ import annotations

import dash
import pytest

from nanometa_live.app.tabs import config_tab
from nanometa_live.app.tabs.config_tab_helpers import build_config_from_form
from nanometa_live.core.utils.attribution import is_negative_control
from tests.dash_test_utils import get_callback_fn

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
    """Save the form with every field at None except the ones under test.

    build_config_from_form takes one keyword per registry field; filling them
    from the registry keeps this test from breaking whenever a field is added
    or removed elsewhere.
    """
    from nanometa_live.app.tabs.config_field_registry import FORM_FIELD_KWARGS

    nanopore, db = valid_paths
    form = {kw_name: None for kw_name in FORM_FIELD_KWARGS}
    form.update({"nanopore_dir": nanopore, "kraken_db": db})
    form.update(kw)
    config, errors = build_config_from_form({}, **form)
    assert config is not None, f"the form refused to save: {errors}"
    return config


class TestTheFieldRoundTrips:
    def test_selected_samples_are_saved(self, valid_paths):
        cfg = _saved(valid_paths, negative_controls=["barcode16", "barcode24"])

        assert cfg.get("negative_control_samples") == ["barcode16", "barcode24"]

    def test_names_are_trimmed_and_blanks_dropped(self, valid_paths):
        """Exact matching means a stray space is a silent failure."""
        cfg = _saved(valid_paths, negative_controls=[" barcode16 ", "", "  "])

        assert cfg.get("negative_control_samples") == ["barcode16"]

    def test_a_scalar_from_a_hand_edited_config_is_accepted(self, valid_paths):
        cfg = _saved(valid_paths, negative_controls="barcode16")

        assert cfg.get("negative_control_samples") == ["barcode16"]

    def test_nothing_selected_saves_an_empty_list(self, valid_paths):
        cfg = _saved(valid_paths, negative_controls=[])

        assert cfg.get("negative_control_samples") == []


class TestWhatIsSavedActuallyWorks:
    def test_the_saved_value_reaches_is_negative_control(self, valid_paths):
        """The point of the field: end to end, not just persisted."""
        cfg = _saved(valid_paths, negative_controls=["barcode16"])

        assert is_negative_control("barcode16", cfg)
        assert not is_negative_control("barcode11", cfg)

    def test_matching_stays_case_insensitive(self, valid_paths):
        cfg = _saved(valid_paths, negative_controls=["Barcode16"])

        assert is_negative_control("barcode16", cfg)


class TestTheOptionsAreUsable:
    @pytest.fixture
    def options_fn(self):
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        config_tab.register_config_callbacks(app, backend_manager=None)
        return get_callback_fn(
            app, "negative-controls-input", input_contains="available-samples"
        )

    def test_detected_samples_are_offered(self, options_fn):
        opts = options_fn(["All Samples", "barcode11", "barcode16"], [])

        values = [o["value"] for o in opts]
        assert values == ["barcode11", "barcode16"]

    def test_the_aggregate_is_not_offered(self, options_fn):
        """"All Samples" is not a sample and cannot be a control."""
        opts = options_fn(["All Samples", "barcode11"], [])

        assert "All Samples" not in [o["value"] for o in opts]

    def test_a_saved_name_survives_a_run_that_lacks_it(self, options_fn):
        """The declaration must not be erased by an absent barcode.

        A dcc.Dropdown drops any value with no matching option, so a control
        declared before the run -- or carried over from a previous one --
        would vanish from the form without a word.
        """
        opts = options_fn(["All Samples", "barcode11"], ["barcode16"])

        assert "barcode16" in [o["value"] for o in opts]

    def test_it_works_before_any_sample_exists(self, options_fn):
        """Setup time: the operator knows the control, the run has no data."""
        opts = options_fn([], ["barcode16"])

        assert [o["value"] for o in opts] == ["barcode16"]

    def test_no_samples_and_no_selection_is_empty(self, options_fn):
        assert options_fn(None, None) == []
