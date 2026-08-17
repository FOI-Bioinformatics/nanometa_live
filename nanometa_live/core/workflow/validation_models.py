"""
Data models for on-demand BLAST/minimap2 validation.

Split out of ``OnDemandValidator`` (core/workflow/on_demand_validator.py,
2026-08-16 code-size remediation): these are plain data carriers with no
behaviour of their own. Re-exported from ``on_demand_validator`` so existing
``from nanometa_live.core.workflow.on_demand_validator import ValidationJob,
ValidationResult, ValidationStatus`` imports keep working unchanged.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class ValidationStatus(Enum):
    """Status of an on-demand validation job."""
    PENDING = "pending"
    DOWNLOADING_GENOME = "downloading_genome"
    BUILDING_BLAST_DB = "building_blast_db"
    EXTRACTING_READS = "extracting_reads"
    RUNNING_BLAST = "running_blast"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ValidationJob:
    """Represents an on-demand validation job."""
    taxid: int
    name: str
    sample: str
    status: ValidationStatus = ValidationStatus.PENDING
    progress_percent: int = 0
    status_message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Results
    total_reads: int = 0
    extracted_reads: int = 0
    validated_reads: int = 0
    validation_rate: float = 0.0
    avg_identity: float = 0.0

    # Paths
    genome_path: Optional[Path] = None
    blast_db_path: Optional[Path] = None
    extracted_fasta: Optional[Path] = None
    blast_results: Optional[Path] = None

    error_message: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of BLAST validation."""
    taxid: int
    name: str
    sample: str
    total_classified_reads: int
    extracted_reads: int
    validated_reads: int
    validation_rate: float
    avg_identity: float
    min_identity: float
    max_identity: float
    success: bool
    error_message: Optional[str] = None
    blast_output_file: Optional[Path] = None
