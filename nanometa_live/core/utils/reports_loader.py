"""Discovery + safe serving of pipeline report artifacts (MultiQC, Nextflow).

nanometanf produces rich HTML reports the GUI never surfaced: the MultiQC report
and the Nextflow execution report / timeline / trace under ``pipeline_info/``.
This module detects which exist under the operator's current results directory
and resolves their on-disk path for a Flask serve route, so the Reports tab can
link to them.

Security model: a Flask route on a localhost operator app serves these files.
Only the fixed REPORT_SPECS globs can ever be resolved (no arbitrary path is
accepted from the client), and the resolved file must stay inside the current
results directory (traversal guard). The "current" directory is held
server-side and refreshed by the Reports-tab callback (which has the app-config),
rather than taken from the URL, so a client cannot point the route at an
arbitrary directory.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# key -> (label, glob relative to results dir, mime kind). The glob picks the
# file(s); for timestamped Nextflow outputs the newest match wins.
REPORT_SPECS: List[Dict[str, str]] = [
    {"key": "multiqc", "label": "MultiQC Report",
     "glob": "multiqc/multiqc_report.html", "kind": "html",
     "desc": "Aggregated QC + classification across all samples and tools."},
    {"key": "exec_report", "label": "Nextflow Execution Report",
     "glob": "pipeline_info/execution_report*.html", "kind": "html",
     "desc": "Per-task CPU / memory / runtime and success/failure summary."},
    {"key": "exec_timeline", "label": "Execution Timeline",
     "glob": "pipeline_info/execution_timeline*.html", "kind": "html",
     "desc": "Gantt-style task execution over time."},
    {"key": "exec_trace", "label": "Execution Trace",
     "glob": "pipeline_info/execution_trace*.txt", "kind": "text",
     "desc": "Tab-separated per-task metrics (status, duration, memory)."},
]

_SPEC_BY_KEY = {s["key"]: s for s in REPORT_SPECS}

# Server-side holder of the directory the operator is currently viewing. Set by
# the Reports-tab callback; read by the Flask serve route.
_current_dir_lock = threading.Lock()
_current_dir: Optional[str] = None


def set_reports_dir(results_dir: Optional[str]) -> None:
    """Record the results directory the Reports tab is currently showing."""
    global _current_dir
    with _current_dir_lock:
        _current_dir = results_dir or None


def _get_reports_dir() -> Optional[str]:
    with _current_dir_lock:
        return _current_dir


def _latest_match(results_dir: Path, glob: str) -> Optional[Path]:
    """Newest file matching ``glob`` under ``results_dir``, or None."""
    matches = sorted(results_dir.glob(glob))
    return matches[-1] if matches else None


def detect_reports(results_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Return one entry per report spec with presence + link URL.

    Each entry: ``{key, label, desc, kind, exists, url}``. ``url`` is the
    ``/reports/<key>`` serve route; ``exists`` is False when the file is absent
    (MultiQC skipped/failed, batch run with no pipeline_info, etc.).
    """
    base = Path(results_dir) if results_dir else None
    out: List[Dict[str, Any]] = []
    for spec in REPORT_SPECS:
        exists = bool(base and base.is_dir() and _latest_match(base, spec["glob"]))
        out.append({
            "key": spec["key"],
            "label": spec["label"],
            "desc": spec["desc"],
            "kind": spec["kind"],
            "exists": exists,
            "url": f"/reports/{spec['key']}",
        })
    return out


def resolve_report_path(key: str) -> Optional[Path]:
    """Resolve the on-disk path for a report key under the current results dir.

    Returns the absolute path only when the key is a known spec, a matching file
    exists, and the resolved path stays inside the current results directory
    (traversal guard). Returns None otherwise -- the Flask route then 404s.
    """
    spec = _SPEC_BY_KEY.get(key)
    if spec is None:
        return None
    results_dir = _get_reports_dir()
    if not results_dir:
        return None
    base = Path(results_dir).resolve()
    if not base.is_dir():
        return None
    match = _latest_match(base, spec["glob"])
    if match is None:
        return None
    resolved = match.resolve()
    # Traversal guard: the file must live inside the results directory.
    try:
        resolved.relative_to(base)
    except ValueError:
        logger.warning("Report path escaped results dir: %s not under %s", resolved, base)
        return None
    return resolved
