"""
BlastValidationParser: Parser for nanometanf BLAST/minimap2 validation results.

This module provides parsers for structured validation results from the nanometanf
pipeline, including BLAST and future minimap2 validation outputs. It handles both
legacy tabular BLAST output (outfmt 6) and modern JSON validation summaries.

Expected nanometanf validation JSON output structure:
{
    "sample_id": "barcode01",
    "taxid": 562,
    "species": "Escherichia coli",
    "total_reads": 1500,
    "validated_reads": 1423,
    "percent_validated": 94.87,
    "percent_identity_mean": 98.5,
    "percent_identity_min": 85.2,
    "percent_identity_max": 100.0,
    "alignment_length_mean": 450,
    "coverage_breadth": 0.87,
    "coverage_depth_mean": 15.3,
    "validation_method": "blast",
    "reference_accession": "GCF_000005845.2",
    "timestamp": "2024-01-15T10:30:00Z"
}

Author: Nanometa Live Development Team
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
import pandas as pd

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Validation status categories for pathogen confirmation."""
    CONFIRMED = "confirmed"      # >= 80% reads validated with high identity
    PARTIAL = "partial"          # 50-80% reads validated
    LOW_CONFIDENCE = "low"       # < 50% reads validated
    UNCERTAIN = "uncertain"      # Backend intermediate status (maps to low_confidence)
    NO_DATA = "no_data"          # No validation data available
    FAILED = "failed"            # Validation process failed


@dataclass
class ValidationResult:
    """
    Structured validation result for a single species in a sample.

    Attributes:
        sample_id: Sample identifier (e.g., barcode01)
        taxid: NCBI taxonomy ID
        species: Species name
        total_reads: Total reads assigned to this taxid by Kraken2
        validated_reads: Reads confirmed by BLAST/minimap2
        percent_validated: Percentage of reads validated
        percent_identity_mean: Mean sequence identity across validated alignments
        percent_identity_min: Minimum identity in alignments
        percent_identity_max: Maximum identity in alignments
        alignment_length_mean: Mean alignment length
        coverage_breadth: Mean fraction of query reads aligned (from BLAST qcovs)
        coverage_depth_mean: Mean coverage depth across reference
        avg_mapq: Mean mapping quality (minimap2 only)
        validation_method: Method used (blast, minimap2)
        reference_accession: Reference genome accession
        status: Validation status category
        timestamp: When validation was performed
    """
    sample_id: str
    taxid: int
    species: str = ""
    total_reads: int = 0
    validated_reads: int = 0
    percent_validated: float = 0.0
    percent_identity_mean: float = 0.0
    percent_identity_min: float = 0.0
    percent_identity_max: float = 0.0
    alignment_length_mean: float = 0.0
    coverage_breadth: float = 0.0
    coverage_depth_mean: float = 0.0
    avg_mapq: float = 0.0
    validation_method: str = "blast"
    reference_accession: str = ""
    status: ValidationStatus = ValidationStatus.NO_DATA
    timestamp: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, handling enum serialization."""
        result = asdict(self)
        # Use status_display so the UI sees "low" for both LOW_CONFIDENCE and UNCERTAIN
        result['status'] = self.status_display
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValidationResult':
        """Create from dictionary, handling status conversion."""
        if 'status' in data and isinstance(data['status'], str):
            # Map backend status values that differ from the frontend enum
            _status_map = {
                'uncertain': 'uncertain',  # kept as-is (UNCERTAIN enum value)
                'rejected': 'low',         # backend rejected -> LOW_CONFIDENCE
            }
            raw = data['status']
            data = dict(data)
            data['status'] = ValidationStatus(_status_map.get(raw, raw))
        return cls(**data)

    def determine_status(self) -> ValidationStatus:
        """Determine validation status based on metrics."""
        if self.errors:
            return ValidationStatus.FAILED
        if self.validated_reads == 0 and self.total_reads == 0:
            return ValidationStatus.NO_DATA
        if self.percent_validated >= 80 and self.percent_identity_mean >= 90:
            return ValidationStatus.CONFIRMED
        if self.percent_validated >= 50:
            return ValidationStatus.PARTIAL
        if self.percent_validated > 0:
            return ValidationStatus.LOW_CONFIDENCE
        return ValidationStatus.NO_DATA

    @property
    def status_display(self) -> str:
        """Return a UI-friendly status string, normalising UNCERTAIN -> low."""
        if self.status == ValidationStatus.UNCERTAIN:
            return "low"
        return self.status.value


class ValidationParser:
    """
    Parser for BLAST and minimap2 validation results from nanometanf pipeline.

    Supports multiple output formats:
    1. nanometanf aggregate JSON (validation_results.json, preferred)
    2. JSON validation summary (validation_summary.json, legacy)
    3. Legacy BLAST tabular output (outfmt 6)

    Directory structure expected:
        results/
        ├── validation/
        │   └── validation_results.json          # nanometanf aggregate output
        ├── blast_validation/
        │   ├── barcode01_562_validation.json    # JSON summary
        │   ├── barcode01_562.blast.txt          # Raw BLAST output
        │   └── validation_summary.json          # Combined summary
        └── ...
    """

    # Validation thresholds
    CONFIRMED_THRESHOLD = 80.0       # % reads for CONFIRMED status
    PARTIAL_THRESHOLD = 50.0         # % reads for PARTIAL status
    MIN_IDENTITY_THRESHOLD = 90.0    # % identity for CONFIRMED status

    def __init__(self, results_dir: str):
        """
        Initialize the parser.

        Args:
            results_dir: Path to nanometanf results directory
        """
        self.results_dir = Path(results_dir)

        # Try multiple possible directory names.
        # nanometanf v1.1+ publishes individual BLAST files to validation/blast/
        # and the aggregate JSON to validation/validation_results.json.
        # Legacy layouts used blast_validation/ or blast/ at the top level.
        self.validation_dir = None
        for dirname in ['blast_validation', 'validation/blast', 'validation', 'blast']:
            test_dir = self.results_dir / dirname
            if test_dir.exists():
                self.validation_dir = test_dir
                break

        if self.validation_dir:
            logger.info(f"ValidationParser initialized with dir: {self.validation_dir}")
        else:
            logger.debug(f"No validation directory found in {self.results_dir}")

        # Per-instance results cache, invalidated on validation-dir mtime
        # change. Closes P1-T06 from
        # docs/audit-2026-04-28-throughput-gui.md, where
        # validation_tab.load_validation_data() called has_validation_data
        # + get_validation_results + get_validation_summary inside one
        # tick -- three independent walks of the validation dir at
        # 24-barcode scale (100-200 file opens per tick). With the
        # cache, the second and third call now reuse the parsed list
        # if the directory's mtime is unchanged.
        self._results_cache_mtime: Optional[float] = None
        self._results_cache: Optional[List["ValidationResult"]] = None

    def _validation_dir_fingerprint(self) -> Optional[float]:
        """Latest mtime under ``validation_dir``; ``None`` when missing."""
        if not self.validation_dir or not self.validation_dir.exists():
            return None
        try:
            latest = self.validation_dir.stat().st_mtime
            for p in self.validation_dir.iterdir():
                try:
                    m = p.stat().st_mtime
                    if m > latest:
                        latest = m
                except OSError:
                    continue
            return latest
        except OSError:
            return None

    def has_validation_data(self) -> bool:
        """Check if any validation data exists."""
        if self.validation_dir and self.validation_dir.exists():
            # Check for any validation files
            patterns = ['*.json', '*.blast.tsv', '*.blast.txt', '*_blast.txt']
            for pattern in patterns:
                if list(self.validation_dir.glob(pattern)):
                    return True
            # Also check for aggregate JSON one level up (validation/validation_results.json)
            if self.validation_dir.name != 'validation':
                parent_agg = self.validation_dir.parent / 'validation_results.json'
                if parent_agg.exists():
                    return True

        # Also check the on_demand_validation/ directory
        on_demand_dir = self.results_dir / "on_demand_validation"
        if on_demand_dir.is_dir():
            if list(on_demand_dir.glob("*.json")):
                return True

        return False

    def parse_validation_json(self, filepath: Path) -> Optional[ValidationResult]:
        """
        Parse a single validation JSON file.

        Args:
            filepath: Path to validation JSON file

        Returns:
            ValidationResult or None if parsing fails
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            result = ValidationResult(
                sample_id=data.get('sample_id', ''),
                taxid=int(data.get('taxid', 0)),
                species=data.get('species', ''),
                total_reads=int(data.get('total_reads', 0)),
                validated_reads=int(data.get('validated_reads', 0)),
                percent_validated=float(data.get('percent_validated', 0.0)),
                percent_identity_mean=float(data.get('percent_identity_mean', 0.0)),
                percent_identity_min=float(data.get('percent_identity_min', 0.0)),
                percent_identity_max=float(data.get('percent_identity_max', 0.0)),
                alignment_length_mean=float(data.get('alignment_length_mean', 0.0)),
                coverage_breadth=float(data.get('coverage_breadth', 0.0)),
                coverage_depth_mean=float(data.get('coverage_depth_mean', 0.0)),
                avg_mapq=float(data.get('avg_mapq', 0.0)),
                validation_method=data.get('validation_method', 'blast'),
                reference_accession=data.get('reference_accession', ''),
                timestamp=data.get('timestamp', ''),
            )

            # Determine status
            result.status = result.determine_status()

            logger.debug(f"Parsed validation JSON: {result.sample_id}/{result.taxid}")
            return result

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.exception(f"Error parsing validation JSON {filepath}: {e}")
            return None

    def parse_blast_tabular(
        self,
        filepath: Path,
        sample_id: str,
        taxid: int,
        total_reads: int = 0
    ) -> ValidationResult:
        """
        Parse legacy BLAST tabular output (outfmt 6).

        BLAST outfmt 6 columns:
        qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore

        Args:
            filepath: Path to BLAST output file
            sample_id: Sample identifier
            taxid: Taxonomy ID being validated
            total_reads: Total reads from Kraken2 (for percentage calculation)

        Returns:
            ValidationResult with computed statistics
        """
        result = ValidationResult(
            sample_id=sample_id,
            taxid=taxid,
            total_reads=total_reads,
            validation_method='blast',
        )

        try:
            if not filepath.exists() or filepath.stat().st_size == 0:
                result.status = ValidationStatus.NO_DATA
                return result

            # Read BLAST tabular output.
            # nanometanf BLASTN_VALIDATION uses outfmt 6 with 15 columns:
            #   qseqid sseqid pident length mismatch gapopen qstart qend
            #   sstart send evalue bitscore qlen slen qcovs
            # Legacy files may have only the standard 12 columns.  We
            # detect the actual column count and assign names accordingly
            # to avoid misalignment (pandas silently mangles data when
            # fewer names are given than columns present).
            _cols_12 = [
                'qseqid', 'sseqid', 'pident', 'length', 'mismatch', 'gapopen',
                'qstart', 'qend', 'sstart', 'send', 'evalue', 'bitscore',
            ]
            _cols_15 = _cols_12 + ['qlen', 'slen', 'qcovs']

            # Peek at the first line to determine number of fields
            with open(filepath) as _peek:
                first_line = _peek.readline()
            ncols = len(first_line.strip().split('\t'))
            col_names = _cols_15 if ncols >= 15 else _cols_12

            df = pd.read_csv(
                filepath,
                sep='\t',
                header=None,
                names=col_names,
            )

            if df.empty:
                result.status = ValidationStatus.NO_DATA
                return result

            # Count unique validated reads
            unique_reads = df['qseqid'].nunique()
            result.validated_reads = unique_reads

            # Calculate percentage if total_reads provided
            if total_reads > 0:
                result.percent_validated = (unique_reads / total_reads) * 100
            else:
                # If no total provided, use validated count as total
                result.percent_validated = 100.0 if unique_reads > 0 else 0.0

            # Identity statistics
            result.percent_identity_mean = float(df['pident'].mean())
            result.percent_identity_min = float(df['pident'].min())
            result.percent_identity_max = float(df['pident'].max())

            # Alignment length statistics
            result.alignment_length_mean = float(df['length'].mean())

            # Determine status
            result.status = result.determine_status()

            logger.debug(
                f"Parsed BLAST tabular for {sample_id}/{taxid}: "
                f"{unique_reads} validated reads, {result.percent_identity_mean:.1f}% identity"
            )
            return result

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError, KeyError, ValueError, TypeError) as e:
            logger.exception(f"Error parsing BLAST tabular {filepath}: {e}")
            result.errors.append(str(e))
            result.status = ValidationStatus.FAILED
            return result

    def parse_nanometanf_aggregate_json(
        self,
        filepath: Path,
        sample: Optional[str] = None,
        taxid: Optional[int] = None
    ) -> List[ValidationResult]:
        """
        Parse the nanometanf aggregate validation_results.json file.

        This file is produced by the AGGREGATE_VALIDATION_RESULTS module and
        contains results from both BLAST and minimap2 validation, keyed by
        sample and taxid.

        Args:
            filepath: Path to validation_results.json
            sample: Optional sample filter
            taxid: Optional taxid filter

        Returns:
            List of ValidationResult objects
        """
        results = []
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            timestamp = data.get('timestamp', '')
            method_default = data.get('validation_method', 'blast')

            for sample_id, taxid_entries in data.get('results', {}).items():
                if sample and sample_id != sample:
                    continue

                for tid_str, entry in taxid_entries.items():
                    tid = int(tid_str)
                    if taxid and tid != taxid:
                        continue

                    method = entry.get('validation_method', method_default)

                    # Map nanometanf fields to ValidationResult
                    kraken_reads = entry.get('kraken_reads', 0)
                    hit_rate = entry.get('hit_rate', 0.0)
                    validated = entry.get('blast_hits', entry.get('mapped_reads', 0))

                    result = ValidationResult(
                        sample_id=sample_id,
                        taxid=tid,
                        species=entry.get('species', ''),
                        total_reads=kraken_reads,
                        validated_reads=validated,
                        percent_validated=hit_rate * 100 if hit_rate <= 1.0 else hit_rate,
                        percent_identity_mean=float(entry.get('avg_identity', 0.0)),
                        coverage_breadth=float(entry.get('avg_coverage', 0.0)),
                        avg_mapq=float(entry.get('avg_mapq', 0.0)),
                        validation_method=method,
                        timestamp=timestamp,
                    )
                    result.status = result.determine_status()
                    results.append(result)

                    # If 'both' method, check for minimap2 fields on a BLAST entry
                    if entry.get('minimap2_mapped') is not None:
                        mm2_result = ValidationResult(
                            sample_id=sample_id,
                            taxid=tid,
                            species=entry.get('species', ''),
                            total_reads=kraken_reads,
                            validated_reads=int(entry.get('minimap2_mapped', 0)),
                            percent_validated=(
                                entry.get('minimap2_hit_rate', 0.0) * 100
                                if entry.get('minimap2_hit_rate', 0.0) <= 1.0
                                else entry.get('minimap2_hit_rate', 0.0)
                            ),
                            percent_identity_mean=float(entry.get('minimap2_identity', 0.0)),
                            avg_mapq=float(entry.get('avg_mapq', 0.0)),
                            validation_method='minimap2',
                            timestamp=timestamp,
                        )
                        mm2_result.status = mm2_result.determine_status()
                        results.append(mm2_result)

            logger.info(f"Parsed {len(results)} results from nanometanf aggregate JSON")
            return results

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as e:
            logger.exception(f"Error parsing nanometanf aggregate JSON {filepath}: {e}")
            return []

    def get_validation_results(
        self,
        sample: Optional[str] = None,
        taxid: Optional[int] = None
    ) -> List[ValidationResult]:
        """
        Get all validation results, optionally filtered by sample or taxid.

        Args:
            sample: Filter by sample name (optional)
            taxid: Filter by taxonomy ID (optional)

        Returns:
            List of ValidationResult objects
        """
        # Cache fast-path: if the validation directory has not changed
        # since the last full parse, reuse the cached unfiltered list
        # and apply the (sample, taxid) filter in-memory.
        fingerprint = self._validation_dir_fingerprint()
        if (
            fingerprint is not None
            and self._results_cache is not None
            and self._results_cache_mtime == fingerprint
        ):
            cached = self._results_cache
            if sample is None and taxid is None:
                return list(cached)
            return [
                r for r in cached
                if (sample is None or r.sample_id == sample)
                and (taxid is None or r.taxid == taxid)
            ]

        # Full parse path. When no filters were requested we cache the
        # result so the next has_validation_data + get_validation_results
        # + get_validation_summary triple inside the same tick reuses
        # one parse rather than three.
        cache_this_call = sample is None and taxid is None
        results = []

        if not self.validation_dir or not self.validation_dir.exists():
            if cache_this_call:
                self._results_cache = []
                self._results_cache_mtime = fingerprint
            return results

        # Build candidate paths for the aggregate JSON, in priority order.
        # The nanometanf AGGREGATE_VALIDATION_RESULTS module always publishes to
        # results/validation/validation_results.json regardless of which sub-directory
        # individual blast/minimap2 files are published to.
        aggregate_candidates = []
        # Direct path inside validation_dir (works when validation_dir IS validation/)
        aggregate_candidates.append(self.validation_dir / 'validation_results.json')
        # Parent level (works when validation_dir is validation/blast or validation/minimap2)
        if self.validation_dir.name != 'validation':
            aggregate_candidates.append(self.validation_dir.parent / 'validation_results.json')
        # Fallback to results_dir/validation/
        aggregate_candidates.append(self.results_dir / 'validation' / 'validation_results.json')

        seen_paths = set()
        for aggregate_path in aggregate_candidates:
            resolved = str(aggregate_path.resolve()) if aggregate_path.exists() else None
            if not aggregate_path.exists() or resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            aggregate_results = self.parse_nanometanf_aggregate_json(
                aggregate_path, sample=sample, taxid=taxid
            )
            if aggregate_results:
                if cache_this_call:
                    self._results_cache = list(aggregate_results)
                    self._results_cache_mtime = fingerprint
                return aggregate_results

        # Next, check for combined summary JSON
        summary_path = self.validation_dir / 'validation_summary.json'
        if summary_path.exists():
            try:
                with open(summary_path, 'r') as f:
                    summary_data = json.load(f)

                for entry in summary_data.get('validations', []):
                    result = ValidationResult.from_dict(entry)

                    # Apply filters
                    if sample and result.sample_id != sample:
                        continue
                    if taxid and result.taxid != taxid:
                        continue

                    results.append(result)

                if results:
                    logger.info(f"Loaded {len(results)} results from summary JSON")
                    if cache_this_call:
                        self._results_cache = list(results)
                        self._results_cache_mtime = fingerprint
                    return results

            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                logger.exception(f"Error reading validation summary: {e}")

        # Fall back to individual files
        json_files = list(self.validation_dir.glob('*_validation.json'))
        for json_file in json_files:
            result = self.parse_validation_json(json_file)
            if result:
                # Apply filters
                if sample and result.sample_id != sample:
                    continue
                if taxid and result.taxid != taxid:
                    continue
                results.append(result)

        # Also check for legacy BLAST tabular files.
        # nanometanf v1.1+ produces *.blast.tsv; legacy formats used *.blast.txt.
        blast_patterns = ['*.blast.tsv', '*.blast.txt', '*_blast.txt']
        for pattern in blast_patterns:
            for blast_file in self.validation_dir.glob(pattern):
                # Try to extract sample and taxid from filename
                # Expected formats: sample_taxid.blast.txt or sample_taxid_blast.txt
                stem = blast_file.stem.replace('_blast', '').replace('.blast', '')
                parts = stem.rsplit('_', 1)

                if len(parts) >= 2:
                    file_sample = parts[0]
                    taxid_part = parts[1]
                    # nanometanf names files with a 'taxid' prefix, e.g.
                    # barcode01_taxid562.blast.tsv -> taxid_part = "taxid562"
                    if taxid_part.startswith('taxid'):
                        taxid_part = taxid_part[5:]
                    try:
                        file_taxid = int(taxid_part)
                    except ValueError:
                        continue

                    # Apply filters
                    if sample and file_sample != sample:
                        continue
                    if taxid and file_taxid != taxid:
                        continue

                    # Check if we already have JSON result for this
                    existing = [r for r in results
                                if r.sample_id == file_sample and r.taxid == file_taxid]
                    if existing:
                        continue

                    # Parse tabular file
                    result = self.parse_blast_tabular(
                        blast_file, file_sample, file_taxid
                    )
                    results.append(result)

        # Also check the on_demand_validation/ directory for results produced by
        # OnDemandValidator.  These supplement (never replace) pipeline results.
        on_demand_dir = self.results_dir / "on_demand_validation"
        if on_demand_dir.is_dir():
            # Check for an aggregate JSON produced by on-demand runs
            od_aggregate = on_demand_dir / "validation_results.json"
            if od_aggregate.exists():
                od_results = self.parse_nanometanf_aggregate_json(
                    od_aggregate, sample=sample, taxid=taxid
                )
                for od_r in od_results:
                    already_present = any(
                        r.sample_id == od_r.sample_id and r.taxid == od_r.taxid
                        for r in results
                    )
                    if not already_present:
                        results.append(od_r)

            # Also scan individual JSON files in on_demand_validation/
            for json_file in on_demand_dir.glob("*_validation.json"):
                od_r = self.parse_validation_json(json_file)
                if od_r is None:
                    continue
                if sample and od_r.sample_id != sample:
                    continue
                if taxid and od_r.taxid != taxid:
                    continue
                already_present = any(
                    r.sample_id == od_r.sample_id and r.taxid == od_r.taxid
                    for r in results
                )
                if not already_present:
                    results.append(od_r)

        logger.info(f"Retrieved {len(results)} validation results")
        if cache_this_call:
            self._results_cache = list(results)
            self._results_cache_mtime = fingerprint
        return results

    def get_validation_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics across all validation results.

        Returns:
            Dictionary with summary statistics
        """
        results = self.get_validation_results()

        if not results:
            return {
                'total_species': 0,
                'confirmed': 0,
                'partial': 0,
                'low_confidence': 0,
                'no_data': 0,
                'failed': 0,
                'avg_percent_validated': 0.0,
                'avg_identity': 0.0,
                'samples': [],
                'species_validated': [],
            }

        # Count by status
        status_counts = {status: 0 for status in ValidationStatus}
        for result in results:
            status_counts[result.status] += 1

        # Aggregate statistics
        validated_results = [r for r in results if r.validated_reads > 0]

        avg_percent = 0.0
        avg_identity = 0.0
        if validated_results:
            avg_percent = sum(r.percent_validated for r in validated_results) / len(validated_results)
            avg_identity = sum(r.percent_identity_mean for r in validated_results) / len(validated_results)

        # Unique samples and species
        samples = list(set(r.sample_id for r in results))
        species = list(set((r.taxid, r.species) for r in results if r.status == ValidationStatus.CONFIRMED))

        return {
            'total_species': len(results),
            'confirmed': status_counts[ValidationStatus.CONFIRMED],
            'partial': status_counts[ValidationStatus.PARTIAL],
            'low_confidence': status_counts[ValidationStatus.LOW_CONFIDENCE],
            'no_data': status_counts[ValidationStatus.NO_DATA],
            'failed': status_counts[ValidationStatus.FAILED],
            'avg_percent_validated': round(avg_percent, 1),
            'avg_identity': round(avg_identity, 1),
            'samples': samples,
            'species_validated': species,
        }

    def get_species_validation(
        self,
        taxid: int,
        sample: Optional[str] = None
    ) -> Optional[ValidationResult]:
        """
        Get validation result for a specific species.

        Args:
            taxid: Taxonomy ID to look up
            sample: Optional sample filter

        Returns:
            ValidationResult or None if not found
        """
        results = self.get_validation_results(sample=sample, taxid=taxid)
        return results[0] if results else None

    def get_sample_validation_status(
        self,
        sample: str
    ) -> Dict[int, ValidationStatus]:
        """
        Get validation status for all species in a sample.

        Args:
            sample: Sample identifier

        Returns:
            Dictionary mapping taxid to ValidationStatus
        """
        results = self.get_validation_results(sample=sample)
        return {r.taxid: r.status for r in results}


def generate_mock_validation_data(
    samples: List[str],
    pathogens: List[Dict[str, Any]],
    output_dir: str
) -> None:
    """
    Generate mock validation data for UI testing.

    Creates realistic validation JSON files without requiring an actual pipeline run.
    Useful for development and testing of the validation UI.

    Args:
        samples: List of sample names
        pathogens: List of pathogen dicts with 'taxid' and 'name' keys
        output_dir: Directory to write mock files
    """
    import random
    from datetime import datetime

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_validations = []

    for sample in samples:
        for pathogen in pathogens:
            taxid = pathogen.get('taxid', 0)
            name = pathogen.get('name', f'Species {taxid}')

            # Generate realistic mock data
            total_reads = random.randint(100, 5000)
            validation_rate = random.uniform(0.3, 0.99)
            validated_reads = int(total_reads * validation_rate)

            # Identity varies with validation rate
            base_identity = 85 + (validation_rate * 12)
            identity_mean = min(100, base_identity + random.uniform(-2, 2))
            identity_min = max(70, identity_mean - random.uniform(5, 15))
            identity_max = min(100, identity_mean + random.uniform(2, 5))

            result = ValidationResult(
                sample_id=sample,
                taxid=taxid,
                species=name,
                total_reads=total_reads,
                validated_reads=validated_reads,
                percent_validated=round(validation_rate * 100, 2),
                percent_identity_mean=round(identity_mean, 1),
                percent_identity_min=round(identity_min, 1),
                percent_identity_max=round(identity_max, 1),
                alignment_length_mean=round(random.uniform(200, 800), 0),
                coverage_breadth=round(random.uniform(0.4, 0.95), 2),
                coverage_depth_mean=round(random.uniform(5, 50), 1),
                validation_method='blast',
                reference_accession=f'GCF_{random.randint(100000, 999999)}.1',
                timestamp=datetime.now().isoformat(),
            )
            result.status = result.determine_status()

            # Write individual file
            filename = f"{sample}_{taxid}_validation.json"
            with open(output_path / filename, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)

            all_validations.append(result.to_dict())

    # Write summary file
    summary = {
        'generated_at': datetime.now().isoformat(),
        'samples': samples,
        'pathogens': len(pathogens),
        'validations': all_validations
    }

    with open(output_path / 'validation_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Generated mock validation data for {len(samples)} samples, {len(pathogens)} pathogens")


# Backward compatibility alias
BlastValidationParser = ValidationParser
