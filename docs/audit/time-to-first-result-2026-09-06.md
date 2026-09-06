# Time to first result: audit (2026-09-06)

**Question.** When many reads already exist at Start, how long until every
barcode shows a preliminary result, in batch and in real-time mode, and does
the pipeline analyse a whole sample before presenting anything?

**Setup.** MacBook (11 CPUs, 18 GB), Bioshield database 7.5 GB
(`bioshield26.1_8G`), 12 barcodes x 20 files x 500 reads built from the demo
corpus by `scripts/ttfr_backlog.py`, launched with the GUI's own parameter
builder (`create_nextflow_params` / `create_nextflow_config`), sampled every
2 s by `scripts/audit_realtime_timeline.py`, analysed by
`scripts/ttfr_analyse.py`. Runs and artifacts live under `/tmp/ttfr/`
(`batch_baseline`, `realtime_baseline`, `batch_mem4`); each run's Nextflow
work directory was deleted after analysis to keep the system volume above its
required free-space floor. nanometanf `5ea4db6` (dev), nanometa_live
`45fb557` (branch `time-to-first-result`, which includes the harness fix
below).

**Harness fix applied before these runs.** The first batch-baseline attempt
was launched with `--out` on an external exFAT volume and failed in under 8 s:
Nextflow's launch directory holds `.nextflow/cache/*/db`, a LevelDB store
opened with an OS file lock, and that open failed immediately with `Can't
open cache DB` on that filesystem (confirmed: a plain Python `flock()` there
succeeded, so the failure is specific to Nextflow/the JVM's own locking path).
`scripts/ttfr_backlog.py` now launches Nextflow from a system-temp directory
and keeps `-work-dir` at the run's own `--out` path; `.nextflow.log` is copied
back into `--out` for the record (commit `45fb557`). All three runs below were
executed after this fix and, on team direction, with `--out` moved off the
external volume entirely and onto the internal disk (`/tmp/ttfr/...`).

## Results at a glance

| Run | first report, first barcode (s) | all barcodes (s) | spread (s) | wall (s) | classifier tasks | max concurrency | median task (s) |
|---|---|---|---|---|---|---|---|
| batch baseline | 114.5 | 154.7 | 40.2 | 169.8 | 12 | 1 | 0.87 |
| realtime baseline | 148.6 | 413.6 | 265.0 | 2159.9 | 231 | 1 | 0.51 |
| batch, memory 4 GB probe | 113.8 | 159.8 | 46.0 | 191.8 | 12 | 2 | 6.4 |

Peak RSS is not recorded on macOS (the pipeline trace has no `/proc` to read
it from); every run's `peak_rss_gb` is `None`. The realtime run's classifier
task count (231) excludes 9 files that took the `EMIT_EMPTY_KRAKEN2_REPORT`
placeholder path instead (231 + 9 = 240, one per input file); no other run
produced that path. See H9 for what those 9 files were and why.

**Correction to "What the code does today."** The plan describes batch mode
reaching the classifier through a samplesheet and the incremental switch.
That is the real-time-mode path. For batch mode with `by_barcode` and
conventional folder names, `_resolve_batch_input_mode`
(`parameter_mapping.py`) instead auto-enables `--input_dir` with no
samplesheet and sends no `kraken2_enable_incremental` (the GUI only sends
that switch in the real-time branch). nanometanf's `INPUT_SCANNER` groups one
item per sample (`groupTuple(by: 0)`, `input_scanner/main.nf:79`), so the
batch baseline and the memory probe both ran the standard `KRAKEN2_KRAKEN2`
module once per barcode, not the incremental classifier. The trace for both
confirms this: `KRAKEN2_KRAKEN2 x 12`, no `KRAKEN2_INCREMENTAL_CLASSIFIER`
row. This is the audit's correction to the plan's evidence section, not a
defect — it is what the GUI does for this input shape today.

## Hypotheses

| Id | Verdict | Evidence |
|---|---|---|
| H1 | confirmed | `first_report_s == complete_s` for 12 of 12 samples in the batch baseline (barcode range 114.5-154.7 s) and 12 of 12 in the memory probe (113.8-159.8 s). A batch barcode's first visible report is already its final answer; there is no partial preview. |
| H2 | partially confirmed | Concurrency confirmed: classifier `max_concurrency = 1` in the batch baseline (18 GB machine, 12 GB reservation), matching `floor(18/12) = 1` regardless of `max_classification_forks`. Order refuted: completion order was barcode05, 08, 10, 06, 04, 07, 02, 03, 11, 12, 01, 09 — not samplesheet order (01..12). `groupTuple` emits the channel in first-seen order, but the parallel per-sample QC chain (CHOPPER/FASTQC/NANOPLOT, up to 11 concurrent) finishes samples in whatever order their QC lands, and the serialized classifier then reports each sample as soon as its own classify task completes, so completion order tracks QC scheduling, not the samplesheet. |
| H3 | refuted | Real-time first-report spread was 265.0 s (barcode05 at 148.6 s to barcode10 at 413.6 s), not "small." The cross-batch round-robin interleaves fairly on the intake side, but the single-lane classifier (`max_concurrency = 1`) and the per-file QC chain across 240 files mean a barcode near the end of the interleave order waits for many single-file tasks ahead of it before its own first file is classified. |
| H4 | confirmed | Real-time's actual data completion (last `complete_s` across barcodes) was 891.6 s, 5.8x the batch baseline's all-barcode completion of 154.7 s. Task counts confirm "many more tasks": 240 CHOPPER / 240 SEQKIT_STATS / 231 KRAKEN2_INCREMENTAL_CLASSIFIER (+9 empty-report placeholders) in real-time versus 12 of each in batch. The reported wall time (2159.9 s) is larger still, but that gap is explained separately below (H4 is about processing throughput, not the timeout wait). |
| H5 | confirmed (direction), not to the naive value | Lowering `kraken2_memory_gb` from 12 to 4 raised achieved concurrency from 1 to 2, confirming memory (not CPU) gates admission — but the naive prediction `floor(18/4) = 4` was not reached; 2 is the measured ceiling on this host, most likely because the concurrent per-sample QC chain (CHOPPER/FASTQC/NANOPLOT for all 12 barcodes) competes for the same CPU/memory pool the local executor is tracking. No task exited 137 or 139; all 12 classifier tasks in the probe completed with exit code 0. Per-task median wall time rose sharply alongside concurrency (0.87 s at 12 GB -> 6.4 s at 4 GB, a 7.4x increase), so overall wall time did not improve (169.8 s -> 191.8 s, slightly worse) even though more tasks ran at once — the two concurrent classifier tasks appear to contend with each other and with the QC chain rather than running for free. Peak RSS could not be measured (macOS trace has no `/proc`). |
| H6 | confirmed in batch mode, not reproduced in real-time | Batch: first classifier task 4.8 s versus a 0.87 s median (5.5x), a real page-in premium. Real-time: first classifier task 0.388 s versus a 0.51 s median (no premium — the first task was if anything faster). Both modes ran the same one-off `KRAKEN2_DB_PRELOAD` step (2.1-2.4 s) immediately before their first classify task, so the preload step is not what explains the difference. The most likely reading: batch's first classify task handles a full barcode (~10,000 reads) while real-time's handles one file (~500 reads), so any residual warm-up cost is proportionally larger, and more visible, in batch. |
| H7 | confirmed | barcode01's standard report (`barcode01.kraken2.report.txt` — batch mode produced no cumulative report, see the correction above) had mtime 150.09 s after `t0`; the sampler's first tick with `barcode01.total_reads > 0` was at 152.7 s. Gap: 2.62 s, well under the hypothesised 15 s ceiling. |
| H8 | refuted | barcode01 appeared in the sample list at 36.3 s after `t0`, well before its report existed (150.09 s / first-measured-reads 152.7 s). All 12 barcodes appeared in the list between 36.3 s and 100.5 s (under two minutes), each far ahead of its own report. The premise that a sample is "absent from the sample list until its first report exists" does not hold: the list populates as soon as `kraken2/<sample>/` appears on disk, and every barcode here was listed (as unmeasured) inside the first 101 s, not "a minute or more" of nothing. |
| H9 (new) | confirmed | A pre-existing file whose reads QC removes entirely is dropped silently in real-time mode: no classification, no lost-input marker, no line on any surface; 9 of 240 files (3.75%) in this run. `pipeline_info/processed_inputs.tsv` lists 231 of 240 files; the missing 9 are exactly the same 3 source-file indices (`..._0`, `..._2`, `..._13` of the demo corpus's `barcode07` directory) repeated across the 3 backlog barcodes built from that source by round-robin (`barcode03`, `barcode07`, `barcode11`). All three files' reads are shorter than the run's `chopper_minlength` (1000 bp: max read lengths measured at 442, 489 and 474 bp respectively, versus a normal file's max of 11,274 bp), so CHOPPER (which completed with exit 0 — this is not a task failure) filters every read, leaving nothing to classify. nanometanf's `EMIT_EMPTY_KRAKEN2_REPORT` path absorbs this (it ran exactly 9 times, matching), so classification is not literally skipped without record in the trace — but because CHOPPER did not fail, `bin/nanometanf_lost_input_marker.sh`'s `afterScript` never fires (it is failure-triggered only) and `pipeline_info/lost_inputs/` holds nothing for these 9 files. The GUI's own "files processed" counter (`NextflowManager._parse_realtime_stats`, `nextflow_manager.py:1290`) sums `GENERATE_SNAPSHOT_STATS` batch-file counts, and that process ran once per input file including the three empty ones — so the header would show **240** files processed while `processed_inputs.tsv` and the classifier both show **231**, with nothing in the GUI naming the gap or the reason for it. |

## What this means for the operator

A batch-mode barcode shows nothing at all until its whole read set has been
classified, and on this corpus most of the wait is not classification: the
first classifier task did not start until 107.0 s (`KRAKEN2_DB_PRELOAD`
completed at 105.9 s) of the run's 154.7 s to reach every barcode, so roughly
two-thirds of the visible delay is pipeline start-up plus the per-sample QC
chain, and the twelve `KRAKEN2_KRAKEN2` tasks themselves took 0.25-4.8 s each.
A real-time run over the same static backlog gives an early per-barcode
signal sooner in the best case (148.6 s) but a much later one in the worst
case (413.6 s, a 265 s spread) because 240 single-file tasks share one
serialized classifier lane, and the run's own reported completion (2159.9 s)
is set by the operator's configured real-time timeout plus its grace period,
not by when the numbers actually stopped moving (891.6 s) — a fact the
interface does not currently surface. For a backlog shaped like this one (a
few thousand reads per barcode, twelve barcodes), an operator wanting every
barcode to show *something* soonest is better served by batch mode today
(all twelve done, and each result already final, by 154.7 s) than by
real-time (all twelve showing a first partial result only by 413.6 s); the
one caveat is that batch's "something" is a finished answer with no earlier
preview, which is the gap Task 4 is meant to close for the barcodes and
corpus sizes where batch's whole-sample wait is much longer than it was here.

## Repairs argued from these numbers

- **Task 4 (chunked, round-robin batch mode).** H1 shows batch mode has no
  partial preview at all — a barcode's first visible result is its last. On
  this small corpus that cost only 154.7 s, but the mechanism (one
  `KRAKEN2_KRAKEN2` task per whole barcode) does not shrink with corpus size;
  a barcode with more reads blocks its own first look for proportionally
  longer. Geometric chunking gives every barcode a report after its first
  (small) chunk, independent of its total size.
- **Task 5 (classifier memory reservation under memory mapping).** H5 shows
  the current reservation serialises the classifier (concurrency 1 at 12 GB)
  and that even a probe reservation only reached concurrency 2, with a 7.4x
  per-task slowdown once two tasks shared the host — evidence that a single
  memory knob is currently doing two incompatible jobs (bounding the rare
  cold/retry cost and gating the common warm-cache cost). A separate
  task-level memory value lets the common case admit more concurrency without
  starving what is actually contended.
- **Task 6 (GUI: preliminary and complete barcodes are named).** H8 shows the
  sample list already renders a barcode 36.3-100.5 s before its report exists,
  and H3/H4 show a real-time run keeps updating for hundreds of seconds after
  its first partial signal. Nothing in the interface today distinguishes
  "listed, unmeasured", "measured, preliminary" (mid-chunk-plan, once Task 4
  lands) and "measured, complete" — an operator reading the current sample
  list cannot tell which state a given barcode is in, in either mode.
- **H9 (QC-emptied files dropped without a marker) is not scoped to any task
  in this plan** and is left for a later one. It is a correctness gap, not a
  latency one: an operator cannot currently learn, from any GUI surface or
  exported report, that a real-time run silently classified fewer files than
  it took in. A fix needs either a lost-input marker on the QC->empty path
  (today's marker only fires on task failure) or a header/report line
  comparing intake count against classified count, in the spirit of Task 6's
  naming work but for files, not barcodes.
