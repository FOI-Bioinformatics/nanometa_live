"""
Unit tests for app/tabs/config_tab_helpers.py (extracted from config_tab.py).

_build_config_list_items renders saved-config metadata into ListGroup rows, with
the auto-saved last-session.yaml shown specially (renamed, no delete button).
"""

import inspect

import pytest
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.config_tab_helpers import (
    _build_config_list_items,
    build_config_from_form,
    config_form_dirty,
    _pipeline_source_from_form,
    _validate_nanopore_dir,
)

pytestmark = pytest.mark.unit


class TestValidateNanoporeDir:
    """Operator feedback: a realtime config with an empty/barcodeless input
    dir must save cleanly -- the dir is watched (watchPath) and fills during
    the run -- while batch keeps the input-content checks."""

    def test_realtime_empty_dir_no_error(self, tmp_path):
        empty = tmp_path / "watched"
        empty.mkdir()
        assert _validate_nanopore_dir(str(empty), "by_barcode", "realtime") == []

    def test_realtime_single_sample_empty_dir_no_error(self, tmp_path):
        empty = tmp_path / "watched"
        empty.mkdir()
        assert _validate_nanopore_dir(str(empty), "single_sample", "realtime") == []

    def test_batch_by_barcode_empty_dir_still_errors(self, tmp_path):
        empty = tmp_path / "in"
        empty.mkdir()
        errors = _validate_nanopore_dir(str(empty), "by_barcode", "batch")
        assert errors and "by-barcode" in errors[0].lower()

    def test_missing_dir_errors_in_any_mode(self, tmp_path):
        missing = str(tmp_path / "nope")
        assert _validate_nanopore_dir(missing, "by_barcode", "realtime")
        assert _validate_nanopore_dir(missing, "by_barcode", "batch")


class TestConfigFormDirty:
    """The Modified-badge detector must flag every operator-editable field,
    including the ones the prior inline detector silently ignored."""

    def _form(self, **overrides):
        base = {
            "analysis_name": "Run",
            "nanopore_output_directory": "/data/in",
            "kraken_db": "/db",
            "results_dir_override": "",
            "update_interval_seconds": 10,
            "processing_mode": "batch",
            "sample_handling": "by_barcode",
            "qc_tool": "chopper",
            "skip_nanoplot": False,
            "pipeline_profile": "conda",
            "pipeline_source": "remote:dev",
            "max_file_age_minutes": 1000,
            "min_reads_for_validation": 50,
        }
        base.update(overrides)
        return base

    def test_unchanged_is_not_dirty(self):
        form = self._form()
        snapshot = dict(form)
        assert config_form_dirty(snapshot, form=form) is False

    def test_no_snapshot_is_not_dirty(self):
        assert config_form_dirty(None, form=self._form()) is False

    @pytest.mark.parametrize("field,new_value", [
        ("processing_mode", "realtime"),       # was never watched
        ("sample_handling", "single_sample"),  # was never watched
        ("pipeline_profile", "docker"),        # was never watched
        ("max_file_age_minutes", 5),           # was never watched
        ("min_reads_for_validation", 99),      # was never watched
        ("qc_tool", "fastp"),                  # watched but never compared
        ("skip_nanoplot", True),               # watched but never compared
    ])
    def test_previously_missed_fields_now_flag_dirty(self, field, new_value):
        snapshot = self._form()
        form = self._form(**{field: new_value})
        assert config_form_dirty(snapshot, form=form) is True

    def test_pipeline_source_change_flags_dirty(self):
        snapshot = self._form(pipeline_source="remote:dev")
        form = self._form(pipeline_source="remote:master")
        assert config_form_dirty(snapshot, form=form) is True

    def test_bool_string_in_snapshot_normalized(self):
        # A legacy snapshot storing "yes"/"true" must compare equal to the
        # boolean the form now carries -- no spurious dirty flag.
        snapshot = self._form(skip_nanoplot="true")
        form = self._form(skip_nanoplot=True)
        assert config_form_dirty(snapshot, form=form) is False


class TestPipelineSourceFromForm:
    def test_remote_branch(self):
        assert _pipeline_source_from_form("remote", "dev", "") == "remote:dev"

    def test_remote_default_branch(self):
        assert _pipeline_source_from_form("remote", "", "") == "remote:master"

    def test_local_path_normalised(self):
        out = _pipeline_source_from_form("local", "", "/tmp/pipe")
        assert out == "/tmp/pipe"

    def test_local_without_path_empty(self):
        assert _pipeline_source_from_form("local", "", "") == ""


def _build(**overrides):
    """Call build_config_from_form with every form field None except overrides."""
    params = [
        p for p in inspect.signature(build_config_from_form).parameters
        if p != "current_config"
    ]
    kwargs = {p: None for p in params}
    kwargs.update(overrides)
    return build_config_from_form({"data_dir": "/tmp/nm_cfg_helper_test"}, **kwargs)


class TestBuildConfigFromForm:
    def test_missing_required_fields_return_errors_and_no_config(self):
        config, errors = _build()
        assert config is None
        joined = "\n".join(errors)
        assert "Nanopore Sequence Data Folder (input) is required" in joined
        assert "Kraken2 Database is required" in joined

    def test_numeric_bound_violation_reported(self):
        # gui_port below the 1024 floor is rejected even though the required
        # path fields are also missing -- errors accumulate into one list.
        _config, errors = _build(gui_port=80)
        assert any("GUI Port must be between 1024-65535" in e for e in errors)

    def test_returns_two_tuple_shape(self):
        result = _build()
        assert isinstance(result, tuple) and len(result) == 2


class TestBuildConfigListItems:
    def test_empty(self):
        assert _build_config_list_items([]) == []

    def test_regular_config_has_load_and_delete(self):
        items = _build_config_list_items([
            {"name": "My Run", "filename": "my_run.yaml",
             "timestamp": "2026-05-30T10:00:00"},
        ])
        assert len(items) == 1
        text = str(items[0])
        assert "My Run" in text
        assert "load-config-item" in text
        assert "delete-config-item" in text  # regular config is deletable
        assert "2026-05-30 10:00:00" in text  # timestamp formatted

    def test_autosave_renamed_and_not_deletable(self):
        items = _build_config_list_items([
            {"name": "whatever", "filename": "last-session.yaml",
             "timestamp": "2026-05-30T10:00:00"},
        ])
        text = str(items[0])
        assert "Last Session (auto-saved)" in text
        assert "delete-config-item" not in text  # autosave cannot be deleted

    def test_bad_timestamp_passed_through(self):
        items = _build_config_list_items([
            {"name": "x", "filename": "x.yaml", "timestamp": "not-a-date"},
        ])
        assert "not-a-date" in str(items[0])

    def test_indices_increment(self):
        items = _build_config_list_items([
            {"name": "a", "filename": "a.yaml"},
            {"name": "b", "filename": "b.yaml"},
        ])
        assert '"index": 0' in str(items[0]) or "'index': 0" in str(items[0])
        assert '"index": 1' in str(items[1]) or "'index': 1" in str(items[1])
