"""Read a run's terminal status from the on-disk run metadata.

BackendManager records ``final_status``/``final_errors`` into
``.nanometa.run.json`` when a run terminates (round 3), and since the
round-4 audit also ``stop_reason``, ``ended_at`` and ``files_processed``
for a run that was stopped by the operator or by the inactivity backstop.
The exported report reads it through here -- the export worker cannot see
the live backend singleton, and every verdict surface must say the same
thing: a report generated over a crashed run must never carry a green
banner, and a report over a stopped or still-active run must say so.
"""

import json
import os
from typing import Any, Dict

RUN_METADATA_FILENAME = ".nanometa.run.json"
LOCK_FILENAME = ".nanometa.lock"


def read_final_run_status(results_dir: str) -> Dict[str, Any]:
    """Return the run's terminal state as the report needs it.

    Keys: ``pipeline_error`` (bool), ``pipeline_error_detail`` (str or None),
    ``run_state`` (``completed`` / ``stopped`` / ``error`` / ``active`` /
    ``unknown``), ``stop_reason``, ``ended_at`` and ``files_processed``.

    ``active`` means the metadata was written at Start, carries no terminal
    status yet, and the backend's lock file is present: the export was taken
    mid-run. ``unknown`` covers trees with no metadata and runs recorded
    before round 3, which render exactly as before.
    """
    result: Dict[str, Any] = {
        "pipeline_error": False,
        "pipeline_error_detail": None,
        "run_state": "unknown",
        "stop_reason": None,
        "ended_at": None,
        "files_processed": None,
    }
    try:
        path = os.path.join(results_dir, RUN_METADATA_FILENAME)
        with open(path) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return result
    if not isinstance(meta, dict):
        return result

    final = meta.get("final_status")
    if final == "error":
        result["pipeline_error"] = True
        errors = meta.get("final_errors") or []
        result["pipeline_error_detail"] = str(errors[-1]) if errors else None
        result["run_state"] = "error"
    elif final in ("completed", "stopped"):
        result["run_state"] = final
    elif meta.get("written_at") and os.path.exists(
            os.path.join(results_dir, LOCK_FILENAME)):
        result["run_state"] = "active"

    result["stop_reason"] = meta.get("stop_reason")
    result["ended_at"] = meta.get("ended_at")
    fp = meta.get("files_processed")
    result["files_processed"] = int(fp) if isinstance(fp, (int, float)) else None
    inbox = meta.get("input_files_at_end")
    result["input_files_at_end"] = int(inbox) if isinstance(inbox, (int, float)) else None
    # Input the run never classified (real-time: files that landed after the
    # timer or the Stop). None when either count is unknown.
    if result["files_processed"] is not None and result["input_files_at_end"] is not None:
        result["unprocessed_input_files"] = max(
            0, result["input_files_at_end"] - result["files_processed"])
    else:
        result["unprocessed_input_files"] = None
    return result
