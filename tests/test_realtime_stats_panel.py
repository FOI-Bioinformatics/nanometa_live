"""Gap 3: realtime performance stats loader + Reports-tab panel.

nanometanf writes realtime_stats/ (throughput, trends, alerts) in realtime mode;
the GUI never surfaced it. These tests pin the defensive loader and the panel
(empty in batch mode, populated for a realtime run).
"""

import json
from pathlib import Path

import pytest

from nanometa_live.core.utils.realtime_stats_loader import load_realtime_stats
from nanometa_live.app.tabs.reports_helpers import build_realtime_performance_panel

pytestmark = pytest.mark.unit


def _write_realtime(tmp_path):
    rt = tmp_path / "realtime_stats"
    rt.mkdir()
    (rt / "cumulative_stats.json").write_text(json.dumps({
        "session_info": {"total_batches": 18},
        "totals": {"total_estimated_reads": 48432},
        "performance": {"reads_per_second": 120.5, "files_per_second": 0.4,
                        "batches_per_minute": 2.0},
        "trends": {"batch_read_counts": [100, 250, 300, 280]},
    }))
    (rt / "alerts.json").write_text(json.dumps({
        "alerts": [{"level": "warning", "message": "Throughput dropped"}]
    }))
    return str(tmp_path)


class TestLoader:
    def test_none_in_batch_mode(self, tmp_path):
        assert load_realtime_stats(str(tmp_path)) is None  # no realtime_stats/
        assert load_realtime_stats(None) is None

    def test_loads_realtime(self, tmp_path):
        stats = load_realtime_stats(_write_realtime(tmp_path))
        assert stats is not None
        assert stats["session"]["total_batches"] == 18
        assert stats["performance"]["reads_per_second"] == pytest.approx(120.5)
        assert stats["trends"]["batch_read_counts"] == [100, 250, 300, 280]
        assert stats["alerts"][0]["level"] == "warning"

    def test_malformed_cumulative_is_none(self, tmp_path):
        rt = tmp_path / "realtime_stats"
        rt.mkdir()
        (rt / "cumulative_stats.json").write_text("{not json")
        assert load_realtime_stats(str(tmp_path)) is None


class TestPanel:
    def test_empty_in_batch_mode(self):
        assert build_realtime_performance_panel(None) == ""

    def test_populated(self, tmp_path):
        stats = load_realtime_stats(_write_realtime(tmp_path))
        panel = build_realtime_performance_panel(stats)
        text = str(panel)
        assert "Live Performance" in text
        assert "Reads/sec" in text and "Batches" in text
        assert "Throughput dropped" in text  # alert surfaced


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
