"""The ``python -m nanometa_live.app`` entry point must honour --config.

Visualization mode (``--main_dir``) used to build its config dict from
scratch, so passing ``--config`` alongside it discarded the entire YAML --
watchlist, kraken_db, thresholds, negative-control list, everything. The
operator got an unscreened dashboard reading NOT SCREENED with no error,
while believing they had configured biothreat screening.

That is the failure class this project already guards against three ways:
a missing measurement rendered as a negative result. The NOT_SCREENED
verdict kept it amber rather than a false green, but the configuration was
gone either way.

The project's own browser harness (tests/realdata/test_live_server.py)
boots with exactly ``--config X --main_dir Y``, so it was silently
exercising the no-watchlist path -- the opposite of its stated purpose.
"""

from __future__ import annotations

import argparse
import pathlib

import pytest
import yaml

from nanometa_live.app import __main__ as app_main

pytestmark = pytest.mark.unit


def _args(**overrides) -> argparse.Namespace:
    """A parsed-args stand-in with the entry point's defaults."""
    base = dict(
        main_dir=None, config=None, port=8050, host="127.0.0.1",
        debug=False, data_dir=None, project=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def captured_config(monkeypatch):
    """Run _run_visualization_mode far enough to capture the built config.

    ``create_app`` is where the config dict is handed to the application, so
    intercepting it there records exactly what the app would have received.
    Serving is stubbed out so nothing binds a port.
    """
    seen = {}

    def fake_create_app(config, data_dir, backend_manager):
        seen["config"] = config

        class _App:
            def run(self, *a, **kw):
                pass

        return _App()

    monkeypatch.setattr(app_main, "create_app", fake_create_app)
    monkeypatch.setattr(app_main, "BackendManager", lambda *a, **kw: object())
    return seen


def _write_config(tmp_path: pathlib.Path) -> pathlib.Path:
    """A config carrying the settings an operator would expect to survive."""
    path = tmp_path / "operator.yaml"
    path.write_text(yaml.safe_dump({
        "kraken_db": "/some/kraken/db",
        "min_reads_for_validation": 77,
        "watchlist": {"enabled": True, "builtin": ["cdc_bioterrorism"]},
        "negative_control_samples": ["barcode99"],
    }))
    return path


class TestConfigSurvivesVisualizationMode:
    def test_the_configured_watchlist_reaches_the_app(
        self, tmp_path, captured_config, monkeypatch
    ):
        """The watchlist is the setting whose loss produces a false verdict."""
        results = tmp_path / "results"
        results.mkdir()
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        app_main._run_visualization_mode(
            _args(main_dir=str(results), config=str(_write_config(tmp_path)))
        )

        config = captured_config["config"]
        assert config.get("watchlist") == {
            "enabled": True, "builtin": ["cdc_bioterrorism"],
        }, (
            "the --config watchlist was dropped; the dashboard will report "
            "NOT SCREENED while the operator believes screening is armed"
        )

    def test_other_configured_settings_also_survive(
        self, tmp_path, captured_config, monkeypatch
    ):
        """The whole dict was rebuilt, so the loss was never watchlist-only."""
        results = tmp_path / "results"
        results.mkdir()
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        app_main._run_visualization_mode(
            _args(main_dir=str(results), config=str(_write_config(tmp_path)))
        )

        config = captured_config["config"]
        assert config.get("kraken_db") == "/some/kraken/db"
        assert config.get("min_reads_for_validation") == 77
        assert config.get("negative_control_samples") == ["barcode99"]

    def test_main_dir_still_wins_over_a_stale_results_directory(
        self, tmp_path, captured_config, monkeypatch
    ):
        """--main_dir is the explicit instruction and must override the YAML.

        A loaded config routinely carries results_output_directory from a
        previous run. If that won, the operator would be pointed at the old
        run's output while believing they had selected the new one -- the same
        class of silent misdirection, one layer down.
        """
        results = tmp_path / "results"
        results.mkdir()
        stale = tmp_path / "previous_run"
        stale.mkdir()
        config_path = tmp_path / "stale.yaml"
        config_path.write_text(yaml.safe_dump({
            "results_output_directory": str(stale),
            "main_dir": str(stale),
        }))
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        app_main._run_visualization_mode(
            _args(main_dir=str(results), config=str(config_path))
        )

        config = captured_config["config"]
        assert config["main_dir"] == str(results)
        assert config["results_output_directory"] == str(results)

    def test_visualization_only_is_still_set(
        self, tmp_path, captured_config, monkeypatch
    ):
        """--main_dir means "do not run a pipeline", config or no config."""
        results = tmp_path / "results"
        results.mkdir()
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        app_main._run_visualization_mode(
            _args(main_dir=str(results), config=str(_write_config(tmp_path)))
        )

        assert captured_config["config"]["visualization_only"] is True

    def test_without_config_the_previous_behaviour_is_unchanged(
        self, tmp_path, captured_config, monkeypatch
    ):
        """--main_dir alone is a documented, supported invocation."""
        results = tmp_path / "results"
        results.mkdir()
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        app_main._run_visualization_mode(_args(main_dir=str(results)))

        config = captured_config["config"]
        assert config["main_dir"] == str(results)
        assert config["visualization_only"] is True
        assert "watchlist" not in config


class TestAnUnreadableConfigIsNotSwallowed:
    def test_a_missing_config_file_exits_rather_than_starting_unconfigured(
        self, tmp_path, captured_config, monkeypatch
    ):
        """Failing loudly is the point of this fix.

        Starting anyway with an empty config would reproduce the original
        defect exactly: a dashboard that looks configured and is not. The
        operator asked for a config; if it cannot be honoured, say so.
        """
        results = tmp_path / "results"
        results.mkdir()
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data"))

        with pytest.raises(SystemExit) as exc:
            app_main._run_visualization_mode(
                _args(main_dir=str(results), config=str(tmp_path / "nope.yaml"))
            )

        assert exc.value.code != 0
        assert "config" not in captured_config, (
            "the app was started despite an unreadable --config"
        )
