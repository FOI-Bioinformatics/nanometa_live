"""Archive moves every result folder a run writes (audit finding 24).

``realtime_stats/`` feeds the Reports tab's throughput panel, so a previous
real-time run's figures stood for a whole batch run after an Archive;
``chopper/``, ``filtlong/``, ``assembly/`` and ``realtime_reports/`` were left
behind the same way.
"""

import os

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit

ADDED = ("realtime_stats", "realtime_reports", "chopper", "filtlong", "assembly")


@pytest.mark.parametrize("name", ADDED)
def test_run_output_folder_is_a_result_subdir(name):
    assert name in BackendManager.RESULT_SUBDIRS


def test_archive_moves_the_added_folders(tmp_path):
    for name in ADDED:
        sub = tmp_path / name
        sub.mkdir()
        (sub / "x.json").write_text("{}")
    archive = BackendManager.archive_existing_results(str(tmp_path))
    assert archive is not None
    for name in ADDED:
        assert not (tmp_path / name).exists(), f"{name} left behind"
        assert os.path.isfile(os.path.join(archive, name, "x.json"))


def test_realtime_stats_alone_triggers_the_collision_modal(tmp_path):
    (tmp_path / "realtime_stats").mkdir()
    (tmp_path / "realtime_stats" / "cumulative_stats.json").write_text("{}")
    assert BackendManager.detect_existing_results(str(tmp_path)) == ["realtime_stats"]
