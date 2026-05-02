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
| 2. realtime_multiplex | 5 barcodes | _running_ | _tbd_ | _tbd_ |
| 3. realtime_single_file | flat layout | _not run_ | _tbd_ | _tbd_ |
| 4. realtime_single_folder | nested layout | _not run_ | _tbd_ | _tbd_ |

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

## Mode 2: Realtime multiplex

_Not yet run. Will execute after Mode 1 returns._

## Mode 3: Realtime single-sample file

_Not yet run._

## Mode 4: Realtime single-sample folder

_Not yet run._

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
