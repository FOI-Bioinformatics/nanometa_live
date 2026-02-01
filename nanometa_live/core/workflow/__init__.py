"""
Workflow management module for Nanometa Live.

This package handles the processing pipeline and all associated
workflow management functionality using Nextflow.

Note: SnakemakeManager is deprecated. The application now uses NextflowManager
via BackendManager. snakemake_manager.py is kept for backward compatibility
with standalone scripts but is not imported by default.
"""

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.workflow.data_processor import DataProcessor
from nanometa_live.core.workflow.pipeline_runner import run_pipeline
from nanometa_live.core.workflow.on_demand_validator import (
    OnDemandValidator,
    ValidationJob,
    ValidationResult,
    ValidationStatus,
)
from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, ReadinessReport
from nanometa_live.core.workflow.mobile_lab_preparer import MobileLabPreparer, PreparationResult
from nanometa_live.core.workflow.bundle_manager import BundleManager

# SnakemakeManager removed from imports - use NextflowManager via BackendManager

__all__ = [
    "BackendManager",
    "DataProcessor",
    "run_pipeline",
    "OnDemandValidator",
    "ValidationJob",
    "ValidationResult",
    "ValidationStatus",
    "ReadinessChecker",
    "ReadinessReport",
    "MobileLabPreparer",
    "PreparationResult",
    "BundleManager",
]
