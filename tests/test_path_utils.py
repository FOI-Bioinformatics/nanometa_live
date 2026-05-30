"""
Unit tests for core/utils/path_utils.py.

This is the single normalisation point for config-managed filesystem paths
(CLAUDE.md "Path lifecycle"). The contract has three deliberate carve-outs that
must not regress: sentinel identifiers (remote:/URL/git@) and bundle-relative
"./" paths are returned unchanged, while ordinary paths are stripped,
~-expanded and absolutised.
"""

import os

import pytest

from nanometa_live.core.utils.path_utils import (
    PATH_CONFIG_KEYS,
    normalise_config_paths,
    normalise_path,
    report_missing_paths,
)


class TestNormalisePath:
    def test_none_and_empty_return_empty_string(self):
        assert normalise_path(None) == ""
        assert normalise_path("") == ""
        assert normalise_path("   ") == ""

    def test_plain_path_is_stripped_and_absolutised(self):
        result = normalise_path("  /tmp/some/dir  ")
        assert result == "/tmp/some/dir"
        assert os.path.isabs(result)

    def test_relative_path_resolved_to_absolute(self):
        result = normalise_path("data/kraken_db")
        assert os.path.isabs(result)
        assert result.endswith("data/kraken_db")

    def test_tilde_is_expanded(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/operator")
        result = normalise_path("~/kraken_db")
        assert "~" not in result
        assert result == "/home/operator/kraken_db"

    @pytest.mark.parametrize(
        "sentinel",
        [
            "remote:dev",
            "remote:master",
            "https://github.com/FOI-Bioinformatics/nanometanf",
            "http://example.com/repo",
            "git@github.com:FOI-Bioinformatics/nanometanf.git",
        ],
    )
    def test_sentinel_identifiers_returned_unchanged(self, sentinel):
        # Surrounding whitespace is still trimmed, but the value is not resolved.
        assert normalise_path(f"  {sentinel}  ") == sentinel

    @pytest.mark.parametrize("rel", ["./pipeline_source", "../nextflow_plugins"])
    def test_bundle_relative_paths_preserved(self, rel):
        assert normalise_path(rel) == rel


class TestNormaliseConfigPaths:
    def test_rewrites_only_changed_path_keys(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/operator")
        config = {
            "kraken_db": "~/db",                 # rewritten
            "results_output_directory": "/abs/out",  # already canonical
            "pipeline_source": "remote:dev",     # sentinel, unchanged
            "processing_mode": "batch",          # not a path key
        }
        rewritten = normalise_config_paths(config)
        assert rewritten == ["kraken_db"]
        assert config["kraken_db"] == "/home/operator/db"
        assert config["results_output_directory"] == "/abs/out"
        assert config["pipeline_source"] == "remote:dev"
        assert config["processing_mode"] == "batch"

    def test_non_string_values_left_untouched(self):
        config = {"data_dir": 123, "kraken_db": ["not", "a", "path"]}
        rewritten = normalise_config_paths(config)
        assert rewritten == []
        assert config["data_dir"] == 123

    def test_absent_keys_skipped(self):
        config = {"unrelated": "value"}
        assert normalise_config_paths(config) == []

    def test_every_path_key_is_recognised(self):
        # Guards against a path key being added to the tuple but a typo making
        # it unreachable.
        assert "kraken_db" in PATH_CONFIG_KEYS
        assert "nanopore_output_directory" in PATH_CONFIG_KEYS


class TestReportMissingPaths:
    def test_existing_path_not_reported(self, tmp_path):
        config = {"kraken_db": str(tmp_path)}
        assert report_missing_paths(config) == {}

    def test_missing_path_reported(self, tmp_path):
        missing_dir = str(tmp_path / "gone")
        config = {"kraken_db": missing_dir}
        assert report_missing_paths(config) == {"kraken_db": missing_dir}

    def test_sentinels_and_empty_excluded(self, tmp_path):
        config = {
            "pipeline_source": "remote:dev",
            "kraken_taxonomy": "https://example.com/tax",
            "data_dir": "",
            "main_dir": str(tmp_path / "absent"),
        }
        missing = report_missing_paths(config)
        assert missing == {"main_dir": str(tmp_path / "absent")}

    def test_non_string_excluded(self):
        config = {"data_dir": 42}
        assert report_missing_paths(config) == {}
