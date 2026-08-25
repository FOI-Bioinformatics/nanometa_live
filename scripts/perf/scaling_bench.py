"""Sample-count scaling benchmark driver.

Usage::

    python -m scripts.perf.scaling_bench
    python -m scripts.perf.scaling_bench --n 1,6,24 --scenarios quiet,incremental
    python -m scripts.perf.scaling_bench --update-baseline
    python -m scripts.perf.scaling_bench --compare scripts/perf/baseline.json
    python -m scripts.perf.scaling_bench --check          # CI gate

Each cell is measured twice. A timing pass runs the poll ``--repeat`` times
with counting off and reports the minimum, which is the least biased
estimator when noise is one-sided. A separate single counted pass produces
the syscall totals; those are deterministic, so one run suffices.

The gate asserts on counts alone. Wall time on shared CI runners varies by
several times between runs, so any threshold tight enough to catch a real
regression would flake, and any threshold loose enough not to flake would
catch nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.perf import fixtures as fx  # noqa: E402
from scripts.perf import instrument as inst  # noqa: E402
from scripts.perf.poll import simulate_poll  # noqa: E402

DEFAULT_FIXTURE_BASE = Path("/tmp/nanometa_perf_fixtures")
BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"

SCENARIOS: Tuple[str, ...] = ("cold", "full_refresh", "incremental", "quiet")
# 48/96 added in round 2 (2026-08-24): the loader-cache capacity cliff only
# bites above ~33 samples and was invisible at N=24.
DEFAULT_N: Tuple[int, ...] = (1, 2, 6, 12, 24, 48, 96)
DEFAULT_LAYOUTS: Tuple[str, ...] = ("batch", "realtime_incremental")

SCHEMA = 1

# Gate thresholds. A regression must exceed both to fail, so trivially small
# cells cannot trip on a couple of extra calls.
GATE_RATIO = 1.05
GATE_ABSOLUTE = 8
# Memory gate band (round 3): looser than the syscall gate because the
# allocator and pandas versions move real bytes for unrelated reasons.
MEM_GATE_RATIO = 1.2
MEM_GATE_ABSOLUTE_KB = 4096


# Axis defaults; a cell measured at these keeps the historical short key so
# the committed baseline's cells remain comparable across rounds.
DEFAULT_TAXA = 300
DEFAULT_BATCHES = 20


@dataclass
class Cell:
    """One measured (layout, scenario, N[, taxa, batches, pairs]) point."""

    layout: str
    scenario: str
    n_samples: int
    taxa: int = DEFAULT_TAXA
    batches: int = DEFAULT_BATCHES
    pairs: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    wall_min_ms: float = 0.0
    wall_med_ms: float = 0.0
    kraken_loads: int = 0
    frame_cache_len: int = 0
    # Round-3 memory columns: tracemalloc peak over the counted poll and
    # the deep byte size of the parsed-frame caches after it.
    mem_peak_kb: int = 0
    frame_cache_kb: int = 0

    @property
    def key(self) -> str:
        base = f"{self.layout}/{self.scenario}/n={self.n_samples}"
        if (self.taxa, self.batches, self.pairs) != (
                DEFAULT_TAXA, DEFAULT_BATCHES, 0):
            base += f"/t={self.taxa}/b={self.batches}/v={self.pairs}"
        return base

    def as_dict(self) -> Dict[str, Any]:
        return {
            "counts": self.counts,
            "wall_min_ms": round(self.wall_min_ms, 2),
            "wall_med_ms": round(self.wall_med_ms, 2),
            "kraken_loads": self.kraken_loads,
            "frame_cache_len": self.frame_cache_len,
            "mem_peak_kb": self.mem_peak_kb,
            "frame_cache_kb": self.frame_cache_kb,
        }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _prepare(scenario: str, root: Path, layout: str,
             build_figures: bool) -> None:
    """Put the caches and the tree into the state the scenario describes."""
    inst.reset_caches()
    if scenario == "cold":
        return
    # Every non-cold scenario starts from a warm cache.
    simulate_poll(str(root), build_figures=build_figures)
    if scenario == "full_refresh":
        fx.touch_all(root, layout)
    elif scenario == "incremental":
        samples = fx.FixtureSpec(n_samples=1, layout=layout).sample_names
        fx.touch_sample(root, samples[0], layout)
    elif scenario == "quiet":
        # A second warm poll, so the measured one is the third and every
        # lazily-populated cache has settled.
        simulate_poll(str(root), build_figures=build_figures)


def measure(spec: fx.FixtureSpec, scenario: str, base: Path,
            repeat: int, build_figures: bool) -> Cell:
    root = fx.build_fixture(spec, base)
    cell = Cell(layout=spec.layout, scenario=scenario,
                n_samples=spec.n_samples, taxa=spec.taxa_per_report,
                batches=spec.effective_batches or spec.batches_per_sample,
                pairs=spec.validation_pairs)

    # Timing pass: counting off so the wrappers do not perturb the duration.
    durations: List[float] = []
    for _ in range(repeat):
        _prepare(scenario, root, spec.layout, build_figures)
        with inst.timed() as holder:
            simulate_poll(str(root), build_figures=build_figures)
        durations.append(holder[0])
    cell.wall_min_ms = min(durations)
    cell.wall_med_ms = _median(durations)

    # Counting pass: deterministic, so once is enough. tracemalloc rides
    # the same pass -- its overhead perturbs wall time (measured separately
    # above) but not counts or allocation sizes.
    import tracemalloc
    _prepare(scenario, root, spec.layout, build_figures)
    tracemalloc.start()
    try:
        with inst.count_syscalls() as counted:
            result = simulate_poll(str(root), build_figures=build_figures)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    cell.counts = counted.as_dict()
    cell.frame_cache_len = counted.frame_cache_len
    cell.kraken_loads = result.kraken_loads
    cell.mem_peak_kb = int(peak / 1024)
    cell.frame_cache_kb = int(inst.report_frame_cache_bytes() / 1024)

    if result.samples != spec.n_samples:
        raise AssertionError(
            f"{cell.key}: poll saw {result.samples} samples, expected "
            f"{spec.n_samples}. The fixture and the loader disagree."
        )
    return cell


def run_matrix(ns: Sequence[int], layouts: Sequence[str],
               scenarios: Sequence[str], base: Path, repeat: int,
               build_figures: bool, taxa_list: Sequence[int],
               batches_list: Sequence[int], pairs_per_sample: int,
               validation_batches: int,
               manifest: bool, verbose: bool) -> Dict[str, Cell]:
    cells: Dict[str, Cell] = {}
    total = (len(ns) * len(layouts) * len(scenarios)
             * len(taxa_list) * len(batches_list))
    done = 0
    for layout in layouts:
        for taxa in taxa_list:
            for batches in batches_list:
                for n in ns:
                    spec = fx.FixtureSpec(
                        n_samples=n, layout=layout, taxa_per_report=taxa,
                        batches_per_sample=batches, write_manifest=manifest,
                        validation_pairs=pairs_per_sample * n,
                        validation_batches=validation_batches,
                    )
                    for scenario in scenarios:
                        cell = measure(spec, scenario, base, repeat,
                                       build_figures)
                        cells[cell.key] = cell
                        done += 1
                        if verbose:
                            print(
                                f"  [{done}/{total}] {cell.key:<50} "
                                f"{cell.wall_min_ms:8.1f} ms  "
                                f"os.stat={cell.counts.get('os.stat', 0):>7}",
                                flush=True,
                            )
    return cells


def _scaling_exponent(ns: Sequence[int], values: Sequence[float]) -> float:
    """Least-squares slope of log(value) against log(N).

    An exponent near 0 means the metric is flat in the sample count; near 1
    means linear; near 2 means quadratic. This single number is what shows
    whether a scaling term has actually been removed.
    """
    pairs = [(math.log(n), math.log(v)) for n, v in zip(ns, values)
             if n > 0 and v > 0]
    if len(pairs) < 2:
        return float("nan")
    mean_x = sum(p[0] for p in pairs) / len(pairs)
    mean_y = sum(p[1] for p in pairs) / len(pairs)
    num = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    den = sum((x - mean_x) ** 2 for x, _ in pairs)
    return num / den if den else float("nan")


def _fmt_ratio(base_v: float, head_v: float) -> str:
    if base_v == 0:
        return "  n/a"
    return f"{head_v / base_v:.2f}x"


def render_table(cells: Dict[str, Cell], baseline: Optional[Dict[str, Any]],
                 metrics: Sequence[str], markdown: bool) -> str:
    out: List[str] = []
    base_cells = (baseline or {}).get("cells", {})

    groups: Dict[Tuple[str, str], List[Cell]] = {}
    for cell in cells.values():
        groups.setdefault((cell.layout, cell.scenario), []).append(cell)

    for (layout, scenario), group in sorted(groups.items()):
        group.sort(key=lambda c: c.n_samples)
        for metric in metrics:
            head_vals = [float(c.counts.get(metric, 0)) for c in group]
            if not any(head_vals):
                continue
            ns = [c.n_samples for c in group]
            out.append("")
            out.append(f"layout={layout}  scenario={scenario}  metric={metric}")
            if base_cells:
                header = f"{'N':>5} {'base':>9} {'head':>9} {'delta':>9} {'ratio':>8}"
            else:
                header = f"{'N':>5} {'head':>9}"
            out.append(header)
            if markdown:
                out.append("|" + "|".join(["---"] * (5 if base_cells else 2)) + "|")
            base_vals: List[float] = []
            for cell, head_v in zip(group, head_vals):
                if base_cells:
                    entry = base_cells.get(cell.key, {})
                    base_v = float(entry.get("counts", {}).get(metric, 0))
                    base_vals.append(base_v)
                    out.append(
                        f"{cell.n_samples:>5} {base_v:>9.0f} {head_v:>9.0f} "
                        f"{head_v - base_v:>9.0f} {_fmt_ratio(base_v, head_v):>8}"
                    )
                else:
                    out.append(f"{cell.n_samples:>5} {head_v:>9.0f}")
            head_exp = _scaling_exponent(ns, head_vals)
            if base_cells and any(base_vals):
                base_exp = _scaling_exponent(ns, base_vals)
                out.append(
                    f"  scaling exponent:  base O(N^{base_exp:.2f})   "
                    f"head O(N^{head_exp:.2f})"
                )
            else:
                out.append(f"  scaling exponent:  O(N^{head_exp:.2f})")

    out.append("")
    out.append("Wall time (informational; not gated)")
    out.append(f"{'cell':<46} {'min ms':>9} {'med ms':>9} {'loads':>7} {'frames':>7}")
    for key in sorted(cells):
        c = cells[key]
        out.append(
            f"{key:<46} {c.wall_min_ms:>9.1f} {c.wall_med_ms:>9.1f} "
            f"{c.kraken_loads:>7} {c.frame_cache_len:>7}"
        )
    return "\n".join(out)


def check_against_baseline(cells: Dict[str, Cell],
                           baseline: Dict[str, Any]) -> List[str]:
    """Return a list of regression messages; empty means the gate passes."""
    failures: List[str] = []
    base_cells = baseline.get("cells", {})
    for key, cell in sorted(cells.items()):
        entry = base_cells.get(key)
        if entry is None:
            continue  # new cell; nothing to compare against
        for metric in inst.GATED_METRICS:
            base_v = int(entry.get("counts", {}).get(metric, 0))
            head_v = int(cell.counts.get(metric, 0))
            if base_v == 0:
                continue
            if head_v > base_v * GATE_RATIO and head_v - base_v > GATE_ABSOLUTE:
                failures.append(
                    f"{key}  {metric}: {base_v} -> {head_v} "
                    f"(+{head_v - base_v}, {head_v / base_v:.2f}x)"
                )
        # Round-3 memory gate: generous band (allocator noise is real) but
        # a 20%+ AND 4 MB+ growth in the traced poll peak is a regression.
        base_mem = int(entry.get("mem_peak_kb", 0))
        head_mem = int(cell.mem_peak_kb)
        if base_mem and head_mem > base_mem * MEM_GATE_RATIO \
                and head_mem - base_mem > MEM_GATE_ABSOLUTE_KB:
            failures.append(
                f"{key}  mem_peak_kb: {base_mem} -> {head_mem} "
                f"(+{head_mem - base_mem} KB, {head_mem / base_mem:.2f}x)"
            )
    return failures


def build_document(cells: Dict[str, Cell], args: argparse.Namespace,
                   label: str) -> Dict[str, Any]:
    import pandas as pd

    return {
        "_comment": (
            "Per-poll scaling baseline. Regenerate with: "
            "python -m scripts.perf.scaling_bench --update-baseline. "
            "Wall times are informational; SYSCALL COUNTS are the gate. "
            "Only ever update to lower counts."
        ),
        "schema": SCHEMA,
        "label": label,
        "fixture": {
            "taxa_axis": str(args.taxa),
            "batches_axis": str(args.batches),
            "pairs_per_sample": args.pairs_per_sample,
            "validation_batches": args.validation_batches,
            "seed": 1337,
            "write_manifest": args.manifest,
        },
        "poll": {
            "build_figures": not args.no_figures,
            "max_taxa_per_level": 25,
            "min_reads": 10,
            "cache_ttl_seconds": inst.cache_ttl_seconds(),
            "repeat": args.repeat,
        },
        "env": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "platform": f"{platform.system().lower()}-{platform.machine()}",
        },
        "cells": {k: c.as_dict() for k, c in sorted(cells.items())},
    }


def _parse_int_list(raw: str) -> List[int]:
    return [int(p) for p in raw.split(",") if p.strip()]


def _parse_str_list(raw: str) -> List[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure per-poll loader cost against sample count.",
    )
    parser.add_argument("--n", default=",".join(str(n) for n in DEFAULT_N),
                        help="comma-separated sample counts")
    parser.add_argument("--layouts", default=",".join(DEFAULT_LAYOUTS),
                        help=f"comma-separated, from {fx.LAYOUTS}")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS),
                        help=f"comma-separated, from {SCENARIOS}")
    parser.add_argument("--repeat", type=int, default=5,
                        help="timing repetitions per cell (default 5)")
    parser.add_argument("--taxa", default=str(DEFAULT_TAXA),
                        help="comma-separated taxa-per-report axis "
                             f"(default {DEFAULT_TAXA})")
    parser.add_argument("--batches", default=str(DEFAULT_BATCHES),
                        help="comma-separated batches-per-sample axis "
                             "(realtime layouts)")
    parser.add_argument("--pairs-per-sample", type=int, default=0,
                        help="validation (sample,taxid) pairs per sample "
                             "(0 = no validation files; 129 = the "
                             "Bioshield watchlist size)")
    parser.add_argument("--validation-batches", type=int, default=0,
                        help="per-pair batch files under validation/*/batch/")
    parser.add_argument("--profile", choices=("exercise",), default=None,
                        help="preset axes: 'exercise' measures the round-3 "
                             "envelope (24/96 barcodes, 5000-taxa reports, "
                             "100 batches, 129 validation pairs/sample) on "
                             "the realtime layout")
    parser.add_argument("--manifest", action="store_true",
                        help="write canonical/_manifest.json (changes the "
                             "sample-detection path)")
    parser.add_argument("--no-figures", action="store_true",
                        help="skip Sankey/Sunburst so loader cost is isolated")
    parser.add_argument("--fixture-base", type=Path,
                        default=DEFAULT_FIXTURE_BASE)
    parser.add_argument("--metrics", default=",".join(inst.GATED_METRICS))
    parser.add_argument("--compare", type=Path, default=None,
                        help="baseline JSON to diff against")
    parser.add_argument("--update-baseline", action="store_true",
                        help=f"write results to {BASELINE_PATH}")
    parser.add_argument("--label", default="head",
                        help="label recorded in the written baseline")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero when a gated count regresses")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    ns = _parse_int_list(args.n)
    layouts = _parse_str_list(args.layouts)
    scenarios = _parse_str_list(args.scenarios)
    metrics = _parse_str_list(args.metrics)
    taxa_list = _parse_int_list(str(args.taxa))
    batches_list = _parse_int_list(str(args.batches))
    pairs_per_sample = args.pairs_per_sample
    validation_batches = args.validation_batches

    if args.profile == "exercise":
        # The round-3 envelope, opt-in because the biggest fixture holds
        # hundreds of thousands of files. Explicit flags still win where
        # the operator narrowed them.
        ns = _parse_int_list(args.n) if args.n != ",".join(
            str(n) for n in DEFAULT_N) else [24, 96]
        layouts = ["realtime_incremental"]
        scenarios = ["quiet", "incremental"]
        taxa_list = [5000]
        batches_list = [100]
        pairs_per_sample = pairs_per_sample or 129
        validation_batches = validation_batches or 10

    args.fixture_base.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print(f"Building fixtures under {args.fixture_base}", flush=True)

    cells = run_matrix(
        ns, layouts, scenarios, args.fixture_base, args.repeat,
        not args.no_figures, taxa_list, batches_list, pairs_per_sample,
        validation_batches, args.manifest,
        verbose=not args.quiet,
    )

    baseline: Optional[Dict[str, Any]] = None
    baseline_path = args.compare or (BASELINE_PATH if args.check else None)
    if baseline_path and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())

    print(render_table(cells, baseline, metrics, args.markdown))

    document = build_document(cells, args, args.label)

    if args.json_out:
        args.json_out.write_text(json.dumps(document, indent=2) + "\n")
        print(f"\nWrote {args.json_out}")

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(document, indent=2) + "\n")
        print(f"\nWrote {BASELINE_PATH}")

    if args.check:
        if baseline is None:
            print("\nNo baseline to check against; run --update-baseline first.")
            return 1
        failures = check_against_baseline(cells, baseline)
        if failures:
            print("\nPER-POLL COST REGRESSION")
            for line in failures:
                print(f"  {line}")
            print(
                "\nIf the increase is intentional, re-record with "
                "--update-baseline and explain it in the commit message."
            )
            return 1
        print("\nPer-poll cost gate: OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
