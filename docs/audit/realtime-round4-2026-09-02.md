# Real-time mode audit, round 4 (nanorunner-driven), 2026-09-01/02

**Scope.** How a real-time run ends (timeout, Stop, Continue), what the
operator is told when the run and the input disagree, and the transient
states that exist only while the pipeline rewrites files under the dashboard.
Earlier rounds (2026-05-09, 2026-08-18, 2026-09-01) had left these
unexercised.

**Method.** Static reading of both repositories produced twenty-two numbered
hypotheses before any run. Three real-time runs plus three Stop drills, one
Continue drill on a stopped outdir, one Continue drill on a completed outdir,
one mid-run export, one corrupt-input injection and one hard kill were then
driven with nanorunner 3.1.0 against the Bioshield demo corpus and the
129-entry `bioshield_agents` watchlist. A 2 s sampler
(`scripts/audit_realtime_timeline.py`) recorded what the dashboard's own
loaders return per tick, and the operator view was read from the browser.
Every claim below states whether it was confirmed live, confirmed from code
only, or refuted.

## Results at a glance

| Id | Finding | Status | Severity |
|---|---|---|---|
| H1 | Real-time timeout is wall-clock in the pipeline, "inactivity" in the GUI text | live | high |
| H5 | Files arriving after the run ended are never mentioned | live | high |
| H2 | Stop and inactivity-stop record no terminal status; stopped run renders as never-started | live | high |
| H13 | A mid-run export is indistinguishable from a final report | live | high |
| H33 | Collision Continue/Archive launches into a fresh hidden outdir | live | high |
| H34 | A new tab carries the boot-time config, not the session's | code | high |
| H20 | An input file lost to error isolation is invisible, during and after the run | live | high |
| H6 | Aggregate drops whole samples for a tick at tier switches | live (sampler) | medium |
| H6b | Per-sample view reads the previous run's canonical JSON after Continue | live | medium |
| H7 | Manifest replaces disk discovery; a late barcode is hidden after Continue | live | medium |
| H15/H19 | Continue reclassifies everything from zero and doubles the batch tree | live | medium |
| H24 | A config naming a watchlist that cannot be found loads zero entries silently | live | medium |
| H28 | "1 sample serving stale data" stays on a healthy run to completion | live | medium |
| H26 | Per-sample values lag the aggregate by one batch | live (sampler) | medium |
| H10 | On-demand validation has no running-guard | code (prerequisite refused it live) | medium |
| H11 | Apply Settings mid-run is unguarded | code | medium |
| H4 | `.fq.gz` never watched; `fastq_fail/` merged; startup blind window | code; blind window not reproduced | medium |
| H21 | Per-batch QC files collide within one second | code | medium |
| H23 | Never-created results dir renders as RESULTS UNAVAILABLE | live | low |
| H36 | "Files processed: N / M" with N > M | live | low |
| H3 | Stop classified by the monitor thread as completed/error | code; not reproduced (fast exit) | low |
| H17, H18, H22, H27, H35 | Nested glob missing from no-data mapping; unguarded per-batch validation parse; latest-batch fallback; batch-vs-cumulative arithmetic; removeChild on button flip | code / minor live | low |
| H25 | Frozen dashboard tab | retracted: Chrome throttling a hidden tab | none |
| H9, H12 | Batch ordering; negative-control memo | verified sound | none |

## How the runs were driven

```
~/nanometa-audit-r4/run.sh <name> <config> <port>     # fresh outdir + watch dir, app, sampler, snapshots
~/nanometa-audit-r4/run_keep.sh ...                    # same, keeping outdir (Continue drills)
nanorunner replay --source ~/nanometa-demo/data/multiplex --target <watch> \
  --operation copy --force-structure multiplex --reads-per-file 2000 --interval 15 --batch-size 1
```

| Run | Setup | Wall time |
|---|---|---|
| R1 | 5 barcodes, `realtime_timeout_minutes: 3`, 47 files over 11.7 min | 22:49-23:01 |
| R2 | timeout 30, late `barcode91` at +6 min, negative control applied at +6, export at +3, Stop at +16 | 23:07-23:23 |
| R2c | Continue on R2's stopped outdir, late barcode, Stop on a busy run | 23:33-23:42 |
| R1c | Continue on R1's completed outdir, late barcode, corrupt chunk, Stop; rerun to timer | 23:45-00:32 |
| R6 | Archive + Start then Stop at 7 s; Archive + Start then `kill -9` at 47 s | 23:56, 06:35 |

The conda environment cache was lost to a disk clean before R1, so R1's first
minutes were environment builds; every later run had a warm cache and its
first cumulative report inside a minute.

## Findings

### H1. One key, three semantics (confirmed live)

The pipeline schedules a one-shot wall-clock timer at
`realtime_timeout_minutes + realtime_processing_grace_period` from monitoring
start (`subworkflows/local/realtime_monitoring/main.nf:231-282`); nothing
resets it, although its own log line says "(idle)". The GUI tooltip
(`app/components/config_form.py:775`) promises a stop "after this many minutes
without new files". The GUI backstop (`core/workflow/backend_manager.py:1036-1116`)
is a genuine inactivity timer on task progress. The banner's auto-stop chip
counts wall-clock from `start_time` (`:966-976`).

R1, timeout 3: timer fired at 22:57:38, exactly 480,000 ms after monitoring
start, with the feeder still writing every 15 s. Nextflow reported "Pipeline
completed successfully" at 23:00:41. Header: "Complete, Pipeline finished
successfully". Banner: COMPLETE. `final_status: completed`. Of 47 input files,
33 were classified; the 14 that landed after the timer were never processed.
R2 showed the chip at "Auto-stop in 29m 00s" one minute in, against a pipeline
timer of 35 minutes.

With the default of 60, a sequencing run longer than 65 minutes is cut
mid-stream and reported complete.

### H5. Nothing compares input to processed (confirmed live)

`_update_file_counts` runs only while running (`backend_manager.py:928-929`);
the readiness fingerprint hashes config keys, not directory contents
(`readiness.py:122-136`). After R1 ended, 14 files sat unprocessed in the
input directory and no surface said so. The sample selector is results-tree
derived (`callbacks/samples.py:192-200`), so an input barcode without output
does not exist in the UI rather than showing as pending.

### H2. Stopped runs have no terminal state (confirmed live, three drills)

`_record_final_status` is called from every branch of
`_apply_terminal_workflow_status` but not from `stop()`
(`backend_manager.py:841-877`) nor from the inactivity stop (`:1103-1116`). All
three Stop drills ended with `final_status` absent, the report generated by
`stop()` with no run-state wording, the header reverted to "STANDBY, Click
'Start Analysis' to begin processing" and the verdict badge to STANDBY, while
the banner correctly kept ACTION REQUIRED with its detections. The inactivity
stop's reason goes into `status["errors"]`, which `update_status_display`
renders only for `pipeline_status == "error"` (`callbacks/status.py:172-178`).
`select_verdict` has no stopped or partial input.

The H3 race (monitor thread classifying the dying process before `stop()`
records it) is real in the code (`stop()` calls `workflow_manager.stop()`,
which blocks up to 30 s, before setting its own status) but did not
materialise: Nextflow exited within one to two seconds on all three drills.
It needs the SIGKILL fallback path to bite.

The hard kill behaved well: `final_status: error` within one second, header
ERROR, banner PIPELINE ERROR with the exit code and failing process.

### H13. The interim export (confirmed live)

Export at 3 min 23 s into R2 produced "Generated 2026-09-01 23:10:49, 5
samples, ACTION REQUIRED - 14 high-priority organisms detected, 5,103 Total
Reads". No run-state word appears in report.html, metadata.json or
summary.json. `generate_export` takes no `backend-status`; `_collect_data`
reads `read_final_run_status`, which treats an absent `final_status` as the
no-error case (`core/export/run_status.py:20-23`). The auto-reports written at
R1's timeout and at each Stop are worded identically to a report over a run
that drained its input.

### H33. Continue and Archive launch into a hidden directory (confirmed live)

The first-Start handler (`app/callbacks/start_stop.py:84-96`) resolves
`results_output_directory` via `resolve_run_outdir` and injects it into the
config. The collision handler (`:289-332`) sets `backend_manager.config` to the
app-config State as is. On R2c that State had `results_output_directory: ''`
(confirmed in the written `config.json`), so `create_nextflow_params` fell
back to a fresh `~/.nanometa/data/analysis_20260901_233348`. The pipeline
wrote there, the viewer followed ("Viewing: .../analysis_20260901_233348"),
the modal had promised "Continue (resume) -- Reuses the existing results" in
results/r2, and `-resume` cache-hit nothing. The operator watched 16,716
reads and 13 pathogens fall to 340 and 3 and climb again. The same State
lacked the negative control applied twenty minutes earlier.

### H34. A new tab carries the boot-time config (confirmed from code)

`app.py:349-358` builds `app.layout` once with `dcc.Store(id='app-config',
data=config)` from the startup config. Applied changes live in the tab that
applied them and in `last-session.yaml`, which only the boot-time Resume
banner reads. Two tabs of one running app carry different configs; whichever
tab clicks Start decides the run. H33 is one consequence.

### H20. A lost input file is invisible, during and after the run (confirmed live)

A corrupt gzip chunk written into barcode06 at 23:47:48 was counted by
`GENERATE_SNAPSHOT_STATS` ("Files processed: 1, Estimated reads: 120"),
reached CHOPPER at 23:52:43, failed with exit 1 ("gzip: invalid compressed
data"), and Nextflow logged "Error is ignored". Forty-seven seconds later the
dashboard carried no word matching fail, isolated, corrupt or error; System
Alerts held only pathogen alerts; the header read "Files processed: 66 / 63",
counting the lost file as processed. The trace row is FAILED and the backend
already parses `processes_failed`; nothing renders it while running.

The end-of-session marker does not cover it either. On the completed rerun,
barcode06's `aggregation_stats.json` says `batches_complete: True, 11 of 11`,
the manifest lists no failed sample, and the report says nothing. Batch ids
are assigned after QC, so a file that dies in QC is never an expected batch.
For a kraken2-stage loss the marker exists but nanometa_live never reads it
(grep: zero hits).

### H6. The aggregate drops whole samples at tier switches (confirmed via sampler)

R1's 2 s sampler recorded 86 violations, all at the switch from per-batch
reports to a sample's first progressive cumulative report. At 22:54:17 the
aggregate fell 1,614 to 619 reads, three of five samples unmeasured for one
tick, F. tularensis 343 to 129, S. aureus vanished; at 22:54:21, 2,081 to
1,462. Mechanism: the new cumulative file is younger than the 1 s stability
gate (`loader_utils._is_file_stable`) and has no last-good frame under its new
path (`classification_loaders.py:262-281`); the tier it replaces is not
consulted. `select_verdict` has no hysteresis. With an alert threshold between
the two values the verdict would have flipped for a tick. The pipeline side
is atomic for the mid-run writer (`taxonomic_classification/main.nf:379-388`,
temp plus rename) and non-atomic only for the end-of-session publishDir copy.

`unmeasured_samples` reported nothing on those ticks. The sampler artefact
noted below may explain part of that; a unit reproduction from the 20 s
snapshots is needed.

### H26 and H27. Per-sample lag, and two counts for one sample (confirmed via sampler)

In 41 of 308 fully measured R1 ticks the aggregate exceeded the sum of
per-sample totals, by one batch per lagging sample, for up to 15 s. At the tier
switch the batch-report accumulation and the progressive cumulative disagree
by a few reads (1,616 to 1,614 total; E. coli 35 to 30). The cumulative
matches seqkit's QC-passed total (9,697), so the accumulation is the suspect.
Both need an offline reproduction.

### H6b, H7, H15, H19. Continue on a completed outdir (confirmed live, R1c)

- At 23:47:17 `kraken2/barcode05.cumulative...` (rewritten by the continued
  run at 23:47:09) totalled 69 reads; `load_kraken_data(r1, "barcode05")`
  returned 2,627 from the previous run's `canonical/classification/
  barcode05.classification.json` (`classification_loaders.py:630-635`
  prefers canonical for a named sample only); "All Samples" returned 3,607
  from the new files. Per-sample surfaces showed the old run, the banner the
  new one.
- `kraken2/barcode91/` existed on disk at 23:46:29; `canonical/_manifest.json`
  listed the five previous samples; `get_available_samples`
  (`sample_detector.py:470-475`) returned exactly those five for the whole
  continued run. On a fresh run (R2) the late barcode was discovered within
  12 s and named in the banner within two minutes, because the manifest is
  written only at session end.
- Continue re-emitted all 47 existing files ("Files processed: 43 / 51" at
  49 s); every file's meta carries a wall-clock stamp
  (`realtime_monitoring/main.nf:447`), so no task cache-hits. The cumulative
  writer restarts from zero (`taxonomic_classification/main.nf:334-336`); the
  aggregate visible to the operator fell 9,697 to 8,288 to 6,466 to 3,473
  before climbing. barcode05 ended with 16 `batches/` entries against R1's 8.

### H24. A config's watchlist can be silently absent (confirmed live)

`watchlist: {enabled: true, builtin: [bioshield_agents]}` under a new config
filename gets a new project dir (`~/nanometa-projects/<stem>`), whose
`.nanometa/watchlists` is empty; `bioshield_agents` is not a package built-in.
The manager resolved nothing, logged nothing, the Watchlist tab showed 0
total, and readiness demoted it to a WARNING as if the operator had chosen no
list. The downstream NOT_SCREENED guard would have caught the verdict; the
configuration's stated intent was contradicted without a word.

### H28. A staleness flag that never clears (confirmed live)

"1 sample serving stale data" appeared in R2's banner at 23:14:13, right after
the late barcode's tier switch, and was still there at 23:16:52 while every
report parsed cleanly in a fresh process (6 cumulative, 108 batch reports,
all stable). On R1c's completed rerun it was still on the COMPLETE banner six
hours later. Suspect the (scope, sample) key derived from a batch_reports path
differs from the one derived from the cumulative path, so the parse-ok under
the new tier never clears the flag set under the old tier.

### Other confirmed items

- **H10.** `run_on_demand_validation` takes no `backend-status`; the on-demand
  launch shares the live run's launch dir and work dir and adds a bare
  `-resume`. Live, the click was refused by a data prerequisite ("per-read
  output files not found", `save_reads_assignment` unset), so the session
  collision itself was not exercised.
- **H11.** `apply_config_changes` has no running guard and recomputes
  `results_output_directory` on every Apply. Applied mid-run in R2 without
  visible harm because the override was set.
- **H4.** Real-time pattern `**.fastq{,.gz}` excludes `.fq`; nothing excludes
  `fastq_fail/`; the startup scan and the watcher baseline leave a window. All
  33 files that landed before R1's timer were processed, so the blind window
  was not reproduced in one run.
- **H21.** Per-batch seqkit filenames derive from a second-granularity
  `batch_time` and collide under bursts (`conf/modules.config:92`). Not
  measured live.
- **H23.** A results directory that does not exist yet renders as RESULTS
  UNAVAILABLE with the mounted-volume wording, before Start, on every run.
- **H36.** "Files processed: 105 / 63" after Archive plus Start: re-emitted
  files are counted against a moving inbox.
- **H35.** The two React `removeChild` console errors fire at the moment the
  Start/Stop button flips (Playwright console, 587 s = first Stop click).
- **Stop is two clicks.** `stop-confirm-modal` must be confirmed; a click on
  the header button alone stops nothing. Not a defect; a runbook note.

### Refuted or retracted

- **H25**, a dashboard tab that stopped polling for five minutes after Start,
  was Chrome suspending timers in an occluded window (`document.hidden` was
  true). Bringing the tab forward resumed polling within one tick. The
  app-side residue is that a page two minutes stale looked alive; a
  clientside "not refreshed for N min" badge would make a stalled page look
  stalled whatever the cause.
- **H7 fresh-run case**: a late barcode on a fresh run is discovered from disk
  because the manifest does not exist yet.
- **H9** batch ordering and **H12** the negative-control memo are sound.

## Measurement caveats

- The Chrome MCP tab went hidden twice while covered by the terminal; every
  browser reading between 23:19 and 23:32 is suspect. Operator-view readings
  after 23:32 came from a headless Playwright browser, which is never
  occluded.
- `unmeasured_samples()` returns the value cached by the last attribution
  build for that sample tuple; a probe that does not run the build each tick
  reads a stale answer. The sampler's `unmeasured` column is unreliable; its
  per-sample rows and aggregate are direct loader calls and are not.
- The demo launcher wraps the app in `conda run`, which swallows the app's
  stdout and stderr; every app log for these runs is empty. Launch with the
  environment's python directly for any run whose server log matters.
- 2,000 reads per input file and chopper's defaults pass about 15% of this
  corpus; "sequences analyzed" is the QC-passed count.

## Not exercised

Sample handling modes other than `by_barcode`; scales beyond six samples; the
H3 race under a slow shutdown; the H10 session collision with
`save_reads_assignment` set; H21 under a same-second burst; a real MinKNOW
producer; Linux.

## Tooling kept

- `scripts/audit_realtime_timeline.py`: 2 s sampler and `--check` for
  monotonicity, vanished detections and measured-to-unmeasured flips.
- `~/nanometa-audit-r4/`: configs, timelines (`timelines/*.jsonl`), 20 s
  results snapshots, events log, feeder and stop-watch logs.

## Fixes shipped with this audit (nanometa_live `dev`, 2026-09-02)

| Finding | Change | Pinned by |
|---|---|---|
| H2, H3, H13 | `stop()` and the inactivity backstop declare intent before signalling Nextflow, record `final_status: stopped` with reason, time, files processed and inbox; STOPPED badge and header; report clause for stopped and interim (lock-file) exports | `tests/test_stopped_run_state.py`, `tests/test_report_generator.py::TestRunStateParity` |
| H33 | Collision Continue/Archive resolves the outdir like the first Start and pins the directory the modal showed | `tests/test_start_stop_callbacks.py::TestCollisionDecisionResolvesTheOutdir` |
| H34 | A new tab merges the running app's config into its Store on the first tick or tab click | `tests/test_startup_callbacks.py::TestNewTabGetsTheLiveRunConfig` |
| H7, H6b, H17 | Manifest unioned with disk discovery; canonical JSON wins only when no older than the sample's reports; nested `batch_reports/` counts as output | `tests/test_continue_loader_state.py` |
| H10 | On-demand validation refuses to arm while the pipeline runs; modal read count uses `cumul_reads` | `tests/test_main_tab_callbacks.py::TestOnDemandValidationWhileRunning` |
| H20 | `processes_failed` reaches the header and the verdict subtitle | `tests/test_stopped_run_state.py::TestFailedTasksAreNamed` |
| H5 | Inbox refreshes after the run; header, metadata and report state the unprocessed-input gap for real-time runs | `tests/test_stopped_run_state.py::TestUnprocessedInputIsNamed` |
| H1 | nanometanf timer resets on every detected file; GUI text and countdown (anchored on the newest input file, timeout plus grace) follow | `tests/test_realtime_timeout_contract.py` |
| H24 | `unresolved_watchlist_ids` feeds a CRITICAL readiness check and the startup toast | `tests/test_unresolved_watchlists.py` |
| H23 | Results-fingerprint Store carries a sticky `dir_seen`; a never-created directory is STANDBY | `tests/test_verdict_banner_callback.py::TestNeverCreatedDirIsNotLost` |
| H21, H4 (pattern) | nanometanf per-batch QC filename carries `batch_id`; real-time pattern includes `.fq` | nanometanf `conf/modules.config`, `nextflow.config` |

## Still open after this session

- **H6, H26, H27, H28** (loader transients: tier-switch drop, per-sample lag,
  batch-vs-cumulative arithmetic, the permanent stale flag). Each needs an
  offline reproduction from `~/nanometa-audit-r4/snapshots/`, replaying
  successive snapshots through one long-lived loader process with mtimes
  touched to "now". The sample-key derivation was checked and is not the
  cause of H28.
- **H15, H19** (Continue reclassifies everything and doubles the batch
  tree). The collision modal's "skip already-completed steps" wording is
  wrong for a real-time run; the pipeline's per-file wall-clock meta stamp
  is the reason no task can cache-hit.
- **H20 pipeline side.** A QC-stage failure is never an expected batch, so
  `aggregation_stats.json` cannot see it; a per-file loss marker written when
  the task is ignored would close this.
- **H4 blind window, H11, H36, H35** and the unexercised list above.
