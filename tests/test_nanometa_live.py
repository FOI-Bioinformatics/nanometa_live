"""Tests for the application entry point (nanometa_live.nanometa_live).

The CLI parsing, default-directory creation, and the main() startup wiring were
previously at 0% coverage. These tests exercise them without starting a real
server (create_app / app.run / BackendManager are mocked).
"""

import os
from unittest import mock

import pytest

from nanometa_live import nanometa_live as entry


# --------------------------------------------------------------------------- #
# parse_arguments
# --------------------------------------------------------------------------- #

def _parse(argv):
    with mock.patch("sys.argv", ["nanometa-live", *argv]):
        return entry.parse_arguments()


def test_parse_arguments_defaults():
    args = _parse([])
    assert args.host == "127.0.0.1"
    assert args.port == 8050
    assert args.debug is False
    assert args.config is None
    assert args.data_dir is None
    assert args.project is None
    assert args.main_dir is None


def test_parse_arguments_custom_values():
    args = _parse([
        "--config", "/tmp/c.yaml", "--host", "0.0.0.0", "--port", "9000",
        "--debug", "--main_dir", "/tmp/results", "--data-dir", "/tmp/data",
        "--project", "/tmp/proj",
    ])
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.debug is True
    assert args.config == "/tmp/c.yaml"
    assert args.main_dir == "/tmp/results"
    assert args.data_dir == "/tmp/data"
    assert args.project == "/tmp/proj"


def test_parse_arguments_main_dir_dash_alias():
    # --main-dir is an accepted alias of --main_dir
    args = _parse(["--main-dir", "/tmp/r"])
    assert args.main_dir == "/tmp/r"


def test_parse_arguments_version_exits():
    with pytest.raises(SystemExit) as exc:
        _parse(["--version"])
    assert exc.value.code == 0


def test_parse_arguments_rejects_non_integer_port():
    with pytest.raises(SystemExit):
        _parse(["--port", "not-a-number"])


# --------------------------------------------------------------------------- #
# create_default_dirs
# --------------------------------------------------------------------------- #

def test_create_default_dirs_creates_expected_tree(tmp_path):
    data_dir = tmp_path / "nm"
    entry.create_default_dirs(str(data_dir))
    for sub in ("", "configs", "data", "reports", "logs"):
        assert (data_dir / sub).is_dir()


def test_create_default_dirs_is_idempotent(tmp_path):
    data_dir = str(tmp_path / "nm")
    entry.create_default_dirs(data_dir)
    entry.create_default_dirs(data_dir)  # must not raise on existing dirs
    assert os.path.isdir(os.path.join(data_dir, "configs"))


# --------------------------------------------------------------------------- #
# main() startup wiring (no real server)
# --------------------------------------------------------------------------- #

@pytest.fixture
def mocked_main(tmp_path):
    """Patch the heavy dependencies of main() and capture the wiring."""
    captured = {}

    class _Loader:
        def __init__(self, *a, **k):
            pass

        def create_default_config(self):
            return {"genome_cache_dir": os.path.expanduser("~/.nanometa")}

        def load_config(self, path):
            captured["loaded_config_path"] = path
            return {"genome_cache_dir": os.path.expanduser("~/.nanometa")}

    fake_app = mock.MagicMock(name="dash_app")

    def _create_app(config, data_dir, backend_manager):
        captured["config"] = config
        captured["data_dir"] = data_dir
        captured["backend_manager"] = backend_manager
        return fake_app

    with mock.patch.object(entry, "ConfigLoader", _Loader), \
         mock.patch.object(entry, "BackendManager", mock.MagicMock(name="backend")), \
         mock.patch.object(entry, "create_app", _create_app), \
         mock.patch.object(entry, "setup_logging", return_value=str(tmp_path / "x.log")), \
         mock.patch.object(entry, "set_data_dir_env"), \
         mock.patch.object(entry, "set_project_dir_env"), \
         mock.patch("nanometa_live.core.utils.rlimit.raise_fd_soft_limit", return_value=(0, 0)), \
         mock.patch("signal.signal"):
        captured["fake_app"] = fake_app
        yield captured


def test_main_starts_server_with_resolved_config(tmp_path, mocked_main):
    data_dir = str(tmp_path / "data")
    with mock.patch("sys.argv", ["nanometa-live", "--data-dir", data_dir, "--port", "8123"]):
        entry.main()

    cfg = mocked_main["config"]
    assert mocked_main["data_dir"] == data_dir
    assert cfg["data_dir"] == data_dir
    assert cfg["gui_port"] == 8123
    assert cfg["project_dir"]  # defaults to cwd, must be set
    # genome cache follows --data-dir when it was the legacy default
    assert cfg["genome_cache_dir"] == data_dir
    # the server was started on the requested port
    mocked_main["fake_app"].run.assert_called_once()
    assert mocked_main["fake_app"].run.call_args.kwargs["port"] == 8123
    # default dirs were created under the chosen data_dir
    assert os.path.isdir(os.path.join(data_dir, "configs"))


def test_main_sets_results_dir_from_main_dir(tmp_path, mocked_main):
    data_dir = str(tmp_path / "data")
    results = str(tmp_path / "results")
    with mock.patch("sys.argv", ["nanometa-live", "--data-dir", data_dir, "--main_dir", results]):
        entry.main()
    cfg = mocked_main["config"]
    assert cfg["results_output_directory"] == os.path.abspath(results)
    assert cfg["main_dir"] == os.path.abspath(results)


def test_main_loads_explicit_config(tmp_path, mocked_main):
    data_dir = str(tmp_path / "data")
    with mock.patch("sys.argv", ["nanometa-live", "--data-dir", data_dir, "--config", "/tmp/my.yaml"]):
        entry.main()
    assert mocked_main["loaded_config_path"] == "/tmp/my.yaml"


def test_main_collapses_leading_double_slash_in_data_dir(tmp_path, mocked_main):
    # POSIX preserves a leading "//"; main() must collapse it.
    with mock.patch("sys.argv", ["nanometa-live", "--data-dir", "//tmp/nm_double"]):
        entry.main()
    assert not mocked_main["data_dir"].startswith("//")
    assert mocked_main["data_dir"].startswith("/tmp/nm_double")
