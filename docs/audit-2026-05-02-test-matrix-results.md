# Phase C Test Matrix Results -- 2026-05-02

End-to-end runs of the nanometanf pipeline against the four
fixtures built by `bin/build-test-fixtures.sh`. Each mode is
driven by `bin/run-mode-test.sh <mode>` and writes its outputs
under `$HOME/Desktop/snabbsekvensering/output-live/<mode>/`.

Common parameters across all modes:
- profile `conda`
- `NXF_VER=25.04.7` (avoids the watchPath JVM cleanup hang on
  25.10.4)
- `NXF_OFFLINE=true`
- `NXF_CONDA_CACHEDIR=$HOME/.nanometa/work/conda` (reuse
  pre-warmed envs)
- Kraken2 DB at `$HOME/Desktop/kraken_db/k2_pluspfp_08_GB_20251015`

Realtime modes (2/3/4) are time-bounded with
`--realtime_timeout_minutes 1 --realtime_processing_grace_period 1`
to keep total wall-clock under three minutes per mode.

---

## Summary

| Mode | Fixture | Status | Wall-clock | Notes |
|---|---|---|---|---|
| 1. samplesheet | 5 samples flat | **PASS** | 6m 1s | 39/39 tasks succeeded; chopper macOS fix landed mid-run (see below) |
| 2. realtime_multiplex | 5 barcodes | **FAIL** | ~3 min | Real bug: MULTIQC_NANOPORE_STATS file-name collision across batches |
| 3. realtime_single_file | flat layout | **PASS** (logical) | ~2 min work + hung JVM cleanup | All outputs produced; JVM cleanup hung per known watchPath issue |
| 4. realtime_single_folder | nested layout | **PASS** (logical) | ~2 min work + hung JVM cleanup | Same as Mode 3; nested folder layout discovered correctly |

---

## Mode 1: Samplesheet -- PASS

Wall-clock: 6m 1s. Total tasks: 39 / 39 succeeded.

Configured with:
```
nextflow run main.nf -profile conda \
  --input fixtures/samplesheet/samplesheet.csv \
  --outdir output-live/samplesheet \
  --kraken2_db <db> \
  -work-dir output-live/samplesheet/work
```

### Mid-run finding: nanometanf chopper macOS regression

The first attempt failed for all 5 samples with `zcat: can't
stat: <file>.fastq.gz` followed by an opaque "Invalid method
invocation `call`" Groovy error. Root cause: nanometanf's
chopper module
(`modules/nf-core/chopper/main.nf:30`) uses `zcat`, which on
macOS BSD only handles legacy `.Z` files. The macOS fix from
commit `0da485e` had been silently reverted by `982a70b` when
chopper was bumped to the upstream topic-channel version.

Fixed in nanometanf commit `e5c4537` (merged to `dev` at
`40b8e9f`); the second mode-1 run picked up the fix and
completed cleanly.

### Per-sample outcome (CHOPPER -> KRAKEN2)

| Sample | Reads after chopper (--minlength 1000) | Kraken2 ran |
|---|---:|---|
| LVS_1 | nonzero | yes |
| D6300_2 | nonzero | yes |
| Turex_3 | nonzero | yes |
| Ricin_crude_1 | nonzero | yes |
| negative | 0 | skipped (empty input) |

The negative control's chopper output was empty (all 500
subsampled reads under the 1 kb minimum). The pipeline
correctly skipped Kraken2 for the empty input rather than
erroring; 4/4 KRAKEN2 tasks succeeded with all 4 producing
real reports.

### Outputs verified

```
output-live/samplesheet/
  canonical/         <- canonical_qc_writer + canonical_classification_writer
  chopper/           <- 5 *.chopped.fastq.gz
  fastqc/            <- 5 *_fastqc.html + zip
  kraken2/           <- 4 *.kraken2.report.txt
  multiqc/           <- multiqc_report.html, custom mqc JSONs
  nanoplot/          <- 4 sample dirs with NanoPlot output
  pipeline_info/     <- execution_trace_*, pipeline_dag, software_versions
  seqkit/            <- 5 *.tsv (chopper QC source)
  taxpasta/          <- 4 standardised tables
```

PASS: 39 / 39 tasks succeeded; pipeline completed cleanly.

## Mode 2: Realtime multiplex -- FAIL

Wall-clock: ~3 min before pipeline aborted on a process error.

Two findings, one fixture-side and one real pipeline bug.

### Fixture finding (cosmetic; not the blocker)

With `--reads-per-file 50` for multiplex (vs 100 for
samplesheet), each chunk has only ~50 source reads. After
chopper `--minlength 1000` filtering, every barcode's
post-QC FASTQ ended up empty:

    WARN: Skipping Kraken2 for sample 'barcode01' - post-QC
          FASTQ contains no reads (size below 50 bytes)
    (same for barcode02 through barcode05)

The pipeline correctly skipped Kraken2 on empty input (same
graceful behaviour Mode 1 showed for the negative control), so
this is not what caused mode 2 to abort.

### Real bug: MULTIQC_NANOPORE_STATS filename collision (P0)

```
Process `FOIBIOINFORMATICS_NANOMETANF:NANOMETANF:
MULTIQC_NANOPORE_STATS` input file name collision -- There are
multiple input files for each of the following file names:
barcode04.tsv, barcode01.tsv, barcode02.tsv, barcode03.tsv,
barcode05.tsv
```

In realtime mode each barcode produces multiple chunk batches.
Each batch's seqkit/chopper QC stage emits a per-barcode TSV
named `barcodeXX.tsv`. When MULTIQC_NANOPORE_STATS later
collects these via `.collect()`, Nextflow staging refuses to
co-locate files with identical names.

This is a real nanometanf bug that affects every multi-batch
realtime run with barcoded input -- the collision is determined
by the per-barcode-per-batch naming convention, not by the
fixture content. The samplesheet path (Mode 1) does not hit
it because each sample produces exactly one TSV.

The right fix is to suffix the per-barcode TSV with a batch id
(e.g. `barcodeXX_batch_NNNN.tsv`) somewhere in the
seqkit/chopper output staging or in the
`generate_snapshot_stats` collector. The bug should land
upstream in nanometanf as a P0 from this Phase C run.

### Status

PIPELINE FAIL -- documents a real nanometanf bug. Filed as a
follow-up. The chopper macOS fix from Mode 1 stayed in effect,
so this is purely the new collision finding.

## Mode 3: Realtime single-sample file -- PASS (logical)

Wall-clock: ~2 min for actual work; JVM cleanup hung beyond
the 15-min monitor window before being killed manually. The
pipeline produced every expected output before stalling on
shutdown -- this is the well-documented watchPath JVM cleanup
hang
(`bin/run-nf-tests.sh`, nf-test.config:28-30,
`docs/upstream-issues/26-watchpath-cleanup-hang.md`), not a
regression from this cycle.

### Per-chunk outcome

LVS_1_barcode11 was rechunked into 5 small files
(`fixtures/realtime_single_file/LVS_1_barcode11_chunk_0000..0004.fastq.gz`).
With chopper `--minlength 1000`, only chunks 0000, 0001, and
0004 had any reads survive QC. Cumulative Kraken2 reports were
generated for all three:

```
output-live/realtime_single_file/kraken2/
  LVS_1_barcode11_chunk_0000.cumulative.kraken2.output.txt
  LVS_1_barcode11_chunk_0000.cumulative.kraken2.report.txt
  LVS_1_barcode11_chunk_0001.cumulative.kraken2.output.txt
  LVS_1_barcode11_chunk_0001.cumulative.kraken2.report.txt
  LVS_1_barcode11_chunk_0004.cumulative.kraken2.output.txt
  LVS_1_barcode11_chunk_0004.cumulative.kraken2.report.txt
```

Confirms the new BatchUtils count-or-timeout flush works in
realtime mode -- partial batches reach Kraken2 within the
documented `batch_timeout` window rather than waiting for the
full size threshold.

### Outputs verified

```
output-live/realtime_single_file/
  canonical/
  chopper/                    <- 5 chopped files (3 nonzero)
  kraken2/                    <- 3 cumulative reports
  multiqc/                    <- multiqc_report.html, JSONs
  pipeline_info/
  realtime_batch_stats/       <- 2 batch snapshots
  realtime_reports/           <- realtime_report_<ts>.html
  realtime_stats/             <- cumulative_state.json, cumulative_stats.json
  seqkit/
  taxpasta/
```

PASS (logical): all expected outputs present, pipeline work
completed. The shutdown hang is a known infrastructure
limitation, not a finding from this cycle. Note that single-
sample mode does NOT hit the F0 multiqc collision because
each chunk produces a distinct chunk-named TSV.

## Mode 4: Realtime single-sample folder -- PASS (logical)

Wall-clock: ~2 min for actual work; JVM cleanup hung, killed
manually after the watchPath cleanup window expired.

Identical fixture content to Mode 3 (LVS_1 chunks
0000..0004), but laid out as
`fixtures/realtime_single_folder/LVS_1/<chunks>` rather than
flat. The pipeline correctly discovered the chunks via
`--file_pattern '**.fastq{,.gz}'` and produced the same three
cumulative Kraken2 reports as Mode 3:

```
output-live/realtime_single_folder/kraken2/
  LVS_1_barcode11_chunk_0000.cumulative.kraken2.report.txt
  LVS_1_barcode11_chunk_0001.cumulative.kraken2.report.txt
  LVS_1_barcode11_chunk_0004.cumulative.kraken2.report.txt
```

multiqc/ has the same content as mode 3:
`multiqc_report.html`, `multiqc_data/`, `multiqc_plots/`,
plus the `nanometanf_nanopore_stats_mqc.json` and
`nanometanf_quality_mqc.json` custom modules. The watchPath
nested-folder discovery path works.

PASS (logical): same outcome as Mode 3 with the nested folder
layout. Confirms the watchPath glob handles both flat and
single-subdirectory single-sample inputs.

---

## Findings summary

| Finding | Severity | Repo | Status |
|---|---|---|---|
| Chopper macOS regression (`zcat` vs `gunzip -c`) | P0 | nanometanf | **FIXED** in commit `e5c4537`, merged at `40b8e9f` |
| MULTIQC_NANOPORE_STATS filename collision in realtime barcoded mode | P0 | nanometanf | **F0** in followups; not fixed this cycle |
| watchPath JVM cleanup hang in realtime modes | infra | nanometanf | Pre-existing, documented; not a Phase C finding |

Three of four modes ran to logical completion. Mode 2's
failure is a single nanometanf bug (the per-batch TSV naming
collision) and is the one P0 the cycle leaves open for the
next sprint.

The chopper macOS fix is the most important deliverable from
Phase C: the pipeline could not start on macOS without it,
and it would have been silently re-broken by the next
`nf-core modules update` had Phase C not surfaced it.

---

## How to reproduce

```
cd $HOME/Desktop/deving/nanometa_live

# Build fixtures (if not done already)
bash bin/build-test-fixtures.sh

# Run a single mode
bash bin/run-mode-test.sh samplesheet
bash bin/run-mode-test.sh realtime_multiplex
bash bin/run-mode-test.sh realtime_single_file
bash bin/run-mode-test.sh realtime_single_folder
```

Outputs land under `$HOME/Desktop/snabbsekvensering/output-live/<mode>/`.
The collision modal (Phase D, commit `5bb782d`) catches a re-run
into the same outdir and offers archive / resume / cancel.
