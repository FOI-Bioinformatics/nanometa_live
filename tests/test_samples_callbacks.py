"""Callback tests for app/callbacks/samples.py (sample/barcode selection)."""

import os
import time
from unittest.mock import MagicMock

import pytest
from dash import Dash, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.samples import register_samples
from nanometa_live.core.testing.mock_data_generator import (
    generate_test_dataset,
    MockDataScenario,
)
from dash_test_utils import get_callback_fn, ctx_with


@pytest.fixture(scope="module")
def samples_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_samples(app, MagicMock())
    return app


@pytest.fixture(scope="module")
def populated_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples_populated")
    generate_test_dataset(str(d), scenario=MockDataScenario.PATHOGEN_DETECTED, num_samples=3)
    old = time.time() - 30
    for dp, _dirs, files in os.walk(str(d)):
        for f in files:
            try:
                os.utime(os.path.join(dp, f), (old, old))
            except OSError:
                pass
    return str(d)


# --------------------------------------------------------------------------- #
# update_available_samples
# --------------------------------------------------------------------------- #

def test_available_samples_empty_config(samples_app):
    fn = get_callback_fn(samples_app, "available-samples")
    with ctx_with("results-fingerprint"):
        samples, mapping = fn("fp", 0, {}, [], {})
    assert samples == ["All Samples"]
    assert mapping == {}


def test_available_samples_unchanged_prevents_update(samples_app):
    fn = get_callback_fn(samples_app, "available-samples")
    with ctx_with("results-fingerprint"):
        with pytest.raises(PreventUpdate):
            # prev already equals what an empty config produces -> no re-render
            fn("fp", 0, {}, ["All Samples"], {})


def test_available_samples_detects_populated(samples_app, populated_dir):
    fn = get_callback_fn(samples_app, "available-samples")
    with ctx_with("results-fingerprint"):
        samples, mapping = fn("fp2", 0, {"results_output_directory": populated_dir}, [], {})
    assert samples[0] == "All Samples"
    assert len(samples) >= 2  # aggregate + >=1 detected sample


# --------------------------------------------------------------------------- #
# update_sample_selector_options
# --------------------------------------------------------------------------- #

def test_selector_options_built_from_samples(samples_app):
    fn = get_callback_fn(samples_app, "sample-selector")
    options, value = fn(["All Samples", "barcode01"], {}, None)
    assert len(options) == 2
    assert options[0]["value"] == "All Samples"
    assert value is no_update


def test_selector_resets_when_selection_gone(samples_app):
    fn = get_callback_fn(samples_app, "sample-selector")
    options, value = fn(["All Samples", "barcode02"], {}, "barcode01")  # barcode01 gone
    assert value == "All Samples"


# --------------------------------------------------------------------------- #
# update_selected_sample
# --------------------------------------------------------------------------- #

def test_selected_sample_passthrough_and_default(samples_app):
    fn = get_callback_fn(samples_app, "selected-sample")
    assert fn("barcode03") == "barcode03"
    assert fn(None) == "All Samples"
    assert fn("") == "All Samples"


# --------------------------------------------------------------------------- #
# update_sample_freshness
# --------------------------------------------------------------------------- #

def test_freshness_empty_without_config(samples_app):
    fn = get_callback_fn(samples_app, "sample-freshness")
    assert fn("fp", 0, ["All Samples"], {}) == {}
    assert fn("fp", 0, None, {"results_output_directory": "/nope"}) == {}
