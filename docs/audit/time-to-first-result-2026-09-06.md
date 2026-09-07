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
(`batch_baseline`, `realtime_baseline`, `batch_mem4`, `batch_heavy_baseline`);
each run's Nextflow work directory was deleted after analysis to keep the
system volume above its required free-space floor. nanometanf `5ea4db6`
(dev), nanometa_live `a02c569` (the harness commit; the document's own commit
cannot cite itself) (branch `time-to-first-result`, which includes the
harness fix below and the `--concat` heavy-corpus builder used for the last
row of the results table).

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
| Heavy corpus (4000-read files, 80k reads per barcode) | 122.4 | 208.6 | 86.2 | 224.1 | 12 | 1 | 0.99 |

Peak RSS is not recorded on macOS (the pipeline trace has no `/proc` to read
it from); every run's `peak_rss_gb` is `None`. The realtime run's classifier
task count (231) excludes 9 files that took the `EMIT_EMPTY_KRAKEN2_REPORT`
placeholder path instead (231 + 9 = 240, one per input file); no other run
produced that path. See H9 for what those 9 files were and why.

**Heavy corpus.** The 500-read demo files used everywhere else in this audit
make per-task overhead (pipeline start-up, per-file scheduling) dominate the
measurements, which does not transfer to a real MinKNOW run (~4000 reads per
file). No heavier corpus exists on this machine, so one was synthesised:
`scripts/ttfr_backlog.py build --concat 8` (commit `a02c569`) makes each
target file a real concatenation of 8 consecutive demo files (a valid
multi-member gzip stream), giving 12 barcodes x 20 files x 4000 reads = 80,000
reads per barcode, built from the same 165-file demo corpus reused across
target barcodes (`/tmp/ttfr/input_heavy`, 852 MB). It was run in batch mode
only (`/tmp/ttfr/batch_heavy_baseline`), same database and pipeline as every
other run here.

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

## After: chunked batch mode and classifier task memory (2026-09-07)

**Setup.** Same machine (11 CPUs, 18 GB), same database (`bioshield26.1_8G`),
same two corpora as the baseline (`/tmp/ttfr/input`, 12x20x500 reads;
`/tmp/ttfr/input_heavy`, 12x20x4000 reads, rebuilt fresh with
`ttfr_backlog.py build --concat 8` for this session — the baseline's own
`/tmp/ttfr` artifacts had been cleared from the system temp volume between
sessions and were not present to compare against directly, only their
recorded summaries). nanometanf `83b2c88` (`1.11.0dev`, Tasks 4 and 5:
first-chunk-first batch chunking and per-task classifier memory reservation),
nanometa_live `9eccff2` (branch `time-to-first-result`, Task 7: the launch
sends `batch_chunking`, `batch_first_chunk_files`, `batch_chunk_growth` and
`kraken2_task_memory_gb`). Every run's `params.json` was checked before
analysis and carried the expected values (`batch_chunking: true`,
`batch_first_chunk_files: 1`, `batch_chunk_growth: 2.0`,
`kraken2_task_memory_gb: 4`; `false`/`null` for the chunking keys in the
single-task control). Each run's `work/` directory was deleted immediately
after analysis.

**Measurement trap, recorded rather than worked around.** The first
light-corpus attempt hung for over 20 minutes on one `NANOPLOT` task: NanoPlot
1.46.1's `kaleido` 1.3.0 backend opens a real headless Chromium tab per
static-image plot (`choreographer`), and one tab reload never returned,
parking the task's 4 reserved CPUs indefinitely. This is an environment/tool
flake — unrelated to Tasks 4/5/7 — but on an 11-CPU host it starves everything
else, so it was killed and Nextflow's normal retry re-ran the task in 15 s. All
runs below except that first discarded attempt completed with either
`failed=0` or (batch_after's first clean run) a single killed-and-retried
NanoPlot task recorded honestly; a small watchdog script killed any NanoPlot
task whose CPU time stalled for >45 s past a 90 s grace period, so no run sat
on this flake for more than about a minute. A second, unrelated trap: the
GUI's own readiness check enforces a 5 GB free-space floor on the output
volume, and this machine's boot volume sits at 99-100% full independent of
this audit; `conda clean --tarballs --packages --index-cache` (removes only
redownloadable package tarballs and index cache, never installed envs)
recovered enough headroom to pass it.

### After results table

| Run | first report, first barcode (s) | all barcodes (s) | spread (s) | wall (s) | classifier tasks | max concurrency | median task (s) |
|---|---|---|---|---|---|---|---|
| batch, light corpus (chunked) | 400.2 | 440.4 | 40.2 | 516.7 | 57 | 2 | 0.36 |
| batch, heavy corpus (chunked) | 54.3 | 461.7 | 407.4 | 688.7 | 60 | 2 | 3.95 |
| realtime, light corpus | 80.4 | 158.7 | 78.3 | 860.3 (ended by operator SIGINT) | 231 | 2 | 0.41 |
| batch, heavy corpus, single-task control (`batch_chunking: false`) | 104.5 | 172.7 | 68.2 | 208.9 | 12 | 2 | 4.1 |

The realtime run was ended deliberately, not by its configured 20-minute
timeout: `pkill -INT` was sent once every sample's `total_reads` had been
unchanged for 120 s and the trace showed no in-flight classifier task (reached
at 796 s of wall time on the monitoring clock, process exit shortly after at
860.3 s); Nextflow logged `Pipeline completed with errors` and
`[cumulative-state] end of session: released in-memory state for 12 sample(s)`
— the expected shape of an external interrupt, with nanometanf's own session
cleanup still running to completion. `NANOPLOT` task counts confirm chunking
multiplies per-chunk QC roughly fivefold versus the single-task control (57
and 60 versus 12), at an unchanged per-invocation median (13.6-16.6 s across
every run in this table, matching the baseline's 15.9 s) — the mechanism
explained below.

### Criterion A — NOT MET (heavy corpus)

All-first-report 461.7 s (target <180 s) and spread 407.4 s (target <90 s) on
the heavy corpus; the light corpus, reported for reference only (no target
set), was 440.4 s / 40.2 s. Two of the three levers worked exactly as
designed and are not the cause:

- **Chunk order** is doing its job at the per-barcode level: on the heavy
  corpus, `barcode07`'s first (smallest) chunk was classified and visible at
  54.3 s — close to the baseline's whole-sample first-classify time of
  106.8 s and far under the 180 s target, proof that a barcode whose chunk
  reaches the front of the queue gets an early result. The problem is that
  which barcode gets there early is now down to scheduling luck, not
  guaranteed order (see below).
- **Task memory** produced exactly the concurrency Task 5's own math
  predicts: `kraken2_task_memory_gb: 4` lifts the memory ceiling, and the
  classifier's CPU request (`max(4, max_cpus / max_classification_forks)` = 4
  cpus/task) caps concurrency at `floor(11/4) = 2` on this host — measured at
  exactly 2 in every one of the four runs above, batch and realtime alike,
  confirming H5's mechanism holds under chunking and in real time too.

**The failing lever is per-task overhead, and it is `NANOPLOT`, not the
classifier.** Chunking's QC\_ANALYSIS subworkflow now runs once per CHUNK
rather than once per whole sample, so `NANOPLOT` invocations rose from 12
(one per barcode) to 57-60 (one per chunk) while each invocation's own cost
stayed flat at its baseline ~14-16 s (matplotlib/report-generation overhead
that does not shrink with a smaller chunk). Each `NANOPLOT` task reserves 4
CPUs (`conf/modules.config:466-471`), so on an 11-CPU host roughly 57-60 tasks
at ~15 s apiece, admitted 2 at a time, cost on the order of 60 x 15 / 2 ≈
450 s of serialized QC scheduling — matching the observed 440-460 s
all-first-report almost exactly. Because Nextflow's local executor schedules
ready tasks against the same CPU pool regardless of process name, a barcode's
tiny first-chunk classify task (cpus 4, ~0.3-4 s) queues behind whichever
`NANOPLOT` tasks got there first, so most barcodes wait out most of the QC
backlog before their own first (and cheapest) classification runs at all —
which is also why the heavy corpus's spread (407.4 s) is so much larger than
the light corpus's (40.2 s): heavy `CHOPPER` inputs take longer per chunk
(median rising with input size, as in the baseline), stretching the queue a
barcode's early chunk can land behind. Chunking's promise — every barcode
gets a cheap early look — is real (barcode07 proves it) but is being
undermined by an unrelated subworkflow it was never designed to interact
with. This is not a case for tuning `kraken2_task_memory_gb` or the chunk
schedule further; it names a fourth lever the plan did not anticipate:
**QC\_ANALYSIS should run once per sample on the final accumulated reads, not
once per chunk**, mirroring how batch mode's `CANONICAL_QC_WRITER` already
treats the non-incremental path, or `NANOPLOT` specifically should be moved
off the per-chunk critical path. Recorded as a finding, not tuned around, per
the plan's own instruction.

### Criterion B — MET

Confirmed live: `conda run -n nf-core python -m nanometa_live.app --config
/tmp/ttfr/batch_heavy_after/config.yaml --port 8051` (the input directory was
repointed to the light corpus via the Configuration tab after the heavy
corpus was deleted to stay under the disk floor; the code path exercised —
`batch_chunking: true` batch mode — is identical), driven with the Playwright
MCP browser. Within the run's first ~6.5 minutes (light-corpus timing, matching
the after-table row above) all three surfaces appeared together:

- Header: `Files processed: 0 / 240, Preliminary: 7 of 12 barcodes; complete:
  0 of 12, Last update: 06:38:54`
- Sample selector badge: `barcode03 ... preliminary 1 of 5` (tooltip: "More
  chunks of this barcode are still classifying; the counts will grow.")
- Verdict subtitle: `MONITORING` — "Moderate-risk species found --
  preliminary: 12 of 12 barcodes still classifying"

Screenshot: [`docs/audit/img/time-to-first-result-2026-09-06-progress.png`](img/time-to-first-result-2026-09-06-progress.png).
The app and pipeline were stopped afterward via the GUI's Stop Analysis
control followed by `pkill -f nanometa_live.app`.

### Criterion C — MET

`ttfr_analyse.py compare` between the heavy chunked run's cumulative reports
and the heavy single-task control's standard reports: `"equal": true`, exit
0, all 12 barcodes, 1509 taxa each, zero differences. Chunked and unchunked
batch mode produce byte-identical final classification for every sample.

## Hypotheses

| Id | Verdict | Evidence | After (2026-09-07) |
|---|---|---|---|
| H1 | confirmed | `first_report_s == complete_s` for 12 of 12 samples in the batch baseline (barcode range 114.5-154.7 s) and 12 of 12 in the memory probe (113.8-159.8 s). A batch barcode's first visible report is already its final answer; there is no partial preview. | No longer applies as stated: chunked batch mode now gives a genuine partial preview (Task 4's goal). The single-task control still shows `first_report_s == complete_s` for all 12 samples (172.7 s max), confirming H1 describes unchunked batch mode correctly. |
| H2 | partially confirmed | Concurrency confirmed: classifier `max_concurrency = 1` in the batch baseline (18 GB machine, 12 GB reservation), matching `floor(18/12) = 1` regardless of `max_classification_forks`. Order refuted: completion order was barcode05, 08, 10, 06, 04, 07, 02, 03, 11, 12, 01, 09 — not samplesheet order (01..12). `groupTuple` emits the channel in first-seen order, but the parallel per-sample QC chain (CHOPPER/FASTQC/NANOPLOT, up to 11 concurrent) finishes samples in whatever order their QC lands, and the serialized classifier then reports each sample as soon as its own classify task completes, so completion order tracks QC scheduling, not the samplesheet. | Concurrency raised to 2 in every after-run (batch and realtime alike), matching Task 5's design (`floor(11/4)` CPU cap, not memory). Order remains QC-scheduling-determined, and chunking makes this worse, not better: heavy corpus first-report order was barcode07, 09, 03/04, 10, 06, 08, 02/05, 12, 01, 11 — still not samplesheet order, now with a 407 s spread instead of the baseline's order-only effect. |
| H3 | refuted | Real-time first-report spread was 265.0 s (barcode05 at 148.6 s to barcode10 at 413.6 s), not "small." The cross-batch round-robin interleaves fairly on the intake side, but the single-lane classifier (`max_concurrency = 1`) and the per-file QC chain across 240 files mean a barcode near the end of the interleave order waits for many single-file tasks ahead of it before its own first file is classified. | Spread nearly halved (265.0 s -> 78.3 s) once concurrency doubled to 2; still not small, but the mechanism (single-lane classifier queueing) is directly confirmed by concurrency's effect on it. |
| H4 | confirmed | Real-time's actual data completion (last `complete_s` across barcodes) was 891.6 s, 5.8x the batch baseline's all-barcode completion of 154.7 s. Task counts confirm "many more tasks": 240 CHOPPER / 240 SEQKIT_STATS / 231 KRAKEN2_INCREMENTAL_CLASSIFIER (+9 empty-report placeholders) in real-time versus 12 of each in batch. The reported wall time (2159.9 s) is larger still, but that gap is explained separately below (H4 is about processing throughput, not the timeout wait). | Still confirmed, and now the shoe is on the other foot: chunked batch mode's own task counts (57-60 NANOPLOT invocations) have grown to where its all-first-report time (440-462 s) is comparable to real time's per-file overhead effect, for a different reason (QC proliferation rather than per-file classification). |
| H5 | confirmed, with a second limiter the hypothesis did not name | Lowering `kraken2_memory_gb` from 12 to 4 raised achieved concurrency from 1 to 2. At 12 GB the memory reservation alone explains it: `floor(18/12) = 1`. At 4 GB memory would admit `floor(18/4) = 4`, but the classifier's CPU request caps it first: `conf/modules.config:218` (and `:316` for the incremental module) sets `cpus = max(4, max_cpus / max_classification_forks)`, which with this run's defaults (`max_cpus` 16, `max_classification_forks` 4) is 4 CPUs per classifier task; on this 11-CPU host that admits `floor(11/4) = 2`. The trace confirms exactly two classifier tasks overlap and never three: `barcode01` 18:52:34.393-36.871 alongside `barcode05` 18:52:34.288-36.976 in the probe's trace, no third task inside that window or any other. So the observed concurrency of 2 is the CPU cap taking over once memory no longer binds, not contention with the QC chain (which was this document's earlier, wrong attribution). No task exited 137 or 139; all 12 classifier tasks in the probe completed with exit code 0. Per-task median wall time still rose alongside concurrency (0.87 s at 12 GB -> 6.4 s at 4 GB), so overall wall time did not improve (169.8 s -> 191.8 s, slightly worse) even with more tasks admitted — some contention is real, it is just not what set the concurrency ceiling. Peak RSS could not be measured (macOS trace has no `/proc`). | Fully reproduced with Task 5's shipped `kraken2_task_memory_gb: 4`: concurrency 2 in all four after-runs, never 3. The CPU-cap mechanism (not memory) is now the production behaviour, not just a probe. |
| H6 | confirmed in batch mode, not reproduced in real-time | Batch: first classifier task 4.8 s versus a 0.87 s median (5.5x), a real page-in premium. Real-time: first classifier task 0.388 s versus a 0.51 s median (no premium — the first task was if anything faster). Both modes ran the same one-off `KRAKEN2_DB_PRELOAD` step (2.1-2.4 s) immediately before their first classify task, so the preload step is not what explains the difference. The most likely reading: batch's first classify task handles a full barcode (~10,000 reads) while real-time's handles one file (~500 reads), so any residual warm-up cost is proportionally larger, and more visible, in batch. | Not re-tested directly; chunked batch mode's first chunk is now file-sized rather than barcode-sized, so the mechanism this hypothesis names (whole-barcode-sized first task) no longer applies to chunked batch mode as configured. |
| H7 | confirmed | barcode01's standard report (`barcode01.kraken2.report.txt` — batch mode produced no cumulative report, see the correction above) had mtime 150.093 s after `t0`; the sampler's first tick with `barcode01.total_reads > 0` was at 152.7 s. Gap: 2.61 s, well under the hypothesised 15 s ceiling. | Not re-measured; unaffected by Tasks 4/5/7 (a sampler-poll-to-mtime gap, not a pipeline-scheduling question). |
| H8 | refuted | barcode01 appeared in the sample list at 36.3 s after `t0`, well before its report existed (150.09 s / first-measured-reads 152.7 s). All 12 barcodes appeared in the list between 36.3 s and 100.5 s (under two minutes), each far ahead of its own report. The premise that a sample is "absent from the sample list until its first report exists" does not hold: the list populates as soon as `kraken2/<sample>/` appears on disk, and every barcode here was listed (as unmeasured) inside the first 101 s, not "a minute or more" of nothing. | Not re-measured directly; Task 6's own preliminary/complete badges (confirmed live under Criterion B) extend this by naming the state explicitly rather than leaving a barcode listed-but-silent. |
| H9 (new) | confirmed | A pre-existing file whose reads QC removes entirely is dropped silently in real-time mode: no classification, no lost-input marker, no line on any surface; 9 of 240 files (3.75%) in this run. `pipeline_info/processed_inputs.tsv` lists 231 of 240 files; the missing 9 are exactly the same 3 source-file indices (`..._0`, `..._2`, `..._13` of the demo corpus's `barcode07` directory) repeated across the 3 backlog barcodes built from that source by round-robin (`barcode03`, `barcode07`, `barcode11`). All three files' reads are shorter than the run's `chopper_minlength` (1000 bp: max read lengths measured at 442, 489 and 474 bp respectively, versus a normal file's max of 11,274 bp), so CHOPPER (which completed with exit 0 — this is not a task failure) filters every read, leaving nothing to classify. nanometanf's `EMIT_EMPTY_KRAKEN2_REPORT` path absorbs this (it ran exactly 9 times, matching), so classification is not literally skipped without record in the trace — but because CHOPPER did not fail, `bin/nanometanf_lost_input_marker.sh`'s `afterScript` never fires (it is failure-triggered only) and `pipeline_info/lost_inputs/` holds nothing for these 9 files. The GUI's own "files processed" counter (`NextflowManager._parse_realtime_stats`, `nextflow_manager.py:1290`) sums `GENERATE_SNAPSHOT_STATS` batch-file counts, and that process ran once per input file including the three empty ones — so the header would show **240** files processed while `processed_inputs.tsv` and the classifier both show **231**, with nothing in the GUI naming the gap or the reason for it. | Not re-scoped by Tasks 4/5/7 (out of scope per the baseline's own "Repairs argued from these numbers"); still open, see below. |

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

**At MinKNOW-sized files, QC dominates even more, classification barely
moves.** Per-process medians, 500-read files versus the 4000-read heavy
corpus (both batch mode, same 12 barcodes): `CHOPPER` 1.0 s -> 6.4 s (6.4x for
8x the reads — sublinear, but a real, large increase); `FASTQC` 2.5 s ->
3.5 s (1.4x); `KRAKEN2_KRAKEN2` 0.87 s -> 0.99 s (1.14x — classification was
already fast and stayed fast); `NANOPLOT` 15.9 s -> 15.9 s, unchanged to the
first decimal in both runs. That last figure is worth flagging rather than
explaining away: at these two corpus sizes NANOPLOT's cost tracked neither
read count nor file size, which suggests it is dominated by fixed
report-generation overhead in this range — untested above 80,000 reads per
barcode, so it may not stay flat at MinKNOW scale. The practical shift: on
the 500-read corpus, classification (0.87 s) was negligible beside the QC
chain; on the 4000-read corpus it is still negligible (0.99 s) beside a QC
chain that itself grew 3-6x. Classification was never the bottleneck in this
audit; it is even less of one as file size grows. Consistent with this,
batch mode's first classifier task started at essentially the same absolute
time in both runs (107.0 s light, 106.8 s heavy) — the extra per-barcode QC
cost delayed each barcode's OWN completion (spread grew from 40.2 s to
86.2 s) more than it delayed the pipeline's first classify slot opening.

**Projection for a 24-barcode, 200,000-reads-per-barcode MinKNOW backlog**
(2x the barcodes, 2.5x the reads per barcode versus the heavy corpus tested
here; not measured, extrapolated): pipeline start-up plus DB preload looks
corpus-size-independent in both baselines (~103-107 s to the first classify
task in every batch run so far), so that portion should hold. Per-barcode QC
cost scaling from the two measured points gives `CHOPPER` roughly 14-16 s
(sublinear extrapolation) and `FASTQC` roughly 4 s; `NANOPLOT` is assumed
flat at ~16 s per the caveat above, and `KRAKEN2_KRAKEN2` stays under 2 s.
Summed, one barcode's own QC-to-classify chain is roughly 35-40 s. With 24
barcodes sharing this machine's 11 CPUs (versus 12 barcodes here), each
barcode queues behind roughly one extra "wave" of other barcodes' QC tasks,
which is where the audit's own spread numbers (40.2 s at 12 barcodes/10k
reads, 86.2 s at 12 barcodes/80k reads) suggest most of the growth would
come from doubling barcode count on the same core count. Order-of-magnitude
estimate: **all 24 barcodes' first (and, in today's unchunked batch mode,
only) report within roughly 4-7 minutes (250-420 s) of Start**, dominated by
QC queueing rather than classification, with classifier concurrency staying
at 1 throughout (H5) regardless of corpus size. This is a projection, not a
measurement; the two biggest sources of error are NANOPLOT's untested
scaling above 80,000 reads and queueing behaviour at 24 barcodes, which
was not run.

## Repairs argued from these numbers

- **Task 4 (chunked, round-robin batch mode).** H1 shows batch mode has no
  partial preview at all — a barcode's first visible result is its last. On
  this small corpus that cost only 154.7 s, but the mechanism (one
  `KRAKEN2_KRAKEN2` task per whole barcode) does not shrink with corpus size;
  a barcode with more reads blocks its own first look for proportionally
  longer. Geometric chunking gives every barcode a report after its first
  (small) chunk, independent of its total size.
- **Task 5 (classifier memory reservation under memory mapping).** H5 shows
  the memory reservation is what serialises the classifier on this laptop
  today (concurrency 1 at 12 GB, `floor(18/12)`); a single memory knob is
  currently doing two incompatible jobs (bounding the rare cold/retry cost and
  gating the common warm-cache cost). But H5 also shows that fixing the
  memory knob alone will not give this host full concurrency: once memory no
  longer binds, the classifier's own CPU request (`max(4, max_cpus /
  max_classification_forks)` = 4 CPUs per task by design) caps concurrency at
  `floor(11/4) = 2` here, which the 4 GB probe already demonstrates
  (exactly two tasks overlap, never three). A separate task-level memory
  value removes the memory ceiling; the CPU request then decides, and on a
  16-CPU field machine that projects to `floor(16/4) = 4` (a projection, not
  measured here).
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

## Still open (2026-09-07)

- **H9** (QC-emptied files dropped silently in real-time mode) remains
  unaddressed; not scoped to Tasks 4/5/6/7.
- **Stale `batch_N` files.** A repartitioned second batch run (e.g. Continue
  into a populated outdir with a different chunk plan) can leave earlier
  `batch_N`-numbered files behind that no longer correspond to the current
  plan; nothing in the chunking or continue path was observed to clean these
  up. Not exercised directly in this round — flagged from reading the
  chunking mechanism against the existing Continue-in-realtime invariant
  (`docs/audit/realtime-round4-2026-09-02.md`) — and worth a dedicated drill.
- **The classifier's four-thread floor decides concurrency on small hosts.**
  `max(4, max_cpus / max_classification_forks)` puts a hard floor of 4 CPUs
  per classifier task regardless of how small the machine is; on this 11-CPU
  laptop that caps concurrency at 2 no matter how low
  `kraken2_task_memory_gb` goes (confirmed again this round: 2 in all four
  after-runs). A field laptop with 8 CPUs would see concurrency 2 collapse to
  a de facto ceiling of `floor(8/4) = 2` still, and a 4-CPU field unit would
  see exactly 1 — the memory fix Task 5 shipped cannot rescue a host this
  small, and the floor itself becomes the binding constraint there.
- **Per-file task overhead in real time is unchanged and still costly.** Real
  time's 231-240 single-file classifier/QC tasks are the same shape measured
  in the baseline; this round's concurrency improvement (1 -> 2) helped
  (spread 265.0 s -> 78.3 s) but did not touch the per-file overhead itself.
  A later plan may apply Task 4's chunk planner to real time's start-up
  backlog (grouping the existing pre-Start files into growing chunks the same
  way, per the original plan's own note), which this round's numbers argue
  for concretely: real time's remaining 78.3 s spread and 158.7 s
  all-first-report, on the identical light corpus that chunked batch mode
  took 440.4 s to clear, show real time's per-file granularity is still
  cheaper in aggregate than chunked batch's current per-chunk QC overhead —
  a fix to the QC\_ANALYSIS-per-chunk problem above would very likely invert
  that comparison again.
- **`NANOPLOT` running once per chunk (new this round).** Not one of the
  original four "still open" items, but the clearest actionable finding from
  this measurement: chunking must not re-run whole-sample QC visualisation
  once per chunk. Recorded above under Criterion A; repeated here because it
  is the direct explanation for Criterion A's miss and the most concrete lead
  for the next round.
