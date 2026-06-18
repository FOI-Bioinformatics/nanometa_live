"""Consensus-sequence result parsing.

nanometanf (when run with ``--generate_consensus``) publishes a per-(sample,
taxid) consensus per validated organism:

    validation/consensus/<sample>_taxid<tid>.consensus.fasta
    validation/consensus/<sample>_taxid<tid>.consensus_stats.json

The consensus is built by aligning the extracted reads to the per-taxid
reference and calling ``samtools consensus``; positions below the depth
threshold are masked ``N`` and the sequence is trimmed to the covered span
(amplicon-focused, no primer scheme). These helpers surface the stats files in
the dashboard and read the FASTA lazily on download.

The stats glob is cheap (small JSON only) and safe to run on the poll path; the
FASTA itself is read only when the operator downloads it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConsensusResult:
    """Parsed ``*.consensus_stats.json`` plus the sibling FASTA path."""

    sample_id: str
    taxid: int
    species: str = ""
    ref_name: str = ""
    ref_length: int = 0
    covered_start: int = 0
    covered_end: int = 0
    span: int = 0
    mean_depth: float = 0.0
    min_depth_threshold: int = 0
    n_count: int = 0
    consensus_length: int = 0
    total_reads: int = 0
    mapped_reads: int = 0
    fasta_path: str = ""

    @property
    def has_sequence(self) -> bool:
        """True when a non-empty consensus was emitted."""
        return self.consensus_length > 0

    @property
    def n_fraction(self) -> float:
        """Fraction of the emitted consensus that is masked ``N``."""
        if self.consensus_length <= 0:
            return 0.0
        return self.n_count / self.consensus_length


def consensus_dir(results_dir: Path) -> Path:
    """Return the canonical consensus output directory."""
    return Path(results_dir) / "validation" / "consensus"


def parse_consensus_stats(filepath: Path) -> Optional[ConsensusResult]:
    """Parse one ``*.consensus_stats.json`` into a ConsensusResult.

    Returns ``None`` on an unreadable file or a missing/invalid taxid.
    """
    try:
        with open(filepath, "r") as f:
            d = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(f"Unreadable consensus stats {filepath}: {e}")
        return None
    try:
        tid = int(d.get("taxid"))
    except (TypeError, ValueError):
        logger.warning(f"consensus stats missing/invalid taxid: {filepath}")
        return None

    fasta_path = str(filepath).replace(".consensus_stats.json", ".consensus.fasta")
    return ConsensusResult(
        sample_id=str(d.get("sample_id", "") or ""),
        taxid=tid,
        species=str(d.get("species", "") or ""),
        ref_name=str(d.get("ref_name", "") or ""),
        ref_length=int(d.get("ref_length", 0) or 0),
        covered_start=int(d.get("covered_start", 0) or 0),
        covered_end=int(d.get("covered_end", 0) or 0),
        span=int(d.get("span", 0) or 0),
        mean_depth=float(d.get("mean_depth", 0.0) or 0.0),
        min_depth_threshold=int(d.get("min_depth_threshold", 0) or 0),
        n_count=int(d.get("n_count", 0) or 0),
        consensus_length=int(d.get("consensus_length", 0) or 0),
        total_reads=int(d.get("total_reads", 0) or 0),
        mapped_reads=int(d.get("mapped_reads", 0) or 0),
        fasta_path=fasta_path if Path(fasta_path).is_file() else "",
    )


def collect_consensus_results(
    results_dir: Path,
    sample: Optional[str] = None,
    taxid: Optional[int] = None,
) -> List[ConsensusResult]:
    """Scan ``validation/consensus/`` and return ConsensusResults.

    Globs only the small stats JSON files (never the FASTA), so it is cheap
    enough for the poll path. Optional ``sample`` / ``taxid`` filters narrow the
    scan the same way the coverage and BLAST loaders do.
    """
    out: List[ConsensusResult] = []
    cdir = consensus_dir(results_dir)
    if not cdir.is_dir():
        return out
    for stats_file in sorted(cdir.glob("*.consensus_stats.json")):
        res = parse_consensus_stats(stats_file)
        if res is None:
            continue
        if sample and res.sample_id != sample:
            continue
        if taxid and res.taxid != taxid:
            continue
        out.append(res)
    return out


def read_consensus_fasta(fasta_path: str) -> Optional[str]:
    """Read a consensus FASTA from disk (lazy; only on download).

    Returns the file contents, or ``None`` if the path is empty/unreadable.
    """
    if not fasta_path:
        return None
    try:
        return Path(fasta_path).read_text()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Unreadable consensus FASTA {fasta_path}: {e}")
        return None
