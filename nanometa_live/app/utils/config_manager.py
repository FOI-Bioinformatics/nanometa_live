"""
Centralized configuration management for Dash callbacks.

This module provides atomic config updates to prevent race conditions
when multiple callbacks write to app-config simultaneously.

The pattern uses a config version number to detect stale writes and
a pending changes store to queue updates for batch processing.
"""

import time
import copy
import logging
import threading
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# Thread-safe config version tracking
_config_lock = threading.Lock()
_config_version = 0
_last_update_time = 0.0


def get_config_version() -> int:
    """Get current config version number."""
    with _config_lock:
        return _config_version


def increment_config_version() -> int:
    """Increment and return new config version."""
    global _config_version, _last_update_time
    with _config_lock:
        _config_version += 1
        _last_update_time = time.time()
        return _config_version


def get_last_update_time() -> float:
    """Get timestamp of last config update."""
    with _config_lock:
        return _last_update_time


@dataclass
class ConfigChange:
    """Represents a pending configuration change."""
    source: str              # Callback that created this change
    changes: Dict[str, Any]  # Key-value pairs to update
    timestamp: float = field(default_factory=time.time)
    priority: int = 0        # Higher priority changes applied last (override)


class ConfigUpdateManager:
    """
    Manages atomic configuration updates to prevent race conditions.

    Usage in callbacks:
        manager = get_config_manager()

        # Queue a change instead of writing directly
        manager.queue_change("my_callback", {"main_dir": "/new/path"})

        # In the single-writer callback:
        updated_config = manager.apply_pending_changes(current_config)
    """

    def __init__(self):
        self._pending_changes: list[ConfigChange] = []
        self._lock = threading.Lock()

    def queue_change(
        self,
        source: str,
        changes: Dict[str, Any],
        priority: int = 0
    ) -> None:
        """
        Queue a configuration change for batch application.

        Args:
            source: Identifier for the callback making this change
            changes: Dictionary of config keys to update
            priority: Higher priority changes applied last (can override earlier changes)
        """
        with self._lock:
            change = ConfigChange(
                source=source,
                changes=changes,
                priority=priority
            )
            self._pending_changes.append(change)
            logger.debug(f"Queued config change from {source}: {list(changes.keys())}")

    def has_pending_changes(self) -> bool:
        """Check if there are pending changes to apply."""
        with self._lock:
            return len(self._pending_changes) > 0

    def apply_pending_changes(
        self,
        current_config: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Apply all pending changes to the current config.

        Args:
            current_config: The current configuration dictionary

        Returns:
            Tuple of (updated_config, was_changed)
        """
        with self._lock:
            if not self._pending_changes:
                return current_config, False

            # Sort by priority (lower first, higher override)
            sorted_changes = sorted(self._pending_changes, key=lambda c: c.priority)

            # Start with a copy of current config
            updated_config = copy.deepcopy(current_config) if current_config else {}

            # Apply changes in order
            for change in sorted_changes:
                for key, value in change.changes.items():
                    if key.startswith("_"):
                        # Internal fields always update
                        updated_config[key] = value
                    elif updated_config.get(key) != value:
                        updated_config[key] = value
                        logger.debug(f"Applied config change from {change.source}: {key}")

            # Update version
            updated_config["_config_version"] = increment_config_version()
            updated_config["_last_update"] = datetime.now().isoformat()

            # Clear pending changes
            applied_count = len(self._pending_changes)
            self._pending_changes.clear()

            logger.info(f"Applied {applied_count} pending config changes")
            return updated_config, True

    def clear_pending(self) -> int:
        """Clear all pending changes. Returns count of cleared changes."""
        with self._lock:
            count = len(self._pending_changes)
            self._pending_changes.clear()
            return count

    def get_pending_sources(self) -> list[str]:
        """Get list of sources with pending changes."""
        with self._lock:
            return [c.source for c in self._pending_changes]


# Global singleton instance
_config_manager: Optional[ConfigUpdateManager] = None
_manager_lock = threading.Lock()


def get_config_manager() -> ConfigUpdateManager:
    """Get the global ConfigUpdateManager instance."""
    global _config_manager
    with _manager_lock:
        if _config_manager is None:
            _config_manager = ConfigUpdateManager()
        return _config_manager


def atomic_config_update(
    current_config: Dict[str, Any],
    updates: Dict[str, Any],
    source: str = "unknown"
) -> Dict[str, Any]:
    """
    Perform an atomic config update with version tracking.

    This is a simpler alternative to the queue-based approach for
    callbacks that must return immediately.

    Args:
        current_config: Current configuration
        updates: Changes to apply
        source: Identifier for logging

    Returns:
        Updated configuration dictionary
    """
    if not current_config:
        current_config = {}

    # Create a shallow copy and apply updates
    new_config = dict(current_config)
    new_config.update(updates)

    # Update version and timestamp
    new_config["_config_version"] = increment_config_version()
    new_config["_last_update"] = datetime.now().isoformat()
    new_config["_last_update_source"] = source

    logger.debug(f"Atomic config update from {source}: {list(updates.keys())}")
    return new_config


def should_skip_stale_update(
    current_config: Dict[str, Any],
    expected_version: Optional[int] = None,
    max_age_seconds: float = 5.0
) -> bool:
    """
    Check if a config update should be skipped due to staleness.

    Use this at the start of callbacks to prevent writing stale data.

    Args:
        current_config: Current config to check
        expected_version: Expected version (if known)
        max_age_seconds: Maximum age of the callback trigger

    Returns:
        True if update should be skipped, False if it's safe to proceed
    """
    if not current_config:
        return False

    current_version = current_config.get("_config_version", 0)

    # If we expected a specific version and it doesn't match, skip
    if expected_version is not None and current_version != expected_version:
        logger.debug(
            f"Skipping stale update: expected v{expected_version}, got v{current_version}"
        )
        return True

    # Check if there was a very recent update from another source
    last_update = get_last_update_time()
    if last_update > 0:
        age = time.time() - last_update
        if age < 0.5:  # Within 500ms of another update
            logger.debug(f"Skipping update: another update occurred {age:.2f}s ago")
            return True

    return False


def merge_config_safely(
    base_config: Dict[str, Any],
    new_config: Dict[str, Any],
    preserve_internal: bool = True
) -> Dict[str, Any]:
    """
    Safely merge two configs, preserving internal state fields.

    Args:
        base_config: The base configuration
        new_config: New configuration to merge in
        preserve_internal: If True, keeps _* fields from base_config

    Returns:
        Merged configuration
    """
    result = dict(new_config) if new_config else {}

    if preserve_internal and base_config:
        # Preserve internal fields from base
        for key, value in base_config.items():
            if key.startswith("_") and key not in result:
                result[key] = value

    return result
