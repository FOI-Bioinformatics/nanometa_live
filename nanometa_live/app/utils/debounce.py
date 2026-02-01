"""
Debounce utilities for Dash callbacks.

Provides mechanisms to prevent rapid-fire callback execution when multiple
triggers occur simultaneously (e.g., interval + sample change + tab switch).
"""

import time
import threading
import logging
from typing import Dict, Any, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)


# Global debounce state storage
_debounce_timestamps: Dict[str, float] = {}
_debounce_lock = threading.Lock()


def should_skip_update(
    callback_id: str,
    debounce_ms: int = 500,
    force_update: bool = False
) -> bool:
    """
    Check if a callback should skip execution due to debounce.

    Use this at the start of callbacks to prevent rapid-fire execution.
    Returns True if the callback was executed recently and should be skipped.

    Args:
        callback_id: Unique identifier for this callback
        debounce_ms: Minimum milliseconds between executions (default: 500ms)
        force_update: If True, bypass debounce and always execute

    Returns:
        True if callback should be skipped, False if it should execute

    Example:
        @app.callback(...)
        def update_plot(n_intervals, ...):
            if should_skip_update("update_plot", debounce_ms=1000):
                raise PreventUpdate
            # ... actual callback logic
    """
    if force_update:
        return False

    current_time = time.time() * 1000  # Convert to milliseconds
    debounce_key = callback_id

    with _debounce_lock:
        last_execution = _debounce_timestamps.get(debounce_key, 0)
        time_since_last = current_time - last_execution

        if time_since_last < debounce_ms:
            logger.debug(
                f"Debounce skip: {callback_id} "
                f"(last: {time_since_last:.0f}ms ago, threshold: {debounce_ms}ms)"
            )
            return True

        # Update timestamp for this callback
        _debounce_timestamps[debounce_key] = current_time
        return False


def get_last_update_time(callback_id: str) -> Optional[float]:
    """
    Get the timestamp of the last execution for a callback.

    Args:
        callback_id: Unique identifier for this callback

    Returns:
        Unix timestamp in seconds, or None if never executed
    """
    with _debounce_lock:
        ts = _debounce_timestamps.get(callback_id)
        return ts / 1000 if ts else None


def reset_debounce(callback_id: Optional[str] = None):
    """
    Reset debounce state for one or all callbacks.

    Args:
        callback_id: Specific callback to reset, or None to reset all
    """
    with _debounce_lock:
        if callback_id:
            _debounce_timestamps.pop(callback_id, None)
        else:
            _debounce_timestamps.clear()


class CallbackThrottler:
    """
    Throttle callback execution to prevent overwhelming the server.

    Unlike debounce (which delays until quiet), throttle ensures a maximum
    rate of execution - callbacks will run at most once per interval.
    """

    def __init__(self, min_interval_ms: int = 1000):
        """
        Initialize throttler.

        Args:
            min_interval_ms: Minimum milliseconds between executions
        """
        self.min_interval_ms = min_interval_ms
        self._last_calls: Dict[str, float] = {}
        self._lock = threading.Lock()

    def can_execute(self, callback_id: str) -> bool:
        """
        Check if callback can execute based on throttle.

        Args:
            callback_id: Unique callback identifier

        Returns:
            True if callback can execute, False if throttled
        """
        current_time = time.time() * 1000

        with self._lock:
            last_call = self._last_calls.get(callback_id, 0)

            if current_time - last_call >= self.min_interval_ms:
                self._last_calls[callback_id] = current_time
                return True
            return False

    def reset(self, callback_id: Optional[str] = None):
        """Reset throttle state."""
        with self._lock:
            if callback_id:
                self._last_calls.pop(callback_id, None)
            else:
                self._last_calls.clear()


# Global throttler instance for callbacks (1 second minimum between calls)
callback_throttler = CallbackThrottler(min_interval_ms=1000)


def is_triggered_by(ctx, trigger_id: str) -> bool:
    """
    Check if a specific component triggered the callback.

    Useful for callbacks with multiple inputs to determine which one fired.

    Args:
        ctx: Dash callback context (dash.ctx)
        trigger_id: ID of the component to check

    Returns:
        True if the specified component triggered this callback

    Example:
        @app.callback(...)
        def update(n_intervals, sample, config):
            if is_triggered_by(dash.ctx, "sample-selector"):
                # Sample changed - force refresh
                ...
            elif is_triggered_by(dash.ctx, "update-interval"):
                # Regular interval - check debounce
                ...
    """
    triggered = ctx.triggered_id
    if triggered is None:
        return False

    if isinstance(triggered, str):
        return triggered == trigger_id

    # Handle pattern-matching callback IDs (dicts)
    if isinstance(triggered, dict):
        return triggered.get('index') == trigger_id

    return False


def get_trigger_type(ctx) -> str:
    """
    Get the type/category of what triggered the callback.

    Args:
        ctx: Dash callback context

    Returns:
        One of: "interval", "user_action", "store_update", "initial", "unknown"
    """
    triggered_id = ctx.triggered_id

    if triggered_id is None:
        return "initial"

    if isinstance(triggered_id, str):
        if "interval" in triggered_id.lower():
            return "interval"
        if "selector" in triggered_id.lower() or "button" in triggered_id.lower():
            return "user_action"
        if "store" in triggered_id.lower() or "config" in triggered_id.lower():
            return "store_update"

    return "unknown"
