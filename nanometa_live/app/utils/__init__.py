"""
App utility functions for Nanometa Live.

This package contains shared utility functions for callback helpers,
visualization theme, chart builders, export utilities, and other app-level utilities.
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

from nanometa_live.app.utils.export_utils import (
    export_to_csv,
    export_to_tsv,
    export_to_biom,
    export_to_krona_xml,
    export_species_summary,
    get_export_filename,
)

from nanometa_live.app.utils.plotly_theme import (
    COLORS,
    DARK_THEME,
    LIGHT_THEME,
    register_templates,
    apply_theme_to_figure,
    get_threat_color,
    get_status_color,
)

from nanometa_live.app.utils.chart_builders import (
    create_pathogen_abundance_chart,
    create_threat_indicator_panel,
    create_quality_gauge,
    create_realtime_reads_chart,
    create_sample_progress_chart,
    create_classification_donut,
    create_multi_sample_heatmap,
    create_sample_comparison_bar,
    create_alpha_diversity_chart,
    create_beta_diversity_heatmap,
    create_diversity_summary_cards,
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

from nanometa_live.app.utils.error_handler import (
    ErrorCategory,
    ActionableError,
    get_actionable_error,
    create_error_toast,
    log_and_create_alert,
    get_pipeline_error,
    PIPELINE_ERROR_MESSAGES,
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
    # Export utilities
    'export_to_csv',
    'export_to_tsv',
    'export_to_biom',
    'export_to_krona_xml',
    'export_species_summary',
    'get_export_filename',
    # Plotly theme
    'COLORS',
    'DARK_THEME',
    'LIGHT_THEME',
    'register_templates',
    'apply_theme_to_figure',
    'get_threat_color',
    'get_status_color',
    # Chart builders
    'create_pathogen_abundance_chart',
    'create_threat_indicator_panel',
    'create_quality_gauge',
    'create_realtime_reads_chart',
    'create_sample_progress_chart',
    'create_classification_donut',
    'create_multi_sample_heatmap',
    'create_sample_comparison_bar',
    'create_alpha_diversity_chart',
    'create_beta_diversity_heatmap',
    'create_diversity_summary_cards',
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
    # Error handling
    'ErrorCategory',
    'ActionableError',
    'get_actionable_error',
    'create_error_toast',
    'log_and_create_alert',
    'get_pipeline_error',
    'PIPELINE_ERROR_MESSAGES',
]
