"""
Unit tests for nanometa_live/cli/prepare.py.

The CLI orchestrates offline-deployment prep. The subcommand handlers do heavy
filesystem/pipeline work, so tests exercise the parts that are safe in
isolation: the progress-bar formatter and the argparse dispatch in main()
(verifying subcommand routing, argument capture, and required-arg enforcement)
with the handlers mocked so nothing actually runs.
"""

from unittest.mock import patch

import pytest

from nanometa_live.cli import prepare as cli
from nanometa_live.cli.prepare import _progress_bar, main


class TestProgressBar:
    def test_zero_percent_is_all_empty(self):
        bar = _progress_bar(0)
        assert bar.startswith("[")
        assert "#" not in bar
        assert "0.0%" in bar

    def test_full_is_all_filled(self):
        bar = _progress_bar(100, width=10)
        assert "#" * 10 in bar
        assert "100.0%" in bar

    def test_half_width(self):
        bar = _progress_bar(50, width=10)
        assert bar.count("#") == 5
        assert bar.count("-") == 5


class TestMainDispatch:
    def test_check_routes_to_check_handler(self):
        with patch.object(cli, "_check") as handler, \
             patch("sys.argv", ["nanometa-prepare", "check", "--config", "cfg.yaml"]):
            main()
        handler.assert_called_once()
        args = handler.call_args[0][0]
        assert args.config == "cfg.yaml"

    def test_deploy_captures_db_override(self):
        with patch.object(cli, "_deploy") as handler, \
             patch("sys.argv", [
                 "nanometa-prepare", "deploy",
                 "--config", "cfg.yaml", "--db", "/data/db",
             ]):
            main()
        args = handler.call_args[0][0]
        assert args.config == "cfg.yaml"
        assert args.db == "/data/db"

    def test_import_requires_db(self):
        with patch("sys.argv", ["nanometa-prepare", "import", "--bundle", "b.tar.gz"]):
            with pytest.raises(SystemExit):
                main()

    def test_missing_subcommand_errors(self):
        with patch("sys.argv", ["nanometa-prepare"]):
            with pytest.raises(SystemExit):
                main()

    def test_check_requires_config(self):
        with patch("sys.argv", ["nanometa-prepare", "check"]):
            with pytest.raises(SystemExit):
                main()


class _Args:
    """Lightweight argparse.Namespace stand-in for handler tests."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TestCheckHandler:
    """Exercise the _check handler body (was uncovered -- dispatch tests mock it)."""

    def test_missing_config_exits_nonzero(self, capsys):
        args = _Args(config="/no/such/config.yaml", db=None, home=None)
        with pytest.raises(SystemExit) as exc:
            cli._check(args)
        assert exc.value.code == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_runs_readiness_and_reports_not_ready(self, capsys, tmp_path):
        # A minimal config with no Kraken2 DB -> readiness is NOT ready -> exit 1.
        cfg = tmp_path / "config.yaml"
        cfg.write_text("analysis_name: t\nkraken_db: ''\n")
        args = _Args(config=str(cfg), db=None, home=str(tmp_path / "home"))
        with pytest.raises(SystemExit) as exc:
            cli._check(args)
        out = capsys.readouterr().out
        assert "Readiness Check" in out
        assert "checks passed" in out
        assert exc.value.code == 1

    def test_db_override_is_applied(self, capsys, tmp_path):
        # The --db override should be injected into the config the checker sees.
        cfg = tmp_path / "config.yaml"
        cfg.write_text("analysis_name: t\n")
        args = _Args(config=str(cfg), db="/tmp/fake_kraken_db", home=str(tmp_path / "h"))
        captured = {}

        class _Report:
            checks = []
            ready = False
            def summary(self):
                return {"passed": 0, "total": 0, "critical_failures": 0, "warnings": 0}

        class _Checker:
            def check_readiness(self, config, home):
                captured["kraken_db"] = config.get("kraken_db")
                return _Report()

        with patch(
            "nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
            _Checker,
        ):
            with pytest.raises(SystemExit):
                cli._check(args)
        assert captured["kraken_db"] == "/tmp/fake_kraken_db"
