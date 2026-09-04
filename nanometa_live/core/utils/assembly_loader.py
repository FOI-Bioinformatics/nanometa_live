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


def load_assembly_decisions(results_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Return the pipeline's assembly decisions, or [] when there are none.

    nanometanf's ASSEMBLY_DEPTH_GATE writes one
    ``<sample>[.taxid<N>].assembly_decision.json`` per candidate, on every
    path, whether it assembled or declined. That record is what turns an
    absent assembly from silence into a stated reason: on a real field corpus
    no organism reached 2x of its reference where a draft needs 30x, so
    declining is the normal answer and the operator needs to see why, with the
    shortfall, rather than an empty panel (assembly audit, 2026-09-03).

    Each entry is the record as written, with ``sample`` filled in for
    convenience. Unreadable files are skipped, as in ``load_assembly_stats``:
    a malformed record must not take the panel down with it.
    """
    if not results_dir:
        return []
    base = Path(results_dir) / "canonical" / "assembly"
    if not base.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for f in sorted(base.glob("*.assembly_decision.json")):
        data = _read_json(f)
        if not data:
            continue
        entry = dict(data)
        entry["sample"] = (data.get("sample_id")
                           or f.name.split(".assembly_decision.json")[0])
        out.append(entry)
    return out
