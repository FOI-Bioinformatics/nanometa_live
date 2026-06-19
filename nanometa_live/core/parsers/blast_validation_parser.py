"""
BlastValidationParser: Parser for nanometanf BLAST/minimap2 validation results.

The aggregate output contract is documented in nanometanf's
``assets/schema_validation_results.json`` (JSON Schema draft 2020-12).
That file is the source of truth for the cross-component contract --
when it changes, this parser changes. The shape is two-level nested:

    {
      "pipeline_version": str,
      "validation_method": "blast" | "minimap2" | "both",
      "timestamp": ISO 8601 UTC,
      "thresholds": {"hit_rate": float, "identity": float},
      "results": {
        "<sample_id>": {
          "<taxid_str>": {ValidationEntry...},
        },
      },
      "summary": {
        "total_samples": int, "total_taxids_validated": int,
        "confirmed": int, "uncertain": int, "rejected": int,
      },
    }

A ValidationEntry has the per-(sample, taxid) fields documented in
the schema's ``$defs/ValidationEntry`` block (taxid, species,
validation_method, kraken_reads, extracted_reads, hit_rate,
avg_identity, avg_coverage, validation_status, plus method-specific
blast_hits / mapped_reads / avg_mapq / ref_name / ref_length and
dual-method minimap2_* sibling fields).

Legacy individual-file format (per-sample JSON written by older
pipeline versions before the AGGREGATE_VALIDATION_RESULTS module
landed) is also accepted as a fallback; ``parse_validation_json``
normalises it into the same ``ValidationResult`` dataclass below.

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
    reference_length: int = 0
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
        # Drop unknown keys so a dict from a newer schema does not raise
        # TypeError (mirrors NCBIResult/GTDBResult.from_dict in this codebase).
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})

    def determine_status(self) -> ValidationStatus:
        """Determine validation status based on metrics."""
        if self.errors:
            return ValidationStatus.FAILED
        if self.validated_reads == 0 and self.total_reads == 0:
            return ValidationStatus.NO_DATA
        # Examined but nothing validated (reads were classified to this organism
        # but BLAST/minimap2 confirmed none): a negative result, NOT "no data".
        # Distinguishing the two matters clinically -- "checked, not confirmed"
        # must not look identical to "not yet checked".
        if self.validated_reads == 0 and self.total_reads > 0:
            return ValidationStatus.LOW_CONFIDENCE
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

    Supports the current nanometanf output formats (under results/validation/):
    1. Aggregate JSON (validation_results.json, preferred when present)
    2. Per-(sample, taxid) JSON summaries (blast/*_validation.json)
    3. Per-(sample, taxid) BLAST tabular output (blast/*.blast.tsv, outfmt 6)
    4. Per-(sample, taxid) minimap2 stats (minimap2/*.minimap2_stats.json)
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
            # The authoritative aggregate JSON is written one level up at
            # validation/validation_results.json (the loader prefers it), but
            # validation_dir often resolves to validation/blast or
            # validation/minimap2. Without folding the aggregate's mtime in, a
            # realtime rewrite of validation_results.json never advances this
            # fingerprint and the cache serves stale results.
            for agg in (
                self.validation_dir.parent / "validation_results.json",
                self.results_dir / "validation" / "validation_results.json",
            ):
                try:
                    if agg.exists():
                        m = agg.stat().st_mtime
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
            patterns = ['*.json', '*.blast.tsv']
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
        Parse BLAST tabular output (outfmt 6).

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

            # Read first, then name columns from the ACTUAL width. Peeking one
            # line to pick 12-vs-15 names is fragile (a leading blank line shifts
            # every column); read_csv skips blank lines so df.shape[1] is reliable.
            df = pd.read_csv(filepath, sep='\t', header=None)
            if df.empty or df.shape[1] < 12:
                result.status = ValidationStatus.NO_DATA
                return result
            ncols = df.shape[1]
            base = _cols_15 if ncols >= 15 else _cols_12
            df.columns = base[:ncols] + [f"col_{i}" for i in range(len(base), ncols)]

            # Count unique validated reads
            unique_reads = df['qseqid'].nunique()
            result.validated_reads = unique_reads

            # Calculate percentage if total_reads provided. Clamp to 100: BLAST
            # can validate more distinct reads than a stale/low Kraken total.
            if total_reads > 0:
                result.percent_validated = min(100.0, (unique_reads / total_reads) * 100)
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

    def _enrich_blast_identity_range(self, results: List['ValidationResult']) -> None:
        """Fill identity min/max + mean alignment length for BLAST results.

        The aggregate ``validation_results.json`` carries only mean identity, so
        the per-read identity range and alignment length are absent. The
        per-(sample, taxid) ``blast.tsv`` (outfmt 6) has them, and
        ``parse_blast_tabular`` already computes them, so enrich each BLAST result
        in place from its tsv when present. Mutates ``results``; no-op when the
        tsv is missing (e.g. minimap2-only runs) so it never fabricates data.
        """
        blast_dir = self.results_dir / 'validation' / 'blast'
        if not blast_dir.is_dir():
            return
        for r in results:
            if r.validation_method != 'blast':
                continue
            if r.percent_identity_min or r.percent_identity_max:
                continue  # already populated (per-file path)
            tsv = blast_dir / f"{r.sample_id}_taxid{r.taxid}.blast.tsv"
            if not tsv.exists():
                continue
            detail = self.parse_blast_tabular(tsv, r.sample_id, r.taxid, r.total_reads)
            if detail.percent_identity_max:
                r.percent_identity_min = detail.percent_identity_min
                r.percent_identity_max = detail.percent_identity_max
                r.alignment_length_mean = detail.alignment_length_mean

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

                    # Map nanometanf fields to ValidationResult. A JSON ``null``
                    # makes ``.get(key, default)`` return None (the default only
                    # applies when the key is ABSENT), and ``None <= 1.0`` /
                    # ``float(None)`` would raise -- caught by the catch-all
                    # except below, which would silently drop the WHOLE aggregate
                    # and blank the Validation tab. Coerce every numeric to a real
                    # number with ``or 0`` before arithmetic.
                    kraken_reads = entry.get('kraken_reads', 0) or 0
                    hit_rate = entry.get('hit_rate', 0.0) or 0.0
                    validated = entry.get('blast_hits', entry.get('mapped_reads', 0)) or 0

                    result = ValidationResult(
                        sample_id=sample_id,
                        taxid=tid,
                        species=entry.get('species', ''),
                        total_reads=int(kraken_reads),
                        validated_reads=int(validated),
                        percent_validated=min(
                            100.0, hit_rate * 100 if hit_rate <= 1.0 else hit_rate
                        ),
                        percent_identity_mean=float(entry.get('avg_identity', 0.0) or 0.0),
                        coverage_breadth=float(entry.get('avg_coverage', 0.0) or 0.0),
                        avg_mapq=float(entry.get('avg_mapq', 0.0) or 0.0),
                        # ref_name / ref_length are emitted by nanometanf but were
                        # previously dropped here; surface the reference identity
                        # and genome size in the GUI.
                        reference_accession=entry.get('ref_name', '') or '',
                        reference_length=int(entry.get('ref_length', 0) or 0),
                        validation_method=method,
                        timestamp=timestamp,
                    )
                    result.status = result.determine_status()
                    results.append(result)

                    # If 'both' method, check for minimap2 fields on a BLAST entry
                    if entry.get('minimap2_mapped') is not None:
                        mm2_hit_rate = entry.get('minimap2_hit_rate', 0.0) or 0.0
                        mm2_result = ValidationResult(
                            sample_id=sample_id,
                            taxid=tid,
                            species=entry.get('species', ''),
                            total_reads=int(kraken_reads),
                            validated_reads=int(entry.get('minimap2_mapped', 0) or 0),
                            percent_validated=min(
                                100.0,
                                mm2_hit_rate * 100 if mm2_hit_rate <= 1.0 else mm2_hit_rate,
                            ),
                            percent_identity_mean=float(entry.get('minimap2_identity', 0.0) or 0.0),
                            coverage_breadth=float(
                                entry.get('minimap2_coverage',
                                          entry.get('avg_coverage', 0.0)) or 0.0
                            ),
                            avg_mapq=float(entry.get('avg_mapq', 0.0) or 0.0),
                            reference_accession=entry.get('ref_name', '') or '',
                            reference_length=int(entry.get('ref_length', 0) or 0),
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
        taxid: Optional[int] = None,
        batch_id: Optional[str] = None,
    ) -> List[ValidationResult]:
        """
        Get all validation results, optionally filtered by sample or taxid.

        Args:
            sample: Filter by sample name (optional)
            taxid: Filter by taxonomy ID (optional)
            batch_id: when set, read a single realtime batch from
                ``validation/{tool}/batch/`` instead of the cumulative files.

        Returns:
            List of ValidationResult objects
        """
        if batch_id:
            from nanometa_live.core.parsers.validation_batch import collect_batch_results
            return collect_batch_results(self.results_dir, batch_id, sample, taxid, self.parse_blast_tabular)

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
                # The aggregate JSON omits identity range + alignment length;
                # enrich BLAST results from their blast.tsv when available.
                self._enrich_blast_identity_range(aggregate_results)
                results.extend(aggregate_results)
                # One aggregate JSON is authoritative; stop at the first match.
                break

        # The aggregate JSON is authoritative for the (sample, taxid, method)
        # tuples it lists, but it can legitimately OMIT BLAST: nanometanf's
        # aggregator keys entries by stats-file glob, so a (sample, taxid) whose
        # blast stats did not reach the aggregator work dir -- or whose blast key
        # was dropped by a realtime cumulative join -- appears as a minimap2-only
        # entry while its blast.tsv still lands on disk. We therefore ALWAYS also
        # scan the on-disk per-pair files below and merge in any (sample, taxid,
        # method) the aggregate did not cover, mirroring the unconditional
        # minimap2 individual-file fallback in collect_minimap2_results. Without
        # this, a minimap2-only aggregate hid on-disk BLAST entirely -- Coverage
        # sub-tab populated, BLAST sub-tab empty (regression in
        # tests/test_blast_validation_parser.py::TestAggregateWinsHidesBlast).
        def _method_class(method):
            # The GUI blast sub-tab treats every non-minimap2 method as blast,
            # so collapse blast/both/missing into one class for dedup.
            return "minimap2" if method == "minimap2" else "blast"

        seen_keys = {
            (r.sample_id, r.taxid, _method_class(getattr(r, "validation_method", "blast")))
            for r in results
        }

        # Per-(sample, taxid) individual JSON summaries
        json_files = list(self.validation_dir.glob('*_validation.json'))
        for json_file in json_files:
            result = self.parse_validation_json(json_file)
            if result:
                # Apply filters
                if sample and result.sample_id != sample:
                    continue
                if taxid and result.taxid != taxid:
                    continue
                key = (result.sample_id, result.taxid,
                       _method_class(result.validation_method))
                if key in seen_keys:
                    continue
                results.append(result)
                seen_keys.add(key)

        # Per-(sample, taxid) BLAST tabular files (nanometanf *.blast.tsv).
        for blast_file in self.validation_dir.glob('*.blast.tsv'):
            # Try to extract sample and taxid from filename
            # Expected format: sample_taxid.blast.tsv
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

                # Skip only when a BLAST-method result already exists for this
                # pair (from the aggregate or a JSON summary). A minimap2 entry
                # for the same pair must NOT block the blast.tsv -- that coarse
                # (sample, taxid) dedup was the hide-on-disk-BLAST bug.
                key = (file_sample, file_taxid, "blast")
                if key in seen_keys:
                    continue

                # Parse tabular file
                result = self.parse_blast_tabular(
                    blast_file, file_sample, file_taxid
                )
                results.append(result)
                seen_keys.add(key)

        # Surface per-(sample, taxid) minimap2 coverage from individual stats
        # files (core/parsers/minimap2_stats.py): keeps the Coverage tab live
        # before the aggregate JSON exists in a realtime run.
        from nanometa_live.core.parsers.minimap2_stats import collect_minimap2_results
        results.extend(collect_minimap2_results(
            self.results_dir, self.validation_dir, sample, taxid, results))

        # On-demand results supersede the pipeline result for the same
        # (sample, taxid, method) in place (see CLAUDE.md); other methods kept.
        on_demand_dir = self.results_dir / "on_demand_validation"
        if on_demand_dir.is_dir():
            def _supersede(od_r):
                key = (od_r.sample_id, od_r.taxid, od_r.validation_method)
                for i, r in enumerate(results):
                    if (r.sample_id, r.taxid, r.validation_method) == key:
                        results[i] = od_r
                        return
                results.append(od_r)

            # Aggregate JSON produced by on-demand runs
            od_aggregate = on_demand_dir / "validation_results.json"
            if od_aggregate.exists():
                for od_r in self.parse_nanometanf_aggregate_json(
                    od_aggregate, sample=sample, taxid=taxid
                ):
                    _supersede(od_r)

            # Individual JSON files in on_demand_validation/
            for json_file in on_demand_dir.glob("*_validation.json"):
                od_r = self.parse_validation_json(json_file)
                if od_r is None:
                    continue
                if sample and od_r.sample_id != sample:
                    continue
                if taxid and od_r.taxid != taxid:
                    continue
                _supersede(od_r)

        # Backfill species names. A blast.tsv parsed from disk carries only a
        # taxid (parse_blast_tabular has no species column), so a BLAST result
        # surfaced purely from disk -- e.g. the on-disk blast.tsv recovered when
        # the aggregate JSON was minimap2-only -- would render with a blank name.
        # Fill any empty species from another result for the same taxid that does
        # carry a name (typically the aggregate's minimap2 entry for that pair).
        species_by_taxid = {
            r.taxid: r.species
            for r in results
            if getattr(r, "species", "")
        }
        if species_by_taxid:
            for r in results:
                if not getattr(r, "species", "") and r.taxid in species_by_taxid:
                    r.species = species_by_taxid[r.taxid]

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


# Backward compatibility alias
BlastValidationParser = ValidationParser


# Per-read column names, matching the nanometanf BLASTN_VALIDATION outfmt.
_PER_READ_COLS_12 = [
    'qseqid', 'sseqid', 'pident', 'length', 'mismatch', 'gapopen',
    'qstart', 'qend', 'sstart', 'send', 'evalue', 'bitscore',
]
_PER_READ_COLS_15 = _PER_READ_COLS_12 + ['qlen', 'slen', 'qcovs']


def parse_blast_per_read(
    filepath: Path,
    sample_id: str,
    taxid: int,
    max_rows: int = 5000,
) -> Dict[str, Any]:
    """Parse a ``*.blast.tsv`` into per-read records + distributions.

    This is the lazy, on-selection companion to :meth:`parse_blast_tabular`
    (which only computes per-(sample, taxid) aggregates on the poll path). It is
    O(reads) and must only be called when the operator opens the per-read panel.

    Dedups by ``qseqid`` keeping the best hit (highest bitscore) per read, so a
    read contributes exactly one row -- matching the hit-rate dedup the pipeline
    and aggregate parser use. When the deduped read count exceeds ``max_rows``,
    the per-read table is capped to the top ``max_rows`` reads by bitscore
    (``sampled=True``, ``total_reads`` carries the full count); the
    distributions and top-subject counts are still computed over ALL reads.

    Returns a dict::

        {
          "sample_id", "taxid", "total_reads", "returned_rows", "sampled",
          "records":     [ {qseqid, sseqid, pident, length, bitscore, evalue, qcovs}, ... ],
          "top_subjects":[ {sseqid, reads, mean_pident}, ... ],
          "distributions": {"pident": [...], "length": [...], "bitscore": [...], "evalue": [...]},
          "subject_agreement": float,   # fraction of reads on the most-common subject
        }

    On an empty/missing/unreadable file returns the same shape with empty lists.
    """
    empty = {
        "sample_id": sample_id, "taxid": taxid, "total_reads": 0,
        "returned_rows": 0, "sampled": False, "records": [],
        "top_subjects": [], "subject_agreement": 0.0,
        "distributions": {"pident": [], "length": [], "bitscore": [], "evalue": []},
    }
    try:
        if not filepath.exists() or filepath.stat().st_size == 0:
            return empty
        df = pd.read_csv(filepath, sep='\t', header=None)
        if df.empty or df.shape[1] < 12:
            return empty
        ncols = df.shape[1]
        base = _PER_READ_COLS_15 if ncols >= 15 else _PER_READ_COLS_12
        df.columns = base[:ncols] + [f"col_{i}" for i in range(len(base), ncols)]

        # One row per read: keep the highest-bitscore hit per qseqid.
        df = df.sort_values('bitscore', ascending=False).drop_duplicates('qseqid')
        total_reads = int(len(df))
        if 'qcovs' not in df.columns:
            df['qcovs'] = 0.0

        # Distributions + top subjects over ALL deduped reads.
        distributions = {
            "pident": df['pident'].astype(float).tolist(),
            "length": df['length'].astype(int).tolist(),
            "bitscore": df['bitscore'].astype(float).tolist(),
            "evalue": df['evalue'].astype(float).tolist(),
        }
        grp = df.groupby('sseqid')
        top = (
            grp.agg(reads=('qseqid', 'size'), mean_pident=('pident', 'mean'))
            .sort_values('reads', ascending=False)
            .reset_index()
        )
        top_subjects = [
            {"sseqid": str(r.sseqid), "reads": int(r.reads),
             "mean_pident": round(float(r.mean_pident), 1)}
            for r in top.itertuples(index=False)
        ]
        # Guard top.iloc[0]: a malformed TSV whose sseqid column is all-null
        # yields an empty groupby, so check not-empty as well as total_reads.
        subject_agreement = (
            float(top.iloc[0]['reads']) / total_reads
            if total_reads and not top.empty else 0.0
        )

        # Per-read table: cap to top-N by bitscore for the DOM.
        sampled = total_reads > max_rows
        table_df = df.head(max_rows) if sampled else df
        cols = ['qseqid', 'sseqid', 'pident', 'length', 'bitscore', 'evalue', 'qcovs']
        records = table_df[cols].to_dict('records')
        for rec in records:
            rec['pident'] = round(float(rec['pident']), 1)
            rec['qcovs'] = round(float(rec['qcovs']), 1)
            rec['bitscore'] = round(float(rec['bitscore']), 1)

        return {
            "sample_id": sample_id, "taxid": taxid, "total_reads": total_reads,
            "returned_rows": len(records), "sampled": sampled,
            "records": records, "top_subjects": top_subjects,
            "subject_agreement": subject_agreement,
            "distributions": distributions,
        }
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
            pd.errors.ParserError, pd.errors.EmptyDataError, KeyError, ValueError,
            TypeError) as e:
        logger.exception(f"Error parsing per-read BLAST {filepath}: {e}")
        return empty
