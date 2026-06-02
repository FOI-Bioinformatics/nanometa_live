"""Per-batch validation result collection (realtime drill-down).

In realtime mode nanometanf preserves each batch's validation outputs under
``validation/{tool}/batch/<sample>_taxid<tid>_<batch_id>.<ext>`` while the
canonical flat files (``validation/{tool}/<sample>_taxid<tid>.<ext>``) hold the
cumulative view kept current by the cumulative aggregator. This module builds a
``ValidationResult`` list for a single batch id so the dashboard's per-batch
view can show one batch in isolation.

``parse_minimap2_stats_json`` (self-describing JSON, no filename parsing) is
reused from ``minimap2_stats``; the BLAST tabular parser is passed in as a bound
method to avoid a circular import with ``blast_validation_parser``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from nanometa_live.core.parsers.minimap2_stats import parse_minimap2_stats_json

logger = logging.getLogger(__name__)


def _batch_dir(results_dir: Path, tool: str) -> Path:
    return Path(results_dir) / "validation" / tool / "batch"


def collect_batch_results(
    results_dir: Path,
    batch_id: str,
    sample: Optional[str],
    taxid: Optional[int],
    parse_blast_tabular: Callable,
) -> List:
    """Return ValidationResults (blast + minimap2) for a single ``batch_id``."""
    results: List = []
    suffix = f"_{batch_id}"

    # minimap2 per-batch stats: self-describing JSON, parsed like the cumulative ones.
    mm2 = _batch_dir(results_dir, "minimap2")
    if mm2.is_dir():
        for stats_file in mm2.glob(f"*{suffix}.minimap2_stats.json"):
            r = parse_minimap2_stats_json(stats_file)
            if r is None:
                continue
            if sample and r.sample_id != sample:
                continue
            if taxid and r.taxid != taxid:
                continue
            results.append(r)

    # blast per-batch tabular: <sample>_taxid<tid>_<batch_id>.blast.tsv
    blast = _batch_dir(results_dir, "blast")
    if blast.is_dir():
        for tsv in blast.glob(f"*{suffix}.blast.tsv"):
            name = tsv.name[: -len(".blast.tsv")]
            if not name.endswith(suffix):
                continue
            stem = name[: -len(suffix)]  # <sample>_taxid<tid>
            if "_taxid" not in stem:
                continue
            file_sample, _, tid_str = stem.rpartition("_taxid")
            try:
                file_taxid = int(tid_str)
            except ValueError:
                continue
            if sample and file_sample != sample:
                continue
            if taxid and file_taxid != taxid:
                continue
            results.append(parse_blast_tabular(tsv, file_sample, file_taxid))

    return results
