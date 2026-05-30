"""
Unit tests for core/utils/logging_utils.py (was 0% covered).

setup_logging mutates the root logger and a few named loggers, so the test
snapshots and restores global logging state to avoid leaking handlers/levels
into other tests.
"""

import logging

import pytest

from nanometa_live.core.utils.logging_utils import setup_logging

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    names = ["werkzeug", "dash.dash", "urllib3", "requests", "api"]
    saved_levels = {n: logging.getLogger(n).level for n in names}
    saved_api_handlers = list(logging.getLogger("api").handlers)
    yield
    for h in list(root.handlers):
        if h not in saved_handlers:
            h.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    api = logging.getLogger("api")
    for h in list(api.handlers):
        if h not in saved_api_handlers:
            h.close()
    api.handlers[:] = saved_api_handlers
    for n, lvl in saved_levels.items():
        logging.getLogger(n).setLevel(lvl)


class TestConsoleConfiguration:
    def test_console_only_returns_none(self):
        assert setup_logging(log_to_console=True) is None

    def test_adds_stream_handler(self):
        setup_logging(log_to_console=True)
        root = logging.getLogger()
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)

    def test_no_console_handler_when_disabled(self):
        setup_logging(log_to_console=False)
        root = logging.getLogger()
        assert not any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            for h in root.handlers
        )

    def test_debug_sets_root_level_and_verbose_console_format(self):
        setup_logging(debug=True, log_to_console=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        stream = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
        assert "%(name)s" in stream.formatter._fmt

    def test_info_level_quiets_third_party_loggers(self):
        setup_logging(debug=False, log_to_console=True)
        assert logging.getLogger("werkzeug").level == logging.WARNING
        assert logging.getLogger("dash.dash").level == logging.WARNING
        assert logging.getLogger("urllib3").level == logging.WARNING


class TestFileHandler:
    def test_creates_log_dir_and_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        result = setup_logging(log_dir=str(log_dir))
        assert log_dir.is_dir()
        assert result is not None
        assert result.startswith(str(log_dir))
        assert result.endswith(".log")

    def test_adds_rotating_file_handler_and_api_logger(self, tmp_path):
        import logging.handlers

        setup_logging(log_dir=str(tmp_path / "logs"))
        root = logging.getLogger()
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
        )
        api = logging.getLogger("api")
        assert api.level == logging.DEBUG
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in api.handlers
        )
