#!/usr/bin/env python3
"""Triage a field run's read counts, failures and lost inputs.

Puts every per-sample count the GUI could show side by side, so a results
folder brought back from the field can be read in one pass:

- ``kraken_reads``: reads Kraken2 classified or left unclassified
  (root + unclassified clade counts), what the Dashboard shows.
- ``seqkit_merged_reads``: ``seqkit/<sample>.tsv``, the merged file the QC
  cards read when it exists.
- ``seqkit_batch_reads``: the sum over ``seqkit/<sample>/batch_stats/``.
- ``chopper_in`` / ``chopper_kept``: chopper's own counts, when the pipeline
  published them (``chopper/<sample>/counts/``).

and for the run: its recorded outcome, failed tasks, lost-input markers and
the pipeline's file-size read estimate. A sample whose SeqKit and Kraken2
counts disagree beyond the QC tab's tolerance is listed under the table.

Written for the Barcelona exercise feedback (2026-11-24): the QC tab showed
63.9 Mb of bases beside 76,642 classified reads and a 1,282 bp mean length.

Usage: python scripts/field_run_triage.py RESULTS_DIR [--json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

import pandas as pd

from nanometa_live.app.tabs.qc_tab_helpers import read_set_note
from nanometa_live.app.utils.callback_helpers import get_classification_stats
from nanometa_live.core.export.run_status import read_final_run_status
from nanometa_live.core.utils.chopper_counts import load_chopper_counts
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.realtime_stats_loader import load_realtime_stats

_REPORT_SUFFIXES = (".cumulative.kraken2.report.txt", ".kraken2.report.txt")


def _sample_names(results_dir: str) -> List[str]:
    names = set()
    for path in glob.glob(os.path.join(results_dir, "kraken2", "*")):
        base = os.path.basename(path)
        if os.path.isdir(path):
            names.add(base)
            continue
        for suffix in _REPORT_SUFFIXES:
            if base.endswith(suffix) and "_batch" not in base:
                names.add(base[: -len(suffix)])
                break
    for path in glob.glob(os.path.join(results_dir, "seqkit", "*")):
        base = os.path.basename(path)
        names.add(base if os.path.isdir(path) else base.removesuffix(".tsv"))
    for path in glob.glob(os.path.join(results_dir, "chopper", "*")):
        if os.path.isdir(path):
            names.add(os.path.basename(path))
    return sorted(n for n in names if n)


def _num_seqs(paths: List[str]) -> Optional[int]:
    total, seen = 0, False
    for path in paths:
        try:
            df = pd.read_csv(path, sep="\t")
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if "num_seqs" in df.columns:
            total += int(pd.to_numeric(df["num_seqs"], errors="coerce").fillna(0).sum())
            seen = True
    return total if seen else None


def _kraken_reads(results_dir: str, sample: str) -> Optional[int]:
    df = load_kraken_data(results_dir, sample)
    if df is None or df.empty:
        return None
    classified, unclassified, _ = get_classification_stats(df)
    return classified + unclassified


def triage(results_dir: str) -> Dict[str, Any]:
    """Per-sample counts and run-level failures for ``results_dir``."""
    samples = []
    for name in _sample_names(results_dir):
        seqkit = os.path.join(results_dir, "seqkit")
        chopper = load_chopper_counts(results_dir, name)
        samples.append({
            "sample": name,
            "kraken_reads": _kraken_reads(results_dir, name),
            "seqkit_merged_reads": _num_seqs(
                [p for p in [os.path.join(seqkit, f"{name}.tsv")] if os.path.isfile(p)]),
            "seqkit_batch_reads": _num_seqs(sorted(glob.glob(
                os.path.join(seqkit, name, "batch_stats", "*.tsv")))),
            "chopper_in": chopper.reads_in if chopper else None,
            "chopper_kept": chopper.reads_kept if chopper else None,
        })
    final = read_final_run_status(results_dir)
    realtime = load_realtime_stats(results_dir) or {}
    return {
        "samples": samples,
        "run": {
            "run_state": final.get("run_state"),
            "failed_tasks": final.get("failed_tasks") or [],
            "lost_inputs": len(final.get("lost_inputs") or []),
            "estimated_reads": (realtime.get("totals") or {}).get("total_estimated_reads"),
        },
    }


def _mismatches(row: Dict[str, Any]) -> List[str]:
    out = []
    kraken = row["kraken_reads"] or 0
    for key, label in (("seqkit_merged_reads", "SeqKit merged"),
                       ("seqkit_batch_reads", "SeqKit batches")):
        value = row[key] or 0
        if read_set_note(value, kraken)[1]:
            out.append(f"{label} {value} vs Kraken2 {kraken}")
    return out


def _print_report(report: Dict[str, Any]) -> None:
    cols = ["sample", "kraken_reads", "seqkit_merged_reads",
            "seqkit_batch_reads", "chopper_in", "chopper_kept"]
    print(pd.DataFrame(report["samples"], columns=cols).to_string(index=False))
    flagged = [(r["sample"], m) for r in report["samples"] for m in _mismatches(r)]
    if flagged:
        print("\nCounts that describe different reads:")
        for sample, message in flagged:
            print(f"  {sample}: {message}")
    run = report["run"]
    print(f"\nRun state: {run['run_state']}")
    print(f"Pipeline read estimate (file size): {run['estimated_reads']}")
    print(f"Lost-input markers: {run['lost_inputs']}")
    for task in run["failed_tasks"]:
        print(f"Failed task: {task}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results_dir")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.results_dir):
        print(f"Not a directory: {args.results_dir}", file=sys.stderr)
        return 2
    report = triage(args.results_dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
