# Comprehensive test plan: realtime x batch, shotgun x amplicon

This plan evaluates the validation pipeline (Kraken2 classification + BLAST and
minimap2 confirmation) across the four combinations operators actually run:

|        | Whole-genome **shotgun** | Targeted **amplicon** |
|--------|--------------------------|-----------------------|
| **Batch**    | Cell 1 | Cell 2 |
| **Realtime** | Cell 3 | Cell 4 |

It complements [`testing-realtime-validation.md`](testing-realtime-validation.md)
(which focuses on the dashboard fixes) and reuses the same SAMMLA live-test
assets and the headless `BackendManager` pattern from
[`tests/test_validation_e2e.py`](../tests/test_validation_e2e.py).

The four cells were executed on 2026-06-10; the **Results** section records the
actual numbers.

## Why amplicon differs from shotgun

Validation behaves differently by library type, and the dashboard is built to
show that difference honestly:

- **Shotgun** spreads reads across the whole genome -> minimap2 coverage has
  high **breadth** (large fraction of the reference covered) at modest depth.
  `CoverageData.is_concentrated == False`; the Coverage tab shows genome-wide
  breadth/depth.
- **Amplicon** concentrates reads on a short locus -> tiny genome breadth but
  high **local depth**. `is_concentrated` fires when `breadth <= 0.05` AND
  `local_mean_depth >= 10` AND `covered_bp >= 200`
  (`core/parsers/paf_coverage_parser.py`); the Coverage tab shows "Focused
  coverage" with "Covered Region" / "Depth in Region" instead of a misleading
  "Low coverage".
- **Multi-copy markers (16S)** are the sharp case: a 16S amplicon maps equally
  to every rrn operon, so minimap2 reports **mapq 0**. The pipeline's
  `minimap2_min_mapq` filter (default 10) then drops every read -> minimap2
  **rejected / NO_DATA** -- while **BLAST still confirms** (it has no mapq). The
  conserved-region caveat (`core/parsers/validation_guards.py`) warns that such a
  call may not distinguish close relatives.

The validation status thresholds (`blast_validation_parser.ValidationResult`):
CONFIRMED at `percent_validated >= 80` and `identity >= 90`; NO_DATA when no
read passes.

## Prerequisites

| Asset | Location |
|-------|----------|
| `nf-core` conda env (nextflow, nf-test, dash, pipeline runtime) | `~/miniforge3/envs/nf-core` |
| amplicon-simulation tools | `badread`, `minimap2` (`~/miniforge3/envs/nanorunner`), `seqkit` (`~/miniforge3/envs/baitdesign`) |
| F. tularensis reference + pre-built BLAST DB | `~/Desktop/SAMMLA-demo/datadir/{genomes,blast}/263.*` |
| Kraken2 DB (NCBI taxonomy) | `~/Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015` |
| real shotgun reads (F. tularensis LVS) | `~/Desktop/SAMMLA-demo/watch/barcode14` |
| nanometanf checkout (must carry the realtime-JSON fix; on `dev`) | `/Users/andreassjodin/Code/nanometanf` |

**Critical:** `genome_cache_dir` must be the **datadir root**
(`~/Desktop/SAMMLA-demo/datadir`), not `datadir/genomes`. `GenomeManager` treats
the value as the cache root and looks in `<root>/genomes` and `<root>/blast`;
pointing it one level too deep makes `pathogen_genomes.json` come back empty and
validation is silently disabled. A fresh process also has an **empty
`WatchlistManager` singleton**, so call
`get_watchlist_manager().enable_watchlist("cdc_bioterrorism")` (which contains
F. tularensis, taxid 263) before building the config.

## Data preparation

Shotgun input is the real `barcode14`. Amplicons are simulated reproducibly from
the F. tularensis reference (single contig `NZ_CP009607.1`, 1,870,206 bp; three
16S rrn operons at ~433.8k, ~943.4k, ~1416k confirmed by mapping the
ZymoBIOMICS E. coli 16S, all mapq 0):

```bash
SK=~/miniforge3/envs/baitdesign/bin/seqkit
BR=~/miniforge3/envs/nanorunner/bin/badread
REF=~/Desktop/SAMMLA-demo/datadir/genomes/263.fasta

# single-copy ~450 bp amplicon (a unique window away from the rrn operons)
$SK subseq -r 100001:100450 "$REF" | $SK replace -p '.+' -r single_copy_amp > single_amp_ref.fasta
# one 16S copy (~1490 bp) -> multi-copy ambiguity when mapped back to the genome
$SK subseq -r 943369:944858 "$REF" | $SK replace -p '.+' -r ft_16S_amp     > 16s_amp_ref.fasta

$BR simulate --reference single_amp_ref.fasta --quantity 300x --length 450,30 \
   --identity 96,99,3 --error_model nanopore2020 --qscore_model nanopore2020 | gzip > single_amp.fastq.gz
$BR simulate --reference 16s_amp_ref.fasta --quantity 300x --length 1490,80 \
   --identity 96,99,3 --error_model nanopore2020 --qscore_model nanopore2020 | gzip > 16s_amp.fastq.gz
```

Stage as `by_barcode` inputs: shotgun -> `barcode14/`; amplicon ->
`barcode91/` (single-copy) and `barcode92/` (16S). For the realtime cells, stream
these into a watch directory with `nanorunner replay -s <src> -t <watch>
--operation copy --output-structure preserve --interval 3 --batch-size 1`.

## Running a cell (headless)

Each cell builds a config and runs `BackendManager(datadir)`, asserting on-disk
artifacts. Shared config: `validation_method: both`, `save_reads_assignment:
true`, `blast_validation: true`, `kraken_taxonomy: ncbi`, `pipeline_source` =
local nanometanf, `genome_cache_dir` = datadir root. **Amplicon cells set
`chopper_minlength: 300`** (amplicon mode, `<500`) so short reads survive QC;
shotgun keeps the default 1000. Realtime cells add `processing_mode: realtime`
and `realtime_timeout_minutes`. The runner scripts used here are
`run_batch.py` and `run_realtime.py` (kept under `/tmp/nm_amptest/` for the
session; the config they build is reproduced above).

Coverage assertions parse each `validation/minimap2/<sample>_taxid<tid>.paf`
directly with `parse_paf_coverage(..., min_mapq=0)` /
`aggregate_contig_coverage` to read back `is_concentrated`, `breadth`,
`local_mean_depth`, `covered_bp`.

### Acceptance criteria

- **Cell 1 (batch shotgun):** 263 BLAST + minimap2 CONFIRMED; coverage
  `is_concentrated == False` with high breadth.
- **Cell 2 (batch amplicon):** single-copy 263 -> `is_concentrated == True`
  (`local_mean_depth >= 10`, `covered_bp >= 200`), both methods CONFIRMED; 16S
  263 -> BLAST CONFIRMED but minimap2 rejected / 0 mapped (mapq filter), raw
  coverage still concentrated.
- **Cell 3 (realtime shotgun):** `validation_results.json` mtime and counts
  **advance repeatedly during the run** (the realtime-aggregation fix), not only
  at the timeout; 263 reaches confirmed.
- **Cell 4 (realtime amplicon):** validation refreshes during the run; the
  single-copy amplicon's focused coverage (`is_concentrated == True`) appears
  before the timeout.

## Results (executed 2026-06-10)

All four cells **PASS**. F. tularensis is taxid 263; reference
`NZ_CP009607.1` (1,870,206 bp).

### Cell 1 - batch x shotgun (real barcode14, `chopper_minlength=1000`)
- Kraken2: 3,554 reads classified to F. tularensis (263).
- Validation: **263 BLAST CONFIRMED** hit_rate 0.987, identity 97.05%;
  **minimap2 CONFIRMED**, 3,494 reads mapped.
- Coverage 263: breadth **0.9305**, mean_depth 5.7x, local_mean_depth 6.2x,
  covered 1,740,138 bp, **is_concentrated = False**.
- Verdict: broad genome-wide coverage -> correct shotgun signature.

### Cell 2 - batch x amplicon (simulated, `chopper_minlength=300`)
- **Single-copy (barcode91), 263:** BLAST CONFIRMED hit_rate 1.0, identity
  97.38%; minimap2 CONFIRMED, 126 mapped. Coverage **is_concentrated = True**,
  breadth 0.0002, **local_mean_depth 120.1x**, covered 442 bp -> focused.
- **16S multi-copy (barcode92), 263:** BLAST **CONFIRMED** hit_rate 1.0,
  identity 97.2%; minimap2 **rejected, 0 mapped** -- the mapq>=10 filter drops
  the reads that map ambiguously to the three rrn operons. Raw (unfiltered)
  coverage **is_concentrated = True**, breadth 0.0024, local_mean_depth 38.8x,
  covered 4,466 bp (~3 x 1,490 bp). Exactly the documented 16S behaviour:
  minimap2 NO_DATA, BLAST confirms, conserved-region caveat applies.

### Cell 3 - realtime x shotgun (streamed barcode14, timeout 3 min)
- **10 distinct `validation_results.json` writes during the run**, mtime
  advancing over a ~76 s window, `total_taxids_validated` growing 0 -> 22 and
  263 reaching confirmed (hit_rate 0.909) before the run stopped on timeout.
- This is the end-to-end proof of the realtime-aggregation fix: the JSON the GUI
  reads refreshes each batch rather than only at the timeout.

### Cell 4 - realtime x amplicon (streamed simulated amplicons, timeout 3 min)
- **19 distinct `validation_results.json` writes during the run.**
- Single-copy amplicon (barcode91), 263: BLAST + minimap2 **CONFIRMED**;
  coverage **is_concentrated = True**, local_mean_depth 68.8x, covered 442 bp --
  focused coverage surfaced mid-run, not just at the end.

## Automated layer (run alongside the live cells)

```bash
# nanometa_live unit/callback suite (fast, no pipeline)
conda run -n nf-core python -m pytest -q                       # ~2456 passed
conda run -n nf-core python scripts/check_code_size.py         # gate clean

# nanometanf validation aggregation (batch + realtime nf-test)
cd /Users/andreassjodin/Code/nanometanf
conda run -n nf-core nf-test test subworkflows/local/validation/tests/main.nf.test   # 3/3

# opt-in headless end-to-end (real SAMMLA data), mirrors Cell 1
NANOMETA_RUN_E2E=1 conda run -n nf-core python -m pytest -o addopts="" -m slow \
  /Users/andreassjodin/Code/nanometa_live/tests/test_validation_e2e.py
```

GUI-only behaviours (the verdict-banner countdown, "View Report" modal, the
empty-state validation diagnostic) are covered by
`tests/test_dashboard_tab_callbacks.py` and `tests/test_validation_status_helpers.py`,
plus the smoke-test-app skill (`--dataset 06_pathogen_detected`).

## Troubleshooting

- **Validation tab empty / no `validation/` dir:** `pathogen_genomes.json` was
  not generated. Check `genome_cache_dir` is the datadir **root** and that the
  watchlist (with 263) is enabled in the running process.
- **Amplicon reads disappear at QC:** set `chopper_minlength < 500` (300 here);
  the default 1000 filters out short amplicons.
- **16S amplicon shows minimap2 NO_DATA:** expected for a multi-copy marker
  (mapq 0 -> filtered). BLAST confirms; trust the BLAST call and the
  conserved-region caveat.
- **`pipeline_source` lacks the realtime fix:** the per-batch JSON refresh
  (Cells 3-4) needs the nanometanf `AGGREGATE_VALIDATION_LIVE` change; point
  `pipeline_source` at a checkout/branch that carries it.
- **`nanorunner` import error:** run it from the `nanorunner` env, not `nf-core`.
