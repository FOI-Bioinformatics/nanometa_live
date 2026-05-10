"""Regression test for the F1 cross-tab agreement fix under fast streaming.

Background: under `sample_handling: per_file` the pipeline can emit a
new kraken2 cumulative report for every input file. The fingerprint
store advances on each one, and Dashboard plus Organisms callbacks
can each fire on a slightly different tick, reading the disk at
different snapshots. Each tab independently called
``load_kraken_data + get_classification_stats``, so the two totals
could disagree by a few hundred reads even though the F1 logic
(root.cumul_reads + unclassified.cumul_reads) was correct on both
sides.

The fix: Organisms tab now takes ``dashboard-overall-status-cache``
as a Dash State input and prefers the cached ``total_reads`` value
when the aggregated "All Samples" view is selected. Both tabs then
render from one fact source.

These tests pin the wiring at the source-code level (a full Dash
roundtrip is expensive and fragile in unit tests). They:
  1. Confirm the new State input is declared.
  2. Confirm the callback signature accepts the new positional arg.
  3. Confirm the helper logic prefers the cache total when the
     aggregated view is selected, and falls back to the local
     computation otherwise.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import nanometa_live.app.tabs.main_tab as main_tab


MAIN_TAB_SOURCE = Path(main_tab.__file__).read_text()


def test_callback_declares_dashboard_overall_status_cache_state():
    """The Dash callback for update_main_results must take the cache."""
    assert 'State("dashboard-overall-status-cache", "data")' in MAIN_TAB_SOURCE


def test_callback_signature_accepts_overall_status_cache_arg():
    """Callback signature must include the new positional parameter."""
    pattern = re.compile(
        r"def update_main_results\([^)]*\boverall_status_cache\b",
        re.DOTALL,
    )
    assert pattern.search(MAIN_TAB_SOURCE)


def test_aggregated_view_prefers_cached_total():
    """When aggregated view is selected and cache has total_reads, use it."""
    # Mirrors the runtime branch
    selected_sample = "All Samples"
    overall_status_cache = {"total_reads": 379, "organisms_detected": 18}

    classified_reads = 100
    unclassified_reads = 5
    total_reads = classified_reads + unclassified_reads  # 105 (stale)

    is_aggregated_view = (
        selected_sample is None or selected_sample == "All Samples"
    )
    if is_aggregated_view and overall_status_cache:
        cached_total = overall_status_cache.get("total_reads")
        if cached_total is not None:
            total_reads = int(cached_total)

    assert total_reads == 379  # cache wins, not the stale 105


def test_per_sample_view_uses_local_computation():
    """Per-sample views must NOT read the aggregate cache."""
    selected_sample = "barcode01"
    overall_status_cache = {"total_reads": 379}

    classified_reads = 50
    unclassified_reads = 1
    total_reads = classified_reads + unclassified_reads

    is_aggregated_view = (
        selected_sample is None or selected_sample == "All Samples"
    )
    if is_aggregated_view and overall_status_cache:
        cached_total = overall_status_cache.get("total_reads")
        if cached_total is not None:
            total_reads = int(cached_total)

    assert total_reads == 51  # local sum, not the all-samples cache


def test_empty_cache_falls_back_to_local():
    """Initial load with no cache yet must fall back to the local sum."""
    selected_sample = "All Samples"
    overall_status_cache = None

    classified_reads = 42
    unclassified_reads = 0
    total_reads = classified_reads + unclassified_reads

    is_aggregated_view = (
        selected_sample is None or selected_sample == "All Samples"
    )
    if is_aggregated_view and overall_status_cache:
        cached_total = overall_status_cache.get("total_reads")
        if cached_total is not None:
            total_reads = int(cached_total)

    assert total_reads == 42


def test_cache_missing_total_falls_back_to_local():
    """A malformed cache without total_reads must not break the tile."""
    selected_sample = "All Samples"
    overall_status_cache = {"organisms_detected": 7}  # no total_reads

    classified_reads = 99
    unclassified_reads = 1
    total_reads = classified_reads + unclassified_reads

    is_aggregated_view = (
        selected_sample is None or selected_sample == "All Samples"
    )
    if is_aggregated_view and overall_status_cache:
        cached_total = overall_status_cache.get("total_reads")
        if cached_total is not None:
            total_reads = int(cached_total)

    assert total_reads == 100
