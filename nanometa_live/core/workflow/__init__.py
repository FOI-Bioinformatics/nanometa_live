"""
Workflow management module for Nanometa Live.

This package handles the processing pipeline and all associated
workflow management functionality.
"""

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.workflow.snakemake_manager import (
    SnakemakeManager,
    SnakemakeExecutor,
)
from nanometa_live.core.workflow.data_processor import DataProcessor
from nanometa_live.core.workflow.pipeline_runner import run_pipeline

__all__ = [
    "BackendManager",
    "SnakemakeManager",
    "SnakemakeExecutor",
    "DataProcessor",
    "run_pipeline",
]
