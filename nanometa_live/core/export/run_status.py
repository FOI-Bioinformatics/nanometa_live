"""Read a run's terminal status from the on-disk run metadata.

BackendManager records ``final_status``/``final_errors`` into
``.nanometa.run.json`` when a run terminates (round 3). The exported
report reads it through here -- the export worker cannot see the live
backend singleton, and every verdict surface must say the same thing: a
report generated over a crashed run must never carry a green banner.
"""

import json
import os
from typing import Any, Dict

RUN_METADATA_FILENAME = ".nanometa.run.json"


def read_final_run_status(results_dir: str) -> Dict[str, Any]:
    """Return ``{"pipeline_error": bool, "pipeline_error_detail": str|None}``.

    ``final_status`` is absent for runs recorded before round 3 and for
    exports taken mid-run; both yield the no-error shape so older trees
    render exactly as before.
    """
    pipeline_error = False
    detail = None
    try:
        path = os.path.join(results_dir, RUN_METADATA_FILENAME)
        with open(path) as f:
            meta = json.load(f)
        if isinstance(meta, dict) and meta.get("final_status") == "error":
            pipeline_error = True
            errors = meta.get("final_errors") or []
            detail = str(errors[-1]) if errors else None
    except (OSError, ValueError):
        pass
    return {
        "pipeline_error": pipeline_error,
        "pipeline_error_detail": detail,
    }
