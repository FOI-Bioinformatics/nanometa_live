"""Callback-level tests for the Taxonomy (classification) tab."""

import pytest
from dash import Dash, no_update
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.classification_tab import register_classification_callbacks
from dash_test_utils import get_callback_fn, make_callback_app


@pytest.fixture(scope="module")
def cls_app():
    return make_callback_app(register_classification_callbacks)


# --------------------------------------------------------------------------- #
# update_levels_from_preset
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("preset,expected", [
    ("standard", ['P', 'C', 'O', 'F', 'G', 'S']),
    ("overview", ['D', 'K', 'P', 'C']),
    ("species_focus", ['F', 'G', 'S']),
    ("clinical", ['F', 'G', 'S']),
    ("full", ['D', 'K', 'P', 'C', 'O', 'F', 'G', 'S']),
])
def test_levels_from_preset(cls_app, preset, expected):
    fn = get_callback_fn(cls_app, "classification-levels-input")
    assert fn(preset) == expected


def test_levels_from_preset_custom_is_noupdate(cls_app):
    fn = get_callback_fn(cls_app, "classification-levels-input")
    assert fn("custom") is no_update


def test_levels_from_preset_unknown_falls_back_to_standard(cls_app):
    fn = get_callback_fn(cls_app, "classification-levels-input")
    assert fn("nonsense") == ['P', 'C', 'O', 'F', 'G', 'S']


# --------------------------------------------------------------------------- #
# update_help_section
# --------------------------------------------------------------------------- #

def test_help_section_sunburst_vs_sankey(cls_app):
    fn = get_callback_fn(cls_app, "classification-help-section")
    sunburst = str(fn("sunburst"))
    sankey = str(fn("sankey"))
    assert "Sunburst" in sunburst and "Sunburst" not in sankey
    assert "Sankey" in sankey and "Sankey" not in sunburst


# --------------------------------------------------------------------------- #
# scale_min_reads_default
# --------------------------------------------------------------------------- #

def test_min_reads_default_single_sample_keeps_default(cls_app):
    fn = get_callback_fn(cls_app, "classification-filter-input")
    value, placeholder = fn(["barcode01"], "barcode01", None)
    assert value == 10
    assert "10 default" in placeholder


def test_min_reads_default_scales_for_aggregate_multiplex(cls_app):
    fn = get_callback_fn(cls_app, "classification-filter-input")
    samples = [f"barcode{i:02d}" for i in range(1, 25)]  # 24 barcodes
    value, placeholder = fn(samples, "All Samples", 10)
    assert value == 120          # max(10, 5 * 24)
    assert "recommended" in placeholder
    assert "24 samples" in placeholder


def test_min_reads_default_preserves_custom_value(cls_app):
    fn = get_callback_fn(cls_app, "classification-filter-input")
    samples = [f"barcode{i:02d}" for i in range(1, 25)]
    value, _ = fn(samples, "All Samples", 50)  # operator typed 50 -> keep it
    assert value == 50


# --------------------------------------------------------------------------- #
# toggle_export_modal
# --------------------------------------------------------------------------- #

def test_classification_export_modal_toggles(cls_app):
    fn = get_callback_fn(cls_app, "classification-export-modal")
    assert fn(1, 0, 0, False) is True     # open
    assert fn(0, 1, 0, True) is False     # confirm -> close
    assert fn(None, None, None, True) is True  # no click -> unchanged
