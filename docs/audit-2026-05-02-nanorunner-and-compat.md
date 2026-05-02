# Audit 2026-05-02 -- nanorunner production readiness + GUI/nanometanf parameter compatibility

Phase B Auditor 3 of an approved multi-agent audit. Read-only review. No
code modifications. All findings cite file:line.

Two artefacts under review:

1. `/Users/andreassjodin/Code/nanorunner/` (nanopore_simulator package,
   conda env `nanorunner`).
2. The seam between
   `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/core/config/parameter_mapping.py`
   and `/Users/andreassjodin/Code/nanometanf/nextflow_schema.json`.

---

## Executive summary

nanorunner ships a clean Typer-based CLI with ten subcommands, all
functional and all exercised by the 726-test pytest suite. CLI option
naming is consistent across subcommands (`--source`/`--target` for
replay/recommend/validate, `--target` only for generate/download).
Three production-readiness concerns surface: (1) the
`replay --reads-per-file` rechunking path names every output chunk after
the alphabetically-first source file, hiding multi-file provenance;
(2) error paths return exit 0 when the default rich-progress monitor is
active, masking failures from CI; (3) an empty source directory yields
a silent successful exit with no warning. None of these are blockers but
all warrant a targeted fix before field deployment.

The GUI/nanometanf seam is in good shape. Of 39 keys the GUI emits, 38
are declared in `nextflow_schema.json`. One orphan -- `max_avg_file_age_minutes` --
is set in realtime mode but only consumed by an internal threshold dict
in `update_cumulative_stats`; it never reaches Nextflow params, so a run
with `validate_params = true` will fail nf-core schema validation. There
are no naming-drift cases (no `min_perc_identity` -> `validation_identity_threshold`
miss; the GUI handles both as a documented backward-compat alias at
`parameter_mapping.py:625-628`).

---

## Part 1 -- nanorunner production readiness

### 1.1 Subcommand inventory

Ten subcommands registered on the shared Typer app
(`nanopore_simulator/cli.py:71-78`, with submodule imports at
`cli.py:133`). All ten are functional:

| Subcommand | File | Status |
|-----|-----|-----|
| `replay` | `cli_replay.py:28-238` | Working. End-to-end run reproduced with three input FASTQ files. |
| `generate` | `cli_generate.py:31-410` | Working. Builtin backend exercised by tests. |
| `list-profiles` | `cli_utils.py:22-31` | Working. Returns 6 profiles. |
| `list-adapters` | `cli_utils.py:34-43` | Working. Returns `nanometa`, `kraken`. |
| `list-generators` | `cli_utils.py:46-56` | Working. Reports backend availability. |
| `list-mocks` | `cli_utils.py:59-79` | Working. Returns 6 mock communities. |
| `check-deps` | `cli_utils.py:82-121` | Working. Categorised dependency table. |
| `recommend` | `cli_utils.py:129-186` | Working. Both `--source` and `--file-count` paths exercised. |
| `validate` | `cli_utils.py:189-220` | Working. Calls `adapters.validate_output`. |
| `download` | `cli_utils.py:223-439` | Working. Independent codepath (does not share `cli_helpers._resolve_and_download_genomes`). |

No dead subcommands.

### 1.2 CLI consistency

The two operational subcommands consistently name their inputs:

- `replay --source/-s --target/-t` (`cli_replay.py:31-47`)
- `generate --target/-t` (no `--source`; uses `--genomes`/`--species`/`--mock`/`--taxid`)
- `recommend --source/-s` (`cli_utils.py:131-141`)
- `validate --target/-t` (`cli_utils.py:197-205`)
- `download --target/-t` (`cli_utils.py:242-247`)

There is no `--source` vs `--input` split between subcommands. `replay`
is the only command that accepts existing FASTQ files and consistently
calls that input `--source`.

Minor inconsistency: `generate` accepts most timing/simulation options
as `Optional` with sentinel-default resolution
(`cli_generate.py:204-297`) so a profile can fill them in, while
`replay` accepts them with concrete defaults and a different precedence
rule (`cli_replay.py:69-128, 192-194`). Both work, but the reader has
to follow two different patterns. Not severe.

### 1.3 Error handling on bad inputs

Verified empirically:

| Scenario | Behaviour | Verdict |
|-----|-----|-----|
| Missing source directory | Typer rejects at parse via `exists=True` (`cli_replay.py:31-40`); exit 2 with rich error panel. | Good. |
| Empty source directory | `manifest.py:175-176` swallows the `ValueError` from `detect_structure`, returns `[]`. `runner.py:186-188` logs at INFO and exits 0 with no stderr. | **Bug.** Operator gets no warning. Should at least warn to stderr. |
| Write-protected target dir, monitor=`none` | `_execute_manifest -> execute_entry -> _copy_file` raises `PermissionError`; `cli_replay.py:232-234` catches and exits 1. | Good. |
| Write-protected target dir, monitor=`default` (the default!) | Error printed to console, but **process exits 0**. | **Bug.** The default rich monitor swallows the typer.Exit code; CI cannot detect failures. Reproduced on `cli_replay.py:227-234`. |
| Reads-per-file with link operation | Detected at `cli_replay.py:162-167` (and again in `config.py:100-107`) before any work. Exit 2. | Good. |
| Malformed FASTQ in source | Not directly exercised in this audit. The fastq parser at `nanopore_simulator/fastq.py` does not appear to validate read structure during rechunking. | Untested -- worth a follow-up. |

### 1.4 Singleplex multi-file rechunk bug -- VERIFIED

The fixture-build report claimed:

> `nanorunner replay --force-structure singleplex` with a multi-file
> source directory only emits chunks for the alphabetically-first file
> and silently skips the rest.

After direct code-read and end-to-end reproduction, the actual
behaviour is more subtle:

- The reads from every source file ARE captured. The chunk-offset map
  built at `manifest.py:_build_chunk_offsets` (`manifest.py:337-380`)
  spans all files, and the executor at
  `executor.py:_rechunk_file` (`executor.py:132-204`) reads from the
  correct source file via `entry.source` and `entry.source_offset`.
- However, **every output chunk filename uses the first source file's
  stem.** The offending line is `manifest.py:300`:

  ```python
  stem = _fastq_stem(first_source) if first_source else "reads"
  ```

  combined with the filename construction at `manifest.py:310`:

  ```python
  filename = f"{stem}_chunk_{chunk_idx:04d}{ext}"
  ```

  `first_source` is `grp["fastq_files"][0][0]`, i.e. the alphabetically
  first source file (because `_singleplex_entries` at
  `manifest.py:202` sorts by name).

Reproduction: source = `{alpha,beta,gamma}.fastq` each containing 2
reads, `--reads-per-file 2 --force-structure singleplex`. Output:

```
alpha_chunk_0000.fastq   <- contains alpha's reads
alpha_chunk_0001.fastq   <- contains beta's reads
alpha_chunk_0002.fastq   <- contains gamma's reads
```

Reads are correct; filenames are misleading. From an `ls` listing the
operator cannot tell that beta and gamma were processed. If beta or
gamma were the larger files, an operator would reasonably conclude
rechunking dropped them.

**Offending function:** `_rechunk_entries` at `manifest.py:234-334`
(stem assignment at line 300).

**Proposed one-line fix:** thread the per-chunk source file's stem
through the loop instead of the bulk `first_source` stem. The
straightforward change is to replace the loop body's filename
construction so each chunk uses the stem of `source_paths[src_file_idx]`:

```python
chunk_stem = _fastq_stem(source_paths[src_file_idx]) if byte_offset is not None else stem
filename = f"{chunk_stem}_chunk_{chunk_idx:04d}{ext}"
```

(Caller still computes `stem` once for the fallback.)

No tests cover this scenario today -- `tests/test_manifest.py` has
`test_rechunk_singleplex` (lines 329-351) but uses identical
filenames `reads_0.fastq` and `reads_1.fastq`, so the stem collision
hides the bug. A regression test should use distinct stems.

### 1.5 Test coverage

726 tests collected (`pytest --collect-only`). Coverage by module:

| File | Lines | Test file present | Notable gaps |
|-----|-----|-----|-----|
| `cli.py`, `cli_helpers.py`, `cli_replay.py`, `cli_generate.py`, `cli_utils.py` | mixed | `test_cli.py` (1168 lines), `test_cli_coverage.py` (365 lines) | Heavy coverage. |
| `manifest.py` | 549 | `test_manifest.py` (576 lines) | **Multi-file singleplex rechunk filename uniqueness** untested (1.4). |
| `executor.py` | 239 | `test_executor.py` (241 lines) | Adequate. |
| `runner.py` | ~350 | `test_runner.py` (378 lines) | Empty source warning behaviour not asserted. |
| `monitoring.py` | n/a | `test_monitoring.py` (341 lines) | **Exit-code-when-monitor-active** path is not asserted (1.3). |
| `detection.py`, `config.py`, `fastq.py`, `generators.py`, `species.py`, `mocks.py`, `profiles.py`, `adapters.py`, `timing.py`, `deps.py` | various | one test file each | OK. |
| `coverage_boost.py`, `integration.py` | n/a | yes | Integration tests cover end-to-end. |

Three `pytest.mark.slow` markers without registration in
`pytest.ini` -- 4 warnings on every collection
(`test_coverage_boost.py:239`, `test_integration.py:896`,
`test_integration.py:1067`, `test_monitoring.py:312`). Cosmetic.

### 1.6 nanorunner score

| Dimension | Weight | Score | Rationale |
|-----|-----|-----|-----|
| `cli_consistency` | 20% | 8/10 | Naming uniform; minor sentinel-vs-default-style split between replay and generate. |
| `error_handling` | 25% | 5/10 | Three concrete defects: empty source silent, monitor swallows exit code, no FASTQ validity check during rechunk. |
| `feature_completeness` | 25% | 8/10 | All 10 subcommands work; rechunk filename bug is the one feature defect. |
| `test_coverage` | 15% | 8/10 | 726 tests, broad coverage. Two specific holes: chunk filename uniqueness, exit code under monitor. |
| `dead_code` | 15% | 9/10 | No dead subcommands. Each module has a clear role. |

**Weighted nanorunner score: 7.3 / 10**
(0.20*8 + 0.25*5 + 0.25*8 + 0.15*8 + 0.15*9 = 1.60 + 1.25 + 2.00 + 1.20 + 1.35).

---

## Part 2 -- GUI / nanometanf parameter compatibility

### 2.1 Methodology

Extracted every key set in `parameter_mapping.create_nextflow_params`:

- The base dict literal at `parameter_mapping.py:600-666`.
- All `params[...] = ...` assignments (`parameter_mapping.py:677-822`).

Cross-referenced against every `properties` key in
`nextflow_schema.json` (extracted programmatically; 113 schema
properties, 39 GUI-emitted keys).

### 2.2 Orphan params (GUI emits, schema does not declare)

| Key | GUI source | Schema present? | Effect |
|-----|-----|-----|-----|
| `max_avg_file_age_minutes` | `parameter_mapping.py:788` | **No** -- not in `nextflow_schema.json` properties. | The string `max_avg_file_age_minutes` IS read by `modules/local/update_cumulative_stats/main.nf:189-199` from a thresholds dict, but it is not exposed as a top-level Nextflow param. Setting `--max_avg_file_age_minutes` from the GUI either silently no-ops or trips nf-schema validation when `validate_params=true`. |

That is the only orphan.

### 2.3 Schema knobs the GUI never sets (76)

These are not bugs -- they are knobs the GUI deliberately does not
expose. Notable ones an operator might want eventually:

- Chopper trimming: `chopper_headcrop`, `chopper_tailcrop`,
  `chopper_maxlength`.
- Filtlong fine controls: `filtlong_keep_percent`, `filtlong_max_length`,
  `filtlong_min_mean_q`, `filtlong_min_window_q`, `filtlong_target_bases`.
- BLAST tuning: `blast_db`, `blast_max_target_seqs`.
- Assembly subworkflow: `enable_assembly`, `assembler`, `genome_size`.
- Realtime tuning: `adaptive_batching`, `batch_timeout`,
  `batch_size_factor`, `realtime_processing_grace_period`,
  `realtime_report_interval`, `report_write_interval`.
- Validation aggregation: `validation_aggregate_interval`, `validation_taxa`.
- Inputs the GUI does not use: `barcode_input_dir`, `reads_dir` (used
  by VALIDATION_ONLY in `on_demand_validator`, but not from
  `create_nextflow_params`), `kraken2_output_dir` (same), `fasta`,
  `genome`, `taxonomy_file`.
- nf-core boilerplate: `config_profile_*`, `custom_config_*`,
  `igenomes_*`, `pipelines_testdata_base_path`, `email_on_fail`,
  `max_multiqc_email_size`, `multiqc_*`, `monochrome_logs`,
  `plaintext_email`, `publish_dir_mode`, `show_hidden`,
  `trace_report_suffix`, `validate_params`, `version`, `help*`,
  `hook_url`. These are correctly left to Nextflow defaults.
- Others: `classifier`, `enable_adapter_trimming`,
  `enable_nanoplot_comparison`, `enable_qc_benchmark`,
  `enable_realtime_stats`, `enable_taxpasta_standardization`,
  `file_pattern`, `kraken2_memory_gb`, `kraken2_use_optimizations`,
  `max_batch_size`, `max_classification_forks`,
  `max_concurrent_batches`, `multiqc_realtime_final_only`,
  `nanoplot_batch_interval`, `nanoplot_realtime_skip_intermediate`,
  `qc_enable_incremental`, `sample_regex`, `sequencing_mode`,
  `skip_fastqc_realtime`, `skip_kraken2`, `skip_krona`,
  `skip_multiqc`, `taxpasta_format`, `validation_only`, `write_canonical`.

Most are intentional. The GUI has chosen reasonable defaults via the
schema's own `default` field.

### 2.4 Naming consistency

No naming drift detected. The high-risk pair the audit explicitly
called out -- `min_perc_identity` vs `validation_identity_threshold` --
is handled correctly:

`parameter_mapping.py:625-628` reads the legacy `min_perc_identity`
config key first, falling back to `validation_identity_threshold`,
and emits the canonical pipeline name `blast_perc_identity`. Comment
at lines 618-624 documents the 2026-04-30 collapse explicitly.

The GUI also separately emits `validation_identity_threshold`
(`parameter_mapping.py:630`), which IS the schema name for the
post-classifier filter (different concept from the BLAST percent
identity). Both schema entries exist and are correctly populated.

`blast_evalue` <- GUI `e_val_cutoff` (`parameter_mapping.py:617`):
correct rename, schema declares `blast_evalue`.

`outdir` <- GUI `results_output_directory` or `main_dir`
(`parameter_mapping.py:430, 601`): correct rename, schema declares
`outdir`.

`kraken2_db` <- GUI `kraken_db` (`parameter_mapping.py:428, 604`):
correct rename, schema declares `kraken2_db`.

`kraken2_memory_mapping` <- GUI `kraken_memory_mapping`
(`parameter_mapping.py:588-597, 605`): correct rename, schema declares
`kraken2_memory_mapping`.

### 2.5 Consistent params (38)

These are populated by the GUI and declared in the schema:

```
batch_interval, batch_size, blast_evalue, blast_perc_identity,
blast_validation, chopper_minlength, chopper_quality, email,
enable_krona_plots, enable_nanopore_stats_mqc, filtlong_min_length,
input, input_dir, kraken2_confidence, kraken2_db,
kraken2_enable_incremental, kraken2_memory_mapping,
kraken2_minimum_hit_groups, max_files, min_batch_size,
minimap2_min_mapq, minimap2_preset, multiqc_title,
nanopore_output_dir, outdir, pathogen_genomes, priority_samples,
qc_tool, realtime_mode, realtime_timeout_minutes, run_validation,
sample_name, save_output_fastqs, save_reads_assignment,
skip_fastp, skip_nanoplot, taxids_to_validate,
validation_hit_rate_threshold, validation_identity_threshold,
validation_method
```

### 2.6 Cross-repo compatibility score

**Score: 8 / 10.**

Rationale: 38/39 GUI-emitted keys map cleanly onto declared schema
properties. One orphan (`max_avg_file_age_minutes`) is an actual
defect that will fail strict schema validation. No naming drift
between repos -- the legacy `min_perc_identity` alias is documented
and handled in Python before reaching Nextflow. This is firmly in
the "minor name drift, no orphans" band per the rubric, with the one
orphan dragging the score down from 9 to 8.

---

## Anti-fabrication verification

Three concrete claims spot-checked by direct file read:

1. **Claim:** `_singleplex_entries` does not deduplicate or skip files
   beyond the first. Verified at `manifest.py:198-211` -- it iterates
   `find_sequencing_files(config.source_dir)` sorted by name and
   creates one entry per file. The "only first file" behaviour is
   localised to the rechunk filename construction, not to the entry
   list. *Verified.*

2. **Claim:** schema declares `barcode_input_dir`. Verified by direct
   grep -- `nextflow_schema.json` contains a `barcode_input_dir`
   property of type `string`, format `directory-path`. The GUI does not
   set it. *Verified.*

3. **Claim:** `min_perc_identity` is handled as a backward-compat alias.
   Verified at `parameter_mapping.py:618-628` with explicit comment and
   `config.get("min_perc_identity", config.get("validation_identity_threshold", 90))`.
   *Verified.*

All three claims hold. No fabricated findings.

---

## Recommended follow-ups

In priority order:

1. Fix the rechunk filename collision in `manifest.py:300` (one-line
   change in 1.4) and add a regression test using distinct source
   stems.
2. Make the default progress monitor propagate non-zero exit codes
   from `cli_replay.py:227-234` so CI catches failures.
3. Warn loudly when `build_replay_manifest` returns `[]`
   (`runner.py:186-188`).
4. Drop `max_avg_file_age_minutes` from `parameter_mapping.py:788` or
   add it to `nextflow_schema.json`. If the threshold lives only in
   `update_cumulative_stats` it should be passed through a config map,
   not a top-level param. (Out of scope for nanorunner; cited here as
   the only cross-repo drift.)
5. Register the `slow` mark in `pytest.ini` to silence the four
   `PytestUnknownMarkWarning`s.

End of report.
