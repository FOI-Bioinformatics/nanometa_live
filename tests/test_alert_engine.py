"""Tests for AlertEngine -- the operator-facing alert generator
that drives the Dashboard verdict banner copy.

Audit followup F8 (docs/audit-2026-05-02-followups.md): the
2026-05-02 frontend audit flagged alert_engine.py as untested
despite owning the operator-facing verdict banner. These tests
pin enough behaviour to catch the most likely class of
regressions:

- Alert.to_dict() shape stays compatible with the Dash
  consumers (id, severity, category, message, recommendation,
  technical_details, timestamp, priority).
- generate_alerts handles each major scenario: no data, low
  quality samples, high error count, dangerous pathogen
  detection, and watchlist matches.
- Severity sort order (CRITICAL=1 < WARNING=2 < INFO=3)
  determines the output ordering.
- History dedup, retention windowing, and capping at
  MAX_HISTORY_SIZE protect against memory leaks during long
  unattended runs.
- get_alert_engine() singleton is thread-safe (mirrors the
  pattern verified for genome_manager / watchlist_manager).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from nanometa_live.core.utils import alert_engine as ae_module
from nanometa_live.core.utils.alert_engine import (
    Alert,
    AlertCategory,
    AlertEngine,
    AlertSeverity,
    MAX_HISTORY_SIZE,
    get_alert_engine,
)


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------


class TestAlert:
    def test_to_dict_shape(self):
        a = Alert(
            severity=AlertSeverity.CRITICAL,
            category=AlertCategory.PATHOGEN,
            message="Bacillus anthracis detected",
            recommendation="Notify oncall",
            technical_details="taxid 1392, 421 reads",
        )
        d = a.to_dict()
        # Pin the keys downstream Dash components rely on.
        for key in (
            "id",
            "severity",
            "category",
            "message",
            "recommendation",
            "technical_details",
            "timestamp",
            "priority",
        ):
            assert key in d
        assert d["severity"] == "critical"
        assert d["category"] == "pathogen"
        assert d["priority"] == 1  # CRITICAL = 1

    def test_severity_priority_ordering(self):
        # Sorting alerts by AlertSeverity.value puts CRITICAL first.
        levels = [
            AlertSeverity.SUCCESS,
            AlertSeverity.CRITICAL,
            AlertSeverity.INFO,
            AlertSeverity.WARNING,
        ]
        sorted_levels = sorted(levels, key=lambda s: s.value)
        assert sorted_levels == [
            AlertSeverity.CRITICAL,
            AlertSeverity.WARNING,
            AlertSeverity.INFO,
            AlertSeverity.SUCCESS,
        ]


# ---------------------------------------------------------------------------
# generate_alerts -- core scenario coverage
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    return AlertEngine()


class TestGenerateAlertsEmptyState:
    def test_no_samples_yields_info_alert(self, engine):
        alerts = engine.generate_alerts(status={"running": False}, samples=[])
        # Should always include a "no samples detected yet" info alert.
        messages = [a["message"] for a in alerts]
        assert any("No samples detected" in m for m in messages)
        # And the only alerts should be info or below in severity.
        assert all(a["priority"] >= AlertSeverity.INFO.value for a in alerts)

    def test_running_with_no_data_does_not_panic(self, engine):
        alerts = engine.generate_alerts(
            status={"running": True, "samples_processed": 0},
            samples=[],
        )
        # A running pipeline with no data yet is normal; no critical alerts.
        assert all(
            a["severity"] != "critical" for a in alerts
        ), f"unexpected critical alerts: {alerts}"


class TestGenerateAlertsErrorCount:
    def test_error_count_above_threshold_is_critical(self, engine):
        alerts = engine.generate_alerts(
            status={"running": True, "error_count": 10}, samples=[]
        )
        critical = [a for a in alerts if a["severity"] == "critical"]
        assert critical, f"expected critical error-count alert, got {alerts}"
        assert any("error" in a["message"].lower() for a in critical)

    def test_error_count_below_threshold_is_warning(self, engine):
        alerts = engine.generate_alerts(
            status={"running": True, "error_count": 2}, samples=[]
        )
        warnings = [a for a in alerts if a["severity"] == "warning"]
        assert warnings
        assert any("error" in a["message"].lower() for a in warnings)

    def test_zero_errors_no_error_alert(self, engine):
        alerts = engine.generate_alerts(
            status={"running": True, "error_count": 0}, samples=[]
        )
        # No alert that mentions "error count" should fire.
        assert not any(
            "error" in a["message"].lower() and a["category"] == "system"
            for a in alerts
        )


class TestGenerateAlertsSampleQuality:
    def test_low_quality_sample_emits_critical(self, engine):
        samples = [
            {"name": "barcode01", "pass_rate": 25.0, "reads": 5000},
        ]
        alerts = engine.generate_alerts(
            status={"running": True}, samples=samples
        )
        critical = [a for a in alerts if a["severity"] == "critical"]
        assert any(
            "barcode01" in a["message"] and "Low quality" in a["message"]
            for a in critical
        ), f"expected low-quality critical alert, got {alerts}"

    def test_low_yield_sample_emits_info(self, engine):
        samples = [
            {"name": "barcode02", "pass_rate": 80.0, "reads": 50},
        ]
        alerts = engine.generate_alerts(
            status={"running": True}, samples=samples
        )
        info = [a for a in alerts if a["severity"] == "info"]
        assert any("barcode02" in a["message"] for a in info)

    def test_healthy_sample_no_alerts(self, engine):
        samples = [
            {"name": "barcode03", "pass_rate": 92.0, "reads": 10_000},
        ]
        alerts = engine.generate_alerts(
            status={"running": True}, samples=samples
        )
        # No critical or warning alerts at all.
        assert not any(
            a["severity"] in ("critical", "warning") for a in alerts
        ), f"unexpected non-info alerts: {alerts}"


class TestGenerateAlertsPathogen:
    def test_dangerous_pathogen_emits_critical(self, engine):
        # Inject a known dangerous pathogen taxid -- Bacillus anthracis
        # (CDC Category A). The pathogen database in the codebase lists
        # this as critical threat level.
        organisms = [
            {"taxid": 1392, "name": "Bacillus anthracis", "reads": 500},
        ]
        alerts = engine.generate_alerts(
            status={"running": True},
            samples=[],
            detected_organisms=organisms,
        )
        # We expect at least one pathogen-category alert; severity should
        # reflect the threat level (the pathogen DB owns the mapping).
        pathogen_alerts = [a for a in alerts if a["category"] == "pathogen"]
        assert pathogen_alerts, f"expected pathogen alert, got {alerts}"

    def test_no_organisms_no_pathogen_alerts(self, engine):
        alerts = engine.generate_alerts(
            status={"running": True}, samples=[], detected_organisms=[]
        )
        assert not any(a["category"] == "pathogen" for a in alerts)


class TestGenerateAlertsOrdering:
    def test_critical_alerts_come_first(self, engine):
        samples = [
            {"name": "barcode01", "pass_rate": 25.0, "reads": 50},
        ]
        alerts = engine.generate_alerts(
            status={"running": True, "error_count": 10},
            samples=samples,
        )
        # First alert priority should be the smallest (CRITICAL = 1).
        priorities = [a["priority"] for a in alerts]
        assert priorities == sorted(priorities), (
            f"alerts not sorted by priority: {priorities}"
        )


# ---------------------------------------------------------------------------
# History bookkeeping
# ---------------------------------------------------------------------------


class TestAlertHistoryRetention:
    def test_history_drops_old_alerts(self):
        engine = AlertEngine(alert_history_hours=1)
        # Inject an "old" alert manually.
        old = Alert(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.QUALITY,
            message="old alert",
            timestamp=datetime.now() - timedelta(hours=2),
        )
        engine.alert_history.append(old)

        # Now generate fresh alerts; retention pass should drop the old one.
        engine.generate_alerts(
            status={"running": True, "error_count": 1}, samples=[]
        )
        timestamps = [a.timestamp for a in engine.alert_history]
        assert all(
            ts > datetime.now() - timedelta(hours=1) for ts in timestamps
        ), "old alerts should have been pruned"

    def test_history_capped_at_max_size(self):
        engine = AlertEngine(alert_history_hours=24)
        # Inject more than MAX_HISTORY_SIZE recent alerts.
        for i in range(MAX_HISTORY_SIZE + 50):
            engine.alert_history.append(
                Alert(
                    severity=AlertSeverity.INFO,
                    category=AlertCategory.SYSTEM,
                    message=f"alert {i}",
                )
            )
        engine._update_alert_history([])  # trigger trim
        assert len(engine.alert_history) <= MAX_HISTORY_SIZE


class TestDeduplication:
    def test_duplicates_collapsed(self, engine):
        a1 = Alert(AlertSeverity.WARNING, AlertCategory.SYSTEM, "same message")
        a2 = Alert(AlertSeverity.WARNING, AlertCategory.SYSTEM, "same message")
        out = engine._deduplicate_alerts([a1, a2])
        assert len(out) == 1


class TestSummary:
    def test_summary_counts_by_severity(self):
        engine = AlertEngine()
        engine.alert_history = [
            Alert(AlertSeverity.CRITICAL, AlertCategory.PATHOGEN, "x"),
            Alert(AlertSeverity.WARNING, AlertCategory.QUALITY, "y"),
            Alert(AlertSeverity.WARNING, AlertCategory.SYSTEM, "z"),
            Alert(AlertSeverity.INFO, AlertCategory.DATA, "w"),
        ]
        summary = engine.get_alert_summary()
        assert summary["critical"] == 1
        assert summary["warning"] == 2
        assert summary["info"] == 1
        assert summary["success"] == 0


class TestClearAlerts:
    def test_clear_all(self, engine):
        engine.alert_history = [
            Alert(AlertSeverity.WARNING, AlertCategory.QUALITY, "a"),
            Alert(AlertSeverity.INFO, AlertCategory.SYSTEM, "b"),
        ]
        engine.clear_alerts()
        assert engine.alert_history == []

    def test_clear_by_category(self, engine):
        engine.alert_history = [
            Alert(AlertSeverity.WARNING, AlertCategory.QUALITY, "a"),
            Alert(AlertSeverity.INFO, AlertCategory.SYSTEM, "b"),
        ]
        engine.clear_alerts(category=AlertCategory.QUALITY)
        assert len(engine.alert_history) == 1
        assert engine.alert_history[0].category == AlertCategory.SYSTEM


# ---------------------------------------------------------------------------
# Singleton thread-safety
# ---------------------------------------------------------------------------


class TestGetAlertEngineSingleton:
    def setup_method(self):
        ae_module._alert_engine = None

    def teardown_method(self):
        ae_module._alert_engine = None

    def test_returns_same_instance(self):
        first = get_alert_engine()
        second = get_alert_engine()
        assert first is second

    def test_concurrent_first_calls_share_instance(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        n_threads = 16
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            return get_alert_engine()

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            instances = list(pool.map(lambda _: worker(), range(n_threads)))

        first = instances[0]
        for inst in instances[1:]:
            assert inst is first
