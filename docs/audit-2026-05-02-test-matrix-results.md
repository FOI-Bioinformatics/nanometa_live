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
| 1. samplesheet | 5 samples flat | _running_ | _tbd_ | _tbd_ |
| 2. realtime_multiplex | 5 barcodes | _not run_ | _tbd_ | Sequenced after Mode 1 confirms the path |
| 3. realtime_single_file | flat layout | _not run_ | _tbd_ | _tbd_ |
| 4. realtime_single_folder | nested layout | _not run_ | _tbd_ | _tbd_ |

---

## Mode 1: Samplesheet

_Running. Results will be appended here when the pipeline
returns._

Configured with:
```
nextflow run main.nf -profile conda \
  --input fixtures/samplesheet/samplesheet.csv \
  --outdir output-live/samplesheet \
  --kraken2_db <db> \
  -work-dir output-live/samplesheet/work
```

Fixture content: 5 chunked FASTQs and a `samplesheet.csv` with
columns `sample,fastq,barcode` covering LVS_1, D6300_2,
Turex_3, Ricin_crude_1, and negative.

Expected outputs (per nanometanf's standard layout):
- `output-live/samplesheet/kraken2/<sample>.kraken2.report.txt`
- `output-live/samplesheet/seqkit/<sample>.tsv` (chopper QC tool)
- `output-live/samplesheet/multiqc/multiqc_report.html`
- `output-live/samplesheet/pipeline_info/execution_trace_*.txt`
- `output-live/samplesheet/taxpasta/*.tsv`

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
