"""One dashboard polling tick, reproduced without a browser.

The harness calls the loaders and figure builders directly rather than
driving the real Dash callbacks through ``tests/dash_test_utils``. Three
reasons:

* The callbacks are gated by ``interval_tick_is_redundant`` module state and
  ``PreventUpdate``. Driving them faithfully would mean reimplementing Dash's
  scheduler inside the harness, which is where fidelity bugs would live.
* In the running app these callbacks fire concurrently off one fingerprint;
  a harness measures a serial sum either way, and the serial sum is the right
  number for a scaling study.
* Binding a committed baseline to Dash internals means a Dash upgrade
  invalidates the measurement history for reasons unrelated to performance.

Fidelity is instead pinned by ``tests/test_perf_poll_fidelity.py``, which
drives the real callbacks with ``load_kraken_data`` wrapped in a counter and
asserts the total matches :func:`simulate_poll`.

Deliberately excluded: ``load_kraken2_taxonomy`` /
``apply_authoritative_taxonomy`` (they need a real Kraken2 ``inspect.txt``,
which would couple the fixture to the database format, and round 3 does not
touch them), Dash JSON serialisation, and the browser.

Round-3 additions, measured as steps 9-10 so the older cells stay
comparable metric by metric: the per-sample organisms build
(``_species_df_to_organisms``, the attribution-path cost that is O(rows)
per sample) and the validation scan (``get_validation_results`` plus the
batch-id enumeration) -- the O(pairs) and O(pairs x batches) paths that
had never been in the measured tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Frozen so figure cost is stable across runs and comparable across N.
PERF_CONFIG: Dict[str, Any] = {
    "default_hierarchy_letters": ["D", "C", "G", "S"],
    "taxonomic_hierarchy_letters": ["D", "C", "G", "S"],
    "max_taxa_per_level": 25,
    "min_reads": 10,
    "kraken_db": "",
    "kraken_taxonomy": "ncbi",
    "offline_mode": True,
}

_DOMAINS = ["Domain_0", "Domain_1"]
_TAX_LEVELS = ["D", "C", "G", "S"]


@dataclass(frozen=True)
class PollResult:
    """Observable side effects of one simulated poll."""

    kraken_loads: int
    figures_built: int
    rows: int
    samples: int
    organisms_built: int = 0
    validation_results: int = 0
    validation_batches_seen: int = 0


def simulate_poll(
    main_dir: str,
    *,
    selected_sample: Optional[str] = None,
    build_figures: bool = True,
) -> PollResult:
    """Run the loader and figure work of a single polling tick.

    The sequence mirrors the real call sites one step at a time. Where a real
    site is a private helper that other work may be refactoring concurrently
    (the dashboard per-sample loops), the harness replicates the loop against
    the public loader instead. The measured I/O is identical; the coupling is
    not.
    """
    from nanometa_live.app.tabs.classification_helpers import (
        create_sankey_data, create_sunburst_data,
    )
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    from nanometa_live.core.utils.loader_utils import check_data_freshness
    from nanometa_live.core.utils.qc_loaders import (
        get_sample_statistics_summary, load_seqkit_stats,
    )
    from nanometa_live.core.utils.sample_detector import get_available_samples

    kraken_loads = 0
    figures_built = 0

    # 1. The poll gate. app/callbacks/status.py:compute_results_fingerprint.
    check_data_freshness(main_dir)

    # 2. Sample enumeration. dashboard_tab.py:_resolve_samples.
    samples = get_available_samples(main_dir)
    real_samples = [s for s in samples if s != "All Samples"]
    if selected_sample is None and real_samples:
        selected_sample = real_samples[0]

    # 3. Per-sample dashboard data. dashboard_helpers.py:_build_sample_data.
    for sample in real_samples:
        load_kraken_data(main_dir, sample)
        kraken_loads += 1

    # 4. Per-sample pathogen attribution.
    #    dashboard_helpers.py:_load_per_sample_organisms.
    for sample in real_samples:
        df = load_kraken_data(main_dir, sample)
        kraken_loads += 1
        if not df.empty:
            df[(df["rank"] == "S") & (df["reads"] >= 5)]

    # 5. QC per-sample table. qc_tab.py:update_per_sample_table. Internally
    #    this loads fastp, nanoplot and kraken data once per sample.
    summary = get_sample_statistics_summary(main_dir)
    kraken_loads += len(real_samples)

    # 6. Seqkit, aggregate and selected. qc_tab.py.
    load_seqkit_stats(main_dir, None)
    if selected_sample:
        load_seqkit_stats(main_dir, selected_sample)

    # 7. Classification tab. classification_tab.py.
    aggregate_df = load_kraken_data(main_dir, None)
    kraken_loads += 1
    selected_df = aggregate_df
    if selected_sample:
        selected_df = load_kraken_data(main_dir, selected_sample)
        kraken_loads += 1

    # 8. Figure construction. classification_tab.py.
    if build_figures and not selected_df.empty:
        create_sankey_data(
            selected_df, _DOMAINS, _TAX_LEVELS,
            PERF_CONFIG["min_reads"], PERF_CONFIG["max_taxa_per_level"],
        )
        figures_built += 1
        create_sunburst_data(
            selected_df, _DOMAINS, _TAX_LEVELS,
            PERF_CONFIG["min_reads"], PERF_CONFIG,
            max_taxa_per_level=PERF_CONFIG["max_taxa_per_level"],
        )
        figures_built += 1

    # 9. Organisms build (round 3). dashboard_helpers._load_per_sample_
    #    organisms turns each sample's species rows into per-taxon dicts;
    #    O(rows) per sample and previously unmeasured. The frames are
    #    cache hits after step 4, so this isolates the dict-build cost.
    from nanometa_live.app.tabs.dashboard_helpers import (
        _species_df_to_organisms, _species_discovery_df,
    )
    organisms_built = 0
    for sample in real_samples:
        df = load_kraken_data(main_dir, sample)
        if not df.empty:
            organisms_built += len(
                _species_df_to_organisms(_species_discovery_df(df)))

    # 10. Validation scan (round 3). main_tab/validation_tab read through
    #     the shared parser each poll; the batch-selector enumerates the
    #     drill-down dirs. O(pairs) and O(pairs x batches) respectively.
    from nanometa_live.core.parsers.blast_validation_parser import (
        get_validation_parser,
    )
    from nanometa_live.app.tabs.validation_tab_helpers import (
        _enumerate_batch_ids,
    )
    validation_results = len(
        get_validation_parser(main_dir).get_validation_results())
    validation_batches_seen = len(
        _enumerate_batch_ids({"results_dir_override": main_dir}))

    return PollResult(
        kraken_loads=kraken_loads,
        figures_built=figures_built,
        rows=int(len(summary)) if summary is not None else 0,
        samples=len(real_samples),
        organisms_built=organisms_built,
        validation_results=validation_results,
        validation_batches_seen=validation_batches_seen,
    )
