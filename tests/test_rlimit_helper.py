"""Tests for the file-descriptor soft-limit helper.

Long-running Dash GUIs under DiskcacheManager + Werkzeug + heavy
fingerprint walking exhaust the default Linux fd limit (1024-4096)
within hours. ``raise_fd_soft_limit`` lifts the soft limit toward
the hard limit at startup so the GUI can absorb the steady-state
load without ``OSError: [Errno 24] Too many open files``.

These tests exercise the helper in isolation. End-to-end coverage
(actual ``ulimit -n`` change after invoking the entry point) is
deferred to the operator's runbook -- it would require spawning a
subprocess and reading rlimit from outside.
"""

from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock

import pytest

from nanometa_live.core.utils.rlimit import raise_fd_soft_limit


@pytest.fixture
def mock_resource():
    """Mock the resource module so tests are deterministic."""
    mock = MagicMock()
    mock.RLIMIT_NOFILE = 7
    mock.RLIM_INFINITY = -1
    with patch.dict(sys.modules, {"resource": mock}):
        yield mock


class TestRaiseFdSoftLimit:
    def test_raises_toward_target(self, mock_resource):
        mock_resource.getrlimit.side_effect = [
            (1024, 65536),   # before setrlimit
            (65536, 65536),  # after setrlimit
        ]
        before, after = raise_fd_soft_limit()
        assert before == 1024
        assert after == 65536
        mock_resource.setrlimit.assert_called_once_with(
            mock_resource.RLIMIT_NOFILE, (65536, 65536)
        )

    def test_clamps_to_hard_limit(self, mock_resource):
        # Operator's host has a stricter hard limit -- 4096. Soft should
        # rise to 4096, not the target 65536.
        mock_resource.getrlimit.side_effect = [
            (1024, 4096),
            (4096, 4096),
        ]
        before, after = raise_fd_soft_limit(target=65536)
        assert before == 1024
        assert after == 4096
        mock_resource.setrlimit.assert_called_once_with(
            mock_resource.RLIMIT_NOFILE, (4096, 4096)
        )

    def test_no_op_when_already_above_target(self, mock_resource):
        # Container / systemd already set a high soft limit. The
        # helper must not lower it.
        mock_resource.getrlimit.return_value = (100000, 1000000)
        before, after = raise_fd_soft_limit(target=65536)
        assert before == after == 100000
        mock_resource.setrlimit.assert_not_called()

    def test_handles_setrlimit_eperm_with_fallback(self, mock_resource):
        # macOS kernel can refuse 65536 even when getrlimit says the
        # hard limit allows it (launchctl maxfiles ceiling). The
        # helper should retry with smaller targets rather than abort.
        mock_resource.getrlimit.side_effect = [
            (256, 65536),    # initial read
            (10240, 65536),  # after successful fallback
        ]
        # First setrlimit attempt fails; second (smaller) succeeds.
        mock_resource.setrlimit.side_effect = [
            OSError("Operation not permitted"),
            None,
        ]
        before, after = raise_fd_soft_limit(target=65536)
        assert before == 256
        # Fallback chain tries 10240 first; that succeeded.
        assert after == 10240

    def test_handles_unlimited_hard_limit(self, mock_resource):
        # RLIM_INFINITY for hard limit -- target is honoured.
        mock_resource.getrlimit.side_effect = [
            (1024, mock_resource.RLIM_INFINITY),
            (65536, mock_resource.RLIM_INFINITY),
        ]
        before, after = raise_fd_soft_limit()
        assert before == 1024
        assert after == 65536

    def test_returns_sentinel_when_resource_module_missing(self):
        # Windows path -- ``import resource`` raises ImportError.
        # Simulate by injecting an ImportError-raising sys.modules entry
        # (a module that raises when accessed isn't easy; use
        # builtins.__import__ monkeypatch instead).
        real_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "resource":
                raise ImportError("simulated Windows host")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            before, after = raise_fd_soft_limit()
            assert before == -1
            assert after == -1

    def test_handles_getrlimit_failure(self, mock_resource):
        # Kernel refuses to report rlimit -- helper should not crash.
        mock_resource.getrlimit.side_effect = OSError("kernel oops")
        before, after = raise_fd_soft_limit()
        assert before == -1
        assert after == -1
