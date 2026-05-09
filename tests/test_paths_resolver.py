"""Tests for the NanometaPaths per-installation directory resolver."""

import os
from pathlib import Path

import pytest

from nanometa_live.core.utils.paths import (
    DEFAULT_DATA_DIR,
    NanometaPaths,
    get_data_dir_from_env,
    set_data_dir_env,
)


def test_resolver_builds_all_subdirs_under_data_dir(tmp_path):
    paths = NanometaPaths(tmp_path)

    expected_root = str(tmp_path)
    for prop in ("configs", "cache", "genomes", "blast", "mappings", "logs"):
        sub = getattr(paths, prop)
        assert str(sub).startswith(expected_root), f"{prop} escaped data_dir"

    assert paths.last_session_yaml.parent == paths.configs
    assert paths.kraken2_local_registry.parent == tmp_path
    assert paths.watchlist_toggle_state.parent == tmp_path


def test_from_config_normalises_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = NanometaPaths.from_config({"data_dir": "~/foo"})

    assert paths.data_dir.is_absolute()
    assert str(paths.data_dir) == str(tmp_path / "foo")


def test_from_config_falls_back_to_default_when_data_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = NanometaPaths.from_config({})

    assert paths.data_dir == Path(os.path.expanduser(DEFAULT_DATA_DIR))


def test_from_data_dir_accepts_pathlike(tmp_path):
    paths = NanometaPaths.from_data_dir(tmp_path)
    assert paths.data_dir == tmp_path


def test_ensure_dirs_creates_full_layout(tmp_path):
    paths = NanometaPaths(tmp_path / "fresh")
    paths.ensure_dirs()

    for prop in ("configs", "cache", "genomes", "blast", "mappings", "logs"):
        assert getattr(paths, prop).is_dir(), f"{prop} not created"


def test_get_data_dir_from_env_reads_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "via-env"))
    assert get_data_dir_from_env() == str(tmp_path / "via-env")


def test_get_data_dir_from_env_falls_back_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # Function expands ~ for the legacy default.
    assert get_data_dir_from_env() == os.path.expanduser(DEFAULT_DATA_DIR)


def test_set_data_dir_env_round_trip(monkeypatch, tmp_path):
    monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
    set_data_dir_env(tmp_path / "x")
    try:
        assert get_data_dir_from_env() == str(tmp_path / "x")
    finally:
        os.environ.pop("NANOMETA_DATA_DIR", None)


def test_resolver_is_frozen(tmp_path):
    paths = NanometaPaths(tmp_path)
    with pytest.raises((AttributeError, TypeError)):
        paths.data_dir = tmp_path / "different"  # type: ignore[misc]
