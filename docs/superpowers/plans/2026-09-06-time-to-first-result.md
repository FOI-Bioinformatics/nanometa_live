# Time-to-First-Result Audit and Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, then shorten, the time from Start Analysis to a preliminary
result for EVERY barcode, in both processing modes, when many reads already
exist when the run starts; and make the interface say which barcodes are
preliminary and which are complete.

**Architecture:** An audit first, then repairs argued from its numbers. A
harness builds a synthetic backlog from the demo corpus (N barcodes x M files),
launches nanometanf exactly as the GUI would (same params file, same custom
config, same samplesheet), and samples the results tree every 2 s with the
dashboard's own loaders while the pipeline's trace records every task. An
analyser turns the two records into per-barcode first-report, completion and
verdict times, the achieved classifier concurrency, and the latency of each
hop. The repairs are: chunked, round-robin batch mode in nanometanf (first
chunk of every barcode before the second chunk of any); a classifier memory
reservation that lets memory-mapped forks actually run in parallel; and a
progress surface in the GUI that names preliminary and complete barcodes.

**Tech Stack:** Python 3.11/3.12, pandas, Dash 4, pytest; Nextflow 26.04.x
strict syntax, nf-test 0.9.5, Groovy `lib/` classes; nanorunner 3.1.0 (not
needed: the backlog is static); conda env `nf-core`; the demo corpus at
`~/nanometa-demo/data/multiplex` (barcode05-08 + unclassified, 178 files of
500 reads) and the 7.5 GB Bioshield database at
`~/nanometa-demo/db/bioshield26.1_8G`; this machine: 11 CPUs, 18 GB RAM.

**Spec:** This plan is the spec. The request: "we want to see results asap
in the interface. How do we handle batch and real-time mode when we have a
lot of reads already generated? Does it analyse all data for a sample before
presenting, or is it chunked so we get indications fast? The end user should
see preliminary results for all barcodes asap instead of first analysing one
single barcode." Acceptance criteria are stated in Global Constraints.

## What the code does today (evidence, gathered 2026-09-06)

These are the facts the hypotheses below are built on. The audit confirms or
refutes each with a number; the repairs assume them.

- **Batch mode classifies each barcode's whole read set in one task.** For a
  conventional barcode layout the GUI's batch launch sends `--input_dir`
  (`parameter_mapping.py`, `_resolve_batch_input_mode`, "Scenario E"), and
  nanometanf's INPUT_SCANNER groups the files with `groupTuple(by: 0)`
  (`subworkflows/local/input_scanner/main.nf:79`) into one item per sample;
  the samplesheet route (custom folder names, single_sample, per_file) ends
  the same way through `PIPELINE_INITIALISATION`'s `.groupTuple()`
  (`subworkflows/local/utils_nfcore_nanometanf_pipeline/main.nf:84-107`).
  DEMULTIPLEXING (`subworkflows/local/demultiplexing/main.nf`) is a
  pass-through, so QC gets one item per sample carrying every file. CHOPPER
  runs once on the concatenation and the standard `KRAKEN2_KRAKEN2` module
  runs once per sample: the GUI sends `kraken2_enable_incremental` only in
  its real-time branch (`parameter_mapping.py:1043` sits inside it), so the
  incremental path is not used in batch mode today (measured 2026-09-06,
  Task 3). The first report a barcode can show is its complete result.
- **Batch mode orders barcodes by samplesheet order.** `groupTuple` on a
  finite channel emits groups in first-seen order, which is
  `find_sample_subdirs` order (barcode01, barcode02, ...). Nothing interleaves.
- **The classifier's memory reservation serialises forks on laptop RAM.**
  `conf/modules.config:299-317`: `memory = kraken2_memory_gb (default 12) x
  attempt`, `maxForks = max_classification_forks (default 4)`. The GUI sizes
  `kraken2_memory_gb` as `max(12, ceil(hash.k2d GiB) + 4)`
  (`parameter_mapping.py:759-790`), 12 GB for the 7.5 GB demo database.
  Nextflow's local executor admits tasks while declared memory fits the host,
  so 18 GB of RAM admits ONE classifier at a time, 32 GB two, 64 GB four,
  whatever `max_classification_forks` says. With `--memory-mapping` (default
  on) the database lives in the shared page cache and the task's own memory
  is small; the reservation describes a cost the task does not pay.
- **Real-time mode already chunks and interleaves.** Pre-existing files are
  listed, age-filtered, and round-robin interleaved by parent directory
  (`subworkflows/local/realtime_monitoring/main.nf:189-193`,
  `BatchUtils.interleaveFilesByParentDir`); intake batches are
  count-or-timeout (`batch_size` 1 from the GUI, `batch_timeout` 60 s); a
  cross-batch deficit round-robin (`lib/CrossBatchInterleaver.groovy`) keeps
  barcodes fair; the batch is then FLATTENED (`realtime_monitoring/main.nf:514-520`)
  so every FILE is one QC task and one classifier task with a per-sample
  `batch_id`; the cumulative report is rewritten after every batch and the
  first batch always flushes (`report_write_interval` 1,
  `taxonomic_classification/main.nf:290-470`). So with a backlog, real-time
  mode gives every barcode a report after one round of files. Its cost is one
  Nextflow task per file (500-4000 reads), and the same memory serialisation.
- **`max_concurrent_batches` is advisory only** and does nothing
  (`realtime_monitoring/main.nf:43-61`).
- **The GUI's own latency is bounded and small.** Poll every 10 s while a run
  is active (`config_loader.py:414`), a 1 s file-stability floor
  (`loader_utils.py:127-140`), the 2 s debounce, and the fingerprint walk; a
  sample is listed when `kraken2/<sample>/` appears and reads as unmeasured
  until a report is readable. Worst case about 13 s from file to render.
- **Downstream already keys on `meta.batch_id`.** QC per-batch stats,
  per-batch reports and stats, the validation cumulative aggregator and the
  suppression of the per-sample canonical JSON all branch on
  `meta.batch_id != null` (`conf/modules.config:85-100,386-405,515-526`).
  Giving batch mode a `batch_id` therefore switches the whole tree to the
  layout the GUI already reads for a real-time run. One exception: the
  seqkit per-batch publish is enabled only for
  `qc_enable_incremental || (realtime_mode && kraken2_enable_incremental)`
  (`conf/modules.config:85`).

## Hypotheses the audit decides

Each is decided by the harness in Task 3 (baseline) and re-checked in Task 8.

| Id | Hypothesis | Decided by |
|----|-----------|------------|
| H1 | In batch mode a barcode's first report appears only when ALL its reads are classified; per-barcode first-report time equals completion time. | timeline: first tick with `total_reads > 0` per sample vs last change |
| H2 | Batch mode completes barcodes in samplesheet order, and on an 18 GB machine one at a time, whatever `max_classification_forks` says. | trace: classifier task start/complete overlap; order of first reports |
| H3 | Real-time mode over the same backlog gives every barcode a first report after one round of files, and the last barcode's first report arrives within `N x (task time / effective forks)` of the first. | timeline per-sample first-report times |
| H4 | Real-time throughput is bounded by per-file task overhead (QC + classify + merge + report per 500-read file), so total completion is longer than batch mode's. | trace: per-process durations and counts; total wall time |
| H5 | The classifier's declared memory, not CPU, decides concurrency: achieved concurrency = floor(RAM / kraken2_memory_gb), capped by forks. | trace: max concurrent classifier tasks; peak_rss per task |
| H6 | The first classifier task pays the database page-in; later tasks do not (warm cache). | trace: first vs median classifier `realtime` |
| H7 | The GUI adds under 15 s between the cumulative report's mtime and the sampler seeing reads for the sample. | timeline: tick time minus report mtime |
| H8 | A sample is absent from the sample list until its first report exists, so in batch mode the operator sees no barcode for the first minute or more. | timeline `samples` list vs run start |

## Global Constraints

- **Acceptance criterion A (all barcodes early).** After the repairs, with 12
  barcodes x 20 files (500 reads each) already present at Start on this
  machine, every barcode has a readable preliminary report within 3 minutes
  of Start in batch mode, and the spread between the first and the last
  barcode's first report is under 90 s. Measured by the harness, recorded in
  the audit document.
- **Acceptance criterion B (nothing hidden).** The header states how many
  barcodes have a preliminary result and how many are complete; the sample
  selector marks a preliminary barcode; the verdict subtitle says
  "preliminary" while any barcode is incomplete. The exported report is not
  changed by this plan (it already states run state).
- **Acceptance criterion C (final result unchanged).** The final cumulative
  report of a chunked batch run equals, read for read per taxid, the report
  of the same input classified in one task. Verified in Task 8 by running the
  harness both ways and comparing with `scripts/ttfr_analyse.py compare`
  (Task 2); the nf-test in Task 4 checks the chunked run's structure.
- nanometanf work stays on its `dev` branch and reaches `master` by pull
  request; the GUI on a feature branch of `nanometa_live` dev. The two are
  released together: `NANOMETANF_MIN_VERSION` (`core/workflow/pipeline_compat.py`)
  is bumped in the commit that first sends the new parameters, and every
  new parameter is declared in `nextflow_schema.json` (nf-schema rejects
  unknown parameters at launch).
- No Unicode in Nextflow files. Modest scientific language everywhere.
- Python floor 3.11; tests as `conda run -n nf-core python -m pytest <path> -q`;
  the nanometanf suite as `conda run -n nf-core nf-test test <file>` from
  `~/Code/nanometanf`; the `nanometa` env lacks pytest-xdist.
- Every live measurement names its machine, database, corpus and command;
  a number without those four is not a measurement.
- Commit subjects `type(scope): summary`; every commit ends with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW`.
- Measurement traps from earlier audits still apply: `conda run` swallows a
  child's stdout, a Chrome tab covered by another window stops polling, and
  the sampler measures the loader path, not the browser.

## File Structure

| Path | Responsibility |
|------|----------------|
| `scripts/ttfr_backlog.py` (new, nanometa_live) | `build`: synthetic N x M backlog from the demo corpus by symlink. `run`: launch nanometanf as the GUI would (params via `create_nextflow_params`), start the sampler, wait, write `run.json`. |
| `scripts/ttfr_analyse.py` (new) | Per-barcode first-report / completion / verdict times from `timeline.jsonl`; concurrency and per-process durations from the pipeline trace; a markdown table and a JSON summary. |
| `tests/test_ttfr_harness.py` (new) | Unit tests for the corpus builder and the analyser on synthetic inputs. |
| `docs/audit/time-to-first-result-2026-09-06.md` (new) | Hypothesis verdicts with numbers, before and after. |
| `lib/BatchChunkPlanner.groovy` (new, nanometanf) | Chunk a sample's file list with geometric growth; interleave chunks across samples by chunk index; write the plan JSON. |
| `workflows/nanometanf.nf` (modify) | Samplesheet branch: chunk and interleave when `params.batch_chunking`. |
| `subworkflows/local/taxonomic_classification/main.nf` (modify) | The incremental gate and the final aggregator gate include `batch_chunking`. |
| `conf/modules.config` (modify) | seqkit per-batch publish enabled for chunked batch mode; classifier memory from `kraken2_task_memory_gb`. |
| `nextflow.config`, `nextflow_schema.json` (modify) | `batch_chunking`, `batch_first_chunk_files`, `batch_chunk_growth`, `kraken2_task_memory_gb`. |
| `tests/lib/batch_chunk_planner.nf.test`, `tests/lib/batch_chunk_planner_functions.nf` (new) | nf-test function tests for the planner. |
| `tests/batch_chunking_structure.nf.test` (new) | Stub run: the plan file names every sample and each has one batch report per planned chunk; chunking off writes no plan. |
| `nanometa_live/core/config/parameter_mapping.py`, `config_loader.py` (modify) | Send the four parameters; size `kraken2_task_memory_gb`; force incremental on when chunking. |
| `nanometa_live/app/utils/batch_progress.py` (new) | Read `pipeline_info/batch_chunk_plan.json` and the batch_reports tree into a progress summary. |
| `nanometa_live/app/callbacks/status.py`, `app/callbacks/samples.py`, `app/tabs/dashboard_helpers.py` (modify) | Header line, selector marker, verdict subtitle. |
| `tests/test_batch_progress.py`, `tests/test_parameter_mapping_chunking.py` (new) | GUI tests. |
| `docs/configuration.md`, `docs/user-guide.md`, `CLAUDE.md`, `CHANGELOG.md` (modify) | Documentation and invariants. |

---

## Task 1: Synthetic backlog and run driver

**Files:**
- Create: `scripts/ttfr_backlog.py`
- Test: `tests/test_ttfr_harness.py` (the builder half; the analyser half is Task 2)

**Interfaces:**
- Produces: `build_backlog(source: Path, out: Path, barcodes: int, files_per_barcode: int, include_unclassified: bool) -> dict[str, list[Path]]`; the CLI `build` and `run` subcommands; `run.json` with keys `t0` (epoch seconds at `nextflow run` spawn), `mode`, `results_dir`, `trace`, `timeline`, `input_dir`, `command`, `returncode`.
- Consumes: `nanometa_live.core.config.parameter_mapping.create_nextflow_params(config)`, `create_nextflow_config(config)`; `scripts/audit_realtime_timeline.py` (unchanged).

- [ ] **Step 1: Write the failing builder test**

Create `tests/test_ttfr_harness.py`:

```python
"""Harness for the time-to-first-result audit: a synthetic backlog and its analysis.

The builder makes N barcode directories with M files each from a small source
corpus by symlink, round-robin over the source barcodes, so a 24-barcode
backlog costs no disk and the sample ids are the directory names the pipeline
uses. The analyser (Task 2) reads the sampler's timeline and the pipeline
trace.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _source_corpus(tmp_path, barcodes=("barcode05", "barcode06"), files=3):
    src = tmp_path / "src"
    for bc in barcodes:
        d = src / bc
        d.mkdir(parents=True)
        for k in range(files):
            (d / f"reads_{bc}_{k}.fastq.gz").write_bytes(b"\x1f\x8b" + bytes([k]))
    return src


class TestBuildBacklog:
    def test_makes_n_barcodes_with_m_symlinks_each(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        out = tmp_path / "input"
        layout = build_backlog(src, out, barcodes=4, files_per_barcode=2, include_unclassified=False)
        assert sorted(layout) == ["barcode01", "barcode02", "barcode03", "barcode04"]
        for bc, files in layout.items():
            assert len(files) == 2
            for f in files:
                assert f.is_symlink() and f.resolve().is_file()
                assert f.parent.name == bc

    def test_sources_rotate_round_robin(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        layout = build_backlog(src, tmp_path / "input", barcodes=3, files_per_barcode=1, include_unclassified=False)
        origins = [layout[bc][0].resolve().parent.name for bc in sorted(layout)]
        assert origins == ["barcode05", "barcode06", "barcode05"]

    def test_refuses_more_files_than_the_source_has(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path, files=2)
        with pytest.raises(ValueError, match="only 2"):
            build_backlog(src, tmp_path / "input", barcodes=1, files_per_barcode=5, include_unclassified=False)

    def test_writes_a_layout_manifest(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        out = tmp_path / "input"
        build_backlog(src, out, barcodes=2, files_per_barcode=2, include_unclassified=False)
        manifest = json.loads((out / "backlog_layout.json").read_text())
        assert manifest["barcodes"] == 2 and manifest["files_per_barcode"] == 2
        assert set(manifest["samples"]) == {"barcode01", "barcode02"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `conda run -n nf-core python -m pytest tests/test_ttfr_harness.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.ttfr_backlog'` (create `scripts/__init__.py` if `scripts/` is not importable; check `ls scripts/__init__.py` first, the other audit scripts are imported by tests the same way).

- [ ] **Step 3: Write the builder and the run driver**

Create `scripts/ttfr_backlog.py`:

```python
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
import subprocess
import sys
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
    from nanometa_live.core.config.config_loader import ConfigLoader

    config = ConfigLoader().default_config()
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
        "run_validation": False,
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
    t0 = time.time()
    with open(out / "nextflow.stdout", "w") as nf_out, open(out / "sampler.stdout", "w") as s_out:
        pipeline = subprocess.Popen(cmd, cwd=str(out), env=env, stdout=nf_out, stderr=subprocess.STDOUT)
        sampler_proc = subprocess.Popen(sampler, stdout=s_out, stderr=subprocess.STDOUT)
        rc = pipeline.wait()
        time.sleep(2 * args.interval + 1)  # one more tick after the last write
        sampler_proc.terminate()
        sampler_proc.wait(timeout=30)
    traces = sorted((results / "pipeline_info").glob("execution_trace_*.txt"))
    (out / "run.json").write_text(json.dumps({
        "t0": t0, "t_end": time.time(), "mode": args.mode, "results_dir": str(results),
        "trace": str(traces[-1]) if traces else None, "timeline": str(out / "timeline.jsonl"),
        "input_dir": str(Path(args.input).expanduser().resolve()), "command": cmd,
        "returncode": rc, "overrides": overrides,
        "host": {"cpus": os.cpu_count()},
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
```

Check two names before running: `ConfigLoader().default_config()` (the plan's
earlier audit named `config_loader.default_config()`; use whichever exists,
`grep -n "def default_config\|def create_default_config" nanometa_live/core/config/config_loader.py`),
and the config key that disables validation (`run_validation` /
`blast_validation`; `grep -n '"run_validation"\|"blast_validation"' nanometa_live/core/config/config_loader.py`).

- [ ] **Step 4: Run the builder tests**

Run: `conda run -n nf-core python -m pytest tests/test_ttfr_harness.py -q`
Expected: 4 passed.

- [ ] **Step 5: Smoke the driver against the real corpus without a pipeline run**

Run:
```bash
conda run -n nf-core python scripts/ttfr_backlog.py build --source ~/nanometa-demo/data/multiplex --out /tmp/ttfr/input --barcodes 12 --files-per-barcode 20
ls /tmp/ttfr/input | head; ls /tmp/ttfr/input/barcode01 | wc -l
```
Expected: `12 samples, 240 files`, twelve `barcodeNN` directories with 20 links each.

- [ ] **Step 6: Commit**

```bash
git add scripts/ttfr_backlog.py tests/test_ttfr_harness.py
git commit -m "test(audit): synthetic backlog builder and run driver for time-to-first-result

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 2: Analyser for timeline and trace

**Files:**
- Create: `scripts/ttfr_analyse.py`
- Test: `tests/test_ttfr_harness.py` (append)

**Interfaces:**
- Consumes: `timeline.jsonl` records written by `scripts/audit_realtime_timeline.py`: each line has `ts` (epoch seconds), `samples` (list), `unmeasured` (list), `per_sample` (dict `sample -> {tier, report_stat, total_reads, watched}`), `trace`, `run_meta`, `input`. The pipeline trace TSV with the nanometanf field list `task_id,hash,native_id,process,tag,name,status,exit,submit,start,complete,duration,realtime,queue,%cpu,%mem,peak_rss,peak_vmem,rchar,wchar,attempt` (`nextflow.config:479`), timestamps `YYYY-MM-DD HH:MM:SS.mmm`.
- Produces: `analyse(run_dir: Path) -> dict` with `per_sample` (`first_report_s`, `complete_s`, `first_watched_s`), `spread_first_report_s`, `all_first_report_s`, `classifier` (`tasks`, `max_concurrency`, `first_task_s`, `median_task_s`, `peak_rss_gb`), `per_process` (`count`, `median_s`), `wall_s`; and `render(summary) -> str` (markdown table). CLI: `python scripts/ttfr_analyse.py <run_dir> [--json out.json]`.

- [ ] **Step 1: Write the failing analyser tests**

Append to `tests/test_ttfr_harness.py`:

```python
def _write_run(tmp_path, ticks, trace_rows, t0=1000.0):
    run = tmp_path / "run"
    run.mkdir()
    timeline = run / "timeline.jsonl"
    with timeline.open("w") as fh:
        for ts, per_sample in ticks:
            fh.write(json.dumps({
                "ts": ts,
                "samples": sorted(per_sample),
                "unmeasured": [s for s, v in per_sample.items() if v["total_reads"] is None],
                "per_sample": per_sample,
                "trace": {}, "run_meta": {}, "input": {},
            }) + "\n")
    trace = run / "trace.txt"
    header = "task_id\thash\tnative_id\tprocess\ttag\tname\tstatus\texit\tsubmit\tstart\tcomplete\tduration\trealtime\tqueue\t%cpu\t%mem\tpeak_rss\tpeak_vmem\trchar\twchar\tattempt\n"
    with trace.open("w") as fh:
        fh.write(header)
        for row in trace_rows:
            fh.write("\t".join(row) + "\n")
    (run / "run.json").write_text(json.dumps({
        "t0": t0, "t_end": t0 + 100, "mode": "batch", "results_dir": str(run),
        "trace": str(trace), "timeline": str(timeline), "input_dir": "", "command": [], "returncode": 0,
    }))
    return run


def _ps(reads, watched=0):
    return {"tier": "cumulative" if reads else "none", "report_stat": None,
            "total_reads": reads, "watched": watched}


class TestAnalyse:
    def test_first_report_completion_and_spread(self, tmp_path):
        from scripts.ttfr_analyse import analyse

        ticks = [
            (1002.0, {"barcode01": _ps(None), "barcode02": _ps(None)}),
            (1010.0, {"barcode01": _ps(100), "barcode02": _ps(None)}),
            (1020.0, {"barcode01": _ps(100), "barcode02": _ps(50, watched=1)}),
            (1030.0, {"barcode01": _ps(300), "barcode02": _ps(50, watched=1)}),
        ]
        run = _write_run(tmp_path, ticks, [])
        s = analyse(run)
        assert s["per_sample"]["barcode01"]["first_report_s"] == 10.0
        assert s["per_sample"]["barcode01"]["complete_s"] == 30.0
        assert s["per_sample"]["barcode02"]["first_report_s"] == 20.0
        assert s["per_sample"]["barcode02"]["first_watched_s"] == 20.0
        assert s["spread_first_report_s"] == 10.0
        assert s["all_first_report_s"] == 20.0

    def test_classifier_concurrency_from_trace(self, tmp_path):
        from scripts.ttfr_analyse import analyse

        def row(tid, process, tag, start, complete, realtime, rss, attempt="1"):
            return [tid, "aa/bb", "1", process, tag, f"{process} ({tag})", "COMPLETED", "0",
                    start, start, complete, "10s", realtime, "0ms", "300%", "5%", rss, "1 GB", "1", "1", attempt]

        rows = [
            row("1", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode01",
                "2026-09-06 12:00:00.000", "2026-09-06 12:00:40.000", "40s", "1.5 GB"),
            row("2", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode02",
                "2026-09-06 12:00:10.000", "2026-09-06 12:00:20.000", "10s", "1.2 GB"),
            row("3", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode03",
                "2026-09-06 12:00:41.000", "2026-09-06 12:00:50.000", "9s", "1.2 GB"),
            row("4", "NANOMETANF:QC:CHOPPER", "barcode01",
                "2026-09-06 11:59:50.000", "2026-09-06 11:59:59.000", "9s", "200 MB"),
        ]
        run = _write_run(tmp_path, [(1002.0, {"barcode01": _ps(1)})], rows)
        s = analyse(run)
        c = s["classifier"]
        assert c["tasks"] == 3
        assert c["max_concurrency"] == 2
        assert c["first_task_s"] == 40.0
        assert c["median_task_s"] == 10.0
        assert c["peak_rss_gb"] == 1.5
        assert s["per_process"]["CHOPPER"]["count"] == 1

    def test_render_lists_every_sample(self, tmp_path):
        from scripts.ttfr_analyse import analyse, render

        run = _write_run(tmp_path, [(1005.0, {"barcode01": _ps(1), "barcode02": _ps(None)})], [])
        text = render(analyse(run))
        assert "barcode01" in text and "barcode02" in text
        assert "never" in text  # barcode02 got no report


REPORT_A = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n40.00\t40\t40\tS\t562\t  Escherichia coli\n"
REPORT_B = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n40.00\t40\t40\tS\t562\t  Escherichia coli\n"
REPORT_C = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n39.00\t39\t39\tS\t562\t  Escherichia coli\n"


class TestCompareReports:
    def test_identical_counts_agree(self, tmp_path):
        from scripts.ttfr_analyse import compare_reports

        a = tmp_path / "a.txt"; a.write_text(REPORT_A)
        b = tmp_path / "b.txt"; b.write_text(REPORT_B)
        result = compare_reports(a, b)
        assert result["equal"] is True and result["differences"] == {}

    def test_a_differing_taxid_is_named(self, tmp_path):
        from scripts.ttfr_analyse import compare_reports

        a = tmp_path / "a.txt"; a.write_text(REPORT_A)
        c = tmp_path / "c.txt"; c.write_text(REPORT_C)
        result = compare_reports(a, c)
        assert result["equal"] is False
        assert result["differences"] == {"562": (40, 39)}

    def test_compare_runs_pairs_samples(self, tmp_path):
        from scripts.ttfr_analyse import compare_runs

        for name, text in (("chunked/kraken2/barcode01.cumulative.kraken2.report.txt", REPORT_A),
                           ("single/kraken2/barcode01.kraken2.report.txt", REPORT_C)):
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        result = compare_runs(tmp_path / "chunked", tmp_path / "single")
        assert result["samples"] == ["barcode01"]
        assert result["equal"] is False
        assert result["per_sample"]["barcode01"]["differences"] == {"562": (40, 39)}
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_ttfr_harness.py -q -k Analyse`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.ttfr_analyse'`.

- [ ] **Step 3: Write the analyser**

Create `scripts/ttfr_analyse.py`:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `conda run -n nf-core python -m pytest tests/test_ttfr_harness.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/ttfr_analyse.py tests/test_ttfr_harness.py
git commit -m "test(audit): analyser for per-barcode first-report latency and classifier concurrency

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 3: Baseline measurements and hypothesis verdicts (live)

**Files:**
- Create: `docs/audit/time-to-first-result-2026-09-06.md`

This task runs the pipeline for real on this machine. Both runs take a few
minutes each. Nothing else may use the CPU heavily at the same time (stop any
running GUI or demo first: `~/nanometa-demo/scripts/stop_all.sh` if it exists,
and `pgrep -fl nextflow`).

- [ ] **Step 1: Build the backlog**

```bash
conda run -n nf-core python scripts/ttfr_backlog.py build \
  --source ~/nanometa-demo/data/multiplex --out /tmp/ttfr/input \
  --barcodes 12 --files-per-barcode 20
```

- [ ] **Step 2: Batch baseline**

```bash
conda run -n nf-core python scripts/ttfr_backlog.py run --input /tmp/ttfr/input \
  --mode batch --db ~/nanometa-demo/db/bioshield26.1_8G \
  --pipeline ~/Code/nanometanf --out /tmp/ttfr/batch_baseline
conda run -n nf-core python scripts/ttfr_analyse.py /tmp/ttfr/batch_baseline --json /tmp/ttfr/batch_baseline/summary.json
```

Expected shape (H1, H2): every sample's `first report` equals its `complete`;
first reports arrive in barcode order; `max concurrency` is 1 on this 18 GB
machine (H5). Record the actual numbers. If the run fails, read
`/tmp/ttfr/batch_baseline/nextflow.stdout` and fix the harness (Task 1), not
the pipeline.

- [ ] **Step 3: Real-time baseline over the same backlog**

```bash
conda run -n nf-core python scripts/ttfr_backlog.py run --input /tmp/ttfr/input \
  --mode realtime --db ~/nanometa-demo/db/bioshield26.1_8G \
  --pipeline ~/Code/nanometanf --out /tmp/ttfr/realtime_baseline
conda run -n nf-core python scripts/ttfr_analyse.py /tmp/ttfr/realtime_baseline --json /tmp/ttfr/realtime_baseline/summary.json
```

Expected shape (H3, H4): every barcode's first report within one round of
files; `spread` small; many more tasks (240 QC + 240 classify) and a longer
wall time than batch. The run ends by the 3-minute timeout plus grace after
the backlog drains; if the backlog is not drained by then, raise
`realtime_timeout_minutes` through `--overrides '{"realtime_timeout_minutes": 8}'`
and rerun.

- [ ] **Step 4: Memory hypothesis probe (H5)**

Rerun batch mode with the classifier reservation lowered, to see what
concurrency the same machine achieves when memory is not the gate. This is a
probe only; the real change is Task 5.

```bash
conda run -n nf-core python scripts/ttfr_backlog.py run --input /tmp/ttfr/input \
  --mode batch --db ~/nanometa-demo/db/bioshield26.1_8G \
  --pipeline ~/Code/nanometanf --out /tmp/ttfr/batch_mem4 \
  --overrides '{"kraken2_memory_gb": 4}'
conda run -n nf-core python scripts/ttfr_analyse.py /tmp/ttfr/batch_mem4
```

Expected: `max concurrency` rises toward 4 and `peak rss` stays far below
12 GB (the database pages are shared). If a task dies with exit 137 or 139,
record it: that is the evidence that the reservation must stay large on the
retry path.

- [ ] **Step 5: GUI latency (H7, H8)**

From the batch baseline timeline, for barcode01: the cumulative report's
mtime (`stat -f %m /tmp/ttfr/batch_baseline/results/kraken2/barcode01.cumulative.kraken2.report.txt`,
or the standard report if no cumulative exists) against the first tick where
`per_sample.barcode01.total_reads > 0`; and the first tick where `barcode01`
appears in `samples`. Record both differences.

- [ ] **Step 6: Write the audit document**

Create `docs/audit/time-to-first-result-2026-09-06.md` with this structure and
the measured numbers (no placeholders: every cell filled from the two
`summary.json` files and Step 5):

```markdown
# Time to first result: audit (2026-09-06)

**Question.** When many reads already exist at Start, how long until every
barcode shows a preliminary result, in batch and in real-time mode, and does
the pipeline analyse a whole sample before presenting anything?

**Setup.** MacBook (11 CPUs, 18 GB), Bioshield database 7.5 GB
(`bioshield26.1_8G`), 12 barcodes x 20 files x 500 reads built from the demo
corpus by `scripts/ttfr_backlog.py`, launched with the GUI's own parameter
builder, sampled every 2 s by `scripts/audit_realtime_timeline.py`, analysed
by `scripts/ttfr_analyse.py`. nanometanf <commit>, nanometa_live <commit>.

## Results at a glance

| Run | first report, first barcode (s) | all barcodes (s) | spread (s) | wall (s) | classifier tasks | max concurrency | median task (s) |
|---|---|---|---|---|---|---|---|
| batch baseline | | | | | | | |
| realtime baseline | | | | | | | |
| batch, memory 4 GB probe | | | | | | | |

## Hypotheses

| Id | Verdict | Evidence |
|---|---|---|
| H1 | confirmed / refuted | first_report_s == complete_s for N of 12 samples |
| H2 | | order of first reports; max_concurrency |
| H3 | | spread in realtime |
| H4 | | tasks and wall time |
| H5 | | concurrency at 12 GB vs 4 GB; peak_rss |
| H6 | | first vs median classifier task |
| H7 | | report mtime to sampler tick |
| H8 | | first tick listing barcode01 vs run start |

## What this means for the operator

(Three sentences: what a batch run shows and when, what a real-time run shows
and when, and which of the two an operator with a backlog should choose
today.)

## Repairs argued from these numbers

Pointers to Tasks 4, 5, 6 of the plan, each with the number it targets.
```

- [ ] **Step 7: Commit**

```bash
git add docs/audit/time-to-first-result-2026-09-06.md
git commit -m "docs(audit): time-to-first-result baseline for a 12-barcode backlog, both modes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 4: nanometanf: chunked, round-robin batch mode

**Why.** A backlog in batch mode should behave like a real-time run over a
static directory: the first chunk of every barcode before the second chunk of
any, each chunk producing a per-batch report and advancing the cumulative
report, so every barcode has a preliminary result after one round. Chunks
grow geometrically (1, 2, 4, 8 ... files) so a 200-file barcode costs about
eight classifier tasks rather than 200 (real-time's cost) or one (today's).

**Repository:** `~/Code/nanometanf`, branch `dev`.

**Files:**
- Create: `lib/BatchChunkPlanner.groovy`
- Modify: `workflows/nanometanf.nf` (the `else` branch "Standard samplesheet input", around line 268)
- Modify: `subworkflows/local/taxonomic_classification/main.nf:181` (the incremental gate) and the gate on `KRAKEN2_FINAL_AGGREGATOR` (find it: `grep -n 'FINAL_AGGREGATOR' subworkflows/local/taxonomic_classification/main.nf`)
- Modify: `conf/modules.config:85` (seqkit per-batch publish `enabled`)
- Modify: `nextflow.config` params, `nextflow_schema.json`, `docs/output.md` (the batch_reports layout now also applies to chunked batch runs), `CHANGELOG.md`
- Test: `tests/lib/batch_chunk_planner_functions.nf`, `tests/lib/batch_chunk_planner.nf.test`, `tests/batch_chunking_equivalence.nf.test`

**Interfaces:**
- Produces params `batch_chunking` (boolean, default `true`), `batch_first_chunk_files` (integer, default 1), `batch_chunk_growth` (number, default 2.0); the plan file `<outdir>/pipeline_info/batch_chunk_plan.json` with shape `{"<sample>": {"files": <int>, "chunks": <int>}}`; every emitted item carries `meta.batch_id` (0-based chunk index), `meta.batch_time`, `meta.chunk_count`.
- Consumed by Task 6 (the plan file) and Task 7 (the params).

- [ ] **Step 1: Write the failing planner tests**

Create `tests/lib/batch_chunk_planner_functions.nf`:

```nextflow
// Thin wrappers so nf-test's function tests can drive the lib class.

def chunk(List files, int firstFiles, double growth) {
    return BatchChunkPlanner.chunk(files, firstFiles, growth)
}

def interleave(Map chunksBySample) {
    return BatchChunkPlanner.interleave(chunksBySample)
}
```

Create `tests/lib/batch_chunk_planner.nf.test`:

```groovy
nextflow_function {
    name "Test BatchChunkPlanner (chunk sizes and cross-sample order)"
    script "tests/lib/batch_chunk_planner_functions.nf"
    tag "unit"
    tag "fast"
    tag "batch"

    test("Chunks grow geometrically from the first size and cover every file once") {
        function "chunk"
        when {
            function {
                """
                input[0] = ['f01','f02','f03','f04','f05','f06','f07','f08','f09','f10','f11']
                input[1] = 1
                input[2] = 2.0
                """
            }
        }
        then {
            assert function.success
            assert function.result.collect { it.size() } == [1, 2, 4, 4]
            assert function.result.flatten() == ['f01','f02','f03','f04','f05','f06','f07','f08','f09','f10','f11']
        }
    }

    test("Growth of 1 keeps every chunk at the first size") {
        function "chunk"
        when {
            function {
                """
                input[0] = ['a','b','c','d','e']
                input[1] = 2
                input[2] = 1.0
                """
            }
        }
        then {
            assert function.success
            assert function.result.collect { it.size() } == [2, 2, 1]
        }
    }

    test("Files are name-sorted before chunking") {
        function "chunk"
        when {
            function {
                """
                input[0] = ['c','a','b']
                input[1] = 1
                input[2] = 2.0
                """
            }
        }
        then {
            assert function.success
            assert function.result == [['a'], ['b','c']]
        }
    }

    test("Interleave emits chunk 0 of every sample before chunk 1 of any") {
        function "interleave"
        when {
            function {
                """
                input[0] = [
                    barcode01: [['a1'], ['a2','a3'], ['a4']],
                    barcode02: [['b1'], ['b2','b3']],
                    barcode03: [['c1']],
                ]
                """
            }
        }
        then {
            assert function.success
            assert function.result.collect { [it[0], it[1]] } == [
                ['barcode01', 0], ['barcode02', 0], ['barcode03', 0],
                ['barcode01', 1], ['barcode02', 1],
                ['barcode01', 2],
            ]
            assert function.result.collect { it[2] }.flatten().size() == 8
        }
    }
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ~/Code/nanometanf && conda run -n nf-core nf-test test tests/lib/batch_chunk_planner.nf.test`
Expected: FAIL, `BatchChunkPlanner` not found.

- [ ] **Step 3: Write the planner**

Create `lib/BatchChunkPlanner.groovy`:

```groovy
import groovy.json.JsonOutput

/**
 * Chunk plan for batch mode with a backlog.
 *
 * A samplesheet run used to classify each sample's whole file list in one
 * task, in samplesheet order, so a barcode showed nothing until every read
 * of it was classified and barcodes finished one after another. This class
 * splits each sample's files into chunks whose sizes grow geometrically
 * (1, 2, 4, 8 ... files with firstFiles 1 and growth 2) and orders the chunks
 * across samples by chunk index, so the first chunk of every sample is
 * classified before the second chunk of any. Downstream, each chunk is a
 * batch with meta.batch_id, exactly as a real-time batch, and the cumulative
 * report advances after each one. A 200-file sample costs about eight
 * classifier tasks this way rather than 200 (one per file) or one.
 *
 * The planner is pure: it neither reads nor orders by file size. Every file
 * appears in exactly one chunk, in name-sorted order within its sample.
 */
class BatchChunkPlanner {

    /** Split name-sorted files into chunks of geometrically growing size. */
    static List<List> chunk(List files, int firstFiles = 1, double growth = 2.0) {
        def sorted = (files ?: []).sort(false) { it.toString() }
        def out = []
        int i = 0
        double size = Math.max(1, firstFiles)
        while (i < sorted.size()) {
            int n = Math.max(1, (int) Math.round(size))
            out << sorted.subList(i, Math.min(sorted.size(), i + n)).collect { it }
            i += n
            if (growth > 1.0) {
                size = size * growth
            }
        }
        return out
    }

    /**
     * Order chunks across samples by chunk index: every sample's chunk 0
     * (in the map's iteration order), then every sample's chunk 1, and so on.
     * Returns a list of [sampleId, chunkIndex, files].
     */
    static List interleave(Map<String, List<List>> chunksBySample) {
        def out = []
        int depth = (chunksBySample?.values()?.collect { it.size() } ?: [0]).max() ?: 0
        for (int k = 0; k < depth; k++) {
            chunksBySample.each { sample, chunks ->
                if (k < chunks.size()) {
                    out << [sample, k, chunks[k]]
                }
            }
        }
        return out
    }

    /** Write {sample: {files, chunks}} so the dashboard can show progress. */
    static void writePlan(String path, Map<String, List<List>> chunksBySample) {
        def summary = chunksBySample.collectEntries { sample, chunks ->
            [(sample): [files: chunks.sum { it.size() } ?: 0, chunks: chunks.size()]]
        }
        def target = new File(path)
        target.parentFile?.mkdirs()
        def temp = new File(target.parentFile, target.name + '.tmp')
        temp.text = JsonOutput.prettyPrint(JsonOutput.toJson(summary))
        java.nio.file.Files.move(temp.toPath(), target.toPath(),
            java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            java.nio.file.StandardCopyOption.ATOMIC_MOVE)
    }
}
```

- [ ] **Step 4: Run the planner tests**

Run: `cd ~/Code/nanometanf && conda run -n nf-core nf-test test tests/lib/batch_chunk_planner.nf.test`
Expected: 4 passed.

- [ ] **Step 5: Declare the parameters**

In `nextflow.config` `params {}`, beside `kraken2_enable_incremental`:

```groovy
    batch_chunking             = true        // Batch mode: classify each sample in growing chunks, first chunk of every sample first, so every barcode has a preliminary report after one round
    batch_first_chunk_files    = 1           // Files in a sample's first chunk (the preliminary result)
    batch_chunk_growth         = 2.0         // Chunk size multiplier after the first chunk (1.0 = constant)
```

In `nextflow_schema.json`, in the same definition group as
`kraken2_enable_incremental`, add:

```json
"batch_chunking": {
    "type": "boolean",
    "default": true,
    "description": "Batch mode: classify each sample in growing chunks, the first chunk of every sample before the second of any, so every barcode has a preliminary report after one round. Off restores one classification per sample."
},
"batch_first_chunk_files": {
    "type": "integer",
    "default": 1,
    "minimum": 1,
    "description": "Number of FASTQ files in a sample's first chunk, which yields its preliminary result."
},
"batch_chunk_growth": {
    "type": "number",
    "default": 2.0,
    "minimum": 1.0,
    "description": "Multiplier applied to the chunk size after each chunk (1.0 keeps every chunk at the first size)."
}
```

- [ ] **Step 6: Wire the planner after the input-routing block**

Both batch input routes end as one item per sample: INPUT_SCANNER
(`--input_dir`, the GUI's route for conventional barcode folders) and the
samplesheet (custom folder names, single_sample, per_file). The planner
therefore applies ONCE, to `ch_processed_samples`, after the whole
`if (params.input_dir || is_barcode_discovery) { ... } else { ... }` block in
`workflows/nanometanf.nf` and before `DEMULTIPLEXING (ch_processed_samples)`,
guarded on batch mode. Insert:

```nextflow
        if (!params.realtime_mode && params.batch_chunking) {
            // Batch mode with chunking. Both batch routes above deliver one
            // item per sample carrying every file (INPUT_SCANNER's
            // groupTuple, or PIPELINE_INITIALISATION's for a samplesheet).
            // Split each sample into growing chunks and order the chunks so
            // the first chunk of every sample is classified before the
            // second of any; each chunk is a batch downstream, exactly as in
            // real-time mode. The channel is finite, so toList() completes
            // at once and the plan is written before any task runs.
            def first_files = (params.batch_first_chunk_files ?: 1) as int
            def growth = (params.batch_chunk_growth ?: 2.0) as double
            ch_processed_samples = ch_processed_samples
                .toList()
                .flatMap { rows ->
                    def by_sample = [:]
                    rows.each { meta, fastqs ->
                        def files = fastqs instanceof List ? fastqs : [fastqs]
                        by_sample[meta.id] = [meta: meta, chunks: BatchChunkPlanner.chunk(files, first_files, growth)]
                    }
                    BatchChunkPlanner.writePlan(
                        "${params.outdir}/pipeline_info/batch_chunk_plan.json",
                        by_sample.collectEntries { id, v -> [(id): v.chunks] })
                    def stamp = new Date().format('yyyy-MM-dd_HH-mm-ss')
                    def ordered = BatchChunkPlanner.interleave(by_sample.collectEntries { id, v -> [(id): v.chunks] })
                    log.info "Batch chunking: ${by_sample.size()} sample(s), ${ordered.size()} chunk(s); first chunk ${first_files} file(s), growth x${growth}"
                    ordered.collect { id, k, files ->
                        def meta = by_sample[id].meta.clone()
                        meta.batch_id = k
                        meta.batch_time = stamp
                        meta.chunk_count = by_sample[id].chunks.size()
                        tuple(meta, files)
                    }
                }
        }
```

Leave the samplesheet `else` branch (`ch_processed_samples = ch_samplesheet`)
as it is.

- [ ] **Step 7: Route chunked batch mode down the incremental path**

In `subworkflows/local/taxonomic_classification/main.nf`, change the gate at
line 181 from
`if (params.kraken2_enable_incremental == true || params.realtime_mode == true) {`
to
`if (params.kraken2_enable_incremental == true || params.realtime_mode == true || (params.batch_chunking == true && !params.realtime_mode)) {`
and add above it:

```nextflow
            if (params.batch_chunking && !params.realtime_mode && !params.kraken2_enable_incremental) {
                log.info "Batch chunking is on, so the incremental classifier path is used (per-chunk reports and a cumulative report per sample)"
            }
```

Find the gate that runs `KRAKEN2_FINAL_AGGREGATOR` at session end
(`grep -n 'FINAL_AGGREGATOR\|realtime_mode' subworkflows/local/taxonomic_classification/main.nf`)
and extend its condition the same way, so a chunked batch run also gets its
final aggregation and canonical output. Do the same for any
`params.realtime_mode` condition in `subworkflows/local/validation/main.nf`
and `subworkflows/local/qc_analysis/main.nf` that selects the cumulative
(per-batch) behaviour; the rule is: "real-time OR chunked batch" wherever
`meta.batch_id` is expected. List every site you changed in the commit body.

In `conf/modules.config:85`, change the seqkit per-batch publish `enabled`
to:

```groovy
                enabled: (params.qc_enable_incremental ?: false) || ((params.realtime_mode ?: false) && (params.kraken2_enable_incremental ?: false)) || ((params.batch_chunking ?: false) && !(params.realtime_mode ?: false)),
```

- [ ] **Step 8: Stub run**

```bash
cd ~/Code/nanometanf
conda run -n nf-core nextflow run main.nf -profile test,conda -stub --outdir /tmp/ttfr/stub_chunked --batch_chunking true
ls /tmp/ttfr/stub_chunked/pipeline_info/batch_chunk_plan.json
ls /tmp/ttfr/stub_chunked/kraken2/*/batch_reports 2>/dev/null | head
```

Expected: the run succeeds, the plan file exists with one entry per test
sample, and per-batch reports exist under `kraken2/<sample>/batch_reports/`.
If a downstream process fails on a chunk (a staging name collision from two
chunks of one sample sharing an output name, as ASSEMBLY_READ_POOL once did),
give the process an `ext.prefix` that includes `meta.batch_id`, as the QC
publish closure does.

- [ ] **Step 9: Write the structure test (stub, runs in CI)**

Create `tests/batch_chunking_structure.nf.test`:

```groovy
nextflow_pipeline {
    name "Chunked batch mode writes the plan and one batch report per chunk"
    script "main.nf"
    tag "batch"
    tag "chunking"
    tag "fast"

    // Chunking changes when results appear, never what they are; the
    // read-for-read equivalence with a single-task run is checked on a real
    // database by the nanometa_live harness (scripts/ttfr_analyse.py compare).
    // This stub test pins the contract the dashboard reads: the plan file
    // names every sample, and each sample has as many per-batch reports as
    // the plan promised.
    test("Plan file and per-batch reports agree") {
        options "-stub"
        when {
            params {
                outdir = "${outputDir}"
                batch_chunking = true
                batch_first_chunk_files = 1
                batch_chunk_growth = 2.0
            }
        }
        then {
            assert workflow.success
            def plan = new groovy.json.JsonSlurper().parse(path("${outputDir}/pipeline_info/batch_chunk_plan.json").toFile())
            assert plan.size() > 0
            plan.each { sample, entry ->
                def reports = path("${outputDir}/kraken2/${sample}/batch_reports").list()
                    .findAll { it.name ==~ /^batch_\d+\.kraken2\.report\.txt$/ }
                assert reports.size() == entry.chunks : "${sample}: ${reports.size()} batch reports for ${entry.chunks} planned chunks"
            }
        }
    }

    test("Chunking off restores one classification per sample") {
        options "-stub"
        when {
            params {
                outdir = "${outputDir}"
                batch_chunking = false
            }
        }
        then {
            assert workflow.success
            assert !path("${outputDir}/pipeline_info/batch_chunk_plan.json").exists()
        }
    }
}
```

Run: `cd ~/Code/nanometanf && conda run -n nf-core nf-test test tests/batch_chunking_structure.nf.test --profile test,conda`
Expected: 2 passed. If the test profile's samplesheet gives every sample a
single file, the plan holds one chunk per sample and the assertion still
holds; the equivalence on real reads is Task 8 Step 1. Add the test to the
CI matrix the way `tests/lib/assembly_accumulator.nf.test` was
(`.github/workflows/nf-test.yml`, the fast-tag list).

- [ ] **Step 10: Documentation and commit**

`docs/output.md`: state that a batch run with `batch_chunking` (default)
publishes the real-time layout (`kraken2/<sample>/batch_reports/`,
`<sample>.cumulative.kraken2.report.txt`, `seqkit/<sample>/batch_stats/`)
and `pipeline_info/batch_chunk_plan.json`. `CHANGELOG.md` under
Unreleased: "Batch mode classifies each sample in growing chunks, the first
chunk of every sample first, so every barcode has a preliminary report after
one round; `--batch_chunking false` restores one classification per sample."

```bash
cd ~/Code/nanometanf
git add lib/BatchChunkPlanner.groovy workflows/nanometanf.nf subworkflows/local/taxonomic_classification/main.nf \
        conf/modules.config nextflow.config nextflow_schema.json docs/output.md CHANGELOG.md \
        tests/lib/batch_chunk_planner_functions.nf tests/lib/batch_chunk_planner.nf.test tests/batch_chunking_structure.nf.test .github/workflows/nf-test.yml
git commit -m "feat(batch): classify each sample in growing chunks, first chunk of every sample first

A samplesheet run classified each sample's whole file list in one task, in
samplesheet order, so a barcode showed nothing until every read of it was
classified and barcodes finished one after another. Each sample is now split
into geometrically growing chunks and the chunks are ordered across samples
by index; each chunk is a batch downstream, so the cumulative report advances
per chunk and every barcode has a preliminary report after one round.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

Run the nf-test CI subset before pushing: `conda run -n nf-core nf-test test --tag fast`.

---

## Task 5: nanometanf: classifier memory reservation under memory mapping

**Why.** With `--memory-mapping` the database pages live in the shared page
cache; each classifier task's own memory is the process plus read buffers
(Task 3 Step 4 measures the number). Reserving the database size per task
makes the local executor run one task at a time on an 18 GB machine and two on
32 GB, whatever `max_classification_forks` says. The reservation must stay
large where it is real: the preload task (which warms the cache), the retry
without memory mapping, and any database too large for the cache.

**Files:**
- Modify: `conf/modules.config` (`KRAKEN2_INCREMENTAL_CLASSIFIER`, `KRAKEN2_OPTIMIZED`, `KRAKEN2_KRAKEN2` memory closures), `nextflow.config`, `nextflow_schema.json`, `docs/usage.md` (resource section), `CHANGELOG.md`
- GUI side (Task 7 sends the value): `nanometa_live/core/config/parameter_mapping.py`

**Interfaces:**
- Produces param `kraken2_task_memory_gb` (integer or null; null = use `kraken2_memory_gb`, today's behaviour).
- Consumed by Task 7's `_resolve_kraken2_task_memory_gb`.

- [ ] **Step 1: Declare the parameter**

`nextflow.config` beside `kraken2_memory_gb`:

```groovy
    kraken2_task_memory_gb     = null        // Memory reserved per classifier task when memory mapping is on (null = kraken2_memory_gb). The database lives in the shared page cache, so a small reservation lets forks run in parallel; the preload and the no-mmap retry keep the full size.
```

`nextflow_schema.json`, beside `kraken2_memory_gb`:

```json
"kraken2_task_memory_gb": {
    "type": "integer",
    "minimum": 1,
    "description": "Memory reserved per classifier task when memory mapping is on. The database lives in the shared page cache, so a small value lets max_classification_forks tasks run at once; the database preload and the retry without memory mapping keep kraken2_memory_gb. Unset: kraken2_memory_gb."
}
```

- [ ] **Step 2: Change the three classifier memory closures**

In `conf/modules.config`, for `KRAKEN2_INCREMENTAL_CLASSIFIER`,
`KRAKEN2_OPTIMIZED` and `KRAKEN2_KRAKEN2`, replace
`memory = { (params.kraken2_memory_gb ?: 12).GB * task.attempt }` with:

```groovy
        // First attempt with memory mapping: the hash lives in the shared
        // page cache, so reserve only the task's own memory when the
        // operator sized it (kraken2_task_memory_gb). A retry runs without
        // memory mapping (see the exit-139 handling below) and needs the
        // whole database in private memory, so it keeps the full size.
        memory = {
            def full = (params.kraken2_memory_gb ?: 12) as int
            def task_gb = params.kraken2_task_memory_gb as Integer
            def mmap = (params.kraken2_memory_mapping == null) ? true : (params.kraken2_memory_mapping as boolean)
            (task.attempt == 1 && mmap && task_gb != null) ? task_gb.GB : full.GB * task.attempt
        }
```

Leave `KRAKEN2_DB_PRELOAD` at its full reservation.

- [ ] **Step 3: Render the config to confirm the closure resolves**

```bash
cd ~/Code/nanometanf
conda run -n nf-core nextflow config -profile conda --kraken2_task_memory_gb 4 | grep -A3 "KRAKEN2_INCREMENTAL_CLASSIFIER" | head
conda run -n nf-core nextflow run main.nf -profile test,conda -stub --outdir /tmp/ttfr/stub_mem --kraken2_task_memory_gb 4
```

Expected: the config renders and the stub run succeeds. Then check the stub
run's trace: `awk -F'\t' 'NR==1 || /KRAKEN2_INCREMENTAL/ {print $4, $13, $17}' /tmp/ttfr/stub_mem/pipeline_info/execution_trace_*.txt | head` shows the tasks.

- [ ] **Step 4: Document and commit**

`docs/usage.md`, in the resources section: two sentences saying what
`kraken2_task_memory_gb` is and that the GUI sizes it (Task 7); `CHANGELOG.md`
Unreleased: "A classifier task reserves `kraken2_task_memory_gb` on its first
attempt when memory mapping is on, so `max_classification_forks` tasks run in
parallel on a machine whose RAM would admit only one at the database size."

```bash
git add conf/modules.config nextflow.config nextflow_schema.json docs/usage.md CHANGELOG.md
git commit -m "feat(kraken2): reserve the task's own memory under memory mapping, not the database's

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 6: GUI: preliminary and complete barcodes are named

**Files:**
- Create: `nanometa_live/app/utils/batch_progress.py`
- Modify: `nanometa_live/app/callbacks/status.py` (the header line near line 211-225 that renders "Files processed"), `nanometa_live/app/callbacks/samples.py` (selector option labels, near the "produced no output" marker at line 276), `nanometa_live/app/tabs/dashboard_helpers.py` (`with_failure_clauses` or the subtitle builder the verdict banner uses; find with `grep -n 'def with_failure_clauses\|def _shallow_depth_clause' nanometa_live/app/tabs/dashboard_helpers.py`)
- Test: `tests/test_batch_progress.py`

**Interfaces:**
- Produces: `read_chunk_plan(results_dir: str) -> dict[str, int]` (sample -> planned chunks; `{}` when the file is absent), `batch_progress(results_dir: str) -> BatchProgress` with fields `planned` (dict), `done` (dict sample -> distinct batch ids seen under `kraken2/<sample>/batch_reports/`), `preliminary` (list of samples with 0 < done < planned), `complete` (list with done >= planned), `pending` (list with done == 0), and `summary_line() -> str | None` returning e.g. `"Preliminary: 12 of 24 barcodes; complete: 3 of 24"` or None when no plan exists (a real-time run, or an older pipeline).
- Consumes: `pipeline_info/batch_chunk_plan.json` from Task 4; batch report names `batch_<N>.kraken2.report.txt` and `<sample>_batch<N>.kraken2.report.txt` (both copies exist per batch; count distinct N).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_progress.py`:

```python
"""Batch-mode progress: which barcodes are preliminary and which complete.

A chunked batch run writes pipeline_info/batch_chunk_plan.json (planned chunks
per sample) and one per-batch report per finished chunk. The progress helper
reads both so the header, the sample selector and the verdict subtitle can say
"preliminary" while a barcode has more chunks to come.
"""

import json
from pathlib import Path

import pytest

from nanometa_live.app.utils.batch_progress import batch_progress, read_chunk_plan

pytestmark = pytest.mark.unit


def _tree(tmp_path, plan, reports):
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "batch_chunk_plan.json").write_text(json.dumps(
        {s: {"files": n * 3, "chunks": n} for s, n in plan.items()}))
    for sample, ids in reports.items():
        d = tmp_path / "kraken2" / sample / "batch_reports"
        d.mkdir(parents=True)
        for k in ids:
            (d / f"batch_{k}.kraken2.report.txt").write_text("100.00\t1\t1\tU\t0\tunclassified\n")
            (d / f"{sample}_batch{k}.kraken2.report.txt").write_text("100.00\t1\t1\tU\t0\tunclassified\n")
    return str(tmp_path)


def test_no_plan_means_no_progress(tmp_path):
    p = batch_progress(str(tmp_path))
    assert p.planned == {} and p.summary_line() is None


def test_read_chunk_plan(tmp_path):
    root = _tree(tmp_path, {"barcode01": 4, "barcode02": 1}, {})
    assert read_chunk_plan(root) == {"barcode01": 4, "barcode02": 1}


def test_states_and_summary(tmp_path):
    root = _tree(tmp_path, {"barcode01": 4, "barcode02": 1, "barcode03": 3},
                 {"barcode01": [0, 1], "barcode02": [0]})
    p = batch_progress(root)
    assert p.done == {"barcode01": 2, "barcode02": 1, "barcode03": 0}
    assert p.preliminary == ["barcode01"]
    assert p.complete == ["barcode02"]
    assert p.pending == ["barcode03"]
    assert p.summary_line() == "Preliminary: 2 of 3 barcodes; complete: 1 of 3"


def test_duplicate_copies_count_once(tmp_path):
    root = _tree(tmp_path, {"barcode01": 2}, {"barcode01": [0]})
    assert batch_progress(root).done["barcode01"] == 1


def test_malformed_plan_is_ignored(tmp_path):
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "batch_chunk_plan.json").write_text("{not json")
    assert read_chunk_plan(str(tmp_path)) == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_batch_progress.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the helper**

Create `nanometa_live/app/utils/batch_progress.py`:

```python
"""Batch-mode progress from the chunk plan and the per-batch reports.

nanometanf's chunked batch mode writes ``pipeline_info/batch_chunk_plan.json``
({sample: {files, chunks}}) before any task runs, and one per-batch report per
finished chunk under ``kraken2/<sample>/batch_reports/`` (two byte-identical
copies per batch: ``batch_N`` and ``<sample>_batchN``). Comparing the two says
which barcodes are preliminary (some chunks done), complete (all done) or
pending (none yet). A real-time run, or an older pipeline, writes no plan and
gets no progress line.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_BATCH_ID_RE = re.compile(r"(?:^|_)batch_?(\d+)\.kraken2\.report\.txt$")


def read_chunk_plan(results_dir: str) -> Dict[str, int]:
    """Planned chunk count per sample, or {} when there is no readable plan."""
    path = os.path.join(results_dir or "", "pipeline_info", "batch_chunk_plan.json")
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    plan: Dict[str, int] = {}
    for sample, entry in (raw or {}).items():
        try:
            plan[str(sample)] = int(entry["chunks"])
        except (KeyError, TypeError, ValueError):
            continue
    return plan


def _done_batches(results_dir: str, sample: str) -> int:
    directory = os.path.join(results_dir, "kraken2", sample, "batch_reports")
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    ids = set()
    for name in names:
        m = _BATCH_ID_RE.search(name)
        if m:
            ids.add(int(m.group(1)))
    return len(ids)


@dataclass
class BatchProgress:
    planned: Dict[str, int] = field(default_factory=dict)
    done: Dict[str, int] = field(default_factory=dict)

    @property
    def preliminary(self) -> List[str]:
        return sorted(s for s, n in self.planned.items() if 0 < self.done.get(s, 0) < n)

    @property
    def complete(self) -> List[str]:
        return sorted(s for s, n in self.planned.items() if self.done.get(s, 0) >= n)

    @property
    def pending(self) -> List[str]:
        return sorted(s for s in self.planned if self.done.get(s, 0) == 0)

    def summary_line(self) -> Optional[str]:
        if not self.planned:
            return None
        total = len(self.planned)
        with_result = len(self.preliminary) + len(self.complete)
        return f"Preliminary: {with_result} of {total} barcodes; complete: {len(self.complete)} of {total}"


def batch_progress(results_dir: str) -> BatchProgress:
    plan = read_chunk_plan(results_dir)
    done = {s: _done_batches(results_dir, s) for s in plan}
    return BatchProgress(planned=plan, done=done)
```

- [ ] **Step 4: Run the tests**

Run: `conda run -n nf-core python -m pytest tests/test_batch_progress.py -q`
Expected: 5 passed.

- [ ] **Step 5: Render it on three surfaces**

1. Header (`app/callbacks/status.py`, where "Files processed" is composed for
   batch mode near line 211-225): after that line, when
   `batch_progress(results_dir).summary_line()` is not None, append it as its
   own line. Resolve `results_dir` the way the surrounding code does (the
   `results-dir-path` Store or `resolve_outdir_for_fingerprint`; do not read
   `app-config` for it).
2. Sample selector (`app/callbacks/samples.py`): where option labels are
   built, suffix a preliminary sample's label with ` (preliminary, k of n)`
   using `p.done[s]` and `p.planned[s]`; leave complete and unplanned samples
   unchanged. The marker for "produced no output" stays as it is.
3. Verdict subtitle (`app/tabs/dashboard_helpers.py`): in the function that
   appends run-state clauses (`with_failure_clauses` or its caller), append
   `"preliminary: N of M barcodes still classifying"` while
   `p.preliminary or p.pending` is non-empty. It is a clause, not a state: a
   detection still renders ACTION REQUIRED.

Each surface reads the helper at most once per tick; the helper does one
`listdir` per planned sample and no parsing, so it fits the per-tick budget
(`tests/test_tick_call_counts.py` must still pass).

- [ ] **Step 6: Callback tests**

Append to `tests/test_batch_progress.py` one test per surface using
`tests/dash_test_utils.get_callback_fn` (see `tests/test_verdict_banner_callback.py`
for the pattern), each with a `_tree` results dir carrying one preliminary
and one complete sample, asserting the rendered text contains
`"Preliminary: 2 of 2 barcodes; complete: 1 of 2"` (header),
`"(preliminary, 2 of 4)"` (selector label) and
`"still classifying"` (verdict subtitle).

Run: `conda run -n nf-core python -m pytest tests/test_batch_progress.py tests/test_tick_call_counts.py tests/test_verdict_banner_callback.py -q`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add nanometa_live/app/utils/batch_progress.py nanometa_live/app/callbacks/status.py \
        nanometa_live/app/callbacks/samples.py nanometa_live/app/tabs/dashboard_helpers.py tests/test_batch_progress.py
git commit -m "feat(dashboard): name the barcodes whose result is preliminary

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 7: GUI: send the parameters, size the task memory, retire the advisory knob

**Files:**
- Modify: `nanometa_live/core/config/parameter_mapping.py` (the incremental block near line 1043-1062; the Kraken2 sizing near line 1303), `nanometa_live/core/config/config_loader.py` (`create_default_config`), `nanometa_live/core/workflow/pipeline_compat.py` (`NANOMETANF_MIN_VERSION`), `README.md` (compatibility table), `docs/configuration.md`, `docs/user-guide.md`, `CHANGELOG.md`
- Test: `tests/test_parameter_mapping_chunking.py`

**Interfaces:**
- Consumes Task 4's and Task 5's parameters.
- Produces config keys `batch_chunking` (True), `batch_first_chunk_files` (1), `batch_chunk_growth` (2.0); `_resolve_kraken2_task_memory_gb(config) -> Optional[int]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parameter_mapping_chunking.py`:

```python
"""The launch sends the chunking and task-memory parameters nanometanf reads.

Chunked batch mode needs the incremental classifier path, so the launch forces
kraken2_enable_incremental on when chunking is on in batch mode. The task
memory is the process's own memory under memory mapping; it is sent only when
the database fits the page cache with room to spare, because forks over a
database larger than RAM thrash the cache and the full reservation, which
serialises them, is the safer choice.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.config import parameter_mapping as pm

pytestmark = pytest.mark.unit


def _config(tmp_path, **over):
    db = tmp_path / "db"
    db.mkdir()
    (db / "hash.k2d").write_bytes(b"0" * 1024)
    base = {
        "nanopore_output_directory": str(tmp_path),
        "results_output_directory": str(tmp_path / "res"),
        "kraken_db": str(db),
        "processing_mode": "batch",
        "sample_handling": "single_sample",
        "kraken2_enable_incremental": False,
        "batch_chunking": True,
        "batch_first_chunk_files": 2,
        "batch_chunk_growth": 3.0,
    }
    base.update(over)
    (tmp_path / "res").mkdir(exist_ok=True)
    (tmp_path / "reads.fastq.gz").write_bytes(b"\x1f\x8b")
    return base


def test_chunking_params_are_sent_and_incremental_is_forced_on(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path))
    assert params["batch_chunking"] is True
    assert params["batch_first_chunk_files"] == 2
    assert params["batch_chunk_growth"] == 3.0
    assert params["kraken2_enable_incremental"] is True


def test_chunking_off_leaves_incremental_alone(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path, batch_chunking=False))
    assert params["batch_chunking"] is False
    # Batch mode sends no incremental switch today (the key is set in the
    # real-time branch only), so "left alone" means absent or False.
    assert params.get("kraken2_enable_incremental") in (None, False)


def test_chunking_is_not_sent_in_realtime_mode(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path, processing_mode="realtime"))
    assert "batch_chunking" not in params


class TestTaskMemory:
    def test_small_database_gets_the_floor(self, tmp_path):
        cfg = _config(tmp_path)
        with patch.object(pm, "_host_memory_bytes", return_value=18 * 1024 ** 3):
            assert pm._resolve_kraken2_task_memory_gb(cfg) == 4

    def test_large_database_gets_none(self, tmp_path):
        cfg = _config(tmp_path)
        (tmp_path / "db" / "hash.k2d").write_bytes(b"0" * (12 * 1024 ** 3 // 1024))  # sparse-ish stand-in
        with patch.object(pm, "_host_memory_bytes", return_value=16 * 1024 ** 3), \
             patch.object(pm, "_hash_bytes", return_value=12 * 1024 ** 3):
            assert pm._resolve_kraken2_task_memory_gb(cfg) is None

    def test_memory_mapping_off_gets_none(self, tmp_path):
        cfg = _config(tmp_path, kraken2_memory_mapping=False)
        assert pm._resolve_kraken2_task_memory_gb(cfg) is None

    def test_explicit_value_wins(self, tmp_path):
        cfg = _config(tmp_path, kraken2_task_memory_gb=6)
        assert pm._resolve_kraken2_task_memory_gb(cfg) == 6

    def test_sent_to_the_pipeline(self, tmp_path):
        with patch.object(pm, "_host_memory_bytes", return_value=18 * 1024 ** 3):
            params = pm.create_nextflow_params(_config(tmp_path))
        assert params["kraken2_task_memory_gb"] == 4
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_parameter_mapping_chunking.py -q`
Expected: FAIL (`KeyError: 'batch_chunking'`, `AttributeError: _resolve_kraken2_task_memory_gb`).

- [ ] **Step 3: Implement**

In `parameter_mapping.py`, inside `create_nextflow_params`, directly after
`params["kraken2_enable_incremental"] = config.get("kraken2_enable_incremental", True)`
(line 1043):

```python
    # Chunked batch mode: the first chunk of every sample is classified before
    # the second of any, so every barcode has a preliminary report after one
    # round. It runs on the incremental path, so that switch is forced on with
    # it. Real-time mode chunks per file already and ignores the parameter.
    if config.get("processing_mode", "batch") != "realtime":
        chunking = bool(config.get("batch_chunking", True))
        params["batch_chunking"] = chunking
        params["batch_first_chunk_files"] = max(1, int(config.get("batch_first_chunk_files") or 1))
        params["batch_chunk_growth"] = max(1.0, float(config.get("batch_chunk_growth") or 2.0))
        if chunking:
            params["kraken2_enable_incremental"] = True
```

Add beside `_resolve_kraken2_memory_gb`:

```python
def _host_memory_bytes() -> Optional[int]:
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:  # psutil is a hard dependency, but never let sizing crash a launch
        return None


def _hash_bytes(db_path: str) -> Optional[int]:
    try:
        return (Path(db_path) / "hash.k2d").stat().st_size
    except OSError:
        return None


KRAKEN2_TASK_MEMORY_FLOOR_GB = 4
_PAGE_CACHE_SHARE = 0.6


def _resolve_kraken2_task_memory_gb(config: Dict[str, Any]) -> Optional[int]:
    """Per-task reservation under memory mapping, or None to keep the full size.

    With memory mapping the database lives in the shared page cache and a
    classifier task's own memory is small, so reserving the database size per
    task makes the local executor run one task at a time on laptop RAM. The
    floor is sent only when the database fits comfortably in the cache
    (under _PAGE_CACHE_SHARE of RAM): forks over a database larger than that
    thrash the cache, and the full reservation, which serialises them, is the
    safer default. An explicit kraken2_task_memory_gb wins.
    """
    explicit = config.get("kraken2_task_memory_gb")
    if explicit:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            logging.warning("Ignoring non-numeric kraken2_task_memory_gb: %r", explicit)
    if not _resolve_kraken2_memory_mapping(config):
        return None
    hash_bytes = _hash_bytes(config.get("kraken_db") or "")
    host = _host_memory_bytes()
    if hash_bytes is None or not host:
        return None
    if hash_bytes > _PAGE_CACHE_SHARE * host:
        return None
    return KRAKEN2_TASK_MEMORY_FLOOR_GB
```

and where `kraken2_memory_gb` is placed into `params` (near line 1304):

```python
    task_memory_gb = _resolve_kraken2_task_memory_gb(config)
    if task_memory_gb is not None:
        params["kraken2_task_memory_gb"] = task_memory_gb
```

In `config_loader.py` `create_default_config`, beside `kraken2_enable_incremental`:

```python
        "batch_chunking": True,
        "batch_first_chunk_files": 1,
        "batch_chunk_growth": 2.0,
        "kraken2_task_memory_gb": None,
```

Remove `max_concurrent_batches` from `create_default_config` and from the
launch (`grep -n max_concurrent_batches nanometa_live/ -r`); if the
Configuration tab carries a widget for it, remove the widget from all three
field lists and the draft (CLAUDE.md, "Config form: save / load / dirty-state
symmetry"). It is advisory only in the pipeline and does nothing.

Bump `NANOMETANF_MIN_VERSION` in `core/workflow/pipeline_compat.py` to the
nanometanf version that carries Tasks 4 and 5 (the next minor, `1.11.0`;
confirm against `~/Code/nanometanf/nextflow.config` `manifest.version` after
its release) and add the README compatibility row `| 0.19.x | 1.11.0 | >= 26.04.0 |`
(`tests/test_compatibility_matrix.py` enforces it).

- [ ] **Step 4: Run the tests**

Run: `conda run -n nf-core python -m pytest tests/test_parameter_mapping_chunking.py tests/test_compatibility_matrix.py tests/test_pipeline_compat.py -q`
Expected: pass. Then the full suite once.

- [ ] **Step 5: Documentation**

`docs/configuration.md`: three entries (`batch_chunking`,
`batch_first_chunk_files`, `batch_chunk_growth`) and one for
`kraken2_task_memory_gb`, each two sentences, with the default. Remove
`max_concurrent_batches`.

`docs/user-guide.md`, in "Processing modes", under "Batch mode", add a short
subsection "What you see, and when": a batch run over existing reads shows
every barcode's preliminary result after the first round of chunks (one file
per barcode by default), the header counts preliminary and complete barcodes,
a preliminary barcode is marked in the selector, and the verdict subtitle says
so; the final result is the same as an unchunked run. Under "Real-time mode":
pre-existing files are interleaved across barcodes and classified per file.

`CHANGELOG.md` Unreleased: the three user-visible changes (chunked batch
mode, parallel classifier tasks, preliminary/complete progress), and
"Requires nanometanf v1.11.0".

- [ ] **Step 6: Commit**

```bash
git add nanometa_live/core/config/parameter_mapping.py nanometa_live/core/config/config_loader.py \
        nanometa_live/core/workflow/pipeline_compat.py README.md docs/configuration.md docs/user-guide.md \
        CHANGELOG.md tests/test_parameter_mapping_chunking.py
git commit -m "feat(launch): send chunked batch mode and the classifier task memory to the pipeline

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

## Task 8: Re-measure, record, and pin the invariants

- [ ] **Step 1: Re-run the harness against the repaired pipeline**

Same commands as Task 3 Steps 2 and 3 with `--out /tmp/ttfr/batch_after` and
`/tmp/ttfr/realtime_after`, using the nanometanf `dev` checkout that carries
Tasks 4 and 5 (`--pipeline ~/Code/nanometanf`). Then:

```bash
conda run -n nf-core python scripts/ttfr_analyse.py /tmp/ttfr/batch_after --json /tmp/ttfr/batch_after/summary.json
conda run -n nf-core python scripts/ttfr_analyse.py /tmp/ttfr/realtime_after --json /tmp/ttfr/realtime_after/summary.json
```

Acceptance criterion A: batch `all-first-report` under 180 s and `spread`
under 90 s. If not met, the numbers say which of the three levers fell short
(chunk order, task memory, or per-task overhead); record that and stop the
plan here with the finding rather than tuning blindly.

Acceptance criterion C: run the same backlog once more with chunking off and
compare the final reports:

```bash
conda run -n nf-core python scripts/ttfr_backlog.py run --input /tmp/ttfr/input \
  --mode batch --db ~/nanometa-demo/db/bioshield26.1_8G \
  --pipeline ~/Code/nanometanf --out /tmp/ttfr/batch_single \
  --overrides '{"batch_chunking": false}'
conda run -n nf-core python scripts/ttfr_analyse.py compare /tmp/ttfr/batch_after/results /tmp/ttfr/batch_single/results
```

Expected: `"equal": true` for all 12 samples (exit 0). A difference means a
read was counted twice or dropped at a chunk boundary; that is a defect in
Task 4, not a tolerance to widen.

- [ ] **Step 2: Verify criterion B in the browser**

Launch the GUI with the batch config the harness wrote
(`conda run -n nf-core python -m nanometa_live.app --config /tmp/ttfr/batch_after/config.yaml --port 8051`),
press Start, and within the first minute confirm with the Playwright MCP
browser (not a covered Chrome tab): the header line "Preliminary: N of 12
barcodes; complete: M of 12", a selector label with "(preliminary, k of n)",
and the verdict subtitle clause. Record a screenshot path in the audit
document.

- [ ] **Step 3: Update the audit document**

Add an "After" table beside the baseline in
`docs/audit/time-to-first-result-2026-09-06.md`, the hypothesis table's
"after" column, and the criterion A and B verdicts with the measured numbers.

- [ ] **Step 4: CLAUDE.md invariants**

Add under "### Processing Modes" (or a new "**Time to first result**"
paragraph near the real-time invariants):

```
**A backlog is classified first-chunk-first, across all barcodes.** In batch
mode nanometanf splits each sample into geometrically growing chunks
(`batch_first_chunk_files`, `batch_chunk_growth`) and orders the chunks by
index across samples (`lib/BatchChunkPlanner.groovy`), so every barcode has a
preliminary report after one round; each chunk is a batch downstream (per-batch
report, cumulative report, `meta.batch_id`), the same tree a real-time run
writes. `pipeline_info/batch_chunk_plan.json` is the contract the dashboard
reads (`app/utils/batch_progress.py`) to say which barcodes are preliminary.
The final cumulative report equals the unchunked result (verified read for
read with `scripts/ttfr_analyse.py compare` on the 2026-09-06 harness runs;
`tests/batch_chunking_structure.nf.test` pins the plan-file contract). A
classifier task reserves
`kraken2_task_memory_gb` (GUI-sized: 4 GB when the database is under 60% of
RAM and memory mapping is on) on its first attempt, so forks run in parallel
on laptop RAM; the preload and the no-mmap retry keep the full size. Measured
2026-09-06 on 12 barcodes x 20 files: <before> -> <after> seconds to every
barcode's first report. Do not reintroduce a per-sample `.collect()` before
the classifier, and do not send `max_concurrent_batches` (advisory only,
retired).
```

- [ ] **Step 5: Commit and hand over**

```bash
git add docs/audit/time-to-first-result-2026-09-06.md CLAUDE.md
git commit -m "docs(audit): time to first result after chunked batch mode and parallel classifier tasks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

Then: nanometanf `dev` to `master` by pull request (v1.11.0), nanometa_live
release 0.19.0 with the compatibility row, both cut together.

---

## Notes for the executor

- **Order.** Tasks 1-3 measure and must come first; Tasks 4-5 are in the
  nanometanf repository and can run in parallel with Task 6 (GUI, depends only
  on the plan-file contract); Task 7 depends on 4 and 5 (parameter names and
  the version floor); Task 8 last.
- **Where the batch-mode item comes from.** `ch_samplesheet` is built in
  `subworkflows/local/utils_nfcore_nanometanf_pipeline/main.nf:84-107` with a
  `groupTuple`; the planner consumes its output, one item per sample. Do not
  change the samplesheet schema or the GUI's one-row-per-file samplesheet.
- **Do not chunk real-time input.** It is already per file and interleaved;
  a later plan can group its backlog into growing chunks with the same
  planner (the `existing_list` in `realtime_monitoring/main.nf:189`), which
  would cut the per-file task overhead H4 measures. Record the H4 number so
  that plan can argue from it.
- **The retry path.** The classifier retries without memory mapping on exit
  139 (`conf/modules.config`, the KRAKEN2_KRAKEN2 block); Task 5 keeps the
  full reservation for `task.attempt > 1`. If Task 3 Step 4 shows exit 137
  (OOM) at 4 GB on the FIRST attempt, raise `KRAKEN2_TASK_MEMORY_FLOOR_GB`
  to the measured peak RSS plus 1 GB and say so in the audit document.
- **Sample ids.** The harness's directories are named `barcodeNN`, so
  `InputDetector.extractSampleId` and the GUI's `is_negative_control` treat
  them as ordinary barcodes.
- **`conda run` swallows a child's stdout**; the driver redirects nextflow's
  output to a file for that reason. Read `nextflow.stdout` and
  `results/.nextflow.log` when a run misbehaves.
