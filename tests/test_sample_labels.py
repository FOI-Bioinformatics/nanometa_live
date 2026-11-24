"""MinKNOW's ``unclassified`` barcode folder is named for what it holds.

At the Barcelona exercise (2026-11-24 feedback) a Japanese encephalitis
detection was attributed to "unclassified, barcode11, barcode06": the reads
MinKNOW could not assign to a barcode, listed as if they were one more
sample, under a word Kraken2 uses for something else.
"""

import pytest

from nanometa_live.core.utils.sample_labels import (
    UNASSIGNED_SAMPLE,
    display_sample_name,
)

pytestmark = pytest.mark.unit


def test_display_name():
    assert UNASSIGNED_SAMPLE == "unclassified"
    assert display_sample_name("unclassified") == "unclassified (no barcode)"
    assert display_sample_name("barcode11") == "barcode11"
    assert display_sample_name("") == ""


def test_banner_phrase_labels_the_unassigned_folder():
    from nanometa_live.core.utils.attribution import (
        PathogenAttribution,
        _attribution_phrase,
    )
    phrase = _attribution_phrase(PathogenAttribution(
        pathogen="Japanese encephalitis virus",
        samples=["unclassified", "barcode11"],
        below_threshold_samples=[], top_reads=100))
    assert "unclassified (no barcode), barcode11" in phrase


def test_below_threshold_phrase_labels_it_too():
    from nanometa_live.core.utils.attribution import (
        PathogenAttribution,
        _attribution_phrase,
    )
    phrase = _attribution_phrase(PathogenAttribution(
        pathogen="X", samples=[], below_threshold_samples=["unclassified"],
        top_reads=3))
    assert "unclassified (no barcode)" in phrase


def test_system_alert_suffix_labels_it():
    from nanometa_live.core.utils.alert_engine import _sample_suffix
    assert _sample_suffix(["unclassified", "barcode11"]) == (
        " in unclassified (no barcode), barcode11")


def test_alert_card_chip_and_popover_label_it():
    from nanometa_live.app.components.attribution import (
        _render_sample_attribution,
        attribution_popover_rows,
    )
    from test_pathogen_alert_rendering import _text

    samples = [{"sample": "unclassified", "reads": 50, "abundance": 1.0},
               {"sample": "barcode11", "reads": 40, "abundance": 1.0}]
    assert "unclassified (no barcode)" in _text(
        _render_sample_attribution(samples, "critical"))
    from dash import html
    assert "unclassified (no barcode)" in _text(
        html.Div(attribution_popover_rows(samples)))


def test_selector_label_changes_and_value_does_not():
    from unittest.mock import MagicMock
    from dash_test_utils import get_callback_fn, make_callback_app
    from nanometa_live.app.callbacks.samples import register_samples
    from test_sample_selector_marks_dataless import _texts

    app = make_callback_app(lambda a: register_samples(a, MagicMock()))
    fn = get_callback_fn(app, "sample-selector", input_contains="available-samples")
    options, _value = fn(["All Samples", "unclassified", "barcode01"], {},
                         "All Samples", {"unclassified": [], "barcode01": []})
    by_value = {o["value"]: " ".join(_texts(o["label"])) for o in options}
    assert "unclassified" in by_value
    assert "unclassified (no barcode)" in by_value["unclassified"]
    assert "(no barcode)" not in by_value["barcode01"]


def test_pathogen_report_modal_breakdown_labels_it():
    from nanometa_live.app.tabs.dashboard_helpers import build_detection_meta
    from test_pathogen_alert_rendering import _text
    meta = build_detection_meta(sample_breakdown=[
        {"sample": "unclassified", "reads": 300}, {"sample": "barcode01", "reads": 200}])
    assert "unclassified (no barcode) (300 reads)" in _text(meta)
