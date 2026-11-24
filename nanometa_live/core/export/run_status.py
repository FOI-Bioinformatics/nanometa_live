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
from typing import Any, Dict, List, Optional

RUN_METADATA_FILENAME = ".nanometa.run.json"
LOCK_FILENAME = ".nanometa.lock"


LOST_INPUTS_SUBDIR = os.path.join("pipeline_info", "lost_inputs")


def read_lost_inputs(results_dir: str) -> List[Dict[str, Any]]:
    """Inputs the pipeline lost to error isolation, from nanometanf's markers.

    ``conf/error_isolation.config`` ignores exit 1/2 on the QC and
    classification processes and runs ``bin/nanometanf_lost_input_marker.sh``
    as their afterScript, which writes one JSON file per absorbed failure
    under ``pipeline_info/lost_inputs/``. A file that dies in QC is never an
    expected batch, so neither the manifest nor ``aggregation_stats.json``
    can see it (round-4 audit, H20); these markers are the record of which
    input files are absent from every count. Each entry carries ``stage``,
    ``sample``, ``exit_status`` and ``input_files``; unreadable markers are
    skipped, and a tree without the directory yields an empty list.
    """
    out: List[Dict[str, Any]] = []
    marker_dir = os.path.join(results_dir, LOST_INPUTS_SUBDIR)
    try:
        names = sorted(n for n in os.listdir(marker_dir) if n.endswith(".json"))
    except OSError:
        return out
    for name in names:
        try:
            with open(os.path.join(marker_dir, name)) as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        files = data.get("input_files")
        out.append({
            "stage": str(data.get("stage") or data.get("process") or "unknown"),
            "sample": str(data.get("sample") or "unknown"),
            "exit_status": data.get("exit_status"),
            "input_files": [str(x) for x in files] if isinstance(files, list) else [],
        })
    return out


PROCESSED_INPUTS_LEDGER = os.path.join("pipeline_info", "processed_inputs.tsv")
_READ_EXTENSIONS = (".fastq", ".fastq.gz", ".fq", ".fq.gz")


def count_unprocessed_inputs(results_dir: str, input_dir: str,
                             started_at: Optional[str],
                             max_file_age_minutes: Optional[float]) -> Optional[int]:
    """Input read files in the watched folder that no run finished classifying.

    nanometanf appends every input it finished classifying to
    ``pipeline_info/processed_inputs.tsv`` (``source_file``, absolute path),
    so the unprocessed inputs are the read files absent from it. Files older
    than the start-up age filter (``max_file_age_minutes`` before
    ``started_at``) were skipped on purpose and are not counted. Returns None
    when there is no ledger (an older pipeline): the caller then has only the
    inbox-minus-processed arithmetic, which also counts those skipped files
    and files an earlier run classified.
    """
    ledger = os.path.join(results_dir or "", PROCESSED_INPUTS_LEDGER)
    if not input_dir or not os.path.isfile(ledger):
        return None
    done = set()
    try:
        with open(ledger) as fh:
            header = fh.readline().rstrip("\n").split("\t")
            col = header.index("source_file") if "source_file" in header else 2
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) > col and parts[col]:
                    done.add(os.path.realpath(parts[col]))
    except OSError:
        return None

    cutoff = None
    if max_file_age_minutes and started_at:
        try:
            from datetime import datetime
            cutoff = (datetime.fromisoformat(started_at).timestamp()
                      - float(max_file_age_minutes) * 60)
        except (TypeError, ValueError):
            cutoff = None

    from nanometa_live.core.utils.auto_detect import find_sample_subdirs
    dirs = [input_dir] + [str(d) for d in find_sample_subdirs(input_dir)]
    count = 0
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.endswith(_READ_EXTENSIONS):
                continue
            path = os.path.join(d, name)
            if cutoff is not None:
                try:
                    if os.stat(path).st_mtime < cutoff:
                        continue
                except OSError:
                    continue
            if os.path.realpath(path) not in done:
                count += 1
    return count


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
        "failed_tasks": [],
        "processes_failed": 0,
        "lost_inputs": [],
    }
    # Markers do not depend on the run metadata: a tree the CLI produced has
    # no .nanometa.run.json and can still have lost inputs.
    result["lost_inputs"] = read_lost_inputs(results_dir)
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
    # Tasks the pipeline failed and skipped under error isolation; their
    # reads are absent from every count in the report (round-4, H20).
    failed = meta.get("failed_tasks")
    result["failed_tasks"] = [str(t) for t in failed] if isinstance(failed, list) else []
    pf = meta.get("processes_failed")
    result["processes_failed"] = (
        int(pf) if isinstance(pf, (int, float)) else len(result["failed_tasks"]))
    fp = meta.get("files_processed")
    result["files_processed"] = int(fp) if isinstance(fp, (int, float)) else None
    inbox = meta.get("input_files_at_end")
    result["input_files_at_end"] = int(inbox) if isinstance(inbox, (int, float)) else None
    # Input the run never classified. The count recorded from the
    # pipeline's ledger is exact; without it, the inbox minus files_processed
    # (which also counts files skipped by the age filter or classified by an
    # earlier run). None when neither is known.
    recorded = meta.get("unprocessed_input_files")
    result["unprocessed_input_exact"] = isinstance(recorded, (int, float))
    if isinstance(recorded, (int, float)):
        result["unprocessed_input_files"] = int(recorded)
    elif result["files_processed"] is not None and result["input_files_at_end"] is not None:
        result["unprocessed_input_files"] = max(
            0, result["input_files_at_end"] - result["files_processed"])
    else:
        result["unprocessed_input_files"] = None
    return result
