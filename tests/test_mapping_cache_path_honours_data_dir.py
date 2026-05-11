"""Regression tests for the taxid-mapping cache path location.

Pre-fix, ``taxid_mapping.get_mapping_cache_path`` always returned
``Path.home() / ".nanometa" / "mappings" / "<hash>_mappings.json"``.
The readiness checker, in contrast, looked under
``NanometaPaths.from_config(config).data_dir / "mappings" /
"<hash>_mappings.json"`` (see ``readiness_checker.py:245-274``). On any
host where the operator configured a ``data_dir`` other than
``~/.nanometa`` (e.g. a server with the data volume mounted at
``/mnt/<volume>/nanometa_data/``), the writer dropped the JSON under
``~/.nanometa/mappings/`` while readiness scanned
``/mnt/<volume>/nanometa_data/mappings/``. The two never met and the
GUI permanently displayed "Taxid mappings not generated".

The fix routes ``get_mapping_cache_path`` through
``get_data_dir_from_env()`` (the canonical helper at
``core/utils/paths.py:124``) which the CLI entry point pre-populates
via ``set_data_dir_env()``. Writer and reader now resolve to the same
directory on every host.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.taxonomy.taxid_mapping import (
    get_mapping_cache_path,
)


class TestMappingCacheHonoursDataDir:
    """``get_mapping_cache_path`` must read the configured data_dir, not Path.home()."""

    def test_uses_NANOMETA_DATA_DIR_env_var(self, tmp_path, monkeypatch):
        # Simulate a server where the CLI entry point exported
        # NANOMETA_DATA_DIR=/mnt/nanoporeRun/nanometa_data via
        # set_data_dir_env().
        custom_data_dir = tmp_path / "nanometa_data"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(custom_data_dir))

        path = get_mapping_cache_path("/tmp/some/kraken_db")

        # The cache file must live under the configured data_dir, NOT
        # under ~/.nanometa/.
        assert str(path).startswith(str(custom_data_dir))
        assert path.parent == custom_data_dir / "mappings"
        assert path.name.endswith("_mappings.json")

    def test_creates_mappings_subdirectory(self, tmp_path, monkeypatch):
        # The function should auto-create the parent directory so the
        # caller can write to the returned path without further setup.
        custom_data_dir = tmp_path / "fresh_nanometa"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(custom_data_dir))
        assert not (custom_data_dir / "mappings").exists()

        path = get_mapping_cache_path("/tmp/some/kraken_db")

        assert (custom_data_dir / "mappings").is_dir()

    def test_falls_back_to_home_when_env_unset(self, tmp_path, monkeypatch):
        # No NANOMETA_DATA_DIR exported: fall through to the legacy
        # ~/.nanometa default via get_data_dir_from_env().
        monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
        # Redirect Path.home() so the test does not touch the real
        # home directory.
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        path = get_mapping_cache_path("/tmp/some/kraken_db")

        assert str(path).startswith(str(fake_home / ".nanometa"))

    def test_mapping_path_matches_readiness_lookup(self, tmp_path, monkeypatch):
        # End-to-end agreement: the path the writer produces must
        # equal the path the readiness checker scans. The readiness
        # checker resolves data_dir via NanometaPaths.from_config(...).
        custom_data_dir = tmp_path / "data"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(custom_data_dir))

        writer_path = get_mapping_cache_path("/tmp/kraken_db")

        # Mirror the readiness check's expression at
        # readiness_checker.py:265.
        from nanometa_live.core.taxonomy.taxid_mapping import (
            get_database_hash,
        )
        db_hash = get_database_hash("/tmp/kraken_db")
        reader_path = custom_data_dir / "mappings" / f"{db_hash}_mappings.json"

        assert writer_path == reader_path
