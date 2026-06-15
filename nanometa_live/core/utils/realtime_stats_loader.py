"""Loader for the realtime performance/quality stats nanometanf emits.

In realtime mode nanometanf writes ``realtime_stats/cumulative_stats.json``
(throughput, session totals, per-batch trends), ``realtime_stats/alerts.json``
(performance/quality alerts), and per-batch snapshots under
``realtime_batch_stats/``. The GUI never surfaced any of it. This loader reads
the cumulative stats + alerts defensively (any key may be absent) and returns a
flat dict for the Reports tab, or ``None`` in batch mode (no realtime_stats/).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
            json.JSONDecodeError, ValueError) as e:
        logger.debug("realtime stats read failed for %s: %s", path, e)
        return None


def load_realtime_stats(results_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return realtime performance stats for the Reports tab, or None.

    None means batch mode / no realtime stats produced. The returned dict has:
    ``session`` (session_info), ``totals``, ``performance``, ``trends``, and
    ``alerts`` (list) -- each defaulting to empty so the panel can render
    whatever is present without KeyErrors.
    """
    if not results_dir:
        return None
    base = Path(results_dir) / "realtime_stats"
    cumulative = _read_json(base / "cumulative_stats.json")
    if cumulative is None:
        return None

    alerts_doc = _read_json(base / "alerts.json") or {}
    alerts = alerts_doc.get("alerts", []) if isinstance(alerts_doc, dict) else []

    return {
        "session": cumulative.get("session_info", {}) or {},
        "totals": cumulative.get("totals", {}) or {},
        "averages": cumulative.get("averages", {}) or {},
        "performance": cumulative.get("performance", {}) or {},
        "trends": cumulative.get("trends", {}) or {},
        "alerts": alerts if isinstance(alerts, list) else [],
    }
