"""
PAF coverage parser for computing per-position genome coverage from minimap2 alignments.

Parses PAF (Pairwise mApping Format) files produced by minimap2 and computes
per-position depth arrays, breadth of coverage, and summary statistics suitable
for visualization in the validation tab.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)

# Safety limit: skip references larger than 500 MB to avoid excessive memory allocation.
MAX_GENOME_SIZE = 500_000_000


@dataclass
class CoverageData:
    """Per-position coverage computed from PAF alignments."""

    ref_name: str
    ref_length: int
    depth_array: np.ndarray  # shape (ref_length,), dtype uint32
    breadth: float = 0.0  # fraction of genome with depth >= 1
    mean_depth: float = 0.0
    median_depth: float = 0.0
    max_depth: int = 0
    positions_above_threshold: Dict[int, float] = field(default_factory=dict)
    # Amplicon-awareness: for full-length 16S / amplicon reads the alignments
    # concentrate in a short window of an otherwise large reference, so the
    # genome-relative ``breadth`` is misleadingly tiny. These describe the
    # covered region itself so the GUI can report "focused coverage" instead of
    # a false "low coverage" verdict (see app/components/coverage_plots.py).
    covered_bp: int = 0           # total positions with depth >= 1
    covered_start: int = -1       # first covered position (-1 if none)
    covered_end: int = -1         # last covered position (-1 if none)
    covered_span: int = 0         # covered_end - covered_start + 1
    local_breadth: float = 0.0    # covered_bp / covered_span (~1.0 for one tight locus)
    local_mean_depth: float = 0.0  # mean depth across COVERED positions only
    is_concentrated: bool = False  # amplicon-like: deep coverage over a tiny genome fraction

    # Concentrated (amplicon) coverage = only a tiny fraction of the reference is
    # covered, yet that covered material is reasonably deep. Keyed on
    # depth-over-covered rather than the contiguous span so it also fires for a
    # multi-copy 16S gene (the rrn operons of a genome sit megabases apart, so a
    # min..max span is misleading). Tuned so a 16S locus (single or multi-copy)
    # in a multi-Mb genome trips it while a partially-covered WGS genome does not.
    _CONCENTRATION_RATIO = 0.05      # covered fraction of the genome < 5%
    _CONCENTRATION_MIN_DEPTH = 10    # mean depth across covered positions
    _CONCENTRATION_MIN_COVERED_BP = 200

    def __post_init__(self):
        if self.depth_array is not None and len(self.depth_array) > 0:
            self.breadth = float(np.count_nonzero(self.depth_array) / self.ref_length)
            self.mean_depth = float(np.mean(self.depth_array))
            self.median_depth = float(np.median(self.depth_array))
            self.max_depth = int(np.max(self.depth_array))
            for threshold in (1, 5, 10, 20, 50):
                if threshold <= self.max_depth:
                    self.positions_above_threshold[threshold] = float(
                        np.sum(self.depth_array >= threshold) / self.ref_length
                    )

            covered = np.nonzero(self.depth_array)[0]
            self.covered_bp = int(covered.size)
            if self.covered_bp:
                self.covered_start = int(covered[0])
                self.covered_end = int(covered[-1])
                self.covered_span = self.covered_end - self.covered_start + 1
                self.local_breadth = float(self.covered_bp / self.covered_span)
                # mean depth where there IS coverage (robust to multi-locus gaps)
                self.local_mean_depth = float(np.mean(self.depth_array[covered]))
                self.is_concentrated = bool(
                    self.breadth <= self._CONCENTRATION_RATIO
                    and self.local_mean_depth >= self._CONCENTRATION_MIN_DEPTH
                    and self.covered_bp >= self._CONCENTRATION_MIN_COVERED_BP
                )


def parse_paf_coverage(
    paf_path: Path, min_mapq: int = 0
) -> Dict[str, CoverageData]:
    """
    Parse a PAF file and compute per-position coverage per reference.

    Args:
        paf_path: Path to PAF file.
        min_mapq: Minimum mapping quality to include (0 = no filter).

    Returns:
        Dict mapping reference name to CoverageData.
    """
    paf_path = Path(paf_path)
    if not paf_path.exists():
        logger.warning("PAF file not found: %s", paf_path)
        return {}

    # First pass: collect ref lengths and alignments
    ref_lengths: Dict[str, int] = {}
    alignments: list = []

    with open(paf_path) as fh:
        for line_num, line in enumerate(fh, 1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 12:
                logger.warning(
                    "Skipping malformed PAF line %d in %s: expected >=12 columns, got %d",
                    line_num, paf_path.name, len(parts),
                )
                continue

            try:
                tname = parts[5]
                tlen = int(parts[6])
                tstart = int(parts[7])
                tend = int(parts[8])
                mapq = int(parts[11])
            except ValueError:
                logger.warning(
                    "Skipping PAF line %d in %s: non-integer value in numeric field",
                    line_num, paf_path.name,
                )
                continue

            # Bounds validation
            if tstart < 0 or tend <= tstart or tend > tlen:
                logger.warning(
                    "Skipping PAF line %d in %s: invalid coordinates "
                    "(tstart=%d, tend=%d, tlen=%d)",
                    line_num, paf_path.name, tstart, tend, tlen,
                )
                continue

            if mapq < min_mapq:
                continue

            ref_lengths[tname] = tlen
            alignments.append((tname, tstart, tend))

    if not alignments:
        logger.info("No alignments found in %s", paf_path)
        return {}

    # Allocate depth arrays, skipping references that exceed the safety limit
    depth_arrays: Dict[str, np.ndarray] = {}
    for rname, rlen in ref_lengths.items():
        if rlen > MAX_GENOME_SIZE:
            logger.warning(
                "Skipping reference %s (%d bp) in %s: exceeds maximum genome size (%d bp)",
                rname, rlen, paf_path.name, MAX_GENOME_SIZE,
            )
            continue
        depth_arrays[rname] = np.zeros(rlen, dtype=np.uint32)

    # Accumulate depth (skip alignments to references that were filtered out)
    for tname, tstart, tend in alignments:
        if tname in depth_arrays:
            depth_arrays[tname][tstart:tend] += 1

    # Build CoverageData objects
    results: Dict[str, CoverageData] = {}
    for rname, depth in depth_arrays.items():
        results[rname] = CoverageData(
            ref_name=rname,
            ref_length=ref_lengths[rname],
            depth_array=depth,
        )

    logger.info(
        "Parsed coverage for %d reference(s) from %s (%d alignments)",
        len(results),
        paf_path.name,
        len(alignments),
    )
    return results


def aggregate_contig_coverage(
    coverage_dict: Dict[str, CoverageData],
) -> CoverageData:
    """
    Aggregate per-contig CoverageData into a single concatenated view.

    For genomes assembled into multiple contigs, this concatenates all depth
    arrays and recomputes summary statistics over the whole genome.

    Args:
        coverage_dict: Dict mapping contig name to CoverageData (from parse_paf_coverage).

    Returns:
        Single CoverageData representing the full genome.
    """
    if not coverage_dict:
        return CoverageData(ref_name="(empty)", ref_length=0, depth_array=np.array([], dtype=np.uint32))

    if len(coverage_dict) == 1:
        return next(iter(coverage_dict.values()))

    # Sort contigs by name for deterministic ordering
    sorted_contigs = sorted(coverage_dict.values(), key=lambda c: c.ref_name)

    total_length = sum(c.ref_length for c in sorted_contigs)
    combined_depth = np.concatenate([c.depth_array for c in sorted_contigs])
    combined_name = f"{sorted_contigs[0].ref_name} (+{len(sorted_contigs) - 1} contigs)"

    return CoverageData(
        ref_name=combined_name,
        ref_length=total_length,
        depth_array=combined_depth,
    )


