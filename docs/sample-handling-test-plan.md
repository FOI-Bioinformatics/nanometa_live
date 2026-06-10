# Sample-handling x processing-mode test plan

Validates the three sample-handling layouts across both processing modes, with an
emphasis on **robust, deterministic** results and active bug-finding.

- **by_barcode** -- `barcode01/`, `barcode02/` subdirs (multiplex)
- **single_sample** -- flat dir, all files collapse to one sample
- **per_file** -- flat dir, each file is its own sample

## Matrix and expected sample structure

| | by_barcode | single_sample | per_file |
|---|---|---|---|
| **batch** | N samples (one per barcode dir) | 1 sample | N samples (one per file) |
| **realtime** | N samples (parent-dir id) | 1 sample (`--sample_name`) | N samples (per-file id) |

Per cell: correct sample count and names, no cross-sample read mis-attribution,
sequences-analysed > 0, and (where applicable) validation confirms F. tularensis
(263) with a populated species name.

## Robustness: termination matters

The earlier species-name flakiness came from a **SIGTERM** stop truncating the
pipeline mid-batch. The intended robust path was graceful `max_files`
(`.take(N)` + PoisonPill). **This was tested and found NOT to work for a
streaming realtime run** -- see Findings. Batch mode terminates cleanly and is
the reliable path; realtime results are currently truncated by the
inactivity-timeout SIGTERM.

Deterministic loader note: the GUI loaders require files to be >=1 s old
(`loader_utils._is_file_stable`). Tests back-date inputs (`os.utime`, ~30 s) so
the stability guard passes immediately.

## Automated layer -- edge-case probes (deterministic)

`tests/test_sample_handling_modes.py` (10 tests). Each probe was verified against
the code; only one was a real bug.

| Probe | Verdict |
|-------|---------|
| `barcode1` glob must not pick up `barcode10` files | **SAFE** (the `{sample}_*` glob has an implicit `_` boundary) -- guard added |
| per_file name sanitisation (`a-1.fastq` vs `a.1.fastq` -> `a_1`) | **BUG -> FIXED**: distinct files were merged into one sample; now disambiguated with a numeric suffix |
| single-read, root-only report counts 1 not 0 | **SAFE** (`get_classification_stats` uses `root.cumul_reads`; the earlier "0" was a too-fresh test file failing the stability guard) -- guard added |
| layout validation rejects per_file/single_sample on a barcode layout | **SAFE** -- guard added |
| a `barcodeNN/` dir signals by_barcode even when empty; flat files do not | **SAFE** (correct, pattern-based) -- guard added |
| sample cache surfaces a newly-added sample file | **SAFE** -- guard added |

## Live cells (executed 2026-06-10)

Headless `BackendManager` against the SAMMLA dataset; harness at
`/tmp/nm_smt/run_cell.py`. Inputs derived from `~/Desktop/SAMMLA-demo/watch`
(barcode14/16 chunks).

### Batch -- all three modes PASS (robust, completed cleanly)

| Cell | Input | Samples detected | Status | Validation |
|------|-------|------------------|--------|------------|
| batch x by_barcode | barcode14 (10) + barcode16 (10) | **barcode14, barcode16** (2) | COMPLETED | 263 *Francisella tularensis* + 1392 *Bacillus anthracis* CONFIRMED, named |
| batch x single_sample | 15 flat files | **sample** (1) | COMPLETED | 263 CONFIRMED, named |
| batch x per_file | sample0..4 (5 files) | **sample0..sample4** (5) | COMPLETED | 263 CONFIRMED for 4/5, named |

Batch sample-handling is correct and robust in all three modes; species names are
deterministic (the `validation_taxon_names.json` path).

### Realtime -- sample detection correct, termination NOT robust

| Cell | Samples | Status | Validation |
|------|---------|--------|------------|
| realtime x by_barcode (max_files=20) | **barcode14, barcode16** (2, correct) | ended `stopped` via 10-min SIGTERM timeout | 70 taxids, **confirmed=0** (truncated) |
| realtime x single_sample (3-min timeout) | **0** (SIGTERM hit before any classification output) | `stopped` | none |

Realtime **sample detection** works (by_barcode -> 2 correct samples). But the
run did **not** terminate gracefully: `max_files=20` was passed yet the run idled
until the `realtime_timeout_minutes` inactivity timeout fired and **SIGTERM'd**
it, truncating validation -- 263 was REJECTED in realtime while batch CONFIRMS it
with identical data. With a short timeout, the SIGTERM lands before any output
exists (0 samples).

## Findings

1. **FIXED -- per_file sample-name collision** (`parameter_mapping.generate_samplesheet`):
   two files whose stems differ only by a non-word char sanitise to the same name
   and were silently merged into one sample. Now disambiguated; regression test
   added. Low severity, contained.

2. **REPORT (medium-high) -- `max_files` does not gracefully stop a realtime run.**
   With `max_files=20` and 20 streamed files, the graceful-close PoisonPill
   (`realtime_monitoring/main.nf:296-317`) did not fire; the run fell through to
   the `realtime_timeout_minutes` inactivity SIGTERM (`backend_manager._monitor_status`,
   `workflow_manager.stop()`). Consequences: realtime validation is **truncated**
   (an organism batch confirms can show all-rejected), and a short timeout yields
   **zero output**. This needs a dedicated nanometanf investigation (why the
   max_files counter/PoisonPill does not terminate the watchPath stream when files
   arrive via streaming, and/or replacing the SIGTERM stop with a graceful drain).
   It is a pipeline-side change and was not fixed here (risky, not nf-testable on
   this machine).

3. **Cleared -- 5 audit "likely bugs" were false alarms** (prefix collision,
   single-read trap, layout validation, empty-barcode detection, cache), each
   verified against the code and pinned with a guard test.

## How to run

```bash
# Automated probes
conda run -n nf-core python -m pytest -o addopts="" -q tests/test_sample_handling_modes.py

# A live cell (batch is the reliable path)
conda run --no-capture-output -n nf-core python /tmp/nm_smt/run_cell.py \
  <input_dir> <results_dir> batch <by_barcode|single_sample|per_file> <label>
```

Batch cells complete cleanly and assert the sample structure (2 / 1 / 5). Realtime
cells exercise sample detection but currently terminate via SIGTERM; treat their
validation completeness as unreliable until finding #2 is addressed.
