# Manual GUI scenario verification: Nextflow 26 + `server` profile

End-to-end runbook for the three sample-handling modes that the
`server` profile in `nanometanf` must support. Use this to verify that
a code change has not regressed real-time behaviour on the operator
laptop before promoting it to the production server.

## 0. Prerequisites

| Component | Location | Conda env |
|-----------|----------|-----------|
| Nanometa Live (GUI) | `/Users/andreassjodin/Code/nanometa_live` | `nf-core` |
| nanometanf (pipeline) | `/Users/andreassjodin/Code/nanometanf` | `nf-core` |
| nanorunner (FASTQ replay) | `/Users/andreassjodin/Code/nanorunner` | `nanorunner` |
| Kraken2 DB | `/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015/` | n/a |
| Source FASTQ files | `/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/rawdata-original/` | n/a |
| Working directory | `/Users/andreassjodin/Desktop/snabbsekvensering/output-live/` | n/a |

All three scenarios reuse the same working directory under
`output-live/`; each scenario writes to its own subdirectory so
artefacts do not collide.

Make sure both repos are at `dev` HEAD:

```bash
cd /Users/andreassjodin/Code/nanometa_live && git status -sb
cd /Users/andreassjodin/Code/nanometanf      && git status -sb
```

You should see `## dev...origin/dev` on each. If not, `git checkout dev && git pull`.

## 1. Stage input directories (one-time)

The three scenarios need three different on-disk layouts. Stage them
once; nanorunner reads from these as its `--source`.

```bash
SRC=/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/rawdata-original
STAGE=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_stage

# Wipe any previous staging
rm -rf "$STAGE" && mkdir -p "$STAGE"

# Scenario A -- multiplex by_barcode: place each FASTQ in its own
# barcodeNN/ subdirectory so nanometanf's sample-detector reads them
# as separate barcoded samples.
mkdir -p "$STAGE/A_multiplex"
i=1
for f in "$SRC"/*.fastq.gz; do
    bc=$(printf "barcode%02d" "$i")
    mkdir -p "$STAGE/A_multiplex/$bc"
    ln -sfn "$f" "$STAGE/A_multiplex/$bc/$(basename "$f")"
    i=$((i + 1))
    [ "$i" -gt 5 ] && break    # cap at 5 barcodes
done

# Scenario B -- flat single_sample: all files in one flat dir; the
# pipeline treats every file as belonging to one sample.
mkdir -p "$STAGE/B_single"
for f in "$SRC"/*.fastq.gz; do
    ln -sfn "$f" "$STAGE/B_single/$(basename "$f")"
done

# Scenario C -- flat per_file: same shape as B; the *config* selects
# per_file handling so each file becomes its own sample. Symlink the
# same source so we do not duplicate disk space.
mkdir -p "$STAGE/C_per_file"
for f in "$SRC"/*.fastq.gz; do
    ln -sfn "$f" "$STAGE/C_per_file/$(basename "$f")"
done

echo "--- stage layout ---"
find "$STAGE" -maxdepth 3 -type l | head -20
```

After this step `$STAGE/A_multiplex/` has 5 barcode subdirectories,
each holding one FASTQ symlink; the other two stages are flat.

## 2. Watch directory (per-scenario) and configs

The pipeline does not read directly from the staging directory; it
watches the directory `nanorunner` *writes to*. Each scenario uses
its own watch directory so the runs do not collide.

```bash
BASE=/Users/andreassjodin/Desktop/snabbsekvensering/output-live

rm -rf "$BASE/watch_A" "$BASE/watch_B" "$BASE/watch_C"
mkdir -p "$BASE/watch_A" "$BASE/watch_B" "$BASE/watch_C"
mkdir -p "$BASE/run_A"   "$BASE/run_B"   "$BASE/run_C"
```

Write three Nanometa Live configs. Save each as
`output-live/scenario_A.yaml` etc. The only differences between them
are `nanopore_output_directory`, `results_output_directory`,
`main_dir`, `sample_handling`, and `analysis_name`.

`output-live/scenario_A.yaml` (multiplex):

```yaml
nanopore_output_directory: "/Users/andreassjodin/Desktop/snabbsekvensering/output-live/watch_A"
results_output_directory:  "/Users/andreassjodin/Desktop/snabbsekvensering/output-live/run_A"
main_dir:                  "/Users/andreassjodin/Desktop/snabbsekvensering/output-live/run_A"
kraken_db:                 "/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015"
processing_mode:    "realtime"
sample_handling:    "by_barcode"
analysis_name:      "Scenario_A_multiplex"
pipeline_profile:   "conda"
pipeline_source:    "/Users/andreassjodin/Code/nanometanf"
pipeline_profiles_extra:
  - "server"
nextflow_extra_args: "--max_cpus 8 --max_memory 32.GB --max_classification_forks=2"
blast_validation: false
update_interval_seconds: 10
realtime_timeout_minutes: 10
batch_size: 2
report_write_interval: 1
max_files: 60
```

`output-live/scenario_B.yaml` (flat single_sample): copy of A with

```yaml
nanopore_output_directory: ".../watch_B"
results_output_directory:  ".../run_B"
main_dir:                  ".../run_B"
sample_handling:    "single_sample"
analysis_name:      "Scenario_B_single_sample"
```

`output-live/scenario_C.yaml` (flat per_file): copy of A with

```yaml
nanopore_output_directory: ".../watch_C"
results_output_directory:  ".../run_C"
main_dir:                  ".../run_C"
sample_handling:    "per_file"
analysis_name:      "Scenario_C_per_file"
```

Notes:

- `pipeline_profiles_extra: ["server"]` tells the GUI's BackendManager
  to combine `conda` with the new `server` profile from `nanometanf`.
- `nextflow_extra_args` carries the host-sizing flags. The
  laptop-friendly values shown above target an 8-thread machine; on a
  40-core server use `--max_cpus 40 --max_memory 256.GB --max_classification_forks=10`,
  on a 96-core server `--max_cpus 96 --max_memory 512.GB --max_classification_forks=24`.
- The `=` syntax on `--max_classification_forks=` is required under
  nf-schema 2.6.1 (the integer parser rejects whitespace-separated form).

## 3. Rechunk source FASTQ to 500-read pieces (nanorunner)

`nanorunner replay --reads-per-file 500` splits each source FASTQ into
several 500-read output files as it streams them into the watch
directory. This produces the per-batch granularity the real-time
mode is designed for.

Run nanorunner in a separate terminal **per scenario** -- the replay
runs continuously and emits files at the specified `--interval`.

### Scenario A -- multiplex, 5 barcodes

```bash
conda activate nanorunner
SRC=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_stage/A_multiplex
WATCH=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/watch_A

nanorunner replay \
    --source "$SRC" \
    --target "$WATCH" \
    --reads-per-file 500 \
    --interval 15 \
    --batch-size 1 \
    --operation copy \
    --force-structure multiplex
```

Nanorunner walks the per-barcode subdirectories in `$SRC` and creates
the same `barcodeNN/` layout under `$WATCH/`. Each 500-read chunk
lands one at a time, 15 seconds apart, until the source is exhausted
(roughly 60+ files per barcode, depending on input size).

### Scenario B -- flat single_sample

```bash
SRC=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_stage/B_single
WATCH=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/watch_B

nanorunner replay \
    --source "$SRC" \
    --target "$WATCH" \
    --reads-per-file 500 \
    --interval 15 \
    --batch-size 1 \
    --operation copy \
    --force-structure singleplex
```

### Scenario C -- flat per_file

Same nanorunner command as Scenario B (the layout is identical; the
distinction is in Nanometa Live's `sample_handling` setting):

```bash
SRC=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_stage/C_per_file
WATCH=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/watch_C

nanorunner replay \
    --source "$SRC" \
    --target "$WATCH" \
    --reads-per-file 500 \
    --interval 15 \
    --batch-size 1 \
    --operation copy \
    --force-structure singleplex
```

To dry-run the chunker first (no streaming), use `--interval 0
--no-wait` and watch the file count grow in `$WATCH`.

## 4. Launch the GUI

In a third terminal:

```bash
conda activate nf-core
cd /Users/andreassjodin/Code/nanometa_live
python -m nanometa_live.app \
    --config /Users/andreassjodin/Desktop/snabbsekvensering/output-live/scenario_A.yaml \
    --port 8050
```

Open `http://localhost:8050/` and:

1. **Configuration tab**: verify the loaded config matches `scenario_A.yaml`. The readiness badge should turn green within a few seconds (it now runs in the background, so it does not block the page).
2. **Preparation tab**: click *Run Preparation*. Watch the genome-download and BLAST-build progress; both finish in a minute or two for a small watchlist. This step is required for validation but optional for the headline real-time path.
3. **Dashboard tab**: click *Start Pipeline*. The verdict banner flips immediately to "starting", then settles to "running" once the first Nextflow process spawns. Conda envs build on the first run (~10-30 min cold); subsequent runs reuse the cache.
4. Once Kraken2 produces its first cumulative report (~60-120 s after the first FASTQ batch lands), the dashboard tile starts ticking, organisms appear in the Organisms tab, and the QC plots populate.

When the scenario is complete (or the replay window closes), click
*Stop Pipeline*. Then re-launch the GUI pointed at `scenario_B.yaml`
or `scenario_C.yaml` and re-run from step 3.

## 5. Acceptance checklist per scenario

Common to all three:

- Verdict banner flips to "running" within ~30 ms of clicking Start
  (the optimistic-status callback short-circuits the first poll).
- First fingerprint advance (visible as the dashboard "Sequences
  analysed" tile leaving zero) under 90 s after the first batch
  lands. Cold conda env builds are excluded from this budget; once
  envs are warm, 60 s is the target.
- Stale-warning never fires while nanorunner is actively producing
  files. It SHOULD fire after the replay window closes and 5 minutes
  of no new files have elapsed.
- Tab-to-tab read counts agree: Dashboard total == Organisms total
  (top of the table) == Classification rank-S total. Mismatches by
  more than ~1% indicate a regression of F1.
- The "Throughput" tile shows non-zero reads/min once at least 2
  cumulative reports exist.

### Scenario A (multiplex, by_barcode)

- 5 samples appear in the sample selector: `barcode01` ... `barcode05`.
- Switching the sample selector to any single barcode shows only its
  reads; switching back to "All Samples" returns the aggregate.
- Per-barcode freshness pills (U2) update independently as new
  batches land for each barcode.
- "Waiting for first kraken2 batch" banner (U4) clears as soon as the
  first cumulative report appears under
  `run_A/kraken2/<barcode>/<barcode>.cumulative.kraken2.report.txt`.

### Scenario B (flat, single_sample)

- Exactly one sample in the selector (named after `analysis_name`
  or the auto-detected sample id).
- All FASTQ files contribute to that single sample's totals.
- Classification Sankey/Sunburst displays one tree (no per-barcode
  split).

### Scenario C (flat, per_file)

- Each input file becomes its own sample. With 12 source files
  rechunked to 500 reads each, expect tens of samples in the
  selector.
- F1 cache-priority guard holds: the aggregate "All Samples" total
  in Organisms matches the Dashboard total even as fingerprint ticks
  advance per-chunk. If the two diverge by more than a single chunk
  size (500 reads), file the regression.

## 6. Stop, clean, repeat

```bash
# Stop nanorunner (Ctrl-C in the replay terminal).
# Stop the GUI (Ctrl-C in the Dash terminal).
# Optional: archive the per-scenario outputs for diffing later.
mv /Users/andreassjodin/Desktop/snabbsekvensering/output-live/run_A \
   /Users/andreassjodin/Desktop/snabbsekvensering/output-live/run_A.$(date +%Y%m%d-%H%M%S)
```

If the scenario passed, the run directory contains:

- `kraken2/` with per-sample cumulative reports and per-batch reports.
- `fastp/` or `seqkit/` (exclusive; depends on `qc_tool` config).
- `taxpasta/` with standardised outputs.
- `pipeline_info/` with the Nextflow trace, report.html, and timeline.html.

A failing scenario typically leaves `.command.err` files under
`work/<hash>/`; check `pipeline_info/execution_trace_*.txt` for the
exit codes and follow the linked work directory for the underlying
tool error.

## 7. Reset everything

```bash
BASE=/Users/andreassjodin/Desktop/snabbsekvensering/output-live
rm -rf "$BASE/_stage" "$BASE/watch_"* "$BASE/run_"*
```
