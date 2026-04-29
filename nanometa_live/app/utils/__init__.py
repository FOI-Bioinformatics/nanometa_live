"""
App utility functions for Nanometa Live.

This package contains shared utility functions for callback helpers,
visualization theme, debounce utilities, and config management.
"""

from nanometa_live.app.utils.callback_helpers import (
    # Error logging
    log_callback_error,
    # Validation functions
    validate_config,
    validate_sample,
    validate_dataframe,
    validate_numeric,
    validate_path,
    validate_callback_inputs,
    empty_figure,
    # Legacy helpers
    validate_config_and_get_main_dir,
    create_empty_alert,
    create_error_alert,
    create_info_alert,
    safe_load_kraken_data,
    get_classification_stats,
    get_total_kraken_reads,
    format_number,
    format_percentage,
    format_bp
)

from nanometa_live.app.utils.plotly_theme import (
    COLORS,
    CHART_CONFIG,
    DARK_THEME,
    LIGHT_THEME,
    register_templates,
    apply_theme_to_figure,
    get_threat_color,
    get_status_color,
)

from nanometa_live.app.utils.debounce import (
    should_skip_update,
    get_last_update_time,
    reset_debounce,
    CallbackThrottler,
    callback_throttler,
    is_triggered_by,
    get_trigger_type,
)

from nanometa_live.app.utils.config_manager import (
    get_config_manager,
    atomic_config_update,
    should_skip_stale_update,
    merge_config_safely,
    ConfigUpdateManager,
)

__all__ = [
    # Error logging
    'log_callback_error',
    # Validation functions
    'validate_config',
    'validate_sample',
    'validate_dataframe',
    'validate_numeric',
    'validate_path',
    'validate_callback_inputs',
    'empty_figure',
    # Callback helpers
    'validate_config_and_get_main_dir',
    'create_empty_alert',
    'create_error_alert',
    'create_info_alert',
    'safe_load_kraken_data',
    'get_classification_stats',
    'get_total_kraken_reads',
    'format_number',
    'format_percentage',
    'format_bp',
    # Plotly theme
    'COLORS',
    'DARK_THEME',
    'LIGHT_THEME',
    'register_templates',
    'apply_theme_to_figure',
    'get_threat_color',
    'get_status_color',
    # Debounce utilities
    'should_skip_update',
    'get_last_update_time',
    'reset_debounce',
    'CallbackThrottler',
    'callback_throttler',
    'is_triggered_by',
    'get_trigger_type',
    # Config management
    'get_config_manager',
    'atomic_config_update',
    'should_skip_stale_update',
    'merge_config_safely',
    'ConfigUpdateManager',
]
