"""Configuration > Load lists what Save and Apply wrote.

Live test 2026-11-24: "Save for Later" wrote <data_dir>/configs/<name>.yaml
while Load listed NanometaPaths(config).configs (the project's), so a saved
preset never appeared; and the list was gated on a PROCESS-wide directory
mtime, so after a page reload (a fresh, empty Store) the gate said "nothing
changed" and Load showed "No saved configurations found" even for the
last-session.yaml that Apply had written.
"""

import json
from unittest.mock import MagicMock

import pytest

from nanometa_live.core.utils.paths import NanometaPaths
from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


@pytest.fixture
def app():
    from nanometa_live.app.tabs.config_tab import register_config_callbacks
    return make_callback_app(lambda a: register_config_callbacks(a, MagicMock()))


def _config(tmp_path):
    return {"data_dir": str(tmp_path / "data"), "project_dir": str(tmp_path / "proj"),
            "analysis_name": "Run"}


def test_save_writes_where_load_looks(app, tmp_path):
    config = _config(tmp_path)
    save = get_callback_fn(app, "notification-trigger.data", input_contains="confirm-save-config")
    save(1, "My Preset", config, str(tmp_path / "data"))
    configs_dir = NanometaPaths.from_config(config).configs
    assert (configs_dir / "my_preset.yaml").exists()


def test_opening_load_reads_the_folder_even_with_an_empty_store(app, tmp_path):
    config = _config(tmp_path)
    configs_dir = NanometaPaths.from_config(config).configs
    configs_dir.mkdir(parents=True, exist_ok=True)
    (configs_dir / "last-session.yaml").write_text("analysis_name: Last\n")
    populate = get_callback_fn(app, "load-config-list.children")
    children, store = populate(True, config)
    assert "No saved configurations" not in str(children)
    assert any(c.get("path", "").endswith("last-session.yaml") for c in json.loads(store))
