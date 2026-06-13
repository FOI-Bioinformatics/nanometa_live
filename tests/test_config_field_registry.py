"""Guard: the Configuration-form field set stays in lock-step everywhere.

The Configuration tab maintained the same field set by hand in four places
(apply_config_changes States, initialize_form_from_config Outputs,
detect_form_changes Inputs, build_config_from_form kwargs). Drift between them
silently mis-reports the form or launches a stale config. These tests assert all
four derive from the single CONFIG_FORM_FIELDS registry, so adding a field to one
consumer but not the registry (or vice versa) fails CI instead of shipping.
"""

import inspect
import re
from unittest.mock import MagicMock

import pytest

from dash_test_utils import make_callback_app
from nanometa_live.app.tabs.config_tab import register_config_callbacks
from nanometa_live.app.tabs.config_tab_helpers import build_config_from_form
from nanometa_live.app.tabs.config_field_registry import (
    FORM_FIELD_IDS,
    FORM_FIELD_KWARGS,
)


@pytest.fixture
def config_app():
    # register_config_callbacks needs a BackendManager; a mock is fine here --
    # we only introspect the registered callbacks' Input/Output/State sets.
    return make_callback_app(lambda app: register_config_callbacks(app, MagicMock()))


def _form_ids(items):
    """Form-widget component ids ("<name>-input") from a spec inputs/state list."""
    out = set()
    for s in items:
        cid = s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None)
        if cid and str(cid).endswith("-input"):
            out.add(str(cid))
    return out


def _find_callback(app, *, key_contains, exclude=()):
    """Return the (cb_id, spec) whose callback_map key contains all of
    ``key_contains`` and none of ``exclude``."""
    for cb_id, spec in app.callback_map.items():
        if all(k in cb_id for k in key_contains) and not any(x in cb_id for x in exclude):
            return cb_id, spec
    raise AssertionError(f"no callback matching {key_contains!r}")


def test_apply_states_match_registry(config_app):
    _cb, spec = _find_callback(config_app, key_contains=["apply-config-button.children"])
    assert _form_ids(spec["state"]) == FORM_FIELD_IDS


def test_detect_inputs_match_registry(config_app):
    _cb, spec = _find_callback(
        config_app, key_contains=["config-form-draft.data", "config-modified.data"]
    )
    assert _form_ids(spec["inputs"]) == FORM_FIELD_IDS


def test_initialize_outputs_match_registry(config_app):
    # initialize_form_from_config's Outputs are encoded in the callback_map key.
    cb_id, _spec = _find_callback(
        config_app, key_contains=["config-form-initialized.data", "analysis-name-input.value"]
    )
    out_ids = set(re.findall(r"([a-z0-9-]+-input)\.value", cb_id))
    assert out_ids == FORM_FIELD_IDS


def test_build_config_from_form_kwargs_match_registry():
    params = inspect.signature(build_config_from_form).parameters
    kw_only = {
        name for name, p in params.items()
        if p.kind == inspect.Parameter.KEYWORD_ONLY
    }
    assert kw_only == FORM_FIELD_KWARGS
