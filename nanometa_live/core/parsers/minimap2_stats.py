"""Individual-file minimap2 coverage stats parsing.

nanometanf publishes per-(sample, taxid) minimap2 results as
``validation/minimap2/<sample>_taxid<tid>.minimap2_stats.json`` (alongside the
matching ``.paf``). The aggregate ``validation_results.json`` carries the same
information once AGGREGATE_VALIDATION_RESULTS has run, but in a realtime run
that aggregate is not written until late, so a Coverage sub-tab driven only by
the aggregate stays empty for most of the run even though high-quality coverage
already exists on disk.

These helpers let ``ValidationParser`` surface those individual stats files as
minimap2 ``ValidationResult`` objects. Field mapping mirrors the minimap2
branch of ``ValidationParser.parse_nanometanf_aggregate_json`` so results are
identical whichever source they came from. ``ValidationResult`` is imported
lazily inside the functions to avoid a circular import with
``blast_validation_parser``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def minimap2_stats_dirs(results_dir: Path, validation_dir: Optional[Path]) -> List[Path]:
    """Return existing directories that may hold ``*.minimap2_stats.json``.

    Depending on which sibling ``validation_dir`` resolved to, ``minimap2/`` is
    reached a couple of different ways; return all plausible ones, existing and
    de-duplicated.
    """
    candidates = [results_dir / "validation" / "minimap2"]
    if validation_dir is not None:
        candidates.append(validation_dir / "minimap2")
        candidates.append(validation_dir.parent / "minimap2")
    seen: set = set()
    out: List[Path] = []
    for d in candidates:
        try:
            key = str(d.resolve())
        except OSError:
            key = str(d)
        if key in seen:
            continue
        seen.add(key)
        if d.is_dir():
            out.append(d)
    return out


def parse_minimap2_stats_json(filepath: Path):
    """Parse one ``*.minimap2_stats.json`` into a minimap2 ValidationResult.

    Returns ``None`` on an unreadable file or a missing/invalid taxid.
    """
    from nanometa_live.core.parsers.blast_validation_parser import ValidationResult

    try:
        with open(filepath, "r") as f:
            d = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(f"Unreadable minimap2 stats {filepath}: {e}")
        return None
    try:
        tid = int(d.get("taxid"))
    except (TypeError, ValueError):
        logger.warning(f"minimap2 stats missing/invalid taxid: {filepath}")
        return None

    hit_rate = d.get("hit_rate", 0.0) or 0.0
    result = ValidationResult(
        sample_id=str(d.get("sample_id", "")),
        taxid=tid,
        species=str(d.get("species", "") or ""),
        total_reads=int(d.get("total_reads", 0) or 0),
        validated_reads=int(d.get("mapped_reads", 0) or 0),
        percent_validated=hit_rate * 100 if hit_rate <= 1.0 else hit_rate,
        percent_identity_mean=float(d.get("avg_identity", 0.0) or 0.0),
        coverage_breadth=float(d.get("avg_coverage", 0.0) or 0.0),
        avg_mapq=float(d.get("avg_mapq", 0.0) or 0.0),
        validation_method="minimap2",
        reference_accession=str(d.get("ref_name", "") or ""),
        timestamp=str(d.get("timestamp", "") or ""),
    )
    result.status = result.determine_status()
    return result


def collect_minimap2_results(
    results_dir: Path,
    validation_dir: Optional[Path],
    sample: Optional[str],
    taxid: Optional[int],
    existing: List,
) -> List:
    """Scan minimap2 stats files and return new minimap2 ValidationResults.

    BLAST and minimap2 are distinct methods for the same (sample, taxid), so
    these supplement the blast.tsv results rather than dedup against them; only
    duplicate minimap2 entries are skipped.
    """
    seen = {
        (r.sample_id, r.taxid)
        for r in existing
        if getattr(r, "validation_method", None) == "minimap2"
    }
    out: List = []
    for mm2_dir in minimap2_stats_dirs(results_dir, validation_dir):
        for stats_file in mm2_dir.glob("*.minimap2_stats.json"):
            mm2 = parse_minimap2_stats_json(stats_file)
            if mm2 is None:
                continue
            if sample and mm2.sample_id != sample:
                continue
            if taxid and mm2.taxid != taxid:
                continue
            key = (mm2.sample_id, mm2.taxid)
            if key in seen:
                continue
            seen.add(key)
            out.append(mm2)
    return out
