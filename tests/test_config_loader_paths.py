"""
Integration tests for ConfigLoader.load_config path handling.

path_utils.py is unit-tested directly in test_path_utils.py. This file exercises
the *loader boundary*: a YAML config read from disk must come back with real
filesystem paths normalised (strip + ~-expand + abspath) while the offline-bundle
sentinels are preserved verbatim. A regression in the sentinel carve-out would
silently break BundleManager's import-rebase, which keys off the exact
"remote:" / URL / git@ / "./pipeline_source" strings.
"""

import os

import pytest

from nanometa_live.core.config.config_loader import ConfigLoader


# The exact sentinel forms the loader must never resolve to a filesystem path.
SENTINELS = [
    "remote:dev",
    "remote:master",
    "https://github.com/FOI-Bioinformatics/nanometanf",
    "http://example.com/repo",
    "git@github.com:FOI-Bioinformatics/nanometanf.git",
    "./pipeline_source",
    "./nextflow_plugins",
]


def _write_config(loader: ConfigLoader, body: dict) -> str:
    """Persist *body* as a minimal YAML config and return its path."""
    return loader.save_config(dict(body), filename="cfg.yaml")


class TestLoadConfigNormalisesRealPaths:
    def test_tilde_path_is_expanded_and_absolutised_on_load(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        loader = ConfigLoader(str(tmp_path / "configs"))
        path = _write_config(loader, {"kraken_db": "~/db"})

        config = loader.load_config(path)

        assert config["kraken_db"] == os.path.join(str(home), "db")
        assert "~" not in config["kraken_db"]
        assert os.path.isabs(config["kraken_db"])

    def test_whitespace_is_stripped_on_load(self, tmp_path):
        loader = ConfigLoader(str(tmp_path / "configs"))
        path = _write_config(loader, {"results_output_directory": "  /abs/out  "})

        config = loader.load_config(path)

        assert config["results_output_directory"] == "/abs/out"

    def test_relative_path_resolved_against_abspath_on_load(self, tmp_path):
        loader = ConfigLoader(str(tmp_path / "configs"))
        # A bare relative path (no "./" prefix, not a sentinel) must absolutise.
        path = _write_config(loader, {"main_dir": "some/results"})

        config = loader.load_config(path)

        assert os.path.isabs(config["main_dir"])
        assert config["main_dir"].endswith(os.path.join("some", "results"))


class TestLoadConfigPreservesSentinels:
    @pytest.mark.parametrize("sentinel", SENTINELS)
    def test_pipeline_source_sentinel_survives_round_trip(self, tmp_path, sentinel):
        loader = ConfigLoader(str(tmp_path / "configs"))
        path = _write_config(loader, {"pipeline_source": sentinel})

        config = loader.load_config(path)

        assert config["pipeline_source"] == sentinel

    def test_real_and_sentinel_keys_coexist_in_one_config(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        loader = ConfigLoader(str(tmp_path / "configs"))
        path = _write_config(
            loader,
            {
                "kraken_db": "~/db",            # real path -> normalised
                "pipeline_source": "remote:dev",  # sentinel -> verbatim
                "processing_mode": "realtime",    # non-path key -> verbatim
            },
        )

        config = loader.load_config(path)

        assert config["kraken_db"] == os.path.join(str(home), "db")
        assert config["pipeline_source"] == "remote:dev"
        assert config["processing_mode"] == "realtime"


class TestLoadConfigReportsMissingPaths:
    def test_missing_path_logged_but_load_succeeds(self, tmp_path, caplog):
        loader = ConfigLoader(str(tmp_path / "configs"))
        missing = str(tmp_path / "gone")
        existing = tmp_path / "present"
        existing.mkdir()
        path = _write_config(
            loader,
            {
                "kraken_db": missing,            # set but absent -> reported
                "results_output_directory": str(existing),  # exists -> silent
                "pipeline_source": "remote:dev",  # sentinel -> excluded
            },
        )

        with caplog.at_level("WARNING"):
            config = loader.load_config(path)

        # Load is non-fatal: the GUI must still come up so the operator can fix it.
        assert config["kraken_db"] == missing
        warnings = " ".join(r.getMessage() for r in caplog.records)
        assert missing in warnings
        assert "kraken_db" in warnings
        # The existing path and the sentinel must not be flagged as missing.
        assert str(existing) not in warnings
        assert "remote:dev" not in warnings
