"""Loader for taxpasta standardized profiles.

nanometanf runs ``taxpasta standardise`` and publishes ``taxpasta/*.tsv``. The
GUI never used them. With the pipeline's current (flag-less) invocation the TSV
carries only ``taxonomy_id`` + ``count`` (no names/ranks), so on their own they
are less informative than the Kraken2-based Taxonomy tab. Their value is a single
CROSS-SAMPLE matrix; this loader returns tidy ``{sample, taxid, count}`` rows
(handling both the per-sample standardise output and a merged wide table) which
the Reports tab pivots and enriches with organism names from the Kraken2 data.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_TAXID_COLS = ("taxonomy_id", "taxid", "tax_id")
_META_COLS = {"name", "rank", "lineage"}


def _taxid_column(columns) -> Optional[str]:
    lower = {c.lower(): c for c in columns}
    for cand in _TAXID_COLS:
        if cand in lower:
            return lower[cand]
    return None


def load_taxpasta_long(results_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Return taxpasta counts as tidy ``{sample, taxid, count}`` rows, or [].

    Handles two shapes: the per-sample ``standardise`` output (``taxonomy_id`` +
    ``count``; the sample is the filename) and a merged wide table (``taxonomy_id``
    + one count column per sample). Malformed/empty files are skipped.
    """
    if not results_dir:
        return []
    base = Path(results_dir) / "taxpasta"
    if not base.is_dir():
        return []

    rows: List[Dict[str, Any]] = []
    for f in sorted(base.glob("*.tsv")):
        try:
            df = pd.read_csv(f, sep="\t")
        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
                pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as e:
            logger.debug("taxpasta read failed for %s: %s", f, e)
            continue
        if df.empty:
            continue
        tax_col = _taxid_column(df.columns)
        if tax_col is None:
            continue

        lower = {c.lower(): c for c in df.columns}
        count_cols = [
            c for c in df.columns
            if c != tax_col and c.lower() not in _META_COLS
        ]
        if "count" in lower:
            # Per-sample standardise output: sample = file stem.
            sample = f.stem
            for _, r in df.iterrows():
                rows.append(_row(sample, r[tax_col], r[lower["count"]]))
        else:
            # Merged wide: each remaining column is a sample.
            for _, r in df.iterrows():
                for c in count_cols:
                    rows.append(_row(str(c), r[tax_col], r[c]))
    return [r for r in rows if r is not None]


def _row(sample: str, taxid: Any, count: Any) -> Optional[Dict[str, Any]]:
    try:
        return {"sample": sample, "taxid": int(taxid), "count": int(float(count))}
    except (TypeError, ValueError):
        return None
