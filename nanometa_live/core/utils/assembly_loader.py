"""Loader for canonical assembly stats (Flye/miniasm via CANONICAL_ASSEMBLY_WRITER).

nanometanf can emit ``canonical/assembly/{sample}.assembly_stats.json`` (contig
lengths, N50/L50, circularity, GC) but the GUI had no assembly view. This loader
reads those per-sample files defensively and returns a list for the Reports tab,
or an empty list when assembly was not run (the default).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
            json.JSONDecodeError, ValueError) as e:
        logger.debug("assembly stats read failed for %s: %s", path, e)
        return None


def load_assembly_stats(results_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Return per-sample assembly stats, or [] when no assembly was produced.

    Each entry: ``{sample, summary, contigs}`` where ``summary`` and ``contigs``
    default to ``{}`` / ``[]`` so callers can render whatever is present.
    """
    if not results_dir:
        return []
    base = Path(results_dir) / "canonical" / "assembly"
    if not base.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for f in sorted(base.glob("*.assembly_stats.json")):
        if "sidecar" in f.name:
            continue
        data = _read_json(f)
        if not data:
            continue
        sample = data.get("sample_id") or f.name.replace(".assembly_stats.json", "")
        out.append({
            "sample": sample,
            "summary": data.get("summary", {}) or {},
            "contigs": data.get("contigs", []) or [],
        })
    return out
