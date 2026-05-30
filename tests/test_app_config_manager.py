"""
Unit tests for app/utils/config_manager.py.

This is the in-memory atomic-update layer for the app-config Store (distinct
from core/config/config_manager.py). Tests cover the version counter, the
queue/apply batching with priority ordering, atomic single-shot updates, the
internal-field-preserving merge, and the deterministic staleness guards.
Fresh ConfigUpdateManager instances are used to avoid singleton cross-talk.
"""

from nanometa_live.app.utils.config_manager import (
    ConfigUpdateManager,
    atomic_config_update,
    get_config_manager,
    get_config_version,
    increment_config_version,
    merge_config_safely,
    should_skip_stale_update,
)


class TestVersionCounter:
    def test_increment_is_monotonic(self):
        before = get_config_version()
        after = increment_config_version()
        assert after == before + 1
        assert get_config_version() == after


class TestConfigUpdateManager:
    def test_queue_and_pending_flags(self):
        mgr = ConfigUpdateManager()
        assert mgr.has_pending_changes() is False
        mgr.queue_change("cb_a", {"main_dir": "/x"})
        assert mgr.has_pending_changes() is True
        assert mgr.get_pending_sources() == ["cb_a"]

    def test_apply_merges_and_clears(self):
        mgr = ConfigUpdateManager()
        mgr.queue_change("cb_a", {"main_dir": "/x"})
        updated, changed = mgr.apply_pending_changes({"existing": 1})
        assert changed is True
        assert updated["main_dir"] == "/x"
        assert updated["existing"] == 1
        assert "_config_version" in updated
        assert mgr.has_pending_changes() is False

    def test_priority_ordering_higher_overrides(self):
        mgr = ConfigUpdateManager()
        mgr.queue_change("low", {"shared": "low"}, priority=0)
        mgr.queue_change("high", {"shared": "high"}, priority=5)
        updated, _ = mgr.apply_pending_changes({})
        assert updated["shared"] == "high"

    def test_apply_with_no_pending_reports_unchanged(self):
        mgr = ConfigUpdateManager()
        cfg = {"a": 1}
        updated, changed = mgr.apply_pending_changes(cfg)
        assert changed is False
        assert updated is cfg

    def test_clear_pending_returns_count(self):
        mgr = ConfigUpdateManager()
        mgr.queue_change("a", {"x": 1})
        mgr.queue_change("b", {"y": 2})
        assert mgr.clear_pending() == 2
        assert mgr.has_pending_changes() is False

    def test_get_config_manager_is_singleton(self):
        assert get_config_manager() is get_config_manager()


class TestAtomicConfigUpdate:
    def test_applies_updates_and_stamps_metadata(self):
        result = atomic_config_update({"a": 1}, {"b": 2}, source="cb")
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["_last_update_source"] == "cb"
        assert "_config_version" in result

    def test_none_base_starts_empty(self):
        result = atomic_config_update(None, {"b": 2})
        assert result["b"] == 2


class TestMergeConfigSafely:
    def test_preserves_internal_fields_from_base(self):
        base = {"_config_version": 7, "main_dir": "/old"}
        new = {"main_dir": "/new"}
        merged = merge_config_safely(base, new)
        assert merged["main_dir"] == "/new"
        assert merged["_config_version"] == 7

    def test_new_internal_field_not_overwritten_by_base(self):
        base = {"_config_version": 7}
        new = {"_config_version": 9}
        merged = merge_config_safely(base, new)
        assert merged["_config_version"] == 9

    def test_preserve_internal_false_drops_base_internals(self):
        base = {"_config_version": 7}
        merged = merge_config_safely(base, {"x": 1}, preserve_internal=False)
        assert "_config_version" not in merged


class TestShouldSkipStaleUpdate:
    def test_no_config_does_not_skip(self):
        assert should_skip_stale_update({}) is False

    def test_version_mismatch_skips(self):
        cfg = {"_config_version": 5}
        assert should_skip_stale_update(cfg, expected_version=3) is True
