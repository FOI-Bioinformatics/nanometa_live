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

import pytest
import yaml

from nanometa_live.core.workflow.bundle_manager import BundleManager

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
