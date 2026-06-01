"""Tests for the NanometaPaths per-installation directory resolver."""

import os
from pathlib import Path

import pytest

from nanometa_live.core.utils.paths import (
    DEFAULT_DATA_DIR,
    NanometaPaths,
    get_data_dir_from_env,
    get_mappings_dir_from_env,
    get_project_dir_from_env,
    set_data_dir_env,
    set_project_dir_env,
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


# --------------------------------------------------------------------------
# Project scope: per-analysis state under <project_dir>/.nanometa/, global
# artifacts under data_dir.
# --------------------------------------------------------------------------

def test_project_scoped_properties_under_project_state(tmp_path):
    data = tmp_path / "global"
    proj = tmp_path / "proj"
    paths = NanometaPaths.from_config(
        {"data_dir": str(data), "project_dir": str(proj)}
    )
    project_state = proj / ".nanometa"
    assert paths.project_state == project_state
    assert paths.configs == project_state / "configs"
    assert paths.mappings == project_state / "mappings"
    assert paths.watchlists == project_state / "watchlists"
    assert paths.watchlist_toggle_state == project_state / "watchlist_toggle_state.yaml"
    assert paths.last_session_yaml == project_state / "configs" / "last-session.yaml"


def test_global_properties_stay_under_data_dir_when_project_set(tmp_path):
    data = tmp_path / "global"
    paths = NanometaPaths.from_config(
        {"data_dir": str(data), "project_dir": str(tmp_path / "proj")}
    )
    assert paths.cache == data / "cache"
    assert paths.genomes == data / "genomes"
    assert paths.blast == data / "blast"
    assert paths.logs == data / "logs"
    assert paths.kraken2_local_registry == data / "kraken2_databases.local.yaml"
    assert paths.kraken2_databases == data / "kraken2_databases"


def test_project_unset_falls_back_to_data_dir(tmp_path):
    paths = NanometaPaths.from_config({"data_dir": str(tmp_path), "project_dir": ""})
    assert paths.project_dir is None
    assert paths.project_state == tmp_path
    assert paths.configs == tmp_path / "configs"
    assert paths.mappings == tmp_path / "mappings"


def test_ensure_dirs_creates_project_layout(tmp_path):
    data = tmp_path / "global"
    proj = tmp_path / "proj"
    paths = NanometaPaths.from_config(
        {"data_dir": str(data), "project_dir": str(proj)}
    )
    paths.ensure_dirs()
    assert (proj / ".nanometa" / "configs").is_dir()
    assert (proj / ".nanometa" / "mappings").is_dir()
    assert (proj / ".nanometa" / "watchlists").is_dir()
    assert (data / "genomes").is_dir()
    assert (data / "cache").is_dir()


def test_mappings_dir_env_project_local_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(tmp_path / "proj"))
    assert get_mappings_dir_from_env() == str(tmp_path / "proj" / ".nanometa" / "mappings")


def test_mappings_dir_env_global_when_project_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "global"))
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
    assert get_mappings_dir_from_env() == str(tmp_path / "global" / "mappings")


def test_set_get_project_dir_env_round_trip(monkeypatch, tmp_path):
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
    assert get_project_dir_from_env() is None
    set_project_dir_env(tmp_path / "p")
    try:
        assert get_project_dir_from_env() == str(tmp_path / "p")
    finally:
        os.environ.pop("NANOMETA_PROJECT_DIR", None)


# --------------------------------------------------------------------------
# Results container + per-run folders (named runs nested in the project).
# --------------------------------------------------------------------------

def test_results_under_project_when_set(tmp_path):
    paths = NanometaPaths.from_config({"project_dir": str(tmp_path / "proj")})
    assert paths.results == tmp_path / "proj" / "results"
    assert paths.run_dir("run_alpha") == tmp_path / "proj" / "results" / "run_alpha"


def test_results_falls_back_to_home_when_no_project(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = NanometaPaths.from_config({"data_dir": str(tmp_path / "g")})
    assert paths.results == Path(os.path.expanduser("~/nanometa_results"))


def test_ensure_dirs_creates_results_only_for_project(tmp_path):
    proj = tmp_path / "proj"
    NanometaPaths.from_config(
        {"data_dir": str(tmp_path / "g"), "project_dir": str(proj)}
    ).ensure_dirs()
    assert (proj / "results").is_dir()
