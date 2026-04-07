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

        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".nanometa"

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
        blast_db = self.blast_dir / f"{taxid}.fasta.nsq"
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

        except Exception as e:
            logger.error(f"Error downloading genome for taxid {taxid}: {e}")
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
        except Exception as e:
            logger.error(f"Error building BLAST database for taxid {taxid}: {e}")
            return False

    def run_blast(
        self,
        query_file: Path,
        taxid: int,
        sample: str,
        percent_identity: float = 90.0,
        evalue: float = 0.01,
        num_threads: int = 4,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Optional[Path]:
        """
        Run BLAST validation.

        Args:
            query_file: Path to query FASTA file (extracted reads)
            taxid: Taxonomy ID
            sample: Sample name
            percent_identity: Minimum percent identity
            evalue: Maximum E-value
            num_threads: Number of threads
            progress_callback: Optional callback(message, percent)

        Returns:
            Path to BLAST output file or None if failed
        """
        blast_db = self.blast_dir / f"{taxid}.fasta"
        output_file = self.validation_dir / f"{sample}_{taxid}_ondemand.blast.txt"

        if not query_file.exists():
            logger.error(f"Query file not found: {query_file}")
            return None

        if not self.has_blast_db(taxid):
            logger.error(f"BLAST database not found for taxid {taxid}")
            return None

        try:
            if progress_callback:
                progress_callback("Running BLAST...", 0)

            cmd = [
                "blastn",
                "-db", str(blast_db),
                "-query", str(query_file),
                "-out", str(output_file),
                "-outfmt", "6",
                "-perc_identity", str(percent_identity),
                "-evalue", str(evalue),
                "-num_threads", str(num_threads),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=1800,
            )

            logger.info(f"BLAST completed: {output_file}")
            return output_file

        except subprocess.TimeoutExpired:
            logger.error("BLAST search timed out (30 min limit)")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"BLAST failed: {e.stderr}")
            return None
        except FileNotFoundError:
            logger.error("blastn not found - BLAST+ toolkit not installed?")
            return None
        except Exception as e:
            logger.error(f"Error running BLAST: {e}")
            return None

    def parse_blast_results(self, blast_output: Path) -> Dict[str, Any]:
        """
        Parse BLAST tabular output.

        Args:
            blast_output: Path to BLAST output file

        Returns:
            Dictionary with validation statistics
        """
        if not blast_output.exists():
            return {
                "validated_reads": 0,
                "avg_identity": 0.0,
                "min_identity": 0.0,
                "max_identity": 0.0,
                "total_hits": 0
            }

        unique_reads = set()
        identities = []

        try:
            with open(blast_output, 'r') as f:
                for line in f:
                    if line.strip():
                        parts = line.strip().split('\t')
                        if len(parts) >= 3:
                            read_id = parts[0]
                            identity = float(parts[2])

                            unique_reads.add(read_id)
                            identities.append(identity)

            return {
                "validated_reads": len(unique_reads),
                "avg_identity": sum(identities) / len(identities) if identities else 0.0,
                "min_identity": min(identities) if identities else 0.0,
                "max_identity": max(identities) if identities else 0.0,
                "total_hits": len(identities)
            }

        except Exception as e:
            logger.error(f"Error parsing BLAST results: {e}")
            return {
                "validated_reads": 0,
                "avg_identity": 0.0,
                "min_identity": 0.0,
                "max_identity": 0.0,
                "total_hits": 0
            }

    def _run_minimap2(
        self,
        query_file: Path,
        taxid: int,
        sample: str,
        preset: str = "map-ont",
        min_mapq: int = 10,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Run minimap2 validation against a reference genome.

        Args:
            query_file: Path to query FASTA file (extracted reads)
            taxid: Taxonomy ID
            sample: Sample name
            preset: minimap2 preset (map-ont, map-hifi, map-pb)
            min_mapq: Minimum mapping quality to count as mapped
            progress_callback: Optional progress callback

        Returns:
            Dict with validation stats or None if failed
        """
        genome_path = self.genomes_dir / f"{taxid}.fasta"
        output_file = self.validation_dir / f"{sample}_{taxid}_ondemand.paf"

        if not genome_path.exists():
            logger.error(f"Reference genome not found for taxid {taxid}")
            return None

        if not query_file.exists():
            logger.error(f"Query file not found: {query_file}")
            return None

        try:
            if progress_callback:
                progress_callback("Running minimap2 alignment...", 0)

            cmd = [
                "minimap2",
                "-x", preset,
                "--secondary=no",
                "-o", str(output_file),
                str(genome_path),
                str(query_file)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=1800,
            )

            logger.info(f"minimap2 completed: {output_file}")

            # Parse PAF output
            return self._parse_paf_results(output_file, min_mapq)

        except subprocess.CalledProcessError as e:
            logger.error(f"minimap2 failed: {e.stderr}")
            return None
        except FileNotFoundError:
            logger.error("minimap2 not found in PATH")
            return None
        except Exception as e:
            logger.error(f"Error running minimap2: {e}")
            return None

    def _parse_paf_results(
        self,
        paf_file: Path,
        min_mapq: int = 10
    ) -> Dict[str, Any]:
        """
        Parse minimap2 PAF output.

        PAF columns: qname qlen qstart qend strand tname tlen tstart tend nmatch alen mapq ...

        Args:
            paf_file: Path to PAF output
            min_mapq: Minimum mapping quality threshold

        Returns:
            Dict with mapped_reads, hit_rate, avg_mapq, avg_identity
        """
        unique_reads = set()
        mapq_values = []
        identities = []
        total_reads_seen = set()

        try:
            with open(paf_file, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) < 12:
                        continue

                    qname = parts[0]
                    qlen = int(parts[1])
                    nmatch = int(parts[9])
                    alen = int(parts[10])
                    mapq = int(parts[11])

                    total_reads_seen.add(qname)

                    if mapq >= min_mapq:
                        unique_reads.add(qname)
                        mapq_values.append(mapq)
                        if alen > 0:
                            identities.append(nmatch / alen * 100)

            mapped = len(unique_reads)
            total = len(total_reads_seen) if total_reads_seen else 0

            return {
                "mapped_reads": mapped,
                "total_reads": total,
                "hit_rate": mapped / total if total > 0 else 0.0,
                "avg_mapq": sum(mapq_values) / len(mapq_values) if mapq_values else 0.0,
                "avg_identity": sum(identities) / len(identities) if identities else 0.0,
                "min_identity": min(identities) if identities else 0.0,
                "max_identity": max(identities) if identities else 0.0,
            }

        except Exception as e:
            logger.error(f"Error parsing PAF results: {e}")
            return {
                "mapped_reads": 0,
                "total_reads": 0,
                "hit_rate": 0.0,
                "avg_mapq": 0.0,
                "avg_identity": 0.0,
                "min_identity": 0.0,
                "max_identity": 0.0,
            }

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

        This ensures BLAST and minimap2 run identically whether triggered by
        the full pipeline or on-demand from the dashboard.

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
        pipeline_profile = config.get("pipeline_profile", "docker")

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

        # Generate pathogen_genomes.json for this single taxid
        genomes_json_path = self.validation_dir / f"pathogen_genomes_{taxid}.json"
        genome_fasta = self.genomes_dir / f"{taxid}.fasta"
        try:
            import json as _json
            with open(genomes_json_path, 'w') as f:
                _json.dump({str(taxid): str(genome_fasta)}, f)
        except Exception as e:
            logger.error(f"Failed to write pathogen genomes JSON: {e}")
            return None

        if progress_callback:
            progress_callback("Launching nanometanf validation...", 20)

        # Build nextflow command
        outdir = self.validation_dir / f"nf_{sample}_{taxid}"
        cmd = [
            "nextflow", "run", pipeline_source,
            "--validation_only",
            "--kraken2_output_dir", str(self.results_dir / "kraken2"),
            "--reads_dir", str(self.input_dir) if self.input_dir else str(self.results_dir),
            "--run_validation",
            "--validation_method", method,
            "--pathogen_genomes", str(genomes_json_path),
            "--taxids_to_validate", str(taxid),
            "--outdir", str(outdir),
            "-profile", pipeline_profile,
        ]

        try:
            logger.info(f"Running nanometanf validation: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minute timeout
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
            logger.error("nanometanf validation timed out")
            return None
        except FileNotFoundError:
            logger.warning("nextflow not found in PATH")
            return None
        except Exception as e:
            logger.error(f"nanometanf validation error: {e}")
            return None

    def validate_organism(
        self,
        taxid: int,
        name: str,
        sample: str,
        method: str = "blast",
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> ValidationResult:
        """
        Run full on-demand validation for an organism.

        This is the main entry point that orchestrates the entire validation
        workflow. When a nanometanf pipeline source is configured, delegates
        to nanometanf via the validation-only entry point. Otherwise falls
        back to local BLAST execution.

        Args:
            taxid: Taxonomy ID
            name: Species/organism name
            sample: Sample name
            method: Validation method - 'blast', 'minimap2', or 'both'
            progress_callback: Optional callback(message, percent)

        Returns:
            ValidationResult with validation statistics
        """
        job_id = self._get_job_id(taxid, sample)
        job = ValidationJob(taxid=taxid, name=name, sample=sample)
        self._jobs[job_id] = job

        def update_job(status: ValidationStatus, msg: str, pct: int):
            job.status = status
            job.status_message = msg
            job.progress_percent = pct
            if progress_callback:
                progress_callback(msg, pct)

        try:
            # Step 1: Check/download genome (0-20%)
            update_job(ValidationStatus.DOWNLOADING_GENOME, f"Checking genome for {name}...", 5)

            if not self.has_genome(taxid):
                update_job(ValidationStatus.DOWNLOADING_GENOME, f"Downloading genome for {name}...", 10)
                genome_path = self.download_genome(taxid, name)
                if not genome_path:
                    job.status = ValidationStatus.FAILED
                    job.error_message = "Failed to download reference genome"
                    return self._create_failed_result(taxid, name, sample, job.error_message)
            else:
                genome_path = self.genomes_dir / f"{taxid}.fasta"

            job.genome_path = genome_path
            update_job(ValidationStatus.DOWNLOADING_GENOME, "Genome ready", 20)

            # Step 2: Check/build BLAST database (20-35%)
            update_job(ValidationStatus.BUILDING_BLAST_DB, "Checking BLAST database...", 25)

            if not self.has_blast_db(taxid):
                update_job(ValidationStatus.BUILDING_BLAST_DB, f"Building BLAST database...", 30)
                if not self.build_blast_db(taxid):
                    job.status = ValidationStatus.FAILED
                    job.error_message = "Failed to build BLAST database"
                    return self._create_failed_result(taxid, name, sample, job.error_message)

            job.blast_db_path = self.blast_dir / f"{taxid}.fasta"
            update_job(ValidationStatus.BUILDING_BLAST_DB, "BLAST database ready", 35)

            # Step 3: Extract reads (35-70%)
            update_job(ValidationStatus.EXTRACTING_READS, "Extracting reads from Kraken2 output...", 40)

            def extraction_progress(msg: str, pct: int):
                # Scale from 40-70%
                scaled_pct = 40 + int(30 * pct / 100)
                update_job(ValidationStatus.EXTRACTING_READS, msg, scaled_pct)

            extraction_result = self.read_extractor.extract_reads_for_taxid(
                sample, taxid, extraction_progress
            )

            if not extraction_result.success:
                job.status = ValidationStatus.FAILED
                job.error_message = extraction_result.error_message or "Failed to extract reads"
                return self._create_failed_result(taxid, name, sample, job.error_message)

            job.total_reads = extraction_result.total_reads
            job.extracted_reads = extraction_result.extracted_reads
            job.extracted_fasta = extraction_result.output_file

            if extraction_result.extracted_reads == 0:
                # No reads to validate - not an error, just no data
                update_job(ValidationStatus.COMPLETED, "No reads to validate", 100)
                job.completed_at = datetime.now()
                return ValidationResult(
                    taxid=taxid,
                    name=name,
                    sample=sample,
                    total_classified_reads=extraction_result.total_reads,
                    extracted_reads=0,
                    validated_reads=0,
                    validation_rate=0.0,
                    avg_identity=0.0,
                    min_identity=0.0,
                    max_identity=0.0,
                    success=True,
                    error_message="No reads found for this taxid"
                )

            update_job(ValidationStatus.EXTRACTING_READS, f"Extracted {extraction_result.extracted_reads} reads", 70)

            # Step 4: Run validation (70-95%)
            blast_stats = None
            mm2_stats = None

            if method in ("blast", "both"):
                update_job(ValidationStatus.RUNNING_BLAST, "Running BLAST validation...", 75)

                if not self.has_blast_db(taxid):
                    update_job(ValidationStatus.BUILDING_BLAST_DB, "Building BLAST database...", 72)
                    if not self.build_blast_db(taxid):
                        if method == "blast":
                            job.status = ValidationStatus.FAILED
                            job.error_message = "Failed to build BLAST database"
                            return self._create_failed_result(taxid, name, sample, job.error_message)

                if self.has_blast_db(taxid):
                    blast_output = self.run_blast(
                        extraction_result.output_file,
                        taxid,
                        sample
                    )
                    if blast_output:
                        blast_stats = self.parse_blast_results(blast_output)
                        job.blast_results = blast_output

            if method in ("minimap2", "both"):
                update_job(ValidationStatus.RUNNING_BLAST, "Running minimap2 validation...", 80)
                mm2_stats = self._run_minimap2(
                    extraction_result.output_file,
                    taxid,
                    sample
                )

            # Use best available stats
            if blast_stats and mm2_stats:
                # Prefer the one with higher validation rate
                blast_rate = blast_stats["validated_reads"] / job.extracted_reads * 100 if job.extracted_reads > 0 else 0
                mm2_rate = mm2_stats["mapped_reads"] / job.extracted_reads * 100 if job.extracted_reads > 0 else 0
                if mm2_rate > blast_rate:
                    primary_stats = {
                        "validated_reads": mm2_stats["mapped_reads"],
                        "avg_identity": mm2_stats["avg_identity"],
                        "min_identity": mm2_stats["min_identity"],
                        "max_identity": mm2_stats["max_identity"],
                    }
                else:
                    primary_stats = blast_stats
            elif mm2_stats:
                primary_stats = {
                    "validated_reads": mm2_stats["mapped_reads"],
                    "avg_identity": mm2_stats["avg_identity"],
                    "min_identity": mm2_stats["min_identity"],
                    "max_identity": mm2_stats["max_identity"],
                }
            elif blast_stats:
                primary_stats = blast_stats
            else:
                job.status = ValidationStatus.FAILED
                job.error_message = "Validation execution failed"
                return self._create_failed_result(taxid, name, sample, job.error_message)

            update_job(ValidationStatus.RUNNING_BLAST, "Parsing results...", 90)

            # Step 5: Finalize results (95-100%)
            job.validated_reads = primary_stats["validated_reads"]
            job.validation_rate = (
                job.validated_reads / job.extracted_reads * 100
                if job.extracted_reads > 0 else 0.0
            )
            job.avg_identity = primary_stats["avg_identity"]
            job.status = ValidationStatus.COMPLETED
            job.completed_at = datetime.now()

            update_job(ValidationStatus.COMPLETED, "Validation complete", 100)

            # Save results to JSON
            self._save_results(job)

            return ValidationResult(
                taxid=taxid,
                name=name,
                sample=sample,
                total_classified_reads=extraction_result.total_reads,
                extracted_reads=extraction_result.extracted_reads,
                validated_reads=primary_stats["validated_reads"],
                validation_rate=job.validation_rate,
                avg_identity=primary_stats["avg_identity"],
                min_identity=primary_stats["min_identity"],
                max_identity=primary_stats["max_identity"],
                success=True,
                blast_output_file=job.blast_results
            )

        except Exception as e:
            logger.error(f"Validation failed for taxid {taxid}: {e}")
            job.status = ValidationStatus.FAILED
            job.error_message = str(e)
            return self._create_failed_result(taxid, name, sample, str(e))

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
        except Exception as e:
            logger.error(f"Failed to save validation results: {e}")

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

        except Exception as e:
            logger.error(f"Failed to load validation result: {e}")
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
