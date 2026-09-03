"""Round-5 audit probes: Configuration tab advanced settings (static pass).

One test per static hypothesis in docs/audit/config-tab-round5-2026-09-03.md.
Each test asserts the EXPECTED behaviour, so a confirmed defect fails red.
The tests that survive the fix pass move to the file that owns the behaviour.
"""

import inspect
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dash import Dash, no_update

from dash_test_utils import get_callback_fn as _callback_fn
from nanometa_live.app.tabs.config_field_registry import CONFIG_FORM_FIELDS
from nanometa_live.app.tabs.config_tab import register_config_callbacks
from nanometa_live.app.tabs.config_tab_helpers import (
    build_config_from_form,
    config_form_dirty,
)
from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.config.parameter_mapping import create_nextflow_params

PKG = Path(__file__).resolve().parents[1] / "nanometa_live"


@pytest.fixture
def cfg_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_config_callbacks(app, MagicMock())
    return app


def _defaults(tmp_path):
    return ConfigLoader(str(tmp_path / "configs")).create_default_config()


def _output_ids(app, output_id, input_contains):
    """Component ids of the Outputs, in declared order, of the callback that
    owns output_id and is triggered by input_contains."""
    for cb_id, spec in app.callback_map.items():
        if output_id not in cb_id:
            continue
        ids = [str(i.get("id")) for i in spec.get("inputs", [])]
        if any(input_contains in x for x in ids):
            return [o.rsplit(".", 1)[0] for o in cb_id.strip(".").split("...")]
    raise AssertionError(f"no callback for {output_id}")


def _output_count(app, output_id, input_contains):
    return len(_output_ids(app, output_id, input_contains))


def _init_index(app):
    ids = _output_ids(app, "config-form-initialized", "refresh-form-trigger")
    return {cid: i for i, cid in enumerate(ids)}


def _init_fn(app):
    return _callback_fn(app, "config-form-initialized", input_contains="refresh-form-trigger")


def _apply(app):
    fn = _callback_fn(app, "app-config", input_contains="apply-config-request")

    def invoke(current_config, backend_status=None, **overrides):
        by_name = {kw: None for _, kw in CONFIG_FORM_FIELDS}
        by_name.update(overrides)
        values = [by_name[kw] for _, kw in CONFIG_FORM_FIELDS]
        return fn({"n": 1}, *values, current_config, backend_status or {"running": False})
    return invoke


def _valid_paths(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (db / name).write_bytes(b"x")
    return str(inbox), str(db)


# ---- A. form lifecycle -------------------------------------------------------


class TestA1InitOutputArity:
    def test_empty_config_path_returns_one_value_per_output(self, cfg_app):
        declared = _output_count(cfg_app, "config-form-initialized", "refresh-form-trigger")
        returned = _init_fn(cfg_app)(1, None, None)
        assert len(returned) == declared, (
            f"initialize_form_from_config declares {declared} Outputs but its "
            f"empty-config path returns {len(returned)} values; Dash raises on "
            "the mismatch when app-config and the draft are both empty"
        )


class TestA2FailedApplyFeedback:
    def test_validation_error_does_not_open_the_success_alert(self, cfg_app, tmp_path):
        inbox, db = _valid_paths(tmp_path)
        config = {"data_dir": str(tmp_path), "nanopore_output_directory": inbox, "kraken_db": db}
        _cfg, _label, toast, alert_open, snapshot, modified = _apply(cfg_app)(
            config, nanopore_dir=inbox, kraken_db=db, validation_identity=120,
        )
        assert toast["color"] == "danger"
        assert alert_open is not True, (
            "a rejected Apply must not open the green 'changes have been "
            "applied' alert beside the red validation toast"
        )
        assert snapshot is no_update and modified is no_update, (
            "a rejected Apply must leave the dirty baseline and badge alone (A3)"
        )


class TestA3SnapshotRebaseIsGatedOnSuccess:
    def test_only_the_validating_callback_writes_the_snapshot_on_apply(self, cfg_app):
        """A click-only callback cannot tell a rejected Apply from an accepted
        one, so whichever callback rebases the snapshot on the Apply click
        must be the one that validates (it writes app-config)."""
        for cb_id, spec in cfg_app.callback_map.items():
            if "saved-config-snapshot" not in cb_id:
                continue
            ids = [str(i.get("id")) for i in spec.get("inputs", [])]
            if "apply-config-button" in ids:
                assert "app-config" in cb_id, (
                    "a click-driven snapshot rebase clears the Modified badge "
                    "on a rejected Apply"
                )


class TestA4DefaultsCoverEveryFormKey:
    def test_untouched_form_is_not_dirty_against_defaults(self, tmp_path):
        defaults = _defaults(tmp_path)
        form = {
            "kraken_memory_mapping": True,
            "kraken2_confidence": 0.0,
            "kraken2_minimum_hit_groups": 0,
        }
        assert not config_form_dirty(defaults, form=form), (
            "a form initialised from the defaults reads Modified before any "
            "edit: these keys are absent from create_default_config and the "
            "dirty check compares the widget value to None"
        )


class TestA5FormLoaderFallbacksMatchDefaults:
    """For every registry field, loading a config that LACKS the key must show
    the same value as loading the full default config. A divergent fallback
    (min_reads_for_validation: 10 in the config, 50 in the loader) makes the
    form show one number and the running app use another until Apply."""

    def test_each_missing_key_falls_back_to_the_default_value(self, cfg_app, tmp_path):
        defaults = _defaults(tmp_path)
        init = _init_fn(cfg_app)
        full = init(1, dict(defaults), None)
        widget_index = _init_index(cfg_app)
        key_for_widget = {
            "min-reads-for-validation-input": "min_reads_for_validation",
            "analysis-name-input": "analysis_name",
            "cores-input": "max_cpus",
            "max-file-age-input": "max_file_age_minutes",
            "min-reads-per-level-input": "default_reads_per_level",
            "update-interval-input": "update_interval_seconds",
            "realtime-timeout-minutes-input": "realtime_timeout_minutes",
            "e-value-cutoff-input": "e_val_cutoff",
            "minimap2-min-mapq-input": "minimap2_min_mapq",
            "validation-identity-input": "validation_identity_threshold",
            "chopper-minlength-input": "chopper_minlength",
            "chopper-quality-input": "chopper_quality",
            "filtlong-minlength-input": "filtlong_min_length",
            "gui-port-input": "gui_port",
            "validation-method-input": "validation_method",
            "qc-tool-input": "qc_tool",
            "assembler-input": "assembler",
            "sample-handling-input": "sample_handling",
            "processing-mode-input": "processing_mode",
        }
        divergent = {}
        for widget, key in key_for_widget.items():
            assert key in defaults, f"{key} missing from create_default_config"
            partial = dict(defaults)
            del partial[key]
            got = init(1, partial, None)[widget_index[widget]]
            if got != full[widget_index[widget]]:
                divergent[key] = (full[widget_index[widget]], got)
        assert not divergent, f"loader fallback differs from the default: {divergent}"


class TestA7ResetRebasesTheSnapshot:
    def test_some_callback_on_reset_writes_the_snapshot(self, cfg_app):
        writers = [
            cb_id for cb_id, spec in cfg_app.callback_map.items()
            if "saved-config-snapshot" in cb_id
            and any("reset-config-confirm" in str(i.get("id")) for i in spec.get("inputs", []))
        ]
        assert writers, (
            "Reset writes defaults to app-config but leaves saved-config-snapshot "
            "on the pre-reset config, so the next edit is compared against the "
            "wrong baseline"
        )


class TestA9CoresField:
    """The CPU Cores field used to write pipeline_cores (never read by the
    launcher), validation_cores and blast_cores (cpu pins on process names
    nanometanf does not have). It is now nanometanf's --max_cpus."""

    def test_cores_field_reaches_the_launch_as_max_cpus(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path, processing_mode="batch",
                                  sample_handling="per_file", max_cpus=3)
        params = create_nextflow_params(cfg)
        assert params.get("max_cpus") == 3

    def test_empty_cores_field_is_omitted(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path, processing_mode="batch",
                                  sample_handling="per_file", max_cpus=None)
        assert "max_cpus" not in create_nextflow_params(cfg)

    def test_custom_config_names_only_real_processes(self):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_config
        text = create_nextflow_config({"pipeline_profile": "conda"})
        for ghost in ("BLAST_BLASTN", "EXTRACT_VALIDATION_SEQS"):
            assert ghost not in text, f"{ghost} is not a nanometanf process"

    def test_form_loader_reads_back_the_key_the_widget_writes(self, cfg_app, tmp_path):
        defaults = _defaults(tmp_path)
        idx = _init_index(cfg_app)["cores-input"]
        shown = _init_fn(cfg_app)(1, {**defaults, "max_cpus": 8}, None)[idx]
        assert shown in (8, "8")
        assert _init_fn(cfg_app)(1, dict(defaults), None)[idx] == ""


class TestA10HitGroupsBound:
    def test_negative_hit_groups_is_rejected(self, tmp_path):
        inbox, db = _valid_paths(tmp_path)
        by_name = {kw: None for _, kw in CONFIG_FORM_FIELDS}
        by_name.update(nanopore_dir=inbox, kraken_db=db, kraken2_hitgroups=-5)
        _cfg, errors = build_config_from_form({"data_dir": str(tmp_path)}, **by_name)
        assert any("hit group" in e.lower() for e in errors), errors

    def test_non_numeric_hit_groups_does_not_raise(self, tmp_path):
        inbox, db = _valid_paths(tmp_path)
        by_name = {kw: None for _, kw in CONFIG_FORM_FIELDS}
        by_name.update(nanopore_dir=inbox, kraken_db=db, kraken2_hitgroups="abc")
        _cfg, errors = build_config_from_form({"data_dir": str(tmp_path)}, **by_name)
        assert errors


class TestA11DeadCode:
    def test_fastq_input_dir_is_not_advertised(self):
        src = (PKG / "core" / "config" / "parameter_mapping.py").read_text()
        assert "fastq_input_dir" not in src, (
            "fastq_input_dir is validated and named in launch-gate error text "
            "but is never emitted and does not exist in nanometanf"
        )

    def test_remove_temp_files_is_gone_from_the_dirty_check(self):
        src = inspect.getsource(config_form_dirty)
        assert "remove_temp_files" not in src


# ---- B. batch mode -----------------------------------------------------------


class TestB1RealtimeOnlyFieldsSaySo:
    @pytest.mark.parametrize("cid", [
        "realtime-timeout-minutes-input",
        "max-file-age-input", "kraken2-incremental-input",
    ])
    def test_help_text_names_the_mode(self, cid):
        src = (PKG / "app" / "components" / "config_form.py").read_text()
        start = src.index(f'id="{cid}"')
        block = src[max(0, start - 600): start + 900]
        assert re.search(r"real-?time|live mode|live sequencing", block, re.I), (
            f"{cid} is dropped from the launch in batch mode; its help text "
            "does not say the field applies to real-time only"
        )


class TestB2PrioritySamplesNotSentInBatch:
    def test_batch_launch_omits_priority_samples(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path, processing_mode="batch")
        with patch("nanometa_live.core.config.parameter_mapping.get_validation_species",
                   return_value=(["4005020", "562"], {})):
            params = create_nextflow_params(cfg)
        assert "priority_samples" not in params, (
            "priority_samples is only read by the real-time monitoring subworkflow"
        )


# ---- C. real-time mode -------------------------------------------------------


@pytest.fixture
def base_config_factory():
    def make(tmp_path, **over):
        inbox = tmp_path / "input"
        inbox.mkdir(exist_ok=True)
        (inbox / "s1.fastq.gz").write_bytes(b"@r\nACGT\n+\n!!!!\n")
        results = tmp_path / "results"
        results.mkdir(exist_ok=True)
        cfg = {
            "nanopore_output_directory": str(inbox),
            "results_output_directory": str(results),
            "kraken_db": str(tmp_path / "db"),
            "processing_mode": "realtime",
            "sample_handling": "by_barcode",
            "analysis_name": "r5",
            "blast_validation": False,
        }
        cfg.update(over)
        return cfg
    return make


class TestC4TimeoutZero:
    def test_zero_timeout_is_not_sent_verbatim(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path, realtime_timeout_minutes=0)
        params = create_nextflow_params(cfg)
        assert params.get("realtime_timeout_minutes") != 0, (
            "nf-schema rejects realtime_timeout_minutes=0 (minimum 1) at launch "
            "while the GUI countdown reads 0 as 'no timeout'"
        )


class TestC5GracePeriodReachesThePipeline:
    def test_configured_grace_period_is_sent(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path, realtime_processing_grace_period=1)
        params = create_nextflow_params(cfg)
        assert params.get("realtime_processing_grace_period") == 1, (
            "the GUI auto-stop chip counts timeout + this grace period but the "
            "pipeline receives only the timeout and applies its own default (5)"
        )


class TestC6PrioritySamplesAreSampleIds:
    def test_priority_samples_do_not_carry_taxids(self, tmp_path, base_config_factory):
        cfg = base_config_factory(tmp_path)
        with patch("nanometa_live.core.config.parameter_mapping.get_validation_species",
                   return_value=(["4005020", "562"], {})):
            params = create_nextflow_params(cfg)
        ps = params.get("priority_samples") or []
        assert not any(str(p).isdigit() for p in ps), (
            "nanometanf matches priority_samples against sample ids with "
            "contains()/matches(); taxids never match a FASTQ stem and each "
            "one is evaluated as a regex"
        )
