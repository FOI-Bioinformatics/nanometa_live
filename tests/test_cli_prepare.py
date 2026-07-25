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


class TestVerifyDispatch:
    def test_verify_routes_to_verify_handler(self):
        with patch.object(cli, "_verify") as handler, \
             patch("sys.argv", [
                 "nanometa-prepare", "verify", "--bundle", "b.tar.gz"]):
            main()
        args = handler.call_args[0][0]
        assert args.bundle == "b.tar.gz"
        assert args.db is None

    def test_verify_requires_bundle(self):
        with patch("sys.argv", ["nanometa-prepare", "verify"]):
            with pytest.raises(SystemExit):
                main()

    def test_verify_does_not_create_data_dirs(self):
        """verify must not touch the machine -- that is its whole point."""
        with patch.object(cli, "_verify"), \
             patch.object(cli, "_ensure_data_dirs") as ensure, \
             patch("sys.argv", [
                 "nanometa-prepare", "verify", "--bundle", "b.tar.gz"]):
            main()
        ensure.assert_not_called()

    def test_other_subcommands_do_create_data_dirs(self):
        with patch.object(cli, "_check"), \
             patch.object(cli, "_ensure_data_dirs") as ensure, \
             patch("sys.argv", [
                 "nanometa-prepare", "check", "--config", "cfg.yaml"]):
            main()
        ensure.assert_called_once()


class TestVerifyHandler:
    def test_missing_bundle_exits_nonzero(self, capsys):
        args = _Args(bundle="/no/such/bundle.tar.gz", db=None, home=None)
        with pytest.raises(SystemExit) as exc:
            cli._verify(args)
        assert exc.value.code == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_clean_bundle_exits_zero(self, capsys, tmp_path):
        bundle = tmp_path / "b.tar.gz"
        bundle.write_bytes(b"x")
        fake = {
            "success": True, "warnings": [], "blockers": [],
            "manifest": {"created": "2026-01-01", "creator": "op",
                         "checksums": {"a": "b"},
                         "build_platform": {"system": "Linux",
                                            "machine": "x86_64"}},
        }
        args = _Args(bundle=str(bundle), db=None, home=None)
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager"
            ".verify_bundle",
            return_value=fake,
        ):
            with pytest.raises(SystemExit) as exc:
                cli._verify(args)
        out = capsys.readouterr().out
        assert exc.value.code == 0
        assert "Bundle verified" in out
        assert "Linux/x86_64" in out

    def test_failed_bundle_lists_mismatches_and_exits_one(self, capsys, tmp_path):
        bundle = tmp_path / "b.tar.gz"
        bundle.write_bytes(b"x")
        fake = {
            "success": False,
            "warnings": ["2 file(s) failed checksum verification"],
            "blockers": ["2 file(s) failed checksum verification"],
            "checksum_mismatches": ["genomes/1.fasta", "blast/2.fasta"],
            "manifest": {"created": "2026-01-01", "checksums": {}},
        }
        args = _Args(bundle=str(bundle), db=None, home=None)
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager"
            ".verify_bundle",
            return_value=fake,
        ):
            with pytest.raises(SystemExit) as exc:
                cli._verify(args)
        out = capsys.readouterr().out
        assert exc.value.code == 1
        assert "genomes/1.fasta" in out
        assert "verification FAILED" in out


class TestDoctorHandler:
    """`check` needs a config; doctor answers 'is this fresh install sane?'."""

    def _run(self, tmp_path, *, nextflow, pipeline=None, make_home=True):
        args = _Args(home=str(tmp_path / "home"), pipeline=pipeline)
        if make_home:
            # main() runs _ensure_data_dirs before dispatch; the doctor's
            # data-directory check reports on that result.
            cli._ensure_data_dirs(args)

        def fake_which(name):
            if name == "nextflow":
                return "/usr/bin/nextflow" if nextflow else None
            if name in ("conda", "mamba"):
                return "/usr/bin/conda"
            return None

        with patch.object(cli.shutil, "which", side_effect=fake_which), \
             patch(
                 "nanometa_live.core.workflow.bundle_manager"
                 "._get_nextflow_version",
                 return_value="26.04.0 build 1",
             ):
            with pytest.raises(SystemExit) as exc:
                cli._doctor(args)
        return exc.value.code

    def test_missing_nextflow_fails(self, tmp_path, capsys):
        code = self._run(tmp_path, nextflow=False)
        out = capsys.readouterr().out
        assert code == 1
        assert "Nextflow" in out
        assert "not found on PATH" in out
        assert "Install is not ready" in out

    def test_healthy_install_passes(self, tmp_path, capsys):
        (tmp_path / "home").mkdir(parents=True)
        code = self._run(tmp_path, nextflow=True)
        out = capsys.readouterr().out
        assert code == 0, out
        assert "Install looks sane" in out

    def test_pipeline_checkout_without_main_nf_fails(self, tmp_path, capsys):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        code = self._run(tmp_path, nextflow=True, pipeline=str(checkout))
        out = capsys.readouterr().out
        assert code == 1
        assert "main.nf" in out

    def test_pipeline_checkout_with_main_nf_passes(self, tmp_path, capsys):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / "main.nf").write_text("workflow {}\n")
        code = self._run(tmp_path, nextflow=True, pipeline=str(checkout))
        assert code == 0, capsys.readouterr().out

    def test_doctor_requires_no_config(self):
        """The whole point: it parses without --config."""
        with patch.object(cli, "_doctor") as handler, \
             patch.object(cli, "_ensure_data_dirs"), \
             patch("sys.argv", ["nanometa-prepare", "doctor"]):
            main()
        handler.assert_called_once()


class TestEnsureDataDirs:
    def test_creates_layout_under_home(self, tmp_path):
        home = tmp_path / "fresh"
        cli._ensure_data_dirs(_Args(home=str(home)))
        assert (home / "cache").is_dir()
        assert (home / "genomes").is_dir()
        assert (home / "blast").is_dir()
        assert (home / "logs").is_dir()

    def test_falls_back_to_env_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "envhome"))
        cli._ensure_data_dirs(_Args(home=None))
        assert (tmp_path / "envhome" / "cache").is_dir()

    def test_unwritable_home_warns_without_raising(self, tmp_path, capsys):
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("regular file")
        cli._ensure_data_dirs(_Args(home=str(blocker / "sub")))
        assert "Could not create" in capsys.readouterr().err
