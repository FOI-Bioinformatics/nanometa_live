"""
On-demand BLAST validation for unexpected organisms.

This module provides validation capability for organisms discovered during
a sequencing run that were not originally on the watchlist. It allows users
to validate Kraken2 classifications without re-running the full pipeline.

Workflow:
1. User sees unexpected organism in Kraken2 output
2. User triggers on-demand validation
3. System downloads reference genome (if missing)
4. System builds BLAST database (if missing)
5. System extracts reads classified to that taxid
6. System runs BLAST validation
7. Results displayed in UI
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nanometa_live.core.utils.read_extractor import ReadExtractor


logger = logging.getLogger(__name__)

# Default on-demand validation timeout (minutes) when config does not set one.
_DEFAULT_VALIDATION_TIMEOUT_MINUTES = 30


def _is_int_str(value: Any) -> bool:
    """True if ``value`` is a string (or value) that parses as an int."""
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _genome_file_looks_valid(path: Path) -> bool:
    """Cheap sanity check that ``path`` is a non-empty FASTA file.

    has_genome() only tests existence; a zero-byte or truncated download
    passes it but fails opaquely once Nextflow tries to align against it.
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            first = fh.readline().lstrip()
        return first.startswith(">")
    except OSError:
        return False


def _validation_timeout_seconds(config: Optional[Dict[str, Any]]) -> int:
    """Resolve the subprocess timeout (seconds) from config, floored at 60s."""
    minutes = (config or {}).get(
        "validation_timeout_minutes", _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    )
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        minutes = _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    return max(60, int(minutes * 60))


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


class OnDemandValidator:
    """
    Orchestrates on-demand BLAST validation for unexpected organisms.

    This class manages the full validation workflow including genome download,
    BLAST database building, read extraction, and BLAST execution.
    """

    def __init__(
        self,
        results_dir: str,
        input_dir: Optional[str] = None,
        cache_dir: Optional[str] = None,
        genome_manager: Optional[Any] = None
    ):
        """
        Initialize the on-demand validator.

        Args:
            results_dir: Path to pipeline results directory
            input_dir: Path to original FASTQ input directory
            cache_dir: Path to cache directory for genomes/BLAST DBs
            genome_manager: Optional GenomeDownloadManager instance
        """
        self.results_dir = Path(results_dir)
        self.input_dir = Path(input_dir) if input_dir else None

        # Set up cache directory. genomes/ and blast/ are GLOBAL (shared
        # across analyses), so resolve from the data_dir env (set by the CLI
        # from --data-dir) rather than hardcoding ~/.nanometa.
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            from nanometa_live.core.utils.paths import get_data_dir_from_env
            self.cache_dir = Path(get_data_dir_from_env())

        self.genomes_dir = self.cache_dir / "genomes"
        self.blast_dir = self.cache_dir / "blast"

        self.genomes_dir.mkdir(parents=True, exist_ok=True)
        self.blast_dir.mkdir(parents=True, exist_ok=True)

        # Validation output directory
        self.validation_dir = self.results_dir / "on_demand_validation"
        self.validation_dir.mkdir(parents=True, exist_ok=True)

        # Read extractor
        self.read_extractor = ReadExtractor(str(self.results_dir), str(self.input_dir) if self.input_dir else None)

        # Optional genome manager for downloads
        self._genome_manager = genome_manager

        # Active jobs
        self._jobs: Dict[str, ValidationJob] = {}

        logger.info(f"Initialized OnDemandValidator with results_dir: {self.results_dir}")

    @property
    def genome_manager(self):
        """Lazy load genome manager to avoid circular imports."""
        if self._genome_manager is None:
            try:
                from nanometa_live.core.utils.genome_manager import GenomeDownloadManager
                self._genome_manager = GenomeDownloadManager(str(self.cache_dir))
            except ImportError:
                logger.warning("GenomeDownloadManager not available")
        return self._genome_manager

    def _get_job_id(self, taxid: int, sample: str) -> str:
        """Generate unique job ID."""
        return f"{sample}_{taxid}"

    def has_genome(self, taxid: int) -> bool:
        """Check if a reference genome exists for a taxid."""
        genome_path = self.genomes_dir / f"{taxid}.fasta"
        return genome_path.exists()

    def has_blast_db(self, taxid: int) -> bool:
        """Check if a BLAST database exists for a taxid."""
        blast_db = self.blast_dir / f"{taxid}.fasta.nhr"
        return blast_db.exists()

    def download_genome(
        self,
        taxid: int,
        name: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Optional[Path]:
        """
        Download reference genome for a taxid.

        Args:
            taxid: Taxonomy ID
            name: Species name (for GTDB/NCBI queries)
            progress_callback: Optional callback(message, percent)

        Returns:
            Path to downloaded genome or None if failed
        """
        if self.has_genome(taxid):
            logger.info(f"Genome already exists for taxid {taxid}")
            return self.genomes_dir / f"{taxid}.fasta"

        if not self.genome_manager:
            logger.error("Genome manager not available for download")
            return None

        try:
            if progress_callback:
                progress_callback(f"Downloading genome for {name}...", 0)

            # Use genome manager to download
            path = self.genome_manager.download_genome(taxid, name)

            if path and path.exists():
                logger.info(f"Downloaded genome for taxid {taxid}: {path}")
                return path
            else:
                logger.error(f"Failed to download genome for taxid {taxid}")
                return None

        except (OSError, AttributeError, ValueError) as e:
            logger.exception(f"Error downloading genome for taxid {taxid}: {e}")
            return None

    def build_blast_db(
        self,
        taxid: int,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> bool:
        """
        Build BLAST database for a taxid.

        Args:
            taxid: Taxonomy ID
            progress_callback: Optional callback(message, percent)

        Returns:
            True if successful, False otherwise
        """
        if self.has_blast_db(taxid):
            logger.info(f"BLAST database already exists for taxid {taxid}")
            return True

        genome_path = self.genomes_dir / f"{taxid}.fasta"
        if not genome_path.exists():
            logger.error(f"Genome not found for taxid {taxid}")
            return False

        try:
            if progress_callback:
                progress_callback(f"Building BLAST database for taxid {taxid}...", 0)

            blast_db_path = self.blast_dir / f"{taxid}.fasta"

            cmd = [
                "makeblastdb",
                "-in", str(genome_path),
                "-dbtype", "nucl",
                "-out", str(blast_db_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )

            if self.has_blast_db(taxid):
                logger.info(f"Built BLAST database for taxid {taxid}")
                return True
            else:
                logger.error(f"BLAST database creation failed for taxid {taxid}")
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"makeblastdb failed for taxid {taxid}: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error("makeblastdb not found - BLAST+ toolkit not installed?")
            return False
        except (subprocess.TimeoutExpired, PermissionError, OSError) as e:
            logger.exception(f"Error building BLAST database for taxid {taxid}: {e}")
            return False

    # Single accumulating pathogen genomes JSON. Living in
    # ``self.validation_dir`` keeps it next to the validation outputs
    # nanometanf writes; the same path is read back across calls so
    # each on-demand request appends its taxid to a stable file rather
    # than starting fresh.
    PATHOGEN_GENOMES_FILENAME = "pathogen_genomes.json"

    def _load_pathogen_genomes(self) -> Dict[str, str]:
        """Read the cumulative pathogen_genomes mapping (taxid -> genome
        FASTA path) if it exists. Returns empty dict on first call or
        when the file is missing/corrupt."""
        path = self.validation_dir / self.PATHOGEN_GENOMES_FILENAME
        if not path.exists():
            return {}
        try:
            import json as _json
            with open(path) as f:
                data = _json.load(f)
            if not isinstance(data, dict):
                return {}
            return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning(f"pathogen_genomes.json unreadable, starting fresh: {e}")
            return {}

    def _save_pathogen_genomes(self, mapping: Dict[str, str]) -> Path:
        """Atomically rewrite the cumulative pathogen_genomes mapping."""
        import json as _json
        path = self.validation_dir / self.PATHOGEN_GENOMES_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            _json.dump(mapping, f, indent=2, sort_keys=True)
        tmp.replace(path)
        return path

    def validate_via_nanometanf(
        self,
        taxid: int,
        name: str,
        sample: str,
        method: str = "blast",
        config: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Optional[ValidationResult]:
        """
        Run validation by delegating to nanometanf validation-only entry point.

        Cumulative + resume-friendly: each call appends ``taxid`` to a
        single ``pathogen_genomes.json`` (kept under ``self.validation_dir``)
        and invokes ``nextflow run -resume`` against the main pipeline's
        outdir. Nextflow's per-(sample, taxid) work cache means previously-
        validated pairs are skipped and only the newly-added taxid actually
        runs through EXTRACT_READS_BY_TAXID + BLASTN_VALIDATION /
        MINIMAP2_VALIDATION. AGGREGATE_VALIDATION_RESULTS rebuilds the
        validation_results.json over the full taxid set.

        Args:
            taxid: Taxonomy ID
            name: Species name
            sample: Sample name
            method: 'blast', 'minimap2', or 'both'
            config: App configuration dict (for pipeline source, profile, etc.)
            progress_callback: Optional callback(message, percent)

        Returns:
            ValidationResult or None if nanometanf is unavailable
        """
        if progress_callback:
            progress_callback("Preparing nanometanf validation...", 5)

        config = config or {}

        # Determine pipeline source
        pipeline_source = config.get("pipeline_source", "")
        # Default profile is conda; the operator's environment is built
        # via the conda profile per the project's nf-core convention.
        pipeline_profile = config.get("pipeline_profile", "conda")

        if not pipeline_source:
            # Try to get from pipeline source config
            source_type = config.get("pipeline_source_type", "remote")
            if source_type == "local":
                pipeline_source = config.get("pipeline_local_path", "")
            else:
                branch = config.get("pipeline_branch", "master")
                pipeline_source = f"FOI-Bioinformatics/nanometanf -r {branch}"

        if not pipeline_source:
            logger.warning("No pipeline source configured for nanometanf delegation")
            return None

        # Ensure genome is available
        if not self.has_genome(taxid):
            if progress_callback:
                progress_callback(f"Downloading genome for {name}...", 10)
            genome_path = self.download_genome(taxid, name)
            if not genome_path:
                return None

        # Integrity gate: a zero-byte or non-FASTA genome passes has_genome()
        # (it only tests existence) but makes the Nextflow validation fail
        # opaquely downstream. Reject it here with a clear log instead.
        genome_fasta = self.genomes_dir / f"{taxid}.fasta"
        if not _genome_file_looks_valid(genome_fasta):
            logger.error(
                "Genome file for taxid %s is missing, empty, or not FASTA: %s",
                taxid, genome_fasta,
            )
            return None

        # Append the new taxid to the cumulative pathogen_genomes mapping.
        # Preserves prior taxids so Nextflow's resume cache reuses their
        # work; only the new (sample, taxid) pair runs end-to-end.
        mapping = self._load_pathogen_genomes()
        # Drop any non-numeric keys a corrupted prior file may carry so the
        # sorted(key=int) below and Nextflow's taxid filter never choke; this
        # also heals the on-disk file when it is re-saved.
        mapping = {k: v for k, v in mapping.items() if _is_int_str(k)}
        mapping[str(taxid)] = str(genome_fasta)
        try:
            genomes_json_path = self._save_pathogen_genomes(mapping)
        except (PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to write pathogen genomes JSON: {e}")
            return None

        # Comma-separated list of every taxid currently mapped. Nextflow
        # filters to this set in the validation subworkflow; passing the
        # whole list is what lets resume keep caches for previously-run
        # pairs while still adding the new taxid.
        taxids_to_validate = ",".join(sorted(mapping.keys(), key=int))

        if progress_callback:
            progress_callback("Launching nanometanf validation...", 20)

        # Build nextflow command. Reuses the main pipeline's outdir so
        # the work/ cache is shared with the original run (this is what
        # makes -resume effective for the on-demand path).
        outdir = self.results_dir
        cmd = [
            "nextflow", "run", pipeline_source,
            "-resume",
            "--validation_only",
            "--kraken2_output_dir", str(self.results_dir / "kraken2"),
            "--reads_dir", str(self.input_dir) if self.input_dir else str(self.results_dir),
            "--run_validation",
            "--validation_method", method,
            "--pathogen_genomes", str(genomes_json_path),
            "--taxids_to_validate", taxids_to_validate,
            "--outdir", str(outdir),
            "-profile", pipeline_profile,
        ]

        # Timeout is operator-configurable: large reference genomes or slow
        # I/O can need more than the historical hardcoded 30 minutes.
        timeout_seconds = _validation_timeout_seconds(config)

        try:
            logger.info(f"Running nanometanf validation: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            if result.returncode != 0:
                logger.error(f"nanometanf validation failed: {result.stderr}")
                return None

            if progress_callback:
                progress_callback("Parsing validation results...", 90)

            # Parse the output validation_results.json
            from nanometa_live.core.parsers.blast_validation_parser import ValidationParser
            parser = ValidationParser(str(outdir))
            results = parser.get_validation_results(sample=sample, taxid=taxid)

            if results:
                r = results[0]
                return ValidationResult(
                    taxid=taxid,
                    name=name,
                    sample=sample,
                    total_classified_reads=r.total_reads,
                    extracted_reads=r.total_reads,
                    validated_reads=r.validated_reads,
                    validation_rate=r.percent_validated,
                    avg_identity=r.percent_identity_mean,
                    min_identity=r.percent_identity_min,
                    max_identity=r.percent_identity_max,
                    success=True,
                )

            logger.warning("No validation results found in nanometanf output")
            return None

        except subprocess.TimeoutExpired:
            logger.error(
                "nanometanf validation timed out after %d minute(s); raise "
                "'validation_timeout_minutes' in config for large genomes",
                timeout_seconds // 60,
            )
            return None
        except FileNotFoundError:
            logger.warning("nextflow not found in PATH")
            return None
        except (subprocess.CalledProcessError, PermissionError, OSError,
                ImportError, AttributeError, KeyError) as e:
            logger.exception(f"nanometanf validation error: {e}")
            return None

    def validate_organism(
        self,
        taxid: int,
        name: str,
        sample: str,
        method: str = "blast",
        progress_callback: Optional[Callable[[str, int], None]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Run full on-demand validation for an organism via nanometanf.

        Delegates to ``validate_via_nanometanf`` so BLAST and minimap2
        run inside the pipeline with ``-resume`` -- previously-validated
        taxids are cached and only the new ``(sample, taxid)`` pair runs
        end-to-end. The legacy local-subprocess fallback was removed in
        the 2026-05-07 audit pass: maintaining a parallel implementation
        of the same validation logic was a bug source (drift from the
        pipeline) and it required users to install blastn/minimap2/
        samtools system-wide instead of letting conda do it.

        Args:
            taxid: Taxonomy ID
            name: Species/organism name
            sample: Sample name
            method: Validation method - 'blast', 'minimap2', or 'both'
            progress_callback: Optional callback(message, percent)
            config: Run configuration. Must include ``pipeline_source``
                (and optionally ``pipeline_profile`` / ``pipeline_branch``)
                so the call can route through nanometanf. Validation now
                requires the pipeline; configure it in the GUI's
                Configuration tab before invoking on-demand validation.

        Returns:
            ValidationResult with validation statistics. Failure cases
            (missing pipeline_source, nanometanf returned no result)
            produce a ValidationResult with ``success=False`` and a
            descriptive ``error_message`` rather than raising.
        """
        job_id = self._get_job_id(taxid, sample)
        job = ValidationJob(taxid=taxid, name=name, sample=sample)
        self._jobs[job_id] = job

        if not (config and config.get("pipeline_source")):
            error = (
                "On-demand validation requires the nanometanf pipeline. "
                "Set 'pipeline_source' in the Configuration tab "
                "(e.g. 'remote:dev' or a local path to nanometanf)."
            )
            job.status = ValidationStatus.FAILED
            job.error_message = error
            return self._create_failed_result(taxid, name, sample, error)

        nf_result = self.validate_via_nanometanf(
            taxid=taxid,
            name=name,
            sample=sample,
            method=method,
            config=config,
            progress_callback=progress_callback,
        )
        if nf_result is not None:
            job.status = ValidationStatus.COMPLETED
            job.status_message = "Validated via nanometanf"
            job.progress_percent = 100
            return nf_result

        # nanometanf delegation returned None -- the pipeline run
        # failed, the genome download failed, or another upstream
        # condition. Surface a clean failure rather than silently
        # falling back to a different code path.
        error = (
            "nanometanf validation did not return a result. Check "
            "the pipeline log under <results>/logs/ for the underlying "
            "Nextflow error."
        )
        job.status = ValidationStatus.FAILED
        job.error_message = error
        return self._create_failed_result(taxid, name, sample, error)

    def _create_failed_result(self, taxid: int, name: str, sample: str, error: str) -> ValidationResult:
        """Create a failed validation result."""
        return ValidationResult(
            taxid=taxid,
            name=name,
            sample=sample,
            total_classified_reads=0,
            extracted_reads=0,
            validated_reads=0,
            validation_rate=0.0,
            avg_identity=0.0,
            min_identity=0.0,
            max_identity=0.0,
            success=False,
            error_message=error
        )

    def _save_results(self, job: ValidationJob) -> None:
        """Save validation results to JSON file."""
        output_file = self.validation_dir / f"{job.sample}_{job.taxid}_validation.json"

        # Compute percent_validated as a percentage (0-100)
        percent_validated = job.validation_rate  # already stored as percentage

        # Determine validation_status using the same thresholds as the parser
        if job.validated_reads == 0 and job.total_reads == 0:
            validation_status = "no_data"
        elif percent_validated >= 80 and job.avg_identity >= 90:
            validation_status = "confirmed"
        elif percent_validated >= 50:
            validation_status = "partial"
        elif percent_validated > 0:
            validation_status = "low"
        else:
            validation_status = "no_data"

        results = {
            # Fields expected by BlastValidationParser.parse_validation_json()
            "sample_id": job.sample,
            "taxid": job.taxid,
            "species": job.name,
            "total_reads": job.total_reads,
            "validated_reads": job.validated_reads,
            "percent_validated": percent_validated,
            "percent_identity_mean": job.avg_identity,
            "validation_method": "blast",
            "validation_status": validation_status,
            "hit_rate": percent_validated / 100.0 if percent_validated else 0.0,
            "timestamp": job.completed_at.isoformat() if job.completed_at else datetime.now().isoformat(),
            # Additional fields kept for load_validation_result() compatibility
            "name": job.name,
            "sample": job.sample,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "extracted_reads": job.extracted_reads,
            "avg_identity": job.avg_identity,
            "genome_path": str(job.genome_path) if job.genome_path else None,
            "blast_results": str(job.blast_results) if job.blast_results else None,
        }

        try:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Saved validation results to {output_file}")
        except (PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to save validation results: {e}")

    def get_job_status(self, taxid: int, sample: str) -> Optional[ValidationJob]:
        """Get status of a validation job."""
        job_id = self._get_job_id(taxid, sample)
        return self._jobs.get(job_id)

    def load_validation_result(self, taxid: int, sample: str) -> Optional[ValidationResult]:
        """Load a previously completed validation result from disk."""
        result_file = self.validation_dir / f"{sample}_{taxid}_validation.json"

        if not result_file.exists():
            return None

        try:
            with open(result_file, 'r') as f:
                data = json.load(f)

            return ValidationResult(
                taxid=data["taxid"],
                name=data["name"],
                sample=data["sample"],
                total_classified_reads=data.get("total_reads", 0),
                extracted_reads=data.get("extracted_reads", 0),
                validated_reads=data.get("validated_reads", 0),
                validation_rate=data.get("validation_rate", 0.0),
                avg_identity=data.get("avg_identity", 0.0),
                min_identity=0.0,  # Not stored
                max_identity=0.0,  # Not stored
                success=True,
                blast_output_file=Path(data["blast_results"]) if data.get("blast_results") else None
            )

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
                json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.exception(f"Failed to load validation result: {e}")
            return None

    def get_available_organisms(self, sample: str) -> List[Dict[str, Any]]:
        """
        Get list of organisms available for on-demand validation.

        Returns organisms that appear in Kraken2 output but may not
        be on the watchlist.

        Args:
            sample: Sample name

        Returns:
            List of dicts with taxid, read_count, and whether validation exists
        """
        taxid_counts = self.read_extractor.get_classified_taxids(sample)

        results = []
        for taxid, count in sorted(taxid_counts.items(), key=lambda x: -x[1]):
            # Check if we already have validation results
            has_validation = (self.validation_dir / f"{sample}_{taxid}_validation.json").exists()

            results.append({
                "taxid": taxid,
                "read_count": count,
                "has_validation": has_validation,
                "has_genome": self.has_genome(taxid),
                "has_blast_db": self.has_blast_db(taxid),
            })

        return results
