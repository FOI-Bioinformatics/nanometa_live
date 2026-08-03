"""End-to-end round-trip test for the offline deployment bundle.

Exercises the real export -> transfer -> import path that an operator follows
to move Nanometa Live to another computer: build a synthetic data home + a
local pipeline checkout + a Nextflow plugin cache, export a bundle, then import
it into a SECOND fresh home and assert the field machine is fully wired
(offline_mode on, kraken_db / pipeline_source / plugins rebased, data restored,
genome_metadata re-templated).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    _local_container_platform,
)
from nanometa_live.core.workflow.nextflow_manager import NextflowManager

pytestmark = pytest.mark.unit


def _build_data_home(home: Path) -> None:
    (home / "genomes").mkdir(parents=True)
    (home / "genomes" / "12345.fasta").write_text(">seq1\nACGTACGT\n")
    (home / "blast").mkdir()
    (home / "blast" / "12345.fasta").write_text(">seq1\nACGTACGT\n")
    (home / "watchlists").mkdir()
    (home / "watchlists" / "custom.yaml").write_text(
        "version: '2.0'\npathogens:\n  - name: Test\n    taxid_ncbi: 12345\n"
    )
    (home / "watchlist_toggle_state.yaml").write_text("12345: true\n")
    # genome_metadata.json with paths UNDER the build home (the portable case).
    (home / "genome_metadata.json").write_text(json.dumps({
        "12345": {
            "taxid": 12345,
            "fasta_path": str(home / "genomes" / "12345.fasta"),
            "blast_db_path": str(home / "blast" / "12345.fasta"),
        }
    }, indent=2))


def _build_pipeline_checkout(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "main.nf").write_text("// fake pipeline\nworkflow {}\n")
    (path / "nextflow.config").write_text(
        "plugins { id 'nf-schema@2.4.2' }\nmanifest { nextflowVersion = '>=26.04.0' }\n"
    )


def test_export_import_round_trip(tmp_path, monkeypatch):
    # Fake HOME so the plugin cache resolves predictably during export.
    fake_home = tmp_path / "fakehome"
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2").mkdir(parents=True)
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2" / "x.jar").write_text("jar")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    build_home = tmp_path / "build_home"
    _build_data_home(build_home)
    pipeline = tmp_path / "pipeline"
    _build_pipeline_checkout(pipeline)

    config = {"pipeline_source": str(pipeline), "kraken_db": ""}
    out = tmp_path / "bundle.tar.gz"

    mgr = BundleManager()
    mgr.export_bundle(
        str(out), config,
        nanometa_home=str(build_home),
        pre_warm_conda_envs=False,
        pipeline_path=str(pipeline),
        containerization="conda",
    )
    assert out.exists()

    # Bundle manifest carries the Nextflow version floor.
    import tarfile
    with tarfile.open(str(out)) as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
    assert manifest["min_versions"]["nextflow"] == "26.04.0"
    assert manifest["export_warnings"] == []  # all genome paths under home

    # --- Import onto a fresh field machine ---
    field_home = tmp_path / "field_home"
    field_home.mkdir()
    fake_kraken = tmp_path / "kraken_db"
    fake_kraken.mkdir()

    result = mgr.import_bundle(
        str(out), kraken_db_path=str(fake_kraken), nanometa_home=str(field_home),
    )
    assert result["success"] is True, result.get("warnings")
    assert not result.get("kraken_db_unset")
    assert not result.get("pipeline_main_missing")

    # Data restored.
    assert (field_home / "genomes" / "12345.fasta").exists()
    assert (field_home / "watchlists" / "custom.yaml").exists()

    # Config rebased for this machine.
    cfg = yaml.safe_load((field_home / "config.yaml").read_text())
    assert cfg["offline_mode"] is True
    assert cfg["kraken_db"] == str(fake_kraken)
    assert cfg["pipeline_source"] == str(field_home / "pipeline_source")
    assert (field_home / "pipeline_source" / "main.nf").exists()
    assert cfg["nxf_plugins_dir"] == str(field_home / "nextflow_plugins")
    assert any((field_home / "nextflow_plugins").iterdir())

    # genome_metadata re-templated to the field home (no placeholder left).
    gm = (field_home / "genome_metadata.json").read_text()
    assert "${NANOMETA_HOME}" not in gm
    assert str(field_home) in gm

    # --- The seam that matters: does the imported config actually configure
    # a Nextflow run? Asserting the config KEY exists proves nothing; the
    # env builder skips any path that is not an existing directory, so only
    # executing it shows the rebased paths survive.
    env = NextflowManager._build_nextflow_env(cfg)
    assert env["NXF_OFFLINE"] == "true"
    assert env["NXF_DISABLE_CHECK_LATEST"] == "true"
    assert env["NXF_PLUGINS_PATH"] == str(field_home / "nextflow_plugins")
    assert env["NXF_PLUGINS_DIR"] == str(field_home / "nextflow_plugins")

    # And the offline guard must accept the rebased local checkout (it
    # rejects remote: / https:// / git@ sources when offline).
    nf_mgr = NextflowManager(
        data_dir=str(field_home), pipeline_source=cfg["pipeline_source"])
    ok, msg = nf_mgr.validate_pipeline_source(cfg)
    assert ok is True, msg


def test_conda_bundle_wires_conda_cachedir_into_run_env(tmp_path, monkeypatch):
    """conda mode: a pre-warmed cache must come back out as NXF_CONDA_CACHEDIR."""
    fake_home = tmp_path / "fakehome"
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2").mkdir(parents=True)
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2" / "x.jar").write_text("jar")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    build_home = tmp_path / "build_home"
    _build_data_home(build_home)
    pipeline = tmp_path / "pipeline"
    _build_pipeline_checkout(pipeline)

    def fake_pre_warm(staging, config, pipeline_path):
        # Stand in for a real `nextflow -profile conda` warm-up: stage the
        # env directory layout Nextflow would have produced.
        cache = Path(staging) / "conda_cache"
        (cache / "env-abc123" / "conda-meta").mkdir(parents=True)
        (cache / "env-abc123" / "conda-meta" / "history").write_text("")
        return {
            "attempted": True, "success": True,
            "scenarios": ["default"], "env_count": 1, "warnings": [],
        }

    out = tmp_path / "bundle.tar.gz"
    mgr = BundleManager()
    with patch.object(mgr, "_pre_warm_conda_envs", side_effect=fake_pre_warm):
        mgr.export_bundle(
            str(out), {"pipeline_source": str(pipeline), "kraken_db": ""},
            nanometa_home=str(build_home),
            pre_warm_conda_envs=True,
            pipeline_path=str(pipeline),
            containerization="conda",
        )

    field_home = tmp_path / "field_home"
    field_home.mkdir()
    kdb = tmp_path / "kraken_db"
    kdb.mkdir()
    result = mgr.import_bundle(
        str(out), kraken_db_path=str(kdb), nanometa_home=str(field_home))
    assert result["success"] is True, result.get("warnings")
    assert result["conda_cache_path"] == str(field_home / "conda_cache")

    cfg = yaml.safe_load((field_home / "config.yaml").read_text())
    env = NextflowManager._build_nextflow_env(cfg)
    assert env["NXF_OFFLINE"] == "true"
    assert env["NXF_CONDA_CACHEDIR"] == str(field_home / "conda_cache")
    assert env["NXF_PLUGINS_PATH"] == str(field_home / "nextflow_plugins")


def test_singularity_bundle_wires_singularity_cachedir_into_run_env(
    tmp_path, monkeypatch
):
    """singularity mode: bundled .img files must come back out as
    NXF_SINGULARITY_CACHEDIR, or the air-gapped run re-pulls and fails."""
    fake_home = tmp_path / "fakehome"
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2").mkdir(parents=True)
    (fake_home / ".nextflow" / "plugins" / "nf-schema-2.4.2" / "x.jar").write_text("jar")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    build_home = tmp_path / "build_home"
    _build_data_home(build_home)
    pipeline = tmp_path / "pipeline"
    _build_pipeline_checkout(pipeline)

    img_name = "quay.io-biocontainers-seqkit-2.9.0--h9ee0642_0.img"

    def fake_pull(engine, staging, config, pipeline_path, target_platform=None):
        images = Path(staging) / "pipeline_containers"
        images.mkdir(parents=True, exist_ok=True)
        (images / img_name).write_bytes(b"SIF\x00fake")
        return {
            "attempted": True, "engine": engine, "image_count": 1,
            "pulled": ["quay.io/biocontainers/seqkit:2.9.0--h9ee0642_0"],
            "warnings": [],
        }

    out = tmp_path / "bundle.tar.gz"
    mgr = BundleManager()
    with patch.object(mgr, "_pull_pipeline_containers", side_effect=fake_pull):
        mgr.export_bundle(
            str(out), {"pipeline_source": str(pipeline), "kraken_db": ""},
            nanometa_home=str(build_home),
            pipeline_path=str(pipeline),
            containerization="singularity",
            # Same-machine round trip: declare this machine's platform so the
            # container-platform guard is not tripped by the linux/amd64
            # default (which is correct for a real field build, not for this).
            target_platform=_local_container_platform(),
        )

    field_home = tmp_path / "field_home"
    field_home.mkdir()
    kdb = tmp_path / "kraken_db"
    kdb.mkdir()
    result = mgr.import_bundle(
        str(out), kraken_db_path=str(kdb), nanometa_home=str(field_home))
    assert result["success"] is True, result.get("warnings")

    # The image survived the transfer under the Nextflow cache name.
    assert (field_home / "pipeline_containers" / img_name).exists()

    cfg = yaml.safe_load((field_home / "config.yaml").read_text())
    assert cfg["pipeline_profile"] == "singularity"
    env = NextflowManager._build_nextflow_env(cfg)
    assert env["NXF_OFFLINE"] == "true"
    assert env["NXF_SINGULARITY_CACHEDIR"] == str(field_home / "pipeline_containers")
    assert env["NXF_SINGULARITY_LIBRARYDIR"] == str(field_home / "pipeline_containers")
    assert env["NXF_PLUGINS_PATH"] == str(field_home / "nextflow_plugins")


def test_verify_bundle_accepts_a_freshly_exported_bundle(tmp_path, monkeypatch):
    """The dry-run verifier must pass a bundle the exporter just wrote --
    otherwise it would cry wolf on every good USB copy."""
    fake_home = tmp_path / "fakehome"
    (fake_home / ".nextflow" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    build_home = tmp_path / "build_home"
    _build_data_home(build_home)
    pipeline = tmp_path / "pipeline"
    _build_pipeline_checkout(pipeline)

    out = tmp_path / "bundle.tar.gz"
    mgr = BundleManager()
    mgr.export_bundle(
        str(out), {"pipeline_source": str(pipeline), "kraken_db": ""},
        nanometa_home=str(build_home),
        pipeline_path=str(pipeline),
        containerization="conda",
    )

    field_home = tmp_path / "field_home"
    verdict = mgr.verify_bundle(str(out))
    assert verdict["success"] is True, verdict["warnings"]
    assert verdict["blockers"] == []
    # Verification is read-only: nothing was installed.
    assert not field_home.exists()
