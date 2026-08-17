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


class TestValidateFileTypes:
    """W3: validate_file must reject type errors instead of letting
    from_dict silently defuse them into different entry behaviour."""

    @staticmethod
    def _validate(tmp_path, pathogen_fields, top_level=None):
        import yaml

        data = {
            "pathogens": [
                {"name": "Yersinia pestis", "threat_level": "critical",
                 **pathogen_fields}
            ],
        }
        data.update(top_level or {})
        path = tmp_path / "candidate.yaml"
        path.write_text(yaml.safe_dump(data))
        return WatchlistLoader().validate_file(path)

    def test_non_numeric_alert_threshold_rejected(self, tmp_path):
        ok, errors = self._validate(tmp_path, {"alert_threshold": "abc"})
        assert not ok
        assert any("alert_threshold" in e for e in errors)

    def test_zero_or_negative_alert_threshold_rejected(self, tmp_path):
        ok, errors = self._validate(tmp_path, {"alert_threshold": 0})
        assert not ok
        ok, errors = self._validate(tmp_path, {"alert_threshold": -5})
        assert not ok

    def test_non_numeric_taxid_rejected(self, tmp_path):
        ok, errors = self._validate(tmp_path, {"taxid_ncbi": "not-an-int"})
        assert not ok
        assert any("taxid_ncbi" in e for e in errors)

    def test_non_numeric_db_taxid_rejected(self, tmp_path):
        ok, errors = self._validate(tmp_path, {"db_taxid": "4005020x"})
        assert not ok

    def test_names_alt_must_be_a_list_of_strings(self, tmp_path):
        ok, errors = self._validate(
            tmp_path, {"names_alt": {"alias": "Y. pestis"}}
        )
        assert not ok
        assert any("names_alt" in e for e in errors)
        ok, _ = self._validate(tmp_path, {"names_alt": ["Y. pestis"]})
        assert ok

    def test_unknown_version_rejected(self, tmp_path):
        ok, errors = self._validate(
            tmp_path, {}, top_level={"version": "1.0"}
        )
        assert not ok
        assert any("version" in e for e in errors)

    def test_valid_and_versionless_files_still_pass(self, tmp_path):
        ok, _ = self._validate(
            tmp_path,
            {"taxid_ncbi": 632, "alert_threshold": 10,
             "names_alt": ["Y. pestis"]},
            top_level={"version": "2.0"},
        )
        assert ok
        ok, _ = self._validate(tmp_path, {"taxid_ncbi": "632"})
        assert ok, "digit strings coerce cleanly and must stay accepted"


class TestInvalidWatchlistFilesAreNamed:
    """W4: a malformed watchlist file must be enumerable, not just logged."""

    def test_malformed_yaml_is_reported(self, tmp_path):
        user_dir = tmp_path / "watchlists"
        user_dir.mkdir()
        (user_dir / "broken.yaml").write_text("pathogens: [unclosed")
        (user_dir / "good.yaml").write_text(VALID_YAML)
        loader = WatchlistLoader()
        with patch.object(WatchlistLoader, "user_watchlist_dir", user_dir):
            invalid = loader.find_invalid_watchlist_files()
        names = [n for n, _ in invalid]
        assert "broken.yaml" in names
        assert "good.yaml" not in names

    def test_type_error_file_is_reported(self, tmp_path):
        user_dir = tmp_path / "watchlists"
        user_dir.mkdir()
        (user_dir / "typed.yaml").write_text(
            VALID_YAML.replace("alert_threshold: 10", "alert_threshold: abc")
        )
        loader = WatchlistLoader()
        with patch.object(WatchlistLoader, "user_watchlist_dir", user_dir):
            invalid = loader.find_invalid_watchlist_files()
        assert any(n == "typed.yaml" for n, _ in invalid)

    def test_clean_install_reports_nothing(self, tmp_path):
        user_dir = tmp_path / "watchlists"
        user_dir.mkdir()
        with patch.object(WatchlistLoader, "user_watchlist_dir", user_dir):
            # Only the built-in tier remains -- shipped lists must validate.
            assert WatchlistLoader().find_invalid_watchlist_files() == []


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
