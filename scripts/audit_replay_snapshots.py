#!/usr/bin/env python
"""Replay results-tree snapshots through one long-lived loader process.

The round-4 realtime audit (docs/audit/realtime-round4-2026-09-02.md) left
four loader findings that only show in a process that lives across many
polls: the tier-switch drop (H6), per-sample lag (H26), batch-vs-cumulative
arithmetic (H27) and a staleness flag that never clears (H28). The 20 s
snapshots taken during the live runs (``~/nanometa-audit-r4/snapshots/<run>/
<HHMMSS>/``) hold every intermediate state of ``kraken2/`` and ``canonical/``.

This script syncs each snapshot in time order into one working results
directory -- copying changed files with their mtime set to NOW, so the
stability gate sees them exactly as fresh as the dashboard did -- and takes
the sampler's measurement twice per step: immediately (inside the 1 s
window) and after ``--settle`` seconds. It also dumps the staleness
registry after every step, which the live sampler could not see.

Usage:
    python scripts/audit_replay_snapshots.py ~/nanometa-audit-r4/snapshots/r2 \
        --config ~/nanometa-audit-r4/configs/r2_live.yaml \
        --out replay_r2.jsonl [--from 231300 --to 231700] [--settle 1.2]
    python scripts/audit_realtime_timeline.py --check replay_r2.jsonl
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
import tempfile
import time
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from audit_realtime_timeline import _load_config, sample_tick  # noqa: E402

SYNC_SUBDIRS = ("kraken2", "canonical")


def _walk(root: str) -> Dict[str, str]:
    """relative path -> absolute path for every file under root."""
    out: Dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, root)] = full
    return out


def sync_snapshot(snapshot: str, workdir: str) -> Dict[str, List[str]]:
    """Make workdir mirror the snapshot; changed files get mtime = now."""
    changed: List[str] = []
    removed: List[str] = []
    now = time.time()
    for sub in SYNC_SUBDIRS:
        src_root = os.path.join(snapshot, sub)
        dst_root = os.path.join(workdir, sub)
        src = _walk(src_root) if os.path.isdir(src_root) else {}
        dst = _walk(dst_root) if os.path.isdir(dst_root) else {}
        for rel, full in src.items():
            target = os.path.join(dst_root, rel)
            if rel in dst and filecmp.cmp(full, target, shallow=False):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Write into a sibling and rename, as the pipeline's head process
            # does, so the file appears whole; the mtime is what makes it
            # "fresh" to the stability gate.
            tmp = target + ".replay.tmp"
            shutil.copyfile(full, tmp)
            os.utime(tmp, (now, now))
            os.replace(tmp, target)
            changed.append(f"{sub}/{rel}")
        for rel in dst.keys() - src.keys():
            os.remove(os.path.join(dst_root, rel))
            removed.append(f"{sub}/{rel}")
    meta = os.path.join(snapshot, ".nanometa.run.json")
    if os.path.isfile(meta):
        shutil.copyfile(meta, os.path.join(workdir, ".nanometa.run.json"))
    return {"changed": changed, "removed": removed}


def staleness_dump(workdir: str) -> Dict[str, object]:
    from nanometa_live.core.utils import staleness

    scope = os.path.realpath(workdir)
    with staleness._lock:
        raw = {
            f"{s}|{sample}": since
            for (s, sample), since in staleness._serving_since.items()
            if s == scope
        }
    return {
        "serving_since": raw,
        "stale_now": [e.sample for e in staleness.stale_entries(workdir)],
    }


def run(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    snaps = sorted(d for d in os.listdir(args.snapshots)
                   if os.path.isdir(os.path.join(args.snapshots, d)) and d.isdigit())
    if args.start:
        snaps = [s for s in snaps if s >= args.start]
    if args.end:
        snaps = [s for s in snaps if s <= args.end]
    workdir = args.workdir or tempfile.mkdtemp(prefix="nanometa_replay_")
    os.makedirs(workdir, exist_ok=True)
    print(f"replaying {len(snaps)} snapshots into {workdir}", flush=True)
    with open(args.out, "w") as out:
        for label in snaps:
            snap = os.path.join(args.snapshots, label)
            delta = sync_snapshot(snap, workdir)
            for phase, wait in (("fresh", 0.0), ("settled", args.settle)):
                if wait:
                    time.sleep(wait)
                tick = sample_tick(workdir, config, None, trace_path="")
                tick["snapshot"] = label
                tick["phase"] = phase
                tick["delta"] = delta if phase == "fresh" else None
                tick["staleness"] = staleness_dump(workdir)
                out.write(json.dumps(tick, default=str) + "\n")
                out.flush()
                agg = tick["aggregate"]
                measured = sum(1 for r in tick["per_sample"].values()
                               if r["total_reads"] is not None)
                print(f"{label} {phase:7} changed={len(delta['changed']):2d} "
                      f"samples={len(tick['samples'])} measured={measured} "
                      f"agg={agg['total_reads']} stale={tick['staleness']['stale_now']} "
                      f"serving={len(tick['staleness']['serving_since'])}", flush=True)
    print(f"workdir kept at {workdir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshots")
    parser.add_argument("--config")
    parser.add_argument("--out", default="replay.jsonl")
    parser.add_argument("--from", dest="start", help="first snapshot label (HHMMSS)")
    parser.add_argument("--to", dest="end", help="last snapshot label (HHMMSS)")
    parser.add_argument("--settle", type=float, default=1.2,
                        help="seconds between the fresh and settled measurements")
    parser.add_argument("--workdir", help="reuse a working results dir instead of a temp one")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
