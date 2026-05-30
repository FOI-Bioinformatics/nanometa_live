"""
Unit tests for app/utils/file_manager_open.py.

open_in_file_manager bridges a documented path to the OS file manager. The
contract: empty/missing paths return a message (never raise), a regular file
resolves to its parent directory, and the platform-native launcher is invoked
via subprocess. subprocess.Popen and sys.platform are mocked so no window opens.
"""

from unittest.mock import patch

from nanometa_live.app.utils import file_manager_open as fmo
from nanometa_live.app.utils.file_manager_open import open_in_file_manager


class TestOpenInFileManager:
    def test_empty_path(self):
        assert open_in_file_manager("") == "Empty path"

    def test_missing_path(self, tmp_path):
        msg = open_in_file_manager(str(tmp_path / "nope"))
        assert "does not exist" in msg

    def test_directory_opens_via_native_launcher(self, tmp_path):
        with patch.object(fmo.sys, "platform", "darwin"), \
             patch.object(fmo.subprocess, "Popen") as popen:
            result = open_in_file_manager(str(tmp_path))
        assert result is None
        assert popen.call_args[0][0] == ["open", str(tmp_path)]

    def test_regular_file_resolves_to_parent(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("x")
        with patch.object(fmo.sys, "platform", "darwin"), \
             patch.object(fmo.subprocess, "Popen") as popen:
            open_in_file_manager(str(f))
        # The parent directory is opened, not the file itself.
        assert popen.call_args[0][0] == ["open", str(tmp_path)]

    def test_unsupported_platform(self, tmp_path):
        with patch.object(fmo.sys, "platform", "sunos"):
            msg = open_in_file_manager(str(tmp_path))
        assert "Unsupported platform" in msg

    def test_launcher_not_found_returns_message(self, tmp_path):
        with patch.object(fmo.sys, "platform", "linux"), \
             patch.object(fmo.subprocess, "Popen", side_effect=FileNotFoundError("xdg-open")):
            msg = open_in_file_manager(str(tmp_path))
        assert "not found" in msg
