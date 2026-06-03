"""Tests for the deployment audit remediations.

Covers BundleManager import guards (manifest-version, platform-mismatch
hard-fail, AppleDouble exclusion), the export size/free-space preflight, and the
size helpers.
"""

import json
import tarfile

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    estimate_bundle_size,
    human_size,
    _file_md5,
)

pytestmark = pytest.mark.unit


def _make_bundle(tmp_path, **manifest_extra):
    """Build a minimal valid bundle whose manifest carries manifest_extra."""
    staging = tmp_path / "staging"
    staging.mkdir()
    genomes = staging / "genomes"
    genomes.mkdir()
    (genomes / "12345.fasta").write_text(">seq1\nATCG\n")

    checksums = {
        str(f.relative_to(staging)): _file_md5(f)
        for f in staging.rglob("*") if f.is_file()
    }
    manifest = {
        "version": "1.1",
        "created": "2026-01-01T00:00:00",
        "creator": "test",
        "checksums": checksums,
    }
    manifest.update(manifest_extra)
    (staging / "manifest.json").write_text(json.dumps(manifest))

    bundle = tmp_path / "bundle.tar.gz"
    with tarfile.open(str(bundle), "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(str(item), arcname=item.name)
    return bundle


class TestManifestVersionGuard:
    def test_unsupported_version_aborts(self, tmp_path):
        bundle = _make_bundle(tmp_path, version="9.9")
        home = tmp_path / "home"; home.mkdir()
        result = BundleManager().import_bundle(
            str(bundle), kraken_db_path="", nanometa_home=str(home))
        assert result["success"] is False
        assert any("Unsupported bundle format" in w for w in result["warnings"])
        assert not (home / "genomes").exists()  # nothing copied

    def test_unsupported_version_force_proceeds(self, tmp_path):
        bundle = _make_bundle(tmp_path, version="9.9")
        home = tmp_path / "home"; home.mkdir()
        result = BundleManager().import_bundle(
            str(bundle), kraken_db_path="", nanometa_home=str(home), force=True)
        assert result["success"] is True


class TestPlatformMismatchHardFail:
    _ALIEN = {"system": "PlanX", "machine": "zarch", "python": "3.12.0"}

    def test_prewarm_mismatch_aborts(self, tmp_path):
        bundle = _make_bundle(
            tmp_path,
            build_platform=self._ALIEN,
            pre_warm_conda_envs={"attempted": True, "success": True},
        )
        home = tmp_path / "home"; home.mkdir()
        result = BundleManager().import_bundle(
            str(bundle), kraken_db_path="", nanometa_home=str(home))
        assert result["success"] is False
        assert any("pre-warmed conda" in w for w in result["warnings"])

    def test_prewarm_mismatch_force_proceeds(self, tmp_path):
        bundle = _make_bundle(
            tmp_path,
            build_platform=self._ALIEN,
            pre_warm_conda_envs={"attempted": True, "success": True},
        )
        home = tmp_path / "home"; home.mkdir()
        result = BundleManager().import_bundle(
            str(bundle), kraken_db_path="", nanometa_home=str(home), force=True)
        assert result["success"] is True

    def test_mismatch_without_prewarm_only_warns(self, tmp_path):
        # No pre-warmed cache -> platform mismatch is advisory, import proceeds.
        bundle = _make_bundle(tmp_path, build_platform=self._ALIEN)
        home = tmp_path / "home"; home.mkdir()
        result = BundleManager().import_bundle(
            str(bundle), kraken_db_path="", nanometa_home=str(home))
        assert result["success"] is True
        assert any("field machine is" in w for w in result["warnings"])


class TestAppleDoubleExclusion:
    def test_export_drops_appledouble_sidecars(self, tmp_path):
        home = tmp_path / "home"; (home / "genomes").mkdir(parents=True)
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        (home / "genomes" / "._1.fasta").write_text("appledouble junk")
        (home / "genomes" / ".DS_Store").write_text("ds")

        out = tmp_path / "out.tar.gz"
        BundleManager().export_bundle(
            str(out), config={"kraken_db": ""}, nanometa_home=str(home))
        with tarfile.open(str(out), "r:gz") as tar:
            names = tar.getnames()
        assert not any(n.split("/")[-1].startswith("._") for n in names)
        assert not any(n.endswith(".DS_Store") for n in names)
        assert any(n.endswith("genomes/1.fasta") for n in names)


class TestSizeHelpers:
    def test_human_size(self):
        assert human_size(0) == "0 B"
        assert human_size(5 * 1024 ** 3) == "5.0 GB"

    def test_estimate_counts_genomes(self, tmp_path):
        home = tmp_path / "home"; (home / "genomes").mkdir(parents=True)
        (home / "genomes" / "g.fasta").write_text("A" * 1000)
        assert estimate_bundle_size(str(home)) >= 1000


class TestExportPreflight:
    def _preflight(self):
        from nanometa_live.app.tabs.preparation_tab import _export_preflight
        return _export_preflight

    def test_empty_directory_warns(self):
        alert = self._preflight()("", {}, False)
        assert alert is not None and alert.color == "warning"

    def test_missing_directory_errors(self, tmp_path):
        alert = self._preflight()(str(tmp_path / "nope"), {}, False)
        assert alert is not None and alert.color == "danger"

    def test_valid_writable_dir_passes(self, tmp_path):
        # Real, writable, plenty of space, empty home -> no objection.
        assert self._preflight()(str(tmp_path), {"data_dir": str(tmp_path)}, False) is None
