"""A watchlist toggle must persist the watchlist, not the whole stale config.

The mirror of tests/test_autosave_watchlist_preserve.py, which pins that a
CONFIG write cannot drop a persisted watchlist. Nothing pinned the other
direction, and the 2026-08-19 config audit reproduced the consequence live:

  1. edit min_reads_for_validation 1 -> 50, Apply  (last-session.yaml: 50)
  2. reload the page                               (app-config store re-seeds
                                                    from the BOOT config, which
                                                    still says 1 -- boot is
                                                    fresh by design)
  3. toggle any watchlist                          (last-session.yaml: 1)

The toggle handler wrote its whole in-memory ``app-config`` dict over
last-session.yaml, so an applied setting was silently reverted by an action
that has nothing to do with it. A watchlist toggle owns the ``watchlist``
block only; everything else must come from what is already persisted.
"""

import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.tabs.watchlist_tab import _save_last_session


def _session_path(tmp_path: Path) -> Path:
    return tmp_path / "configs" / "last-session.yaml"


def _write_session(tmp_path: Path, payload: dict) -> Path:
    path = _session_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload))
    return path


class TestWatchlistWriteScope:
    def test_stale_config_does_not_clobber_persisted_settings(self, tmp_path):
        _write_session(tmp_path, {
            "data_dir": str(tmp_path),
            "min_reads_for_validation": 50,
            "kraken_db": "/applied/db",
            "watchlist": {"enabled": True, "builtin": []},
        })

        # What the toggle handler actually holds: the boot config, which
        # predates the operator's Apply.
        _save_last_session({
            "data_dir": str(tmp_path),
            "min_reads_for_validation": 1,
            "kraken_db": "/boot/db",
            "watchlist": {"enabled": True, "builtin": ["clinical_pathogens"]},
        })

        saved = yaml.safe_load(_session_path(tmp_path).read_text())
        assert saved["min_reads_for_validation"] == 50, (
            "a watchlist toggle reverted an applied setting: the handler "
            "wrote its whole stale config over last-session.yaml"
        )
        assert saved["kraken_db"] == "/applied/db"
        # ...while the change it DOES own is persisted.
        assert saved["watchlist"]["builtin"] == ["clinical_pathogens"]

    def test_writes_full_config_when_no_session_exists_yet(self, tmp_path):
        (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
        _save_last_session({
            "data_dir": str(tmp_path),
            "kraken_db": "/first/db",
            "watchlist": {"enabled": True, "builtin": ["select_agents"]},
        })

        saved = yaml.safe_load(_session_path(tmp_path).read_text())
        assert saved["kraken_db"] == "/first/db", (
            "with nothing persisted yet the in-memory config is the best "
            "available baseline and must still be written"
        )
        assert saved["watchlist"]["builtin"] == ["select_agents"]

    def test_unreadable_session_file_does_not_lose_the_toggle(self, tmp_path):
        path = _session_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{{ not: valid: yaml")

        _save_last_session({
            "data_dir": str(tmp_path),
            "watchlist": {"enabled": True, "builtin": ["zoonotic"]},
        })

        saved = yaml.safe_load(path.read_text())
        assert saved["watchlist"]["builtin"] == ["zoonotic"], (
            "a corrupt session file must not swallow the operator's toggle"
        )
