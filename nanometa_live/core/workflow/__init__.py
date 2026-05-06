"""
Workflow management module for Nanometa Live.

This package handles the processing pipeline and all associated
workflow management functionality using Nextflow via the nanometanf
pipeline. Earlier versions also shipped a Snakemake backend; that
code path has been removed.
"""

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.workflow.on_demand_validator import (
    OnDemandValidator,
    ValidationJob,
    ValidationResult,
    ValidationStatus,
)
from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, ReadinessReport
from nanometa_live.core.workflow.mobile_lab_preparer import MobileLabPreparer, PreparationResult
from nanometa_live.core.workflow.bundle_manager import BundleManager

__all__ = [
    "BackendManager",
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
