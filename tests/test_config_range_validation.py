"""Server-side range validation in ``apply_config_changes``.

The numeric Configuration inputs carry browser-level ``min``/``max``, but
those are advisory only -- a programmatic post or devtools edit can submit
out-of-range values. ``apply_config_changes`` therefore re-validates the
bounds server-side and returns a danger toast listing every offending
field. These tests invoke the unwrapped callback with one field out of
range at a time and assert the matching message is surfaced.
"""

from __future__ import annotations

import inspect

import dash

from nanometa_live.app.tabs.config_tab import register_config_callbacks
from tests.dash_test_utils import get_callback_fn


_AMPLICON_FIELD_IDS = [
    "chopper-minlength-input",
    "chopper-quality-input",
    "filtlong-minlength-input",
    "validation-identity-input",
    "kraken2-confidence-input",
    "minimap2-min-mapq-input",
]


def _apply_callback():
    """Register callbacks and return the unwrapped apply_config_changes fn."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_config_callbacks(app, backend_manager=None)
    for spec in app.callback_map.values():
        state_ids = [
            (s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None))
            for s in (spec.get("state", []) or [])
        ]
        if all(f in state_ids for f in _AMPLICON_FIELD_IDS):
            fn = spec["callback"]
            return getattr(fn, "__wrapped__", fn)
    raise AssertionError("apply_config_changes callback not found")


def _invoke(**overrides):
    """Call apply_config_changes with all params None except the overrides.

    Numeric checks are guarded by ``is not None`` so unrelated fields are
    skipped. nanopore_dir/kraken_db are left empty, which appends 'required'
    errors -- harmless, since every error accumulates into the same list
    that is returned together. We assert on the specific bound message.
    """
    fn = _apply_callback()
    params = list(inspect.signature(fn).parameters)
    kwargs = {p: None for p in params}
    kwargs["n_clicks"] = 1
    kwargs["current_config"] = {"data_dir": "/tmp/nanometa_rangetest"}
    kwargs.update(overrides)
    return fn(**kwargs)


def _message(result) -> str:
    """Extract the toast message from the 4-tuple return."""
    toast = result[2]
    assert isinstance(toast, dict), toast
    assert toast.get("color") == "danger"
    return toast.get("message", "")


class TestRangeValidation:
    def test_mapq_above_max_rejected(self):
        assert "MAPQ" in _message(_invoke(minimap2_min_mapq=99))

    def test_mapq_negative_rejected(self):
        assert "MAPQ" in _message(_invoke(minimap2_min_mapq=-1))

    def test_validation_identity_above_100_rejected(self):
        assert "identity" in _message(_invoke(validation_identity=150)).lower()

    def test_kraken2_confidence_above_one_rejected(self):
        assert "confidence" in _message(_invoke(kraken2_confidence=2.0)).lower()

    def test_chopper_quality_above_max_rejected(self):
        assert "quality" in _message(_invoke(chopper_quality=99)).lower()

    def test_chopper_minlength_negative_rejected(self):
        assert "minimum length" in _message(_invoke(chopper_minlength=-5)).lower()

    def test_filtlong_minlength_negative_rejected(self):
        assert "minimum length" in _message(_invoke(filtlong_minlength=-5)).lower()

    def test_alert_threshold_below_one_rejected(self):
        assert "Alert Threshold" in _message(_invoke(danger_threshold=0))

    def test_in_range_values_produce_no_bound_error(self):
        # All within bounds: the only errors should be the required-field
        # ones (nanopore/kraken), never a bound message.
        msg = _message(_invoke(
            minimap2_min_mapq=30,
            validation_identity=90,
            kraken2_confidence=0.5,
            chopper_quality=10,
            chopper_minlength=1000,
            filtlong_minlength=1000,
            danger_threshold=100,
        ))
        for needle in ("MAPQ", "identity must", "confidence must",
                       "quality must", "minimum length", "Alert Threshold"):
            assert needle not in msg
