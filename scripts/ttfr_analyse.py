#!/usr/bin/env python
"""Turn a ttfr run (timeline + trace) into per-barcode latencies and a table.

Reads ``run.json`` from ``scripts/ttfr_backlog.py run``: the sampler's
``timeline.jsonl`` gives, per tick, what the dashboard's loaders returned for
every sample; the pipeline's execution trace gives every task's start and
completion. All times are seconds from ``t0`` (the ``nextflow run`` spawn).

Usage:
    python scripts/ttfr_analyse.py /tmp/ttfr/batch_baseline [--json summary.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

CLASSIFIER_PROCESSES = ("KRAKEN2_INCREMENTAL_CLASSIFIER", "KRAKEN2_OPTIMIZED", "KRAKEN2_KRAKEN2")
_UNIT = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}


def _epoch(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text or text == "-":
        return None
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").timestamp()


def _seconds(text: str) -> Optional[float]:
    """Nextflow durations: '40s', '1m 2s', '350ms', '1h 2m'."""
    text = (text or "").strip()
    if not text or text == "-":
        return None
    total = 0.0
    for value, unit in re.findall(r"([\d.]+)\s*(ms|h|m|s)", text):
        total += float(value) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def _bytes(text: str) -> Optional[float]:
    m = re.match(r"([\d.]+)\s*([KMGT]?B)", (text or "").strip())
    return float(m.group(1)) * _UNIT[m.group(2)] if m else None


def _load_timeline(path: Path) -> List[Dict[str, Any]]:
    with Path(path).open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _per_sample_latencies(ticks: List[Dict[str, Any]], t0: float) -> Dict[str, Dict[str, Optional[float]]]:
    samples = sorted({s for t in ticks for s in (t.get("per_sample") or {})})
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for s in samples:
        first = complete = watched_at = None
        last_reads = None
        for t in ticks:
            row = (t.get("per_sample") or {}).get(s) or {}
            reads = row.get("total_reads")
            rel = round(float(t["ts"]) - t0, 1)
            if reads and first is None:
                first = rel
            if reads is not None and reads != last_reads:
                complete = rel
                last_reads = reads
            if (row.get("watched") or 0) > 0 and watched_at is None:
                watched_at = rel
        out[s] = {"first_report_s": first, "complete_s": complete, "first_watched_s": watched_at}
    return out


def _trace_rows(path: Optional[str]) -> List[Dict[str, str]]:
    if not path or not Path(path).is_file():
        return []
    with Path(path).open() as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _classifier_summary(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    tasks = [r for r in rows if any(p in r.get("process", "") for p in CLASSIFIER_PROCESSES)]
    intervals = [(_epoch(r["start"]), _epoch(r["complete"])) for r in tasks]
    intervals = [(a, b) for a, b in intervals if a is not None and b is not None]
    events = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals], key=lambda e: (e[0], e[1]))
    depth = peak = 0
    for _, d in events:
        depth += d
        peak = max(peak, depth)
    durations = [_seconds(r["realtime"]) for r in sorted(tasks, key=lambda r: _epoch(r["start"]) or 0)]
    durations = [d for d in durations if d is not None]
    rss = [_bytes(r.get("peak_rss")) for r in tasks]
    rss = [x for x in rss if x is not None]
    return {
        "tasks": len(tasks),
        "max_concurrency": peak,
        "first_task_s": durations[0] if durations else None,
        "median_task_s": statistics.median(durations) if durations else None,
        "peak_rss_gb": round(max(rss) / _UNIT["GB"], 2) if rss else None,
    }


def _per_process(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[float]] = {}
    for r in rows:
        name = r.get("process", "").split(":")[-1]
        d = _seconds(r.get("realtime"))
        if d is not None:
            groups.setdefault(name, []).append(d)
    return {k: {"count": len(v), "median_s": round(statistics.median(v), 1)} for k, v in groups.items()}


def analyse(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    t0 = float(meta["t0"])
    ticks = _load_timeline(meta["timeline"])
    per_sample = _per_sample_latencies(ticks, t0)
    firsts = [v["first_report_s"] for v in per_sample.values() if v["first_report_s"] is not None]
    rows = _trace_rows(meta.get("trace"))
    return {
        "mode": meta.get("mode"),
        "overrides": meta.get("overrides", {}),
        "wall_s": round(float(meta.get("t_end", t0)) - t0, 1),
        "samples": len(per_sample),
        "samples_with_report": len(firsts),
        "per_sample": per_sample,
        "all_first_report_s": max(firsts) if len(firsts) == len(per_sample) and firsts else None,
        "spread_first_report_s": round(max(firsts) - min(firsts), 1) if firsts else None,
        "classifier": _classifier_summary(rows),
        "per_process": _per_process(rows),
    }


def render(summary: Dict[str, Any]) -> str:
    lines = [
        f"mode: {summary['mode']}  wall: {summary['wall_s']} s  samples: {summary['samples']}  "
        f"with report: {summary['samples_with_report']}  all-first-report: {summary['all_first_report_s']} s  "
        f"spread: {summary['spread_first_report_s']} s",
        "",
        "| sample | first report (s) | complete (s) | first watched (s) |",
        "|---|---|---|---|",
    ]
    for s, v in sorted(summary["per_sample"].items()):
        fmt = lambda x: "never" if x is None else f"{x:.1f}"
        lines.append(f"| {s} | {fmt(v['first_report_s'])} | {fmt(v['complete_s'])} | {fmt(v['first_watched_s'])} |")
    c = summary["classifier"]
    lines += [
        "",
        f"classifier tasks: {c['tasks']}  max concurrency: {c['max_concurrency']}  "
        f"first task: {c['first_task_s']} s  median task: {c['median_task_s']} s  peak rss: {c['peak_rss_gb']} GB",
        "",
        "| process | count | median (s) |",
        "|---|---|---|",
    ]
    for name, v in sorted(summary["per_process"].items()):
        lines.append(f"| {name} | {v['count']} | {v['median_s']} |")
    return "\n".join(lines)


def _report_counts(path: Path) -> Dict[str, int]:
    """{taxid: cumulative reads} from a Kraken2 report (columns 2 and 5)."""
    counts: Dict[str, int] = {}
    for line in Path(path).read_text().splitlines():
        cols = line.split("\t")
        if len(cols) < 6:
            continue
        counts[cols[4].strip()] = int(float(cols[1]))
    return counts


def compare_reports(a: Path, b: Path) -> Dict[str, Any]:
    """Per-taxid cumulative counts of two reports; equal when every taxid agrees."""
    ca, cb = _report_counts(a), _report_counts(b)
    diffs = {t: (ca.get(t, 0), cb.get(t, 0)) for t in sorted(set(ca) | set(cb)) if ca.get(t, 0) != cb.get(t, 0)}
    return {"equal": not diffs, "differences": diffs, "taxa": len(set(ca) | set(cb))}


def compare_runs(chunked_results: Path, single_results: Path) -> Dict[str, Any]:
    """Pair each sample's cumulative report (chunked run) with its standard
    report (single-task run) and compare. Acceptance criterion C."""
    chunked_dir, single_dir = Path(chunked_results) / "kraken2", Path(single_results) / "kraken2"
    per_sample: Dict[str, Any] = {}
    for report in sorted(chunked_dir.glob("*.cumulative.kraken2.report.txt")):
        sample = report.name[: -len(".cumulative.kraken2.report.txt")]
        other = single_dir / f"{sample}.kraken2.report.txt"
        per_sample[sample] = compare_reports(report, other) if other.is_file() else {"equal": False, "differences": {"missing": (1, 0)}, "taxa": 0}
    return {"samples": sorted(per_sample), "equal": bool(per_sample) and all(v["equal"] for v in per_sample.values()), "per_sample": per_sample}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")
    a = sub.add_parser("analyse", help="per-barcode latencies for one run (default)")
    a.add_argument("run_dir")
    a.add_argument("--json")
    c = sub.add_parser("compare", help="chunked vs single-task final reports")
    c.add_argument("chunked_results")
    c.add_argument("single_results")
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in ("analyse", "compare"):
        argv = ["analyse"] + list(argv)
    args = parser.parse_args(argv)
    if args.cmd == "compare":
        result = compare_runs(Path(args.chunked_results), Path(args.single_results))
        print(json.dumps(result, indent=2))
        return 0 if result["equal"] else 1
    summary = analyse(Path(args.run_dir))
    print(render(summary))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
