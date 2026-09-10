"""Batch-mode progress from the chunk plan and the per-batch reports.

nanometanf's chunked batch mode writes ``pipeline_info/batch_chunk_plan.json``
({sample: {files, chunks}}) before any task runs, and one per-batch report per
finished chunk under ``kraken2/<sample>/batch_reports/`` (two byte-identical
copies per batch: ``batch_N`` and ``<sample>_batchN``). Comparing the two says
which barcodes are preliminary (some chunks done), complete (all done) or
pending (none yet). A real-time run, or an older pipeline, writes no plan and
gets no progress line.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_BATCH_ID_RE = re.compile(r"(?:^|_)batch_?(\d+)\.kraken2\.report\.txt$")


def read_chunk_plan(results_dir: str) -> Dict[str, int]:
    """Planned chunk count per sample, or {} when there is no readable plan."""
    path = os.path.join(results_dir or "", "pipeline_info", "batch_chunk_plan.json")
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    plan: Dict[str, int] = {}
    for sample, entry in (raw or {}).items():
        try:
            plan[str(sample)] = int(entry["chunks"])
        except (KeyError, TypeError, ValueError):
            continue
    return plan


def _done_batches(results_dir: str, sample: str) -> int:
    directory = os.path.join(results_dir, "kraken2", sample, "batch_reports")
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    ids = set()
    for name in names:
        m = _BATCH_ID_RE.search(name)
        if m:
            ids.add(int(m.group(1)))
    return len(ids)


@dataclass
class BatchProgress:
    planned: Dict[str, int] = field(default_factory=dict)
    done: Dict[str, int] = field(default_factory=dict)

    @property
    def preliminary(self) -> List[str]:
        return sorted(s for s, n in self.planned.items() if 0 < self.done.get(s, 0) < n)

    @property
    def complete(self) -> List[str]:
        return sorted(s for s, n in self.planned.items() if self.done.get(s, 0) >= n)

    @property
    def pending(self) -> List[str]:
        return sorted(s for s in self.planned if self.done.get(s, 0) == 0)

    def summary_line(self) -> Optional[str]:
        """One line naming how many barcodes are complete, running and waiting.

        The word "preliminary" is deliberately absent here. It used to open
        this line, counting barcodes that HAVE a preliminary result, while the
        verdict subtitle used the same word for barcodes that are NOT yet
        complete -- so one frame could read "Preliminary: 11 of 12" above
        "preliminary: 12 of 12 barcodes still classifying" and invite the
        operator to read 11 and 12 as one quantity. The three counts here are
        disjoint and sum to the total, so no reading of them collides with the
        clause. The per-barcode selector badge keeps the word, where it is
        literally a preliminary result for that one barcode.
        """
        if not self.planned:
            return None
        total = len(self.planned)
        complete = len(self.complete)
        if complete == total:
            return f"Barcodes: {total} of {total} complete"
        parts = [f"{complete} complete"]
        in_progress = len(self.preliminary)
        if in_progress:
            parts.append(f"{in_progress} in progress")
        pending = len(self.pending)
        if pending:
            parts.append(f"{pending} pending")
        return f"Barcodes: {', '.join(parts)} of {total}"


#: ``results_dir -> (plan mtime_ns, plan, per-sample dir mtimes, result)``.
#: Three callbacks (header, sample selector, verdict subtitle) ask for the
#: same progress on every poll, and each ask cost one ``open`` plus one
#: ``listdir`` per planned sample -- about 291 syscalls per tick at 96
#: barcodes, against the ~2,119 the scaling invariant budgets. The memo
#: re-checks with one ``stat`` per planned sample instead, which is both
#: cheaper than a ``listdir`` and sufficient: adding a per-batch report
#: bumps the containing directory's mtime. Cleared at run boundaries via
#: ``clear_all_loader_caches``.
_progress_memo: dict = {}

#: Distinct results directories worth remembering. One run writes one, so
#: the cap only bounds a long-lived process that has followed several.
_PROGRESS_MEMO_MAX = 8


def clear_batch_progress_memo() -> None:
    """Drop the per-directory progress memo (run boundary, or a cold cell)."""
    _progress_memo.clear()


def _mtime_ns(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _batch_dir_key(results_dir: str, plan: Dict[str, int]) -> tuple:
    """One stat per planned sample's ``batch_reports/`` directory."""
    return tuple(
        (sample, _mtime_ns(os.path.join(results_dir, "kraken2", sample, "batch_reports")))
        for sample in sorted(plan)
    )


def batch_progress(results_dir: str) -> BatchProgress:
    """Planned versus finished chunks per sample, memoised on directory mtimes.

    The returned object is shared between callers within a poll; every
    consumer only reads it.
    """
    root = results_dir or ""
    plan_path = os.path.join(root, "pipeline_info", "batch_chunk_plan.json")
    plan_mtime = _mtime_ns(plan_path)

    cached = _progress_memo.get(root)
    if cached is not None and cached[0] == plan_mtime:
        plan = cached[1]
        dir_key = _batch_dir_key(root, plan)
        if dir_key == cached[2]:
            return cached[3]
    else:
        plan = read_chunk_plan(root)
        dir_key = _batch_dir_key(root, plan)

    done = {s: _done_batches(root, s) for s in plan}
    progress = BatchProgress(planned=plan, done=done)
    if root not in _progress_memo and len(_progress_memo) >= _PROGRESS_MEMO_MAX:
        _progress_memo.clear()
    _progress_memo[root] = (plan_mtime, plan, dir_key, progress)
    return progress
