"""Reset restores analysis settings, not the session's identity.

Live test 2026-11-24: on an app launched with --data-dir/--project and
Offline on, Configuration > Reset replaced app-config with bare defaults.
Those carry no data_dir, project_dir or offline_mode, so Offline switched off
(on an air-gapped machine) and the session file was written to the real
~/.nanometa instead of the project, and every later Apply followed it.
"""

from unittest.mock import patch

import pytest

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback

SESSION = {
    "data_dir": "/session/data",
    "project_dir": "/session/proj",
    "offline_mode": True,
    "gui_port": 8099,
    "visualization_only": True,
    "main_dir": "/results",
    "analysis_name": "Edited name",
    "min_reads_for_validation": 99,
}


@pytest.fixture
def reset_fn():
    from nanometa_live.app.tabs.config_tab import register_config_callbacks
    from unittest.mock import MagicMock
    app = make_callback_app(lambda a: register_config_callbacks(a, MagicMock()))
    return get_callback_fn(app, "saved-config-snapshot.data",
                           input_contains="reset-config-confirm")


def test_reset_keeps_folders_offline_and_mode(reset_fn, tmp_path):
    from nanometa_live.app.tabs import config_tab
    saved = {}
    with patch.object(config_tab, "autosave_session_config",
                      side_effect=lambda c: saved.update(c)):
        config, _note, _refresh, _draft, snapshot = reset_fn(1, str(tmp_path), SESSION)
    for key in ("data_dir", "project_dir", "offline_mode", "gui_port",
                "visualization_only", "main_dir"):
        assert config[key] == SESSION[key], key
        assert saved[key] == SESSION[key], key
    assert snapshot == config


def test_reset_restores_analysis_settings(reset_fn, tmp_path):
    from nanometa_live.app.tabs import config_tab
    from nanometa_live.core.config.config_loader import default_config
    with patch.object(config_tab, "autosave_session_config"):
        config, *_ = reset_fn(1, str(tmp_path), SESSION)
    assert config["min_reads_for_validation"] == default_config()["min_reads_for_validation"]
    assert config["analysis_name"] != "Edited name"
