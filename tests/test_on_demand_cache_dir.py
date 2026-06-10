"""Regression test: OnDemandValidator honours an explicit cache_dir.

The pipeline launch path resolves pathogen genomes / BLAST DBs from
``config["genome_cache_dir"]`` (see
``core/config/parameter_mapping._generate_pathogen_genomes_json``). When an
operator sets an explicit ``genome_cache_dir`` that differs from the
``--data-dir`` root, on-demand re-validation must look in the same place,
otherwise it finds no references and silently no-ops.

This pins the contract that an explicit ``cache_dir`` is honoured and that
``genomes_dir`` / ``blast_dir`` resolve under it.
"""

import os

from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator


def test_explicit_cache_dir_is_honoured(tmp_path):
    results_dir = tmp_path / "results"
    cache_root = tmp_path / "explicit_cache"

    validator = OnDemandValidator(
        results_dir=str(results_dir),
        cache_dir=str(cache_root),
    )

    assert validator.cache_dir == cache_root
    assert validator.genomes_dir == cache_root / "genomes"
    assert validator.blast_dir == cache_root / "blast"

    # The validator eagerly creates the cache subdirectories.
    assert validator.genomes_dir.is_dir()
    assert validator.blast_dir.is_dir()


def test_cache_dir_falls_back_to_data_dir_env(tmp_path, monkeypatch):
    """Without an explicit cache_dir the env data-dir fallback still applies."""
    data_root = tmp_path / "data_root"
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(data_root))

    results_dir = tmp_path / "results"
    validator = OnDemandValidator(results_dir=str(results_dir))

    assert validator.genomes_dir == data_root / "genomes"
    assert validator.blast_dir == data_root / "blast"
