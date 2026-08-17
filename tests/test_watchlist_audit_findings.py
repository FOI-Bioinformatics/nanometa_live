"""Watchlist findings from the 2026-08-17 audit (W1, W7, W8).

- W1: the GUI upload callback re-derived the destination file from the raw
  browser filename while ``import_watchlist`` sanitized it, so any name the
  sanitizer changed was imported but never activated in the session.
  ``WatchlistLoader.sanitize_upload_name`` is now the single sanitizer both
  sides use.
- W7: ``_copy_builtin_watchlists`` swallowed OSError at debug level, so a
  bundle could export with zero built-in watchlists and say nothing.
- W8: the manager's name-only (pseudo-taxid) merge branch dropped the
  incoming entry's ``names_alt``, ``db_taxid`` and ``enabled`` state,
  unlike the taxid-keyed branch beside it.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistEntry,
    WatchlistManager,
    WatchlistSource,
)
from nanometa_live.core.workflow.bundle_manager import BundleManager

VALID_YAML = """\
version: "2.0"
metadata:
  name: "Audit list"
pathogens:
  - name: "Yersinia pestis"
    taxid_ncbi: 632
    threat_level: "critical"
    bsl_level: 3
    alert_threshold: 10
"""


class TestSanitizeUploadName:
    def test_plain_name_passes_through(self):
        assert WatchlistLoader.sanitize_upload_name("list.yaml") == "list.yaml"

    def test_traversal_reduced_to_basename(self):
        assert (
            WatchlistLoader.sanitize_upload_name("../../evil.yaml")
            == "evil.yaml"
        )

    def test_absolute_path_reduced_to_basename(self):
        assert (
            WatchlistLoader.sanitize_upload_name("/tmp/x/mylist.yaml")
            == "mylist.yaml"
        )

    def test_unusable_names_rejected(self):
        assert WatchlistLoader.sanitize_upload_name("") is None
        assert WatchlistLoader.sanitize_upload_name(".") is None
        assert WatchlistLoader.sanitize_upload_name("..") is None

    def test_import_writes_to_the_sanitized_destination(self, tmp_path):
        """W1: the file must land exactly where sanitize_upload_name says,
        so the upload callback can find it by calling the same function."""
        src = tmp_path / "upload.tmp"
        src.write_text(VALID_YAML)
        user_dir = tmp_path / "user_watchlists"
        loader = WatchlistLoader()
        with patch.object(
            WatchlistLoader, "user_watchlist_dir", user_dir
        ):
            ok, _ = loader.import_watchlist(
                src, destination="user", file_name="sub/dir/uploaded.yaml"
            )
        assert ok
        expected = user_dir / WatchlistLoader.sanitize_upload_name(
            "sub/dir/uploaded.yaml"
        )
        assert expected.exists()


class TestBuiltinWatchlistCopyWarns:
    def test_unresolvable_builtin_dir_is_an_export_warning(self, tmp_path):
        manifest = {"export_warnings": []}
        with patch(
            "nanometa_live.core.workflow.bundle_manager."
            "_resolve_builtin_watchlist_dir",
            return_value=None,
        ):
            BundleManager()._copy_builtin_watchlists(
                tmp_path / "watchlists", manifest
            )
        assert manifest["export_warnings"], (
            "a bundle shipping without built-in watchlists must say so"
        )

    def test_oserror_is_an_export_warning(self, tmp_path):
        manifest = {"export_warnings": []}
        with patch(
            "nanometa_live.core.workflow.bundle_manager."
            "_resolve_builtin_watchlist_dir",
            side_effect=OSError("disk error"),
        ):
            BundleManager()._copy_builtin_watchlists(
                tmp_path / "watchlists", manifest
            )
        assert any("disk error" in w for w in manifest["export_warnings"])


class TestNameOnlyMergeParity:
    """W8: the pseudo-taxid merge branch must mirror the taxid branch."""

    NAME = "Unnamed organism X"

    @staticmethod
    def _add(manager, watchlist_id, **extra):
        data = {
            "name": TestNameOnlyMergeParity.NAME,
            "threat_level": "moderate",
            "alert_threshold": 100,
        }
        data.update(extra)
        manager._add_entry_from_dict(
            data, WatchlistSource.IMPORTED, watchlist_id
        )

    def _merged(self, manager):
        entry = manager.get_entry_by_name(self.NAME)
        assert entry is not None
        return entry

    def test_merge_adopts_enabled_state(self):
        manager = WatchlistManager()
        self._add(manager, "list-a", enabled=False)
        self._add(manager, "list-b", enabled=True)
        assert self._merged(manager).enabled is True

    def test_merge_adopts_names_alt_and_indexes_them(self):
        manager = WatchlistManager()
        self._add(manager, "list-a")
        self._add(manager, "list-b", names_alt=["Alias organism X"])
        merged = self._merged(manager)
        assert "Alias organism X" in merged.names_alt
        assert manager._name_index["alias organism x"] == merged.taxid

    def test_merge_adopts_db_taxid_when_absent(self):
        manager = WatchlistManager()
        self._add(manager, "list-a")
        self._add(manager, "list-b", db_taxid=4005020)
        assert self._merged(manager).db_taxid == 4005020

    def test_merge_never_overwrites_existing_db_taxid(self):
        manager = WatchlistManager()
        self._add(manager, "list-a", db_taxid=4001111)
        self._add(manager, "list-b", db_taxid=4005020)
        assert self._merged(manager).db_taxid == 4001111
