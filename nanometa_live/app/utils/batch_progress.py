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
        if not self.planned:
            return None
        total = len(self.planned)
        with_result = len(self.preliminary) + len(self.complete)
        return f"Preliminary: {with_result} of {total} barcodes; complete: {len(self.complete)} of {total}"


def batch_progress(results_dir: str) -> BatchProgress:
    plan = read_chunk_plan(results_dir)
    done = {s: _done_batches(results_dir, s) for s in plan}
    return BatchProgress(planned=plan, done=done)
