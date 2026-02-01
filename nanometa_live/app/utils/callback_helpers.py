"""
Shared callback utility functions for Nanometa Live.

This module reduces code duplication across tab callbacks by providing
common validation, data loading, and UI component creation functions.
"""

import os
import logging
import traceback
from typing import Optional, Tuple, Any, Dict, List, Union
from functools import wraps

import pandas as pd
import numpy as np
import dash_bootstrap_components as dbc
from dash import html, no_update
import plotly.graph_objects as go

from nanometa_live.core.utils.data_loaders import load_kraken_data


# =============================================================================
# Error Logging Utilities
# =============================================================================

def log_callback_error(
    callback_name: str,
    error: Exception,
    level: int = logging.ERROR,
    extra_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log a callback exception with full traceback for debugging.

    Use this instead of simple logging.error() to capture the full
    stack trace, which is essential for diagnosing production issues.

    Args:
        callback_name: Name of the callback function (use __name__ or a descriptive string)
        error: The caught exception
        level: Logging level (default ERROR, use WARNING for recoverable errors)
        extra_context: Optional dict of additional context to log

    Example:
        try:
            result = process_data(data)
        except Exception as e:
            log_callback_error("update_classification_plot", e, extra_context={"sample": sample_name})
            return empty_figure("Error processing data")
    """
    # Build context string
    context_str = ""
    if extra_context:
        context_parts = [f"{k}={v!r}" for k, v in extra_context.items()]
        context_str = f" Context: {', '.join(context_parts)}"

    # Get the full traceback
    tb_str = traceback.format_exc()

    # Log with appropriate level
    logging.log(
        level,
        f"Callback '{callback_name}' raised {type(error).__name__}: {error}{context_str}\n"
        f"Traceback:\n{tb_str}"
    )


# =============================================================================
# Input Validation Functions
# =============================================================================

def validate_config(config: Any) -> Tuple[bool, Optional[str]]:
    """
    Validate that config is a proper configuration dictionary.

    Args:
        config: Value to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if config is None:
        return False, "No configuration loaded"
    if not isinstance(config, dict):
        return False, "Invalid configuration format"
    return True, None


def validate_sample(sample: Any, available_samples: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate sample selection.

    Args:
        sample: Sample name to validate
        available_samples: List of valid sample names (optional)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if sample is None:
        return False, "No sample selected"
    if not isinstance(sample, str):
        return False, "Invalid sample format"
    if available_samples and sample not in available_samples and sample != "All Samples":
        return False, f"Sample '{sample}' not found"
    return True, None


def validate_dataframe(df: Any, required_columns: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate that a value is a non-empty DataFrame with required columns.

    Args:
        df: Value to validate
        required_columns: List of required column names

    Returns:
        Tuple of (is_valid, error_message)
    """
    if df is None:
        return False, "No data available"
    if not isinstance(df, pd.DataFrame):
        return False, "Invalid data format"
    if df.empty:
        return False, "No data available"
    if required_columns:
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            return False, f"Missing required columns: {', '.join(missing)}"
    return True, None


def validate_numeric(value: Any, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate that a value is numeric and within bounds.

    Args:
        value: Value to validate
        min_val: Minimum allowed value (optional)
        max_val: Maximum allowed value (optional)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if value is None:
        return False, "Value is required"
    try:
        num = float(value)
        if np.isnan(num) or np.isinf(num):
            return False, "Value must be a valid number"
        if min_val is not None and num < min_val:
            return False, f"Value must be at least {min_val}"
        if max_val is not None and num > max_val:
            return False, f"Value must be at most {max_val}"
        return True, None
    except (TypeError, ValueError):
        return False, "Value must be a number"


def validate_path(path: Any, must_exist: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Validate a file or directory path.

    Args:
        path: Path to validate
        must_exist: Whether the path must exist

    Returns:
        Tuple of (is_valid, error_message)
    """
    if path is None or not isinstance(path, str) or not path.strip():
        return False, "Path is required"
    path = path.strip()
    if ".." in path:
        return False, "Path contains invalid characters"
    if must_exist and not os.path.exists(path):
        return False, f"Path does not exist: {path}"
    return True, None


# =============================================================================
# Empty Figure Creation
# =============================================================================

def empty_figure(message: str = "No data available", height: int = 400) -> go.Figure:
    """
    Create an empty figure with a centered message.

    Use this when data is unavailable or invalid to show a clear message
    instead of a blank or broken chart.

    Args:
        message: Message to display
        height: Figure height in pixels

    Returns:
        Plotly figure with centered message
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=16, color="#6c757d"),
        align="center"
    )
    fig.update_layout(
        height=height,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig


# =============================================================================
# Callback Input Validation Decorator
# =============================================================================

def validate_callback_inputs(
    config_param: Optional[str] = "config",
    sample_param: Optional[str] = None,
    return_on_invalid: Any = no_update
):
    """
    Decorator to validate common callback inputs.

    Automatically validates config and sample parameters if specified.
    Returns the specified value if validation fails.

    Args:
        config_param: Name of config parameter in callback args (None to skip)
        sample_param: Name of sample parameter in callback args (None to skip)
        return_on_invalid: Value to return if validation fails

    Returns:
        Decorator function

    Example:
        @app.callback(Output(...), Input(...), State("app-config", "data"))
        @validate_callback_inputs(config_param="config")
        def my_callback(n_intervals, config):
            # config is guaranteed to be a valid dict here
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Find config in args or kwargs
            if config_param:
                config = kwargs.get(config_param)
                if config is None:
                    # Try to find it in positional args by parameter name
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if config_param in params:
                        idx = params.index(config_param)
                        if idx < len(args):
                            config = args[idx]

                if config is not None:
                    is_valid, error = validate_config(config)
                    if not is_valid:
                        logging.debug(f"Callback validation failed for {func.__name__}: {error}")
                        return return_on_invalid

            # Find sample in args or kwargs
            if sample_param:
                sample = kwargs.get(sample_param)
                if sample is None:
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if sample_param in params:
                        idx = params.index(sample_param)
                        if idx < len(args):
                            sample = args[idx]

                if sample is not None:
                    is_valid, error = validate_sample(sample)
                    if not is_valid:
                        logging.debug(f"Callback validation failed for {func.__name__}: {error}")
                        return return_on_invalid

            return func(*args, **kwargs)
        return wrapper
    return decorator


def get_pipeline_output_dir(config: Optional[Dict]) -> Optional[str]:
    """
    Get the directory where Nextflow pipeline output is stored.

    This returns 'results_output_directory' (where Nextflow --outdir points),
    NOT 'main_dir' (which is the internal analysis metadata directory).

    Args:
        config: Application configuration dictionary

    Returns:
        Valid output directory path or None if not configured/doesn't exist
    """
    if not config:
        return None

    # Primary: use results_output_directory (Nextflow --outdir)
    output_dir = config.get("results_output_directory", "")
    if output_dir and os.path.exists(output_dir):
        return output_dir

    # Fallback: try main_dir (legacy compatibility)
    main_dir = config.get("main_dir", "")
    if main_dir and os.path.exists(main_dir):
        return main_dir

    return None


def validate_config_and_get_main_dir(config: Optional[Dict]) -> Optional[str]:
    """
    Validate config and return the pipeline output directory or None if invalid.

    Note: This function now returns the pipeline OUTPUT directory (where kraken2/,
    fastp/, etc. are located), not the internal analysis directory.

    Args:
        config: Application configuration dictionary

    Returns:
        Valid output directory path or None if config is invalid
    """
    return get_pipeline_output_dir(config)


def create_empty_alert(
    message: str = "Loading...",
    color: str = "light"
) -> dbc.Alert:
    """
    Create a standard empty/loading alert component.

    Args:
        message: Alert message text
        color: Bootstrap color class

    Returns:
        Alert component
    """
    return dbc.Alert(message, color=color, className="text-center")


def create_error_alert(message: str) -> dbc.Alert:
    """
    Create a standard error alert component.

    Args:
        message: Error message text

    Returns:
        Alert component with error styling
    """
    return dbc.Alert(
        [
            html.I(className="bi bi-exclamation-triangle me-2"),
            message
        ],
        color="danger",
        className="text-center"
    )


def create_info_alert(message: str) -> dbc.Alert:
    """
    Create a standard info alert component.

    Args:
        message: Info message text

    Returns:
        Alert component with info styling
    """
    return dbc.Alert(
        [
            html.I(className="bi bi-info-circle me-2"),
            message
        ],
        color="info",
        className="text-center"
    )


def safe_load_kraken_data(
    main_dir: str,
    sample: str
) -> pd.DataFrame:
    """
    Load Kraken data with consistent error handling.

    Args:
        main_dir: Main output directory
        sample: Sample name or "All Samples"

    Returns:
        DataFrame with Kraken2 data, empty DataFrame on error
    """
    try:
        return load_kraken_data(main_dir, sample)
    except Exception as e:
        logging.warning(f"Could not load Kraken data: {e}")
        return pd.DataFrame()


def get_classification_stats(
    kraken_df: pd.DataFrame
) -> Tuple[int, int, float]:
    """
    Calculate classification statistics from Kraken2 data.

    Args:
        kraken_df: DataFrame with Kraken2 report data

    Returns:
        Tuple of (classified_reads, unclassified_reads, classification_rate)
    """
    if kraken_df.empty:
        return 0, 0, 0.0

    # Ensure 'name' column exists and has proper type
    if 'name' not in kraken_df.columns:
        return 0, 0, 0.0

    # Create a copy and ensure string type for safe string operations
    df = kraken_df.copy()
    df['name'] = df['name'].astype(str)

    # In Kraken2: root cumul_reads = classified, unclassified cumul_reads = unclassified
    root = df[df['name'].str.strip() == 'root']
    unclassified = df[df['name'].str.strip() == 'unclassified']

    classified_reads = int(root.iloc[0]['cumul_reads']) if not root.empty else 0
    unclassified_reads = int(unclassified.iloc[0]['cumul_reads']) if not unclassified.empty else 0

    total = classified_reads + unclassified_reads
    rate = (classified_reads / total * 100) if total > 0 else 0.0

    return classified_reads, unclassified_reads, rate


def get_total_kraken_reads(kraken_df: pd.DataFrame) -> int:
    """
    Get total reads from Kraken2 data (classified + unclassified).

    Args:
        kraken_df: DataFrame with Kraken2 report data

    Returns:
        Total number of reads
    """
    classified, unclassified, _ = get_classification_stats(kraken_df)
    return classified + unclassified


def format_number(value: int) -> str:
    """
    Format a number with thousands separator.

    Args:
        value: Integer value to format

    Returns:
        Formatted string with commas
    """
    return f"{value:,}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format a percentage value.

    Args:
        value: Percentage value (0-100)
        decimals: Number of decimal places

    Returns:
        Formatted string with percent sign
    """
    return f"{value:.{decimals}f}%"


def format_bp(value: int) -> str:
    """
    Format base pairs with appropriate unit (bp, Kb, Mb, Gb).

    Args:
        value: Number of base pairs

    Returns:
        Formatted string with appropriate unit
    """
    if value >= 1e9:
        return f"{value/1e9:.2f} Gb"
    elif value >= 1e6:
        return f"{value/1e6:.2f} Mb"
    elif value >= 1e3:
        return f"{value/1e3:.2f} Kb"
    else:
        return f"{value:,} bp"
