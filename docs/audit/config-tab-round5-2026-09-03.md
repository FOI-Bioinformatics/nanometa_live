# Audit round 5: Configuration tab advanced settings, batch and real-time

Date: 2026-09-03. Build: nanometa_live 0.16.0 (dev), nanometanf dev (1.8.1dev).
Plan: `~/.claude/plans/make-a-plan-to-squishy-reddy.md`. Kit: `~/nanometa-audit-r5/`.

## Method

Rounds 1 to 4 drove the real-time lifecycle with five-key configs and form
defaults. This round takes the Configuration tab itself as the object: does
the value an operator sets reach the pipeline, in batch and in real-time
mode, and does the pipeline do what the label says.

Three hops were read statically first (form widget -> config key ->
`params.json` -> nanometanf behaviour), giving 33 numbered hypotheses. Each
was then settled by the cheapest sufficient method: a unit probe
(`tests/test_config_tab_audit_r5.py`, one test per static hypothesis,
asserting the expected behaviour so a defect fails red), a headless browser
drill against the live form (`set_form.js`), or a live run. Live runs used
the Bioshield demo corpus and database; batch runs on
`~/nanometa-demo/data/multiplex`, real-time runs fed by nanorunner 3.1.0
replay. Every launch was snapshotted (`params.json`, `custom.config`, the
command line) and diffed against the form values through the GUI's own key
mapping (`diff_launch.py`).

Severity: H = wrong result, lost setting or aborted run the operator is not
told about; M = a control that does nothing or reports the wrong state;
L = cosmetic or dead code.

## Results at a glance

| ID | Finding | Sev | Status |
|---|---|---|---|
| A1 | `initialize_form_from_config` declares 42 Outputs, returns 41 on the empty-config path | H | static, confirmed; fixed |
| A2 | A rejected Apply opens the green "changes have been applied" alert beside the red toast | M | live, confirmed; fixed |
| A2b | Number inputs drop out-of-range and off-grid values client-side: the widget shows the typed value, Apply reports success, the config keeps the old one | H | live, confirmed; fixed |
| A3 | The snapshot rebase and badge clear fire on the click, not on a successful Apply | M | static, confirmed; fixed |
| A4 | Three form keys absent from `create_default_config`; the form is dirty before any edit | M | static, confirmed; fixed |
| A5 | Loader fallback differs from the default for `min_reads_for_validation` (10 vs 50) and `analysis_name` | M | static, confirmed; fixed |
| A6 | Unsaved draft edits survive a reload with a clean Modified badge | M | live, confirmed; fixed |
| A7 | Reset leaves the dirty snapshot and `last-session.yaml` on the old config | L | static, confirmed; fixed |
| A8 | `qc_tool: fastp` rewritten to chopper on Apply with a log line only | M | static, by design since 2026-09-02, wording |
| A9 | `pipeline_cores` reaches nothing; a divergent `validation_cores`/`blast_cores` is flattened on Apply | M | static, confirmed; fixed |
| A10 | `kraken2_minimum_hit_groups` has no server bound; a non-numeric value raises | L | static, confirmed; fixed |
| A11 | Dead code: `fastq_input_dir`, `remove_temp_files` remnants, `config-status-message` | L | static, confirmed; fixed |
| A12 | Widget `value=` differs from the config default (cores 4 vs 1, branch dev vs master, blank name) | L | static, confirmed; fixed |
| A13 | Negative controls cannot be declared before the first run has produced output | M | live, confirmed; fixed |
| A14 | The step grid: `min=1, step=50` accepts only 1, 51, 101 ...; the default 1000 cannot be typed back | H | live, confirmed (part of A2b); fixed |
| A15 | A missing `--config` file boots the app on defaults with two log lines | M | live, confirmed; fixed |
| A16 | A start that fails before Nextflow launches is announced as "Analysis Complete. Results are up to date." | H | live, confirmed; fixed |
| A17 | "Nextflow not found" is reported when `nextflow -version` fails for any reason (here: no Java runtime) | L | live, confirmed; fixed |
| B1 | Real-time-only fields are editable and saved in batch mode; Check Interval's help text does not say so | M | static, confirmed for Check Interval; field retired |
| B2 | `priority_samples` (129 taxids) is sent in batch mode where the pipeline never reads it | L | live, confirmed; fixed |
| B3 | Every mode-independent field with a non-default value reaches `params.json` with the right value and type | - | live, PASS (39 params, one int/float note) |
| B4 | Custom-named sample subdirectories (`Turex/`, `Zymo/`) pass Apply as by_barcode and are split into one sample per file by the pipeline | H | live, confirmed; fixed (both repos) |
| B5 | Memory mapping off reaches the kraken2 command line (no `--memory-mapping`) | - | live, PASS |
| A18 | Kraken2 confidence and minimum hit groups reach only the optional `KRAKEN2_OPTIMIZED` module; the default batch classifier and the real-time incremental classifier never receive them | H | live, confirmed (both repos); fixed (nanometanf) |
| A19 | A failed run's errors are never cleared at the next Start; the following successful run is recorded and shown as PIPELINE ERROR | H | live, confirmed; fixed |
| A9b | The CPU Cores widget targets `BLAST_BLASTN`, `NANOPLOT`, `EXTRACT_VALIDATION_SEQS`; the validation processes are `BLASTN_VALIDATION` and `EXTRACT_READS_BY_TAXID`, so no cores value reaches any task | M | live, confirmed; fixed |
| P1 | `qc_tool: filtlong` aborts every multi-file sample: the nf-core module takes one positional file | H | live, confirmed (nanometanf); fixed |
| P2 | `assembler: miniasm` aborts the run: minimap2 all-vs-all stages the same file twice (input file name collision) | H | live, confirmed (nanometanf); fixed |
| P3 | `.nanometa.run.json` records `processes_failed: 0` and no failed task for a fatal process failure; the banner shows Nextflow's generic text without the process name | M | live, confirmed; fixed |
| C1 | Check Interval does nothing: `batch_interval` is only logged; with `batch_size` 1 every file is a batch on arrival (classifier tasks 6 to 15 s apart under a 300 s setting) | H | live, confirmed; field retired |
| C2 | Maximum file age does not exclude anything: nanometanf uses `max_avg_file_age_minutes` only as a "high file age" alert threshold in `UPDATE_CUMULATIVE_STATS`; six files aged 3 h were classified under a 60 min setting | H | live, confirmed (both repos); fixed (both repos) |
| C3 | Running totals OFF in real time | | pending (RT2) |
| C4 | Empty timeout sent as JSON null; hand-edited 0 rejected by the schema while the GUI reads it as "no timeout" | H | static confirmed for 0; fixed (0 sent as null); null pending (RT3) |
| C5 | GUI countdown = timeout + config grace (1); pipeline budget = timeout + its own default grace (5), the config value is never sent | M | live, confirmed (see evidence); fixed |
| C6 | `priority_samples` = 129 taxids; pipeline logs "Priority routing ENABLED" and matches them against sample ids | M | live, confirmed; fixed |
| C7 | Adaptive batching on, effective batch size 1 for the GUI's values | L | live, refuted as a defect |
| C8 | Assembly in real time runs Flye on every 2000-read batch; each fails ("No overlaps found") and is skipped, counted in the header as failed tasks | M | live, confirmed; fixed (not run in real time) |
| C9 | Validation settings reach the per-batch modules: `-perc_identity 80 -evalue 0.001`, minimap2 `min_mapq=20 identity_threshold=80` | - | live, PASS |
| C10 | Chopper `--quality 7 --minlength 501 --maxlength 20001` per batch; `skip_nanoplot` honoured | - | live, PASS (krona/stats checked at run end) |
| C11 | Apply during a run then Continue | | pending (RT4) |
| C12 | sample_handling in real time | | pending (RT5) |
| C13 | Real-time by_barcode on a flat directory passes Apply with no message (batch rejects it with a suggestion) | M | static, confirmed; fixed |
| C15 | Update interval 5 s gives a ~5 s poll cadence | - | live, PASS |
| C16 | An empty genome cache folder silently disables validation (log warning only; `blast_validation` sent as false while the switch shows on) | M | live, confirmed; fixed |

## Evidence

### A1 to A12: static probes

`tests/test_config_tab_audit_r5.py` (20 probes, 16 red before the fix pass).
Baseline suite: 4478 passed, 126 skipped.

### A2b and A14: what the number inputs refuse

Probe: type into `chopper-minlength-input` (min 1, max 50000, step 50),
press Tab, Apply, read `last-session.yaml`.

| typed | `validity.stepMismatch` | saved |
|---|---|---|
| 500 | true | unchanged |
| 1000 | true | unchanged |
| 550 | true | unchanged |
| 501 | false | 501 |
| 2000 | true | unchanged |
| 1234 | true | unchanged |

The HTML step base is `min`, so with `min=1` the accepted grid is 1 + 50k.
`chopper-maxlength-input` (min 1, step 100) accepts 20001 and refuses 20000;
`max-file-age-input` (min 0, step 60) accepts only whole hours although the
label says minutes; `validation-identity-input` refuses 120 by `max`. In every
case the widget keeps the typed value, the toast says "Changes Applied", and
the config keeps the previous value. Dash's number Input does not propagate
an invalid value to the server, so the server-side range validator never sees
these and the "Validation Error" toast is unreachable from the browser for
bounded fields.

### A6: reload keeps unsaved edits and clears the badge

Set `cores-input` to 5 without Apply, reload: the form shows 5, the Modified
badge is hidden, `last-session.yaml` says 1. Same for the profile select set
to docker. The `config-form-draft` session Store restores the edit and the
form-init cascade consumes the `form_initialized` flag, which resets the badge.

### A13: negative controls before the first run

The dropdown's options are the detected samples unioned with saved values. On
a batch config pointing at a by_barcode directory that has not been processed,
the list is empty, so a control cannot be declared before Start.

### A16: a failed start announced as complete

Toasts captured at 400 ms during a Start whose preflight failed:

1. Starting Analysis / Start running in the background...
2. Start failed / Nextflow not found. Please install Nextflow.
3. Analysis Complete / R5 batch has finished. Results are up to date.

The click writes the optimistic `{running: True}` to `backend-status`; the
next poll writes the real `running: False`; `announce_completion` sees
running -> not running and, with no `user-stop-requested` flag, reports a
finished run. No Nextflow process existed.

### B3: batch launch diff

`diff_launch.py launches/batch3 expected_batch3.json`: all mode-independent
fields OK. Mode-only drops as designed: `batch_interval`,
`realtime_timeout_minutes`, `kraken2_enable_incremental`,
`max_avg_file_age_minutes`. `validation_identity_threshold` is sent as int 80
where the config holds 80.0 (harmless). `priority_samples` carries 129 taxids.

### P1: filtlong

```
filtlong --min_length 801 --max_length 20001 --keep_percent 90 \
    FBE98306_pass_barcode08_..._23.fastq.gz FBE98306_pass_barcode08_..._22.fastq.gz ...
Error: passed in argument, but no positional arguments were ready to receive it
```

`modules/nf-core/filtlong/main.nf` is unpatched and takes `path(longreads)`
as one positional file; the chopper module carries a local `gunzip -c`
concatenation. Every barcode of the corpus has many files.

### P2: miniasm

```
Process ASSEMBLY:MINIMAP2_ALIGN input file name collision -- There are
multiple input files for each of the following file names: barcode05.chopped.fastq.gz
```

`subworkflows/local/assembly/main.nf` passes the reads as both query and
reference for the all-vs-all overlap; the nf-core minimap2/align module stages
both under the same name.

## Measurement caveats

- Launching the app with the env's python directly (to keep stdout) needs the
  env activated (`source miniforge3/bin/activate nf-core`): Nextflow finds its
  Java through the env's activation script, and without it every start fails
  with "Nextflow not found" (A17).
- Each headless driver session is a fresh browser context, so `app-config`
  hydrates from the boot config and an Apply from that session overwrites the
  previous session's applied values in `last-session.yaml`. Apply and Start
  must happen in one session.
- The number-input step rule (A14) means a scripted matrix must use grid
  values (501, 801, 20001, 60), or the launch silently carries the defaults.
- A relative `--config` path with a launcher that changes directory boots the
  app on defaults (A15).

## Fix pass (2026-09-03)

Every confirmed finding except the three pending live runs (C3, C11, C12)
and the null-timeout half of C4 has a fix and a pinning test. The probes in
`tests/test_config_tab_audit_r5.py` assert the expected behaviour and are
green against the fixed build; the file stays as the audit's regression set.

### nanometa_live (dev)

- **Form lifecycle.** A1 (Output arity derived from the registry); A2/A3
  (the validating callback owns the feedback alert, the snapshot and the
  badge; the click-only rebase callback is gone); A4/A5 (`kraken2_confidence`
  and `kraken2_minimum_hit_groups` written by `default_config()`, an absent
  `kraken_memory_mapping` compares as True, every form-loader fallback reads
  `config_loader.default_config()`); A6 (a draft-restored form is not marked
  initialised, so the badge reflects the restored edits); A7 (Reset rebases
  the snapshot and persists like Apply); A10 (hit groups bounded and
  non-numeric reported; the update-interval floor is 5, matching the widget);
  A11 (`fastq_input_dir` / `barcode_input_dir` / `remove_temp_files` remnants
  removed); A12 (widget defaults follow the config defaults, the branch parse
  fallback is dev); A13 (the negative-control options include the input
  directory's sample folders).
- **Number inputs (A2b/A14).** Integer fields carry `step=1`, float fields
  `step="any"`. The Apply click first runs a browser-side `checkValidity()`
  pass over the form and writes `apply-config-request`; the server Apply
  fires from that Store and refuses with the invalid fields named, since a
  refused value never reaches the server at all.
- **Launch mapping.** A9/A9b (`max_cpus` replaces the three cores keys;
  the `-c` config carries no validation cpu pins); B2/C6 (`priority_samples`
  not sent); C1 (Check Interval retired; `batch_interval` not sent); C2
  (`max_file_age_minutes` sent to the new nanometanf param; empty = process
  every file); C4 (0 sent as null); C5 (grace period sent when configured);
  C8 (`enable_assembly` dropped in real-time mode, the form says so); B4
  (batch by_barcode with a custom-named folder generates a samplesheet).
- **Run state.** A16 (the completion detector arms only on an authoritative
  running status); A19 (a Start clears the previous run's errors); P3 (a
  fatal process failure is named in `failed_tasks` / `processes_failed`);
  A15 (a missing `--config` file is fatal in full mode too); A17 (the
  Nextflow probe reports what `nextflow -version` said); C13 (a real-time
  by_barcode config on a directory that already holds flat files is
  rejected like batch); C16 (validation silently off is a launch warning the
  "Analysis Started" toast shows).

### nanometanf (dev)

- A18: `--kraken2_confidence` / `--kraken2_minimum_hit_groups` through
  `ext.args` on `KRAKEN2_KRAKEN2` and `KRAKEN2_INCREMENTAL_CLASSIFIER`.
- P1: the patched filtlong module concatenates a multi-file sample.
- P2: a local `MINIMAP2_AVA` module (single input, `-x ava-ont`) replaces
  the reads-as-reference call of nf-core minimap2/align. Verified by a stub
  run: `MINIMAP2_AVA` executes and `MINIASM` receives the joined paf
  (MINIASM's own version probe needs the tool, which stub mode without conda
  cannot provide).
- B4/C12: `InputDetector.sampleSubdirs` treats every direct subfolder
  holding reads as a sample (MinKNOW bins excepted); `INPUT_SCANNER` iterates
  it; `extractSampleId` takes the input root.
- C2: `--max_file_age_minutes` applied to the start-up listing in
  `RealtimeIntake.partitionExisting`.
- 28 nf-tests green (`tests/lib/input_detector.nf.test`,
  `tests/lib/realtime_intake.nf.test`, `tests/input_scanner.nf.test`),
  including seven new cases.

### What the smoke test added

Driving the fixed build in a browser (synthetic dataset
`06_pathogen_detected`) caught one defect the unit suite could not: the blank
CPU Cores widget submits `""`, and the range check's `cores < 1` raised
`TypeError`, so EVERY Apply returned HTTP 500. The empty-means-default fields
now parse before comparing, pinned in `tests/test_config_range_validation.py`.
After the fix: the out-of-range drill showed "Validation Error - Nothing was
applied. These values are outside the field's allowed range: - Validation
identity threshold (%): "120" (allowed 0 to 100)", a valid edit reached the
server validator, and all nine tabs rendered with zero console errors.

### Still open

- C3 (running totals off), C11 (Apply during a run, then Continue), C12
  live (real-time sample handling on the three layouts) and the null half of
  C4 need the RT2 to RT5 runs; the static halves are fixed.
- A8 wording only; A17 root cause (the env's Java) is a launcher matter.
- The miniasm path has been verified in stub mode only; a conda run of the
  assembly subworkflow is the remaining check for P2.
