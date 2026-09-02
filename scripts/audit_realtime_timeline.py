#!/usr/bin/env python
"""Timeline sampler for a real-time run, and a checker for the samples.

Every ``--interval`` seconds it records what the dashboard's own loaders
return for a results directory: the sample list, each sample's report tier and
file state, total reads, watched-organism counts per sample, the aggregate
detections, the run-metadata terminal status, the trace-file age and the input
directory's FASTQ count. One JSON object per line.

``--check`` reads such a file and reports every violation of the properties a
real-time run must satisfy while the pipeline is running: cumulative counts
never decrease, a detection never disappears, a sample never flips from
measured to unmeasured.

Usage:
    python scripts/audit_realtime_timeline.py <results_dir> --config cfg.yaml \
        --input-dir <watch_dir> --out timeline.jsonl [--interval 2]
    python scripts/audit_realtime_timeline.py --check timeline.jsonl

The sampler runs in its own process, so it measures the loader path the
dashboard uses, not the dashboard's own cache instance.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FASTQ_SUFFIXES = (".fastq", ".fastq.gz", ".fq", ".fq.gz")


def _tier_of(paths: List[str]) -> str:
    if not paths:
        return "none"
    first = os.path.basename(paths[0])
    if ".cumulative." in first:
        return "cumulative"
    if "batch" in first:
        return "batch"
    return "standard"


def _stat_triple(path: str) -> Optional[List[int]]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size, st.st_ino]


def _input_files(input_dir: Optional[str]) -> Dict[str, Any]:
    if not input_dir or not os.path.isdir(input_dir):
        return {"count": None, "latest_mtime": None}
    count = 0
    latest = 0.0
    for root, _dirs, files in os.walk(input_dir):
        for name in files:
            if name.startswith(".") or not name.endswith(FASTQ_SUFFIXES):
                continue
            count += 1
            try:
                latest = max(latest, os.stat(os.path.join(root, name)).st_mtime)
            except OSError:
                continue
    return {"count": count, "latest_mtime": latest or None}


def _trace_state(trace_path: str) -> Dict[str, Any]:
    try:
        st = os.stat(trace_path)
    except OSError:
        return {"age_s": None, "completed": 0, "failed": 0}
    completed = failed = 0
    try:
        with open(trace_path) as fh:
            for line in fh:
                if "\tCOMPLETED\t" in line:
                    completed += 1
                elif "\tFAILED\t" in line:
                    failed += 1
    except OSError:
        pass
    return {"age_s": round(time.time() - st.st_mtime, 1),
            "completed": completed, "failed": failed}


def _watched_hits(organisms: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, int]:
    from nanometa_live.app.tabs.dashboard_helpers import _check_pathogens_both

    dangerous, subthreshold = _check_pathogens_both(organisms, config)
    hits: Dict[str, int] = {}
    for hit in list(dangerous) + list(subthreshold):
        name = str(hit.get("name"))
        hits[name] = max(hits.get(name, 0), int(hit.get("reads") or 0))
    return hits


def _sample_row(main_dir: str, sample: str, config: Dict[str, Any]) -> Dict[str, Any]:
    from nanometa_live.app.tabs.dashboard_helpers import (
        _species_df_to_organisms,
        _species_discovery_df,
    )
    from nanometa_live.app.utils.callback_helpers import get_classification_stats
    from nanometa_live.core.utils.classification_loaders import (
        _discover_sample_reports,
        load_kraken_data,
    )

    kraken_dir = os.path.join(main_dir, "kraken2")
    reports = _discover_sample_reports(kraken_dir, sample)
    row: Dict[str, Any] = {
        "tier": _tier_of(reports),
        "report_stat": _stat_triple(reports[0]) if reports else None,
        "total_reads": None,
        "watched": {},
    }
    df = load_kraken_data(main_dir, sample)
    if df is None or df.empty:
        return row
    classified, unclassified, _rate = get_classification_stats(df)
    row["total_reads"] = int(classified) + int(unclassified)
    organisms = _species_df_to_organisms(_species_discovery_df(df, floor=0))
    row["watched"] = _watched_hits(organisms, config)
    return row


def sample_tick(main_dir: str, config: Dict[str, Any], input_dir: Optional[str],
                trace_path: str) -> Dict[str, Any]:
    """One observation of the results tree through the dashboard's loaders."""
    from nanometa_live.app.callbacks.samples import _dataless_samples
    from nanometa_live.app.tabs.dashboard_helpers import (
        _species_df_to_organisms,
        _species_discovery_df,
        unmeasured_samples,
    )
    from nanometa_live.app.utils.callback_helpers import get_classification_stats
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    from nanometa_live.core.utils.sample_detector import (
        get_available_samples,
        get_sample_file_mapping,
    )
    from nanometa_live.core.workflow.backend_manager import BackendManager

    now = time.time()
    available = get_available_samples(main_dir)
    samples = [s for s in available if s != "All Samples"]
    mapping = get_sample_file_mapping(main_dir)
    dataless = sorted(_dataless_samples(available, mapping, config))

    tick: Dict[str, Any] = {
        "ts": now,
        "run_meta": BackendManager.read_run_metadata(main_dir) or {},
        "trace": _trace_state(trace_path),
        "input": _input_files(input_dir),
        "samples": samples,
        "dataless": dataless,
        "unmeasured": unmeasured_samples(main_dir, available, config),
        "per_sample": {s: _sample_row(main_dir, s, config) for s in samples},
        "aggregate": {"total_reads": None, "watched": {}},
    }
    agg = load_kraken_data(main_dir, "All Samples")
    if agg is not None and not agg.empty:
        classified, unclassified, _rate = get_classification_stats(agg)
        tick["aggregate"]["total_reads"] = int(classified) + int(unclassified)
        organisms = _species_df_to_organisms(_species_discovery_df(agg))
        tick["aggregate"]["watched"] = _watched_hits(organisms, config)
    tick["run_meta"] = {k: tick["run_meta"].get(k) for k in ("final_status", "written_at")}
    return tick


def _is_running(tick: Dict[str, Any]) -> bool:
    meta = tick.get("run_meta") or {}
    return bool(meta.get("written_at")) and not meta.get("final_status")


def _check_pair(prev: Dict[str, Any], cur: Dict[str, Any]) -> List[str]:
    """Violations between two consecutive ticks, both taken while running."""
    out: List[str] = []
    stamp = time.strftime("%H:%M:%S", time.localtime(cur["ts"]))
    pa, ca = prev["aggregate"], cur["aggregate"]
    if pa["total_reads"] is not None and ca["total_reads"] is not None \
            and ca["total_reads"] < pa["total_reads"]:
        out.append(f"{stamp} aggregate total_reads fell {pa['total_reads']} -> {ca['total_reads']}")
    for name, reads in pa["watched"].items():
        if name not in ca["watched"]:
            out.append(f"{stamp} aggregate detection vanished: {name} ({reads} reads)")
        elif ca["watched"][name] < reads:
            out.append(f"{stamp} aggregate {name} fell {reads} -> {ca['watched'][name]}")
    for sample, prow in prev["per_sample"].items():
        crow = cur["per_sample"].get(sample)
        if crow is None:
            out.append(f"{stamp} sample disappeared from the list: {sample}")
            continue
        if prow["tier"] != "none" and crow["tier"] == "none":
            out.append(f"{stamp} {sample} lost its report (tier {prow['tier']} -> none)")
        if prow["total_reads"] is not None and crow["total_reads"] is None:
            out.append(f"{stamp} {sample} went measured -> unmeasured")
        if prow["total_reads"] is not None and crow["total_reads"] is not None \
                and crow["total_reads"] < prow["total_reads"]:
            out.append(f"{stamp} {sample} total_reads fell {prow['total_reads']} -> {crow['total_reads']}")
        for name, reads in prow["watched"].items():
            cur_reads = crow["watched"].get(name, 0)
            if cur_reads < reads:
                out.append(f"{stamp} {sample} {name} fell {reads} -> {cur_reads}")
    for sample in cur["dataless"]:
        if sample not in prev["dataless"] and prev["per_sample"].get(sample, {}).get("tier", "none") != "none":
            out.append(f"{stamp} {sample} marked 'no data' although it had a report")
    return out


def check_timeline(path: str) -> int:
    ticks: List[Dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                ticks.append(json.loads(line))
    running = [t for t in ticks if _is_running(t)]
    violations: List[str] = []
    for prev, cur in zip(running, running[1:]):
        violations.extend(_check_pair(prev, cur))
    print(f"{len(ticks)} ticks, {len(running)} while running, {len(violations)} violation(s)")
    for v in violations:
        print("  " + v)
    return 1 if violations else 0


def _load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    from nanometa_live.core.config.config_loader import ConfigLoader
    from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

    config = ConfigLoader(os.path.dirname(os.path.abspath(path))).load_config(path)
    get_watchlist_manager().load_config(config)
    return config


def run_sampler(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    input_dir = args.input_dir or config.get("nanopore_output_directory")
    trace_path = args.trace or os.path.expanduser("~/.nanometa/logs/trace.txt")
    deadline = time.time() + args.duration if args.duration else None
    n = 0
    with open(args.out, "a") as out:
        while deadline is None or time.time() < deadline:
            started = time.time()
            try:
                tick = sample_tick(args.results_dir, config, input_dir, trace_path)
            except Exception as exc:  # keep sampling through transient states
                tick = {"ts": started, "error": repr(exc)}
            out.write(json.dumps(tick, default=str) + "\n")
            out.flush()
            n += 1
            if not args.quiet:
                agg = tick.get("aggregate", {})
                print(f"{time.strftime('%H:%M:%S')} samples={len(tick.get('samples', []))} "
                      f"reads={agg.get('total_reads')} watched={len(agg.get('watched', {}))} "
                      f"final={tick.get('run_meta', {}).get('final_status')} "
                      f"input={tick.get('input', {}).get('count')}", flush=True)
            time.sleep(max(0.0, args.interval - (time.time() - started)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", nargs="?")
    parser.add_argument("--config")
    parser.add_argument("--input-dir")
    parser.add_argument("--trace", help="Nextflow trace file (default ~/.nanometa/logs/trace.txt)")
    parser.add_argument("--out", default="timeline.jsonl")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=None, help="Seconds to sample; default forever")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--check", metavar="JSONL", help="Check a recorded timeline instead of sampling")
    args = parser.parse_args()
    if args.check:
        return check_timeline(args.check)
    if not args.results_dir:
        parser.error("results_dir is required unless --check is given")
    return run_sampler(args)


if __name__ == "__main__":
    raise SystemExit(main())
