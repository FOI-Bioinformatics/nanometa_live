#!/usr/bin/env python
"""Synthetic backlog for the time-to-first-result audit, and a run driver.

``build`` lays out N barcode directories with M FASTQ files each, as symlinks
into a source corpus (round-robin over its barcode directories), so a large
multiplexed backlog costs no disk and the sample ids are the directory names
the pipeline derives. ``run`` launches nanometanf the way the GUI does -- the
same ``create_nextflow_params`` / ``create_nextflow_config`` call, the same
samplesheet -- with the pipeline's trace enabled, starts the timeline sampler
beside it, and records ``run.json`` for the analyser.

Usage:
    python scripts/ttfr_backlog.py build --source ~/nanometa-demo/data/multiplex \
        --out /tmp/ttfr/input --barcodes 12 --files-per-barcode 20
    python scripts/ttfr_backlog.py run --input /tmp/ttfr/input --mode batch \
        --db ~/nanometa-demo/db/bioshield26.1_8G --pipeline ~/Code/nanometanf \
        --out /tmp/ttfr/batch_baseline
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def _fastqs(directory: Path) -> List[Path]:
    return sorted(p for p in directory.iterdir() if p.name.endswith(FASTQ_SUFFIXES))


def build_backlog(source: Path, out: Path, barcodes: int, files_per_barcode: int,
                  include_unclassified: bool) -> Dict[str, List[Path]]:
    """Create ``out/barcodeNN/`` for NN in 1..barcodes, each holding
    ``files_per_barcode`` symlinks into the source corpus. Returns the layout."""
    source = Path(source).expanduser().resolve()
    out = Path(out).expanduser().resolve()
    sources = sorted(d for d in source.iterdir() if d.is_dir() and d.name.startswith("barcode"))
    if not sources:
        raise ValueError(f"no barcode directories under {source}")
    out.mkdir(parents=True, exist_ok=True)
    layout: Dict[str, List[Path]] = {}
    for i in range(barcodes):
        origin = sources[i % len(sources)]
        origin_files = _fastqs(origin)
        if len(origin_files) < files_per_barcode:
            raise ValueError(
                f"{origin.name} holds only {len(origin_files)} FASTQ files; "
                f"{files_per_barcode} requested per barcode"
            )
        name = f"barcode{i + 1:02d}"
        target = out / name
        target.mkdir(exist_ok=True)
        links = []
        for f in origin_files[:files_per_barcode]:
            link = target / f.name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(f)
            links.append(link)
        layout[name] = links
    if include_unclassified and (source / "unclassified").is_dir():
        target = out / "unclassified"
        target.mkdir(exist_ok=True)
        links = []
        for f in _fastqs(source / "unclassified")[:files_per_barcode]:
            link = target / f.name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(f)
            links.append(link)
        layout["unclassified"] = links
    (out / "backlog_layout.json").write_text(json.dumps({
        "source": str(source),
        "barcodes": barcodes,
        "files_per_barcode": files_per_barcode,
        "samples": {k: [str(p) for p in v] for k, v in layout.items()},
    }, indent=2))
    return layout


def _run_config(input_dir: Path, mode: str, db: Path, pipeline: Path, results: Path,
                overrides: Dict[str, object]) -> Dict[str, object]:
    from nanometa_live.core.config.config_loader import default_config

    config = default_config()
    config.update({
        "analysis_name": f"ttfr_{mode}",
        "nanopore_output_directory": str(input_dir),
        "results_output_directory": str(results),
        "results_dir_override": str(results),
        "kraken_db": str(db),
        "pipeline_source": str(pipeline),
        "pipeline_profile": "conda",
        "processing_mode": mode,
        "sample_handling": "by_barcode",
        "blast_validation": False,
        "enable_assembly": False,
        "realtime_timeout_minutes": 3,
        "offline_mode": False,
    })
    config.update(overrides)
    return config


def run(args: argparse.Namespace) -> int:
    from nanometa_live.core.config.parameter_mapping import (
        create_nextflow_config, create_nextflow_params,
    )
    import yaml

    out = Path(args.out).expanduser().resolve()
    results = out / "results"
    out.mkdir(parents=True, exist_ok=True)
    results.mkdir(exist_ok=True)
    overrides = json.loads(args.overrides) if args.overrides else {}
    config = _run_config(Path(args.input).expanduser().resolve(), args.mode,
                         Path(args.db).expanduser().resolve(),
                         Path(args.pipeline).expanduser().resolve(), results, overrides)
    (out / "config.yaml").write_text(yaml.safe_dump(config))
    params = create_nextflow_params(config)
    (out / "params.json").write_text(json.dumps(params, indent=2))
    (out / "custom.config").write_text(create_nextflow_config(config))

    env = dict(os.environ)
    conda_cache = Path("~/.nanometa/work/conda").expanduser()
    if conda_cache.is_dir() and "NXF_CONDA_CACHEDIR" not in env:
        env["NXF_CONDA_CACHEDIR"] = str(conda_cache)  # reuse the GUI's warmed envs
    cmd = [
        "nextflow", "run", str(Path(args.pipeline).expanduser()),
        "-params-file", str(out / "params.json"),
        "-c", str(out / "custom.config"),
        "-profile", "conda",
        "-work-dir", str(out / "work"),
        "-ansi-log", "false",
    ]
    sampler = [
        sys.executable, os.path.join(os.path.dirname(__file__), "audit_realtime_timeline.py"),
        str(results), "--config", str(out / "config.yaml"),
        "--input-dir", str(Path(args.input).expanduser().resolve()),
        "--out", str(out / "timeline.jsonl"), "--interval", str(args.interval), "--quiet",
    ]
    # Nextflow's own launch directory holds `.nextflow/cache/*/db`, a LevelDB
    # store opened with an OS file lock. When `--out` sits on a non-POSIX-lock
    # filesystem (observed: exFAT over the macOS FSKit driver on an external
    # drive) opening that DB fails immediately with "Can't open cache DB" --
    # even though plain flock() from Python succeeds there, so the failure is
    # specific to Nextflow/JVM's locking path, not a generic flock probe.
    # Nextflow's own error message names the fix: launch from a local
    # (lock-capable) directory and keep the shared `-work-dir` wherever it
    # needs to be for disk space. The launch dir holds only cache metadata and
    # `.nextflow.log`, so a system-temp location is fine even when the boot
    # volume is otherwise near full.
    launch_dir = Path(tempfile.mkdtemp(prefix=f"ttfr_nf_launch_{out.name}_"))
    t0 = time.time()
    with open(out / "nextflow.stdout", "w") as nf_out, open(out / "sampler.stdout", "w") as s_out:
        pipeline = subprocess.Popen(cmd, cwd=str(launch_dir), env=env, stdout=nf_out, stderr=subprocess.STDOUT)
        sampler_proc = subprocess.Popen(sampler, stdout=s_out, stderr=subprocess.STDOUT)
        rc = pipeline.wait()
        time.sleep(2 * args.interval + 1)  # one more tick after the last write
        sampler_proc.terminate()
        sampler_proc.wait(timeout=30)
    nf_log = launch_dir / ".nextflow.log"
    if nf_log.is_file():
        shutil.copy2(nf_log, out / ".nextflow.log")
    traces = sorted((results / "pipeline_info").glob("execution_trace_*.txt"))
    (out / "run.json").write_text(json.dumps({
        "t0": t0, "t_end": time.time(), "mode": args.mode, "results_dir": str(results),
        "trace": str(traces[-1]) if traces else None, "timeline": str(out / "timeline.jsonl"),
        "input_dir": str(Path(args.input).expanduser().resolve()), "command": cmd,
        "returncode": rc, "overrides": overrides,
        "host": {"cpus": os.cpu_count()},
        "launch_dir": str(launch_dir),
    }, indent=2))
    print(f"pipeline exit {rc}; artifacts in {out}")
    return rc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--barcodes", type=int, default=12)
    b.add_argument("--files-per-barcode", type=int, default=20)
    b.add_argument("--include-unclassified", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--input", required=True)
    r.add_argument("--mode", choices=["batch", "realtime"], required=True)
    r.add_argument("--db", required=True)
    r.add_argument("--pipeline", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--interval", type=float, default=2.0)
    r.add_argument("--overrides", help="JSON dict merged into the config before params are built")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        layout = build_backlog(Path(args.source), Path(args.out), args.barcodes,
                               args.files_per_barcode, args.include_unclassified)
        print(f"{len(layout)} samples, {sum(len(v) for v in layout.values())} files under {args.out}")
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
