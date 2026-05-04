"""
Pipeline runner for Nanometa Live (DEPRECATED).

This module previously provided Snakemake pipeline execution. The application
now uses NextflowManager via BackendManager for all pipeline operations.

This file is retained as a stub so that any external scripts importing from
nanometa_live.core.workflow.pipeline_runner receive a clear deprecation message
rather than an ImportError.
"""

import warnings


def _deprecated(name: str):
    """Emit a deprecation warning for removed Snakemake functions."""
    warnings.warn(
        f"{name}() is deprecated and has no effect. "
        "Use NextflowManager via BackendManager instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def run_pipeline(config_path: str, cores: int = 1, dryrun: bool = False) -> bool:
    """Deprecated. Use NextflowManager via BackendManager."""
    _deprecated("run_pipeline")
    return False


def run_pipeline_python_api(
    config_path: str, cores: int = 1, dryrun: bool = False
) -> bool:
    """Deprecated. Use NextflowManager via BackendManager."""
    _deprecated("run_pipeline_python_api")
    return False


def setup_project_directories(main_dir: str) -> bool:
    """Deprecated. Use NextflowManager via BackendManager."""
    _deprecated("setup_project_directories")
    return False


def check_pipeline_requirements(config: dict) -> tuple:
    """Deprecated. Use ReadinessChecker instead."""
    _deprecated("check_pipeline_requirements")
    return False, "Deprecated: use ReadinessChecker"


def check_pipeline_status(main_dir: str) -> dict:
    """Deprecated. Use BackendManager.get_status() instead."""
    _deprecated("check_pipeline_status")
    return {"errors": ["Deprecated: use BackendManager.get_status()"]}
