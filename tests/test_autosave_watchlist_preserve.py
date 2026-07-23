"""autosave_session_config must not drop a persisted watchlist when it runs
where the WatchlistManager singleton is empty -- e.g. the download_kraken_database
background worker (a separate process). Regression for the audit correctness note.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from nanometa_live.app.tabs.config_tab_helpers import autosave_session_config
from nanometa_live.core.utils.paths import NanometaPaths


def _configs_dir(tmp_path):
    d = Path(NanometaPaths.from_config({"data_dir": str(tmp_path)}).configs)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_preserves_existing_watchlist_when_manager_empty(tmp_path):
    configs = _configs_dir(tmp_path)
    (configs / "last-session.yaml").write_text(yaml.safe_dump({
        "kraken_db": "/old/db",
        "watchlist": {"pathogens": [{"taxid_ncbi": 263}]},
    }))

    with patch(
        "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
        return_value=MagicMock(_loaded=False),
    ):
        autosave_session_config({"data_dir": str(tmp_path), "kraken_db": "/new/db"})

    saved = yaml.safe_load((configs / "last-session.yaml").read_text())
    assert saved["kraken_db"] == "/new/db"                       # new value written
    assert saved["watchlist"] == {"pathogens": [{"taxid_ncbi": 263}]}  # NOT dropped


def test_no_watchlist_key_when_none_persisted_and_manager_empty(tmp_path):
    _configs_dir(tmp_path)  # no last-session.yaml written
    with patch(
        "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
        return_value=MagicMock(_loaded=False),
    ):
        autosave_session_config({"data_dir": str(tmp_path), "kraken_db": "/new/db"})
    saved = yaml.safe_load(
        (_configs_dir(tmp_path) / "last-session.yaml").read_text())
    assert "watchlist" not in saved


def test_loaded_manager_watchlist_wins(tmp_path):
    configs = _configs_dir(tmp_path)
    (configs / "last-session.yaml").write_text(yaml.safe_dump({
        "watchlist": {"pathogens": [{"taxid_ncbi": 263}]}}))
    mgr = MagicMock(_loaded=True)
    mgr.export_config.return_value = {"pathogens": [{"taxid_ncbi": 999}]}
    with patch(
        "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
        return_value=mgr,
    ):
        autosave_session_config({"data_dir": str(tmp_path), "kraken_db": "/x"})
    saved = yaml.safe_load((configs / "last-session.yaml").read_text())
    assert saved["watchlist"] == {"pathogens": [{"taxid_ncbi": 999}]}  # live state
