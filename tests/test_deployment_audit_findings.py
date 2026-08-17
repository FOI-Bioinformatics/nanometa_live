"""Deployment findings from the 2026-08-17 audit (G1-G4, G6, G8).

- G2: ``verify_bundle`` did not check that the bundle can actually run a
  pipeline offline (pipeline_source/main.nf present, plugins bundled) --
  both checks lived only in the import path, so the advertised dry run
  blessed bundles the import would flag.
- G3: ``nanometa-prepare verify`` told the operator "Do not import without
  --force" while the import subcommand defined no ``--force`` flag.
- G6: readiness reported a remote pipeline_source as passed/INFO even with
  offline_mode enabled, although the launch path refuses exactly that.
- G8: plugin bundling read ``~/.nextflow/plugins`` unconditionally,
  ignoring NXF_HOME / NXF_PLUGINS_DIR.
- G1: ``validate_pipeline_source`` had zero production callers; the launch
  path now delegates to it.
"""

import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    _nextflow_plugins_home,
)
from nanometa_live.core.workflow.readiness_checker import (
    ReadinessChecker,
    Severity,
)


def _bundle_with(tmp_path, files):
    """Build a bundle tar.gz holding exactly ``files`` ({relpath: text})."""
    import hashlib
    import json

    staging = tmp_path / "staging"
    staging.mkdir()
    for rel, text in files.items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    checksums = {
        str(f.relative_to(staging)): hashlib.md5(f.read_bytes()).hexdigest()
        for f in staging.rglob("*") if f.is_file()
    }
    manifest = {
        "version": "1.1",
        "created": "2026-01-01T00:00:00",
        "creator": "test",
        "checksums": checksums,
        "tool_versions": {},
        "container_runtime": None,
    }
    (staging / "manifest.json").write_text(json.dumps(manifest))
    bundle = tmp_path / "bundle.tar.gz"
    with tarfile.open(str(bundle), "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(str(item), arcname=item.name)
    return bundle


class TestVerifyRunnableOffline:
    def test_truncated_pipeline_source_is_a_blocker(self, tmp_path):
        bundle = _bundle_with(tmp_path, {
            "pipeline_source/nextflow.config": "// no main.nf",
        })
        report = BundleManager().verify_bundle(str(bundle))
        assert any("main.nf" in b for b in report["blockers"])
        assert not report["success"]

    def test_missing_plugins_is_a_warning(self, tmp_path):
        bundle = _bundle_with(tmp_path, {
            "pipeline_source/main.nf": "workflow {}",
        })
        report = BundleManager().verify_bundle(str(bundle))
        assert any("plugin" in w.lower() for w in report["warnings"])

    def test_complete_bundle_raises_neither(self, tmp_path):
        bundle = _bundle_with(tmp_path, {
            "pipeline_source/main.nf": "workflow {}",
            "nextflow_plugins/nf-schema-2.0.0/ok.txt": "x",
        })
        report = BundleManager().verify_bundle(str(bundle))
        assert not any("main.nf" in b for b in report["blockers"])
        assert not any("plugin" in w.lower() for w in report["warnings"])


class TestCliForceFlag:
    def test_import_subparser_accepts_force(self):
        from nanometa_live.cli import prepare

        # Building the parser is enough: parse a canned import invocation.
        import argparse
        import unittest.mock as mock

        with mock.patch.object(
            prepare, "_import_bundle"
        ) as handler, mock.patch(
            "sys.argv",
            ["nanometa-prepare", "import", "--bundle", "b.tar.gz",
             "--db", "/db", "--force"],
        ):
            try:
                prepare.main()
            except SystemExit:
                pass
        assert handler.called
        args = handler.call_args[0][0]
        assert args.force is True


class TestReadinessOfflineRemoteSource:
    def test_offline_remote_source_is_critical(self):
        checker = ReadinessChecker()
        result = checker._check_pipeline_cached(
            {"pipeline_source": "remote:dev", "offline_mode": True}
        )
        assert result.passed is False
        assert result.severity == Severity.CRITICAL

    def test_online_remote_source_still_passes_as_info(self):
        checker = ReadinessChecker()
        result = checker._check_pipeline_cached(
            {"pipeline_source": "remote:dev", "offline_mode": False}
        )
        assert result.passed is True


class TestPluginsHomeHonorsEnv:
    def test_nxf_plugins_dir_wins(self, monkeypatch):
        monkeypatch.setenv("NXF_PLUGINS_DIR", "/opt/nxf/plugins")
        monkeypatch.setenv("NXF_HOME", "/opt/nxf-home")
        assert _nextflow_plugins_home() == Path("/opt/nxf/plugins")

    def test_nxf_home_used_when_set(self, monkeypatch):
        monkeypatch.delenv("NXF_PLUGINS_DIR", raising=False)
        monkeypatch.setenv("NXF_HOME", "/opt/nxf-home")
        assert _nextflow_plugins_home() == Path("/opt/nxf-home/plugins")

    def test_default_is_home_dotnextflow(self, monkeypatch):
        monkeypatch.delenv("NXF_PLUGINS_DIR", raising=False)
        monkeypatch.delenv("NXF_HOME", raising=False)
        assert _nextflow_plugins_home() == Path.home() / ".nextflow" / "plugins"


class TestLaunchDelegatesToValidator:
    def test_setup_refuses_local_source_without_main_nf(self, tmp_path):
        """G1: the launch path now runs the full validator, so a local
        checkout missing main.nf is refused at setup rather than failing
        cryptically at nextflow run."""
        bad_checkout = tmp_path / "checkout"
        bad_checkout.mkdir()
        db = tmp_path / "kraken_db"
        db.mkdir()
        for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (db / name).write_text("x")
        manager = BackendManager(data_dir=str(tmp_path / "data"))
        manager.config = {
            "pipeline_source": str(bad_checkout),
            "kraken_db": str(db),
            "nanopore_output_directory": str(tmp_path),
            "results_output_directory": str(tmp_path / "results"),
        }
        ok, msg = manager.setup_project(manager.config)
        assert ok is False
        assert "main.nf" in msg or "not a" in msg
