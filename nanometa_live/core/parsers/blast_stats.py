"""Individual-file BLAST stats parsing.

The counterpart to ``minimap2_stats.py``. nanometanf publishes per-(sample,
taxid) BLAST results as
``validation/blast/<sample>_taxid<tid>.blast_stats.json`` alongside the
``.blast.tsv`` (see ``modules/local/blastn_validation/main.nf``), carrying
``total_reads``, ``blast_hits``, ``hit_rate``, ``avg_identity`` and
``avg_coverage``.

Only the TSV was read before, and the TSV holds hits without the read count
they were measured against. The denominator was backfilled from the aggregate
``validation_results.json`` -- which in a realtime run is not written until
session end -- so for most of a run every BLAST result carried
``total_reads=0``. ``determine_status`` then falls through to UNCERTAIN
("Low Confidence") no matter how clean the evidence: measured on a tree with
40 hits of 50 reads at 99% identity, BLAST rendered 0.0% / Low Confidence
while minimap2 on the same reads rendered 96% / CONFIRMED.

``ValidationResult`` is imported lazily to avoid a circular import with
``blast_validation_parser``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_blast_stats_json(filepath: Path) -> Optional[dict]:
    """Read one ``*.blast_stats.json`` into a plain dict.

    Returns ``None`` when the file is unreadable or carries no usable taxid,
    so a malformed sidecar degrades to the previous TSV-only behaviour rather
    than losing the result.
    """
    try:
        with open(filepath, "r") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Unreadable BLAST stats %s: %s", filepath, exc)
        return None
    try:
        int(data.get("taxid"))
    except (TypeError, ValueError):
        logger.warning("BLAST stats missing/invalid taxid: %s", filepath)
        return None
    return data


def collect_blast_stats(validation_dir: Optional[Path]) -> Dict[Tuple[str, int], dict]:
    """Map ``(sample_id, taxid)`` to its BLAST stats dict.

    Scanned from the same directory the ``.blast.tsv`` files come from, so a
    sidecar is only used for a pair whose TSV is also being read.
    """
    out: Dict[Tuple[str, int], dict] = {}
    if validation_dir is None or not validation_dir.is_dir():
        return out
    for stats_file in validation_dir.glob("*.blast_stats.json"):
        data = parse_blast_stats_json(stats_file)
        if not data:
            continue
        try:
            key = (str(data.get("sample_id", "")), int(data.get("taxid")))
        except (TypeError, ValueError):
            continue
        out[key] = data
    return out


def apply_blast_stats(result, stats: Optional[dict]):
    """Enrich a TSV-derived BLAST result with its stats sidecar.

    Fills only what the TSV cannot know -- the read count the hits were
    measured against and the coverage figure -- then recomputes the status,
    which depends on the denominator. Values already present on the result
    (identity from the TSV, which is per-alignment and more precise) are kept.
    """
    if not stats:
        return result
    total = int(stats.get("total_reads", 0) or 0)
    if total > 0 and not result.total_reads:
        result.total_reads = total
        if result.total_reads:
            result.percent_validated = (
                result.validated_reads / result.total_reads * 100)
    if not result.coverage_breadth:
        result.coverage_breadth = float(stats.get("avg_coverage", 0.0) or 0.0)
    if not result.percent_identity_mean:
        result.percent_identity_mean = float(stats.get("avg_identity", 0.0) or 0.0)
    result.status = result.determine_status()
    return result
