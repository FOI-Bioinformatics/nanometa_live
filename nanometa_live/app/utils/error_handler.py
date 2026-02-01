"""
Centralized error handling with actionable user messages.

This module provides a mapping from common exceptions to user-friendly error
messages with suggested actions for resolution. It helps users understand
what went wrong and how to fix it.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List, Callable
import traceback

import dash_bootstrap_components as dbc
from dash import html


class ErrorCategory(Enum):
    """Categories of errors for grouping and handling."""
    CONFIGURATION = "configuration"
    FILE_SYSTEM = "file_system"
    PIPELINE = "pipeline"
    DATA_PARSING = "data_parsing"
    NETWORK = "network"
    DATABASE = "database"
    VALIDATION = "validation"
    PERMISSION = "permission"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


@dataclass
class ActionableError:
    """Represents an error with user-friendly message and actions."""
    title: str
    message: str
    suggestions: List[str]
    category: ErrorCategory
    severity: str = "error"  # error, warning, info
    show_technical: bool = False
    technical_details: str = ""
    retry_id: Optional[str] = None  # Button ID for retry action

    def to_alert(self, include_technical: bool = False) -> dbc.Alert:
        """Convert to a Dash Bootstrap alert component."""
        icon_map = {
            "error": "bi-exclamation-triangle-fill",
            "warning": "bi-exclamation-circle-fill",
            "info": "bi-info-circle-fill"
        }
        color_map = {
            "error": "danger",
            "warning": "warning",
            "info": "info"
        }

        children = [
            html.H5([
                html.I(className=f"bi {icon_map.get(self.severity, 'bi-exclamation-triangle-fill')} me-2"),
                self.title
            ], className="alert-heading"),
            html.P(self.message, className="mb-2"),
        ]

        if self.suggestions:
            children.append(html.Hr())
            children.append(html.P("Suggested actions:", className="mb-1 fw-bold"))
            children.append(html.Ul([
                html.Li(suggestion) for suggestion in self.suggestions
            ]))

        if include_technical and self.technical_details:
            children.append(html.Hr())
            children.append(html.Details([
                html.Summary("Technical details", className="text-muted"),
                html.Pre(
                    self.technical_details,
                    style={
                        "fontSize": "0.8rem",
                        "backgroundColor": "#f8f9fa",
                        "padding": "0.5rem",
                        "borderRadius": "4px",
                        "maxHeight": "150px",
                        "overflow": "auto"
                    }
                )
            ]))

        if self.retry_id:
            children.append(html.Hr())
            children.append(
                dbc.Button(
                    [html.I(className="bi bi-arrow-clockwise me-2"), "Retry"],
                    id=self.retry_id,
                    color="warning",
                    size="sm"
                )
            )

        return dbc.Alert(
            children,
            color=color_map.get(self.severity, "danger"),
            dismissable=True,
            className="mb-3"
        )


# Exception to ActionableError mapping
ERROR_MAPPINGS: Dict[str, Callable[[Exception], ActionableError]] = {}


def register_error_handler(exception_types: List[type]):
    """Decorator to register an error handler for exception types."""
    def decorator(func: Callable[[Exception], ActionableError]):
        for exc_type in exception_types:
            ERROR_MAPPINGS[exc_type.__name__] = func
        return func
    return decorator


# File System Errors
@register_error_handler([FileNotFoundError])
def handle_file_not_found(exc: Exception) -> ActionableError:
    path = str(exc).split("'")[1] if "'" in str(exc) else "the specified file"
    return ActionableError(
        title="File Not Found",
        message=f"The file or directory could not be found: {path}",
        suggestions=[
            "Verify the file path is correct in the configuration",
            "Check that the file exists and has not been moved or deleted",
            "Ensure you have read permissions for the file location",
            "If this is a new analysis, run the pipeline first to generate output files"
        ],
        category=ErrorCategory.FILE_SYSTEM
    )


@register_error_handler([PermissionError])
def handle_permission_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Permission Denied",
        message="Unable to access the file or directory due to permission restrictions.",
        suggestions=[
            "Check that you have read/write permissions for the directory",
            "On Unix/Mac: try 'chmod 755' or 'chown' to fix permissions",
            "Ensure the file is not locked by another process",
            "Try running with elevated privileges if appropriate"
        ],
        category=ErrorCategory.PERMISSION
    )


@register_error_handler([IsADirectoryError, NotADirectoryError])
def handle_directory_error(exc: Exception) -> ActionableError:
    is_dir = isinstance(exc, IsADirectoryError)
    return ActionableError(
        title="Directory/File Mismatch",
        message=f"Expected a {'file' if is_dir else 'directory'} but found a {'directory' if is_dir else 'file'}.",
        suggestions=[
            "Check that the path points to the correct type (file vs directory)",
            "Verify the configuration paths are correctly set",
            "Review the input and output directory settings"
        ],
        category=ErrorCategory.FILE_SYSTEM
    )


@register_error_handler([OSError, IOError])
def handle_os_error(exc: Exception) -> ActionableError:
    error_msg = str(exc)
    if "No space left" in error_msg:
        return ActionableError(
            title="Disk Space Full",
            message="The disk has run out of space.",
            suggestions=[
                "Free up disk space by removing unnecessary files",
                "Check available space with 'df -h' (Unix/Mac) or Disk Management (Windows)",
                "Consider using a different output directory with more space",
                "Clean up old analysis results if they are no longer needed"
            ],
            category=ErrorCategory.RESOURCE,
            severity="error"
        )
    elif "Too many open files" in error_msg:
        return ActionableError(
            title="Too Many Open Files",
            message="The system limit for open files has been reached.",
            suggestions=[
                "Close other applications to free up file handles",
                "Increase the system's open file limit (ulimit -n)",
                "Process data in smaller batches"
            ],
            category=ErrorCategory.RESOURCE
        )
    else:
        return ActionableError(
            title="System Error",
            message=f"A system error occurred: {error_msg}",
            suggestions=[
                "Check system resources (disk space, memory)",
                "Verify file system permissions",
                "Review the technical details for more information"
            ],
            category=ErrorCategory.FILE_SYSTEM,
            show_technical=True,
            technical_details=traceback.format_exc()
        )


# Data Parsing Errors
@register_error_handler([ValueError])
def handle_value_error(exc: Exception) -> ActionableError:
    error_msg = str(exc)
    if "could not convert" in error_msg.lower() or "invalid literal" in error_msg.lower():
        return ActionableError(
            title="Data Format Error",
            message="Unable to parse the data due to unexpected format.",
            suggestions=[
                "Check that input files are in the expected format",
                "Verify Kraken2 reports are standard format (.kreport2 or .kraken2.report.txt)",
                "Ensure FASTP JSON files are not corrupted",
                "Re-run the pipeline to regenerate output files"
            ],
            category=ErrorCategory.DATA_PARSING
        )
    else:
        return ActionableError(
            title="Invalid Value",
            message=f"An invalid value was encountered: {error_msg}",
            suggestions=[
                "Check configuration values are within valid ranges",
                "Verify input data is properly formatted",
                "Review the technical details for the specific issue"
            ],
            category=ErrorCategory.VALIDATION,
            show_technical=True,
            technical_details=str(exc)
        )


@register_error_handler([KeyError])
def handle_key_error(exc: Exception) -> ActionableError:
    key = str(exc).strip("'\"")
    return ActionableError(
        title="Missing Data Field",
        message=f"Required data field '{key}' was not found.",
        suggestions=[
            "Ensure the pipeline has completed successfully",
            "Check that output files contain all expected fields",
            "Verify the Kraken2 database and pipeline version are compatible",
            "Try re-running the analysis with a fresh output directory"
        ],
        category=ErrorCategory.DATA_PARSING
    )


@register_error_handler([IndexError])
def handle_index_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Data Out of Range",
        message="Attempted to access data that does not exist.",
        suggestions=[
            "This may indicate empty or incomplete output files",
            "Check that the pipeline has produced valid results",
            "Verify input files contain data (not empty)",
            "Re-run the analysis if files appear corrupted"
        ],
        category=ErrorCategory.DATA_PARSING
    )


# Network and API Errors
@register_error_handler([ConnectionError, ConnectionRefusedError, ConnectionResetError])
def handle_connection_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Connection Failed",
        message="Unable to establish a network connection.",
        suggestions=[
            "Check your internet connection",
            "Verify that any required services are running",
            "Check if a firewall is blocking the connection",
            "Try again in a few moments if it's a temporary issue"
        ],
        category=ErrorCategory.NETWORK
    )


@register_error_handler([TimeoutError])
def handle_timeout_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Operation Timed Out",
        message="The operation took too long and was cancelled.",
        suggestions=[
            "Check network connectivity for API calls",
            "For local operations, verify system resources are not overloaded",
            "Try processing smaller batches of data",
            "Increase timeout settings if available"
        ],
        category=ErrorCategory.NETWORK,
        severity="warning"
    )


# Memory and Resource Errors
@register_error_handler([MemoryError])
def handle_memory_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Out of Memory",
        message="The system has run out of available memory.",
        suggestions=[
            "Close other applications to free up memory",
            "Process data in smaller batches",
            "Reduce the number of concurrent samples",
            "Consider using a machine with more RAM for large datasets"
        ],
        category=ErrorCategory.RESOURCE,
        severity="error"
    )


# Type Errors
@register_error_handler([TypeError])
def handle_type_error(exc: Exception) -> ActionableError:
    return ActionableError(
        title="Type Mismatch",
        message="An unexpected data type was encountered.",
        suggestions=[
            "This usually indicates a bug or incompatible data format",
            "Try reloading the configuration",
            "Clear the cache and restart the application",
            "Report this issue if it persists"
        ],
        category=ErrorCategory.DATA_PARSING,
        show_technical=True,
        technical_details=traceback.format_exc()
    )


# Configuration Errors
@register_error_handler([AttributeError])
def handle_attribute_error(exc: Exception) -> ActionableError:
    attr = str(exc).split("'")[-2] if "'" in str(exc) else "unknown"
    return ActionableError(
        title="Configuration Error",
        message=f"Missing or invalid configuration attribute: {attr}",
        suggestions=[
            "Check that all required configuration fields are set",
            "Reload the configuration from the Configuration tab",
            "Verify the YAML configuration file syntax is correct",
            "Reset to default configuration if issues persist"
        ],
        category=ErrorCategory.CONFIGURATION
    )


# Import/Module Errors
@register_error_handler([ImportError, ModuleNotFoundError])
def handle_import_error(exc: Exception) -> ActionableError:
    module = str(exc).split("'")[1] if "'" in str(exc) else "unknown module"
    return ActionableError(
        title="Missing Dependency",
        message=f"Required module '{module}' is not installed.",
        suggestions=[
            "Install the missing package: pip install <package_name>",
            "Ensure you are using the correct Python environment",
            "Reinstall nanometa_live to get all dependencies",
            "Check the installation documentation"
        ],
        category=ErrorCategory.CONFIGURATION
    )


def get_actionable_error(
    exc: Exception,
    context: Optional[str] = None,
    include_traceback: bool = False
) -> ActionableError:
    """
    Convert an exception to an ActionableError with user-friendly message.

    Args:
        exc: The exception to convert
        context: Optional context string describing what was being attempted
        include_traceback: Whether to include the full traceback in technical details

    Returns:
        ActionableError with user-friendly message and suggestions
    """
    exc_type = type(exc).__name__

    # Look up handler for this exception type
    handler = ERROR_MAPPINGS.get(exc_type)

    if handler:
        error = handler(exc)
    else:
        # Generic fallback for unmapped exceptions
        error = ActionableError(
            title="Unexpected Error",
            message=f"An unexpected error occurred: {str(exc)[:200]}",
            suggestions=[
                "Try the operation again",
                "Restart the application if the issue persists",
                "Check the technical details for more information",
                "Report persistent issues at the GitHub repository"
            ],
            category=ErrorCategory.UNKNOWN,
            show_technical=True
        )

    # Add context if provided
    if context:
        error.message = f"While {context}: {error.message}"

    # Add traceback if requested
    if include_traceback:
        error.show_technical = True
        error.technical_details = traceback.format_exc()

    return error


def create_error_toast(
    error: ActionableError,
    duration: int = 10000
) -> Dict[str, Any]:
    """
    Create a toast notification dict for an ActionableError.

    Args:
        error: The ActionableError to display
        duration: How long to show the toast (milliseconds)

    Returns:
        Dict suitable for the toast-message store
    """
    icon_map = {
        "error": "bi-exclamation-triangle-fill",
        "warning": "bi-exclamation-circle-fill",
        "info": "bi-info-circle-fill"
    }

    # Include first suggestion in the toast
    message = error.message
    if error.suggestions:
        message += f" Try: {error.suggestions[0]}"

    return {
        "header": error.title,
        "body": message,
        "icon": icon_map.get(error.severity, "bi-exclamation-triangle-fill"),
        "duration": duration,
        "type": error.severity
    }


def log_and_create_alert(
    callback_name: str,
    exc: Exception,
    context: Optional[str] = None,
    include_technical: bool = False
) -> dbc.Alert:
    """
    Log an error and create a user-friendly alert component.

    This is a convenience function that combines logging with UI feedback.

    Args:
        callback_name: Name of the callback where error occurred
        exc: The exception
        context: Optional context string
        include_technical: Whether to show technical details

    Returns:
        dbc.Alert component with actionable error message
    """
    # Log the error
    logging.error(
        f"Callback '{callback_name}' error: {type(exc).__name__}: {exc}\n"
        f"Traceback:\n{traceback.format_exc()}"
    )

    # Get actionable error
    error = get_actionable_error(exc, context=context, include_traceback=include_technical)

    return error.to_alert(include_technical=include_technical)


# Pipeline-specific error messages
PIPELINE_ERROR_MESSAGES = {
    "nextflow_not_found": ActionableError(
        title="Nextflow Not Found",
        message="The Nextflow workflow engine is not installed or not in PATH.",
        suggestions=[
            "Install Nextflow: curl -s https://get.nextflow.io | bash",
            "Ensure Nextflow is in your PATH",
            "Verify with: nextflow -version",
            "See https://www.nextflow.io/docs/latest/getstarted.html"
        ],
        category=ErrorCategory.PIPELINE
    ),
    "docker_not_running": ActionableError(
        title="Docker Not Running",
        message="Docker is required but is not running.",
        suggestions=[
            "Start Docker Desktop (Mac/Windows) or the Docker daemon (Linux)",
            "Verify Docker is running: docker info",
            "Switch to Singularity profile if Docker is not available",
            "Use Conda profile as an alternative"
        ],
        category=ErrorCategory.PIPELINE
    ),
    "singularity_not_found": ActionableError(
        title="Singularity Not Found",
        message="Singularity container runtime is not installed.",
        suggestions=[
            "Install Singularity/Apptainer",
            "Switch to Docker profile if available",
            "Use Conda profile as an alternative"
        ],
        category=ErrorCategory.PIPELINE
    ),
    "kraken_db_not_found": ActionableError(
        title="Kraken2 Database Not Found",
        message="The specified Kraken2 database does not exist.",
        suggestions=[
            "Verify the database path in configuration",
            "Download a Kraken2 database using kraken2-build",
            "Use the built-in database download feature",
            "Check for typos in the database path"
        ],
        category=ErrorCategory.CONFIGURATION
    ),
    "invalid_input_dir": ActionableError(
        title="Invalid Input Directory",
        message="The input directory does not exist or contains no FASTQ files.",
        suggestions=[
            "Verify the input directory path",
            "Check that FASTQ files exist in the directory",
            "For barcoded data, ensure barcode subdirectories exist",
            "Verify file extensions (.fastq, .fastq.gz, .fq, .fq.gz)"
        ],
        category=ErrorCategory.CONFIGURATION
    ),
    "pipeline_failed": ActionableError(
        title="Pipeline Execution Failed",
        message="The Nextflow pipeline encountered an error during execution.",
        suggestions=[
            "Check the Nextflow log files for details",
            "Verify all input paths and database configurations",
            "Try running with -resume to continue from last checkpoint",
            "Check system resources (memory, disk space)"
        ],
        category=ErrorCategory.PIPELINE
    ),
    "no_samples_found": ActionableError(
        title="No Samples Detected",
        message="No valid samples were found in the input directory.",
        suggestions=[
            "Check that FASTQ files exist in the input directory",
            "Verify the sample handling mode matches your data structure",
            "For barcoded data, ensure proper barcode directory naming",
            "Check file extensions match expected formats"
        ],
        category=ErrorCategory.DATA_PARSING
    )
}


def get_pipeline_error(error_key: str) -> ActionableError:
    """
    Get a predefined pipeline error message.

    Args:
        error_key: Key for the pipeline error type

    Returns:
        ActionableError for the specified pipeline error
    """
    return PIPELINE_ERROR_MESSAGES.get(error_key, ActionableError(
        title="Pipeline Error",
        message="An error occurred in the analysis pipeline.",
        suggestions=[
            "Check the pipeline logs for details",
            "Verify configuration settings",
            "Try restarting the analysis"
        ],
        category=ErrorCategory.PIPELINE
    ))
