"""Every file shipped in a bundle must be covered by a checksum.

``nanometa-prepare verify`` tells an operator whether a bundle survived the
transfer to a field machine. It answered "Bundle verified. Safe to import."
for a bundle whose pipeline source had been replaced with the word
CORRUPTED, because the manifest checksummed only the handful of trees whose
copy loops happened to record one -- 8 of 1151 files in a real bundle.

The trees it missed are the ones that matter most on an air-gapped machine:
``pipeline_source/`` (the workflow itself) and ``nextflow_plugins/`` (without
which Nextflow cannot even parse the pipeline), plus the built-in watchlists,
which were copied *after* the watchlist checksum loop ran.

These tests assert coverage as a property of the bundle rather than of any
one tree, so a future contributor who stages a new directory cannot silently
reintroduce the gap.
"""

from __future__ import annotations

import json
import pathlib
import tarfile

import pytest
import yaml

from nanometa_live.core.workflow.bundle_manager import BundleManager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_machine(tmp_path, monkeypatch):
    """Keep export off the real machine.

    export_bundle stages the Nextflow plugin cache from ``Path.home()`` and
    the taxonomy cache from the data dir. Unisolated, this test pulled ~100 MB
    of the developer's real plugins into every bundle and spent minutes
    gzipping them.
    """
    fake_home = tmp_path / "fakehome"
    plugins = fake_home / ".nextflow" / "plugins" / "nf-schema-2.6.1"
    plugins.mkdir(parents=True)
    (plugins / "nf-schema-2.6.1.jar").write_bytes(b"jar-bytes")
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "datadir"))
    yield


def _existing_install(tmp_path):
    """A minimal but realistic 'working installation' to export from."""
    home = tmp_path / "oldmachine"
    (home / "genomes").mkdir(parents=True)
    (home / "genomes" / "1392.fasta").write_text(">seq\nACGT\n")
    (home / "watchlists").mkdir()
    (home / "watchlists" / "operator.yaml").write_text(
        "metadata:\n  name: Operator list\npathogens:\n"
        "  - name: Bacillus anthracis\n    taxid_ncbi: 1392\n"
    )

    pipeline = tmp_path / "nanometanf"
    (pipeline / "conf").mkdir(parents=True)
    (pipeline / "main.nf").write_text("workflow { }\n")
    (pipeline / "nextflow.config").write_text("manifest { name = 'nanometanf' }\n")
    (pipeline / "conf" / "base.config").write_text("process { cpus = 1 }\n")

    config = {
        "nanometa_home": str(home),
        "kraken_db": str(tmp_path / "db"),
        "pipeline_source": str(pipeline),
    }
    return home, config


def _export(tmp_path, config, home):
    """Export, pinning the source home EXPLICITLY.

    ``nanometa_home`` inside the config dict is ignored -- NanometaPaths
    resolves the data dir from the environment/default, so a test that only
    sets it in the config exports the developer's real ~/.nanometa.
    """
    out = tmp_path / "bundle.tar.gz"
    result = BundleManager().export_bundle(
        str(out), config=config, nanometa_home=str(home),
        pre_warm_conda_envs=False,
    )
    path = result if isinstance(result, str) else out
    assert tarfile.is_tarfile(path), f"export did not produce a tar: {result}"
    return str(path)


def _manifest_of(bundle_path):
    with tarfile.open(bundle_path) as tar:
        member = tar.extractfile("manifest.json")
        return json.load(member)


def _members(bundle_path):
    with tarfile.open(bundle_path) as tar:
        return [m.name for m in tar.getmembers() if m.isfile()]


class TestCoverageIsComplete:
    def test_every_shipped_file_is_checksummed(self, tmp_path):
        """The property, stated once.

        Asserting per-tree would let the next staged directory slip through;
        asserting over the tar guarantees it cannot.
        """
        home, config = _existing_install(tmp_path)
        bundle = _export(tmp_path, config, home)
        checksums = _manifest_of(bundle)["checksums"]

        # manifest.json cannot checksum itself; AppleDouble sidecars are
        # stripped by the tar filter and so are legitimately absent.
        shipped = {
            m for m in _members(bundle)
            if m != "manifest.json"
            and not m.split("/")[-1].startswith("._")
            and m.split("/")[-1] != ".DS_Store"
        }
        missing = sorted(shipped - set(checksums))
        assert not missing, (
            f"{len(missing)} of {len(shipped)} shipped files have no checksum, "
            f"so verify cannot detect their corruption: {missing[:10]}"
        )

    def test_the_pipeline_itself_is_covered(self, tmp_path):
        """Named explicitly because it is the file an operator runs."""
        home, config = _existing_install(tmp_path)
        checksums = _manifest_of(_export(tmp_path, config, home))["checksums"]
        assert "pipeline_source/main.nf" in checksums
        assert "pipeline_source/nextflow.config" in checksums

    def test_builtin_watchlists_are_covered(self, tmp_path):
        """They were copied after the checksum loop, so none were recorded."""
        home, config = _existing_install(tmp_path)
        checksums = _manifest_of(_export(tmp_path, config, home))["checksums"]
        builtin = [k for k in checksums if k.startswith("watchlists/")]
        assert len(builtin) > 1, (
            f"only {builtin} covered; the built-in watchlists copied after "
            f"the checksum loop are missing"
        )


class TestVerifyDetectsCorruption:
    def _tamper(self, tmp_path, bundle, target, content="CORRUPTED"):
        """Rewrite one file inside the bundle, leaving the manifest intact."""
        extracted = tmp_path / "unpacked"
        with tarfile.open(bundle) as tar:
            tar.extractall(extracted, filter="data")
        victim = extracted / target
        assert victim.exists(), f"{target} not in bundle"
        victim.write_text(content)
        repacked = tmp_path / "tampered.tar.gz"
        with tarfile.open(repacked, "w:gz") as tar:
            for item in sorted(extracted.rglob("*")):
                tar.add(item, arcname=str(item.relative_to(extracted)))
        return str(repacked)

    def test_corrupted_pipeline_source_is_refused(self, tmp_path):
        """The exact scenario verify used to greenlight."""
        home, config = _existing_install(tmp_path)
        bundle = _export(tmp_path, config, home)
        tampered = self._tamper(tmp_path, bundle, "pipeline_source/nextflow.config")

        report = BundleManager().verify_bundle(tampered)
        assert report["blockers"], (
            "verify reported a corrupted pipeline as safe to import"
        )
        assert any("checksum" in str(b).lower() for b in report["blockers"])

    def test_corrupted_pipeline_blocks_import(self, tmp_path):
        """Verify and import must agree; a dry run that lies is worse than none."""
        home, config = _existing_install(tmp_path)
        bundle = _export(tmp_path, config, home)
        tampered = self._tamper(tmp_path, bundle, "pipeline_source/main.nf")

        new_home = tmp_path / "fieldlaptop"
        result = BundleManager().import_bundle(
            tampered, kraken_db_path="", nanometa_home=str(new_home)
        )
        assert result["success"] is False

    def test_intact_bundle_still_verifies(self, tmp_path):
        """Wider coverage must not make a good bundle fail.

        Repacking alone changes tar metadata but no file content, so this
        also proves the check is on content rather than on the archive.
        """
        home, config = _existing_install(tmp_path)
        bundle = _export(tmp_path, config, home)
        repacked = self._tamper(
            tmp_path, bundle, "pipeline_source/main.nf", content="workflow { }\n"
        )
        report = BundleManager().verify_bundle(repacked)
        assert not report["blockers"], (
            f"an unmodified bundle was rejected: {report['blockers']}"
        )
