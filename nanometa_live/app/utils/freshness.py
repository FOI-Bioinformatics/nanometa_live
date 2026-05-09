"""
Pure helpers for per-sample freshness derivation (U2, 2026-05-09 UX spec).

A sample's freshness is the wall-clock seconds since its most recent
output file mtime. We look first at the realtime incremental layout
(``kraken2/<sample>/batch_reports/*``) and fall back to top-level
``kraken2/*<sample>*`` reports when batch_reports is empty.

Logic is isolated here so it can be unit tested without filesystem
mocks for callback wiring.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, Optional


def _max_mtime_in_dir(path: str) -> Optional[float]:
    """Return the maximum file mtime in a directory, or None when empty."""
    if not path or not os.path.isdir(path):
        return None
    latest: Optional[float] = None
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        mt = entry.stat().st_mtime
                        if latest is None or mt > latest:
                            latest = mt
                except OSError:
                    continue
    except OSError:
        return None
    return latest


def sample_last_data_ts(main_dir: str, sample: str) -> Optional[float]:
    """
    Return the most recent output mtime for a single sample.

    Checks ``kraken2/<sample>/batch_reports/`` first (the realtime layout)
    then falls back to scanning top-level ``kraken2/`` for files whose
    name contains the sample identifier.
    """
    if not main_dir or not sample or sample == "All Samples":
        return None
    kraken_dir = os.path.join(main_dir, "kraken2")
    nested = os.path.join(kraken_dir, sample, "batch_reports")
    nested_mt = _max_mtime_in_dir(nested)
    if nested_mt is not None:
        return nested_mt

    if not os.path.isdir(kraken_dir):
        return None
    latest: Optional[float] = None
    try:
        with os.scandir(kraken_dir) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False) and sample in entry.name:
                        mt = entry.stat().st_mtime
                        if latest is None or mt > latest:
                            latest = mt
                except OSError:
                    continue
    except OSError:
        return None
    return latest


def freshness_map(
    main_dir: str, samples: Iterable[str]
) -> Dict[str, Optional[float]]:
    """Build a {sample_name: last_data_ts} map for the given samples."""
    out: Dict[str, Optional[float]] = {}
    for s in samples or []:
        if s == "All Samples":
            continue
        out[s] = sample_last_data_ts(main_dir, s)
    return out


def age_seconds_for(
    last_data_ts: Optional[float], now: float
) -> Optional[float]:
    """Return age = now - last_data_ts, or None when the timestamp is missing."""
    if last_data_ts is None:
        return None
    return max(0.0, float(now) - float(last_data_ts))
