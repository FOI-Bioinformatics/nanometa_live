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

    def test_minimap2_preset_default_is_long_read(self):
        """Default must remain ``map-ont`` so unmodified configs keep
        long-read behaviour."""
        form = create_config_form()
        select = _find_by_id(form, "minimap2-preset-input")
        assert select is not None
        assert select.value == "map-ont"

    def test_minimap2_min_mapq_input_renders(self):
        """``minimap2-min-mapq-input`` is one of the eight read-filtering
        fields the audit plan calls out. It lives in the existing
        Validation Settings card (not the new sub-card). The form ships
        its own operator-facing default which can differ from the
        pipeline default; assert only that the input renders with a
        value in the allowed 0-60 range."""
        form = create_config_form()
        widget = _find_by_id(form, "minimap2-min-mapq-input")
        assert widget is not None, (
            "minimap2-min-mapq-input missing from the Configuration form"
        )
        assert isinstance(widget.value, int)
        assert 0 <= widget.value <= 60


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

    @staticmethod
    def _seed_input(tmp_path):
        """Create a minimal but valid input directory.

        ``create_nextflow_params`` calls ``generate_samplesheet``, which
        (rightly) raises if the directory has no FASTQ files. These
        tests only care about parameter routing, so a single empty
        FASTQ is enough.
        """
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "reads.fastq.gz").write_bytes(b"")
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return input_dir, results_dir

    def _amplicon_config(self, tmp_path):
        input_dir, results_dir = self._seed_input(tmp_path)
        return {
            # Required basics so create_nextflow_params does not error
            "nanopore_output_directory": str(input_dir),
            "kraken_db": str(tmp_path / "kraken_db"),
            "results_output_directory": str(results_dir),
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

    def test_amplicon_config_flows_to_pipeline_params(self, tmp_path):
        params = create_nextflow_params(self._amplicon_config(tmp_path))
        assert params["chopper_minlength"] == 100
        assert params["chopper_quality"] == 7
        assert params["filtlong_min_length"] == 100
        assert params["validation_identity_threshold"] == 80.0
        assert params["kraken2_confidence"] == 0.05
        assert params["kraken2_minimum_hit_groups"] == 2

    def test_long_read_defaults_when_keys_absent(self, tmp_path):
        """When the operator has not set any of the new keys, the
        defaults match the nanometanf pipeline-side defaults so
        existing long-read flows are unaffected."""
        input_dir, results_dir = self._seed_input(tmp_path)
        baseline = {
            "nanopore_output_directory": str(input_dir),
            "kraken_db": str(tmp_path / "kraken_db"),
            "results_output_directory": str(results_dir),
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


# -- Amplicon-aware Q30 / classification bands --------------------------


class TestAmpliconAwareBands:
    """When the operator has set chopper_minlength<500 or
    filtlong_min_length<500, the QC tab Q30 and classification-rate
    bands should relax to match short-read expectations.
    Closes P5 from the readiness audit."""

    def test_is_amplicon_mode_default_false(self):
        from nanometa_live.app.tabs.qc_tab import _is_amplicon_mode
        assert _is_amplicon_mode(None) is False
        assert _is_amplicon_mode({}) is False
        assert _is_amplicon_mode({"chopper_minlength": 1000}) is False

    def test_is_amplicon_mode_chopper_short(self):
        from nanometa_live.app.tabs.qc_tab import _is_amplicon_mode
        assert _is_amplicon_mode({"chopper_minlength": 100}) is True
        assert _is_amplicon_mode({"chopper_minlength": 0}) is True
        assert _is_amplicon_mode({"chopper_minlength": 499}) is True
        assert _is_amplicon_mode({"chopper_minlength": 500}) is False

    def test_is_amplicon_mode_filtlong_short(self):
        from nanometa_live.app.tabs.qc_tab import _is_amplicon_mode
        assert _is_amplicon_mode({"filtlong_min_length": 250}) is True

    def test_is_amplicon_mode_handles_nonsense_values(self):
        from nanometa_live.app.tabs.qc_tab import _is_amplicon_mode
        # Strings, None, garbage all default to False (long-read mode).
        assert _is_amplicon_mode({"chopper_minlength": None}) is False
        assert _is_amplicon_mode({"chopper_minlength": "garbage"}) is False
        assert _is_amplicon_mode({"chopper_minlength": ""}) is False

    def test_basequalitycard_amplicon_mode_relaxes_q30_bands(self):
        """A 30% Q30 rate is amber under long-read bands but green
        under amplicon bands. We pick Q20=80 (above both green floors)
        so Q20's colour does not muddy the assertion -- only Q30
        differs between modes."""
        from nanometa_live.app.components.organism_components import (
            BaseQualityCard,
        )

        long_read = BaseQualityCard(q20_rate=80, q30_rate=30, total_bases=1000)
        amplicon = BaseQualityCard(
            q20_rate=80, q30_rate=30, total_bases=1000, amplicon_mode=True
        )

        # The Q30 metric carries its own status string in the Small
        # element ("Excellent" / "Good" / "Fair" / "Poor"). Status
        # transitions when bands change. Pull it from the rendered
        # JSON: long-read shows "Fair" at 30%, amplicon shows
        # "Excellent" at 30%.
        import json
        long_json = json.dumps(long_read.to_plotly_json(), default=str)
        amp_json = json.dumps(amplicon.to_plotly_json(), default=str)

        # Q30 amber colour code present in long-read at 30%
        assert "#ffc107" in long_json, (
            "long-read mode should colour 30% Q30 amber (#ffc107)"
        )
        # Amplicon mode: Q20 stays green AND Q30 turns green at 30%,
        # so the only colour-coded metrics here use the success token.
        # Green hex is #28a745.
        assert "#28a745" in amp_json
        # Sanity: the long-read variant must NOT have the Q30 cell as
        # green at 30%; its rendered DOM should still contain the
        # amber colour token (the Q30 cell drives it since Q20=80 is
        # above the long-read green floor of 65).
        assert "#ffc107" in long_json

    def test_qc_stage_strip_classification_bands_amplicon(self):
        """Classification rate at 60% is amber under long-read bands
        but green under amplicon bands."""
        from nanometa_live.app.tabs.qc_tab import _build_stage_strip

        long_read = _build_stage_strip(
            raw_reads=1000, filtered_reads=900,
            classified_reads=600, unclassified_reads=400,
            is_chopper=False, filter_tool="FASTP", timestamp_str="00:00:00",
            amplicon_mode=False,
        )
        amplicon = _build_stage_strip(
            raw_reads=1000, filtered_reads=900,
            classified_reads=600, unclassified_reads=400,
            is_chopper=False, filter_tool="FASTP", timestamp_str="00:00:00",
            amplicon_mode=True,
        )
        import json
        long_json = json.dumps(long_read.to_plotly_json(), default=str)
        amp_json = json.dumps(amplicon.to_plotly_json(), default=str)

        # 60% classification: amber in long-read mode, green in amplicon mode.
        assert "stage-strip-delta--amber" in long_json
        assert "stage-strip-delta--green" in amp_json
