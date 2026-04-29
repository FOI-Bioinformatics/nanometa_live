"""Tests for the amplicon-friendly Read Filtering and Validation
controls in the Configuration tab.

The audit at ``docs/audit-2026-04-29-short-amplicons.md`` identified
six length / quality / threshold parameters that operators need to
override when running short-amplicon ONT data. The override flow is:

    Config form input -> apply_config_changes callback -> app-config
        -> parameter_mapping.create_nextflow_params -> nanometanf

These tests verify each link in the chain is wired correctly. See
the plan at /Users/andreassjodin/.claude/plans/how-could-we-make-cheerful-shell.md
for the W7-style implementation walkthrough.
"""

from __future__ import annotations

from typing import List

import dash
import dash_bootstrap_components as dbc
import pytest

from nanometa_live.app.components.config_form import create_config_form
from nanometa_live.app.tabs.config_tab import register_config_callbacks
from nanometa_live.core.config.parameter_mapping import create_nextflow_params


_AMPLICON_FIELD_IDS: List[str] = [
    "chopper-minlength-input",
    "chopper-quality-input",
    "filtlong-minlength-input",
    "validation-identity-input",
    "kraken2-confidence-input",
    "kraken2-hitgroups-input",
]


def _walk_components(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        if hasattr(c, "children") or hasattr(c, "id"):
            yield from _walk_components(c)


def _find_by_id(root, target_id: str):
    for node in _walk_components(root):
        if getattr(node, "id", None) == target_id:
            return node
    return None


# -- Layout --------------------------------------------------------------


class TestReadFilteringSubCardLayout:
    """The Configuration tab's Advanced Settings accordion must surface
    every amplicon-tunable field with the documented defaults."""

    def test_all_six_inputs_render_with_long_read_defaults(self):
        form = create_config_form()
        widgets = {tid: _find_by_id(form, tid) for tid in _AMPLICON_FIELD_IDS}

        for tid, widget in widgets.items():
            assert widget is not None, f"{tid} missing from Advanced Settings"

        # Defaults match nanometanf pipeline-side defaults so an operator
        # who has not touched the new card keeps the long-read behaviour.
        assert widgets["chopper-minlength-input"].value == 1000
        assert widgets["chopper-quality-input"].value == 10
        assert widgets["filtlong-minlength-input"].value == 1000
        assert widgets["validation-identity-input"].value == 90
        assert widgets["kraken2-confidence-input"].value == 0.0
        assert widgets["kraken2-hitgroups-input"].value == 0

    def test_no_duplicate_component_ids(self):
        """Sanity: adding the new sub-card must not collide with any
        existing input id (Dash duplicate-id is a fatal runtime error)."""
        form = create_config_form()
        ids = []
        for node in _walk_components(form):
            nid = getattr(node, "id", None)
            if isinstance(nid, str) and nid:
                ids.append(nid)

        from collections import Counter
        dupes = [k for k, v in Counter(ids).items() if v > 1]
        assert not dupes, f"duplicate ids found: {dupes}"

    def test_minimap2_preset_includes_short_read_option(self):
        """The existing Validation Settings dropdown must offer ``sr``
        for short-amplicon protocols. This is the single source of
        truth for the preset; the new sub-card cross-references it."""
        form = create_config_form()
        select = _find_by_id(form, "minimap2-preset-input")
        assert select is not None
        values = [opt["value"] for opt in select.options]
        assert "sr" in values, (
            "minimap2-preset-input must offer 'sr' for short amplicons"
        )


# -- Callback wiring -----------------------------------------------------


class TestCallbackWiring:
    """The three callbacks that touch the 6 amplicon fields must
    subscribe to (or write) all of them. ``State`` for apply,
    ``Input`` for detect-modified, ``Output`` for init-from-config."""

    def _register(self):
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        register_config_callbacks(app, backend_manager=None)
        return app

    @staticmethod
    def _ids_of(specs):
        result = []
        for s in specs:
            if isinstance(s, dict):
                result.append(s.get("id"))
            else:
                result.append(getattr(s, "component_id", None))
        return result

    def test_apply_callback_reads_all_six_states(self):
        app = self._register()
        for cb_id, spec in app.callback_map.items():
            state_ids = self._ids_of(spec.get("state", []) or [])
            if all(e in state_ids for e in _AMPLICON_FIELD_IDS):
                return  # found it
        pytest.fail("No apply_config_changes callback reads all 6 amplicon fields")

    def test_detect_modified_callback_observes_all_six_inputs(self):
        app = self._register()
        for cb_id, spec in app.callback_map.items():
            input_ids = self._ids_of(spec.get("inputs", []) or [])
            if all(e in input_ids for e in _AMPLICON_FIELD_IDS):
                return
        pytest.fail("No detect_form_changes callback observes all 6 fields")

    def test_init_callback_writes_all_six_outputs(self):
        app = self._register()
        for cb_id, spec in app.callback_map.items():
            outputs = spec.get("output", [])
            if not isinstance(outputs, list):
                outputs = [outputs]
            output_ids = self._ids_of(outputs)
            if all(e in output_ids for e in _AMPLICON_FIELD_IDS):
                return
        pytest.fail("No initialize_form_from_config callback writes all 6 fields")


# -- parameter_mapping --------------------------------------------------


class TestAmpliconParamsRouted:
    """The five new pipeline params must flow through
    ``create_nextflow_params`` when the operator has set them."""

    def _amplicon_config(self):
        return {
            # Required basics so create_nextflow_params does not error
            "nanopore_output_directory": "/tmp/test_amplicon",
            "kraken_db": "/tmp/test_db",
            "results_output_directory": "/tmp/test_results",
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "blast_validation": False,
            # The amplicon-mode overrides
            "chopper_minlength": 100,
            "chopper_quality": 7,
            "filtlong_min_length": 100,
            "validation_identity_threshold": 80.0,
            "kraken2_confidence": 0.05,
            "kraken2_minimum_hit_groups": 2,
        }

    def test_amplicon_config_flows_to_pipeline_params(self):
        params = create_nextflow_params(self._amplicon_config())
        assert params["chopper_minlength"] == 100
        assert params["chopper_quality"] == 7
        assert params["filtlong_min_length"] == 100
        assert params["validation_identity_threshold"] == 80.0
        assert params["kraken2_confidence"] == 0.05
        assert params["kraken2_minimum_hit_groups"] == 2

    def test_long_read_defaults_when_keys_absent(self):
        """When the operator has not set any of the new keys, the
        defaults match the nanometanf pipeline-side defaults so
        existing long-read flows are unaffected."""
        baseline = {
            "nanopore_output_directory": "/tmp/test",
            "kraken_db": "/tmp/db",
            "results_output_directory": "/tmp/results",
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "blast_validation": False,
        }
        params = create_nextflow_params(baseline)
        assert params["chopper_minlength"] == 1000
        assert params["chopper_quality"] == 10
        assert params["filtlong_min_length"] == 1000
        assert params["kraken2_confidence"] == 0.0
        assert params["kraken2_minimum_hit_groups"] == 0
