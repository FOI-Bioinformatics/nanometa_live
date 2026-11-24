# Barcelona Exercise Feedback Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six issues from the October 2026 Barcelona exercise that are still present in nanometa_live 0.20.0 / nanometanf 1.12.0, and provide a triage tool for the questions that need the exercise's run data.

**Architecture:** One pipeline change (nanometanf records Chopper's own input/output read counts) and seven GUI changes. Each GUI change puts its rule in one pure helper with unit tests, and the callbacks only call it. Nothing new is sent to the pipeline, so the nanometanf floor (1.12.0) does not move: the GUI uses the Chopper counts when they exist and keeps today's "not recorded" text when they do not.

**Tech Stack:** Python 3.11+, Dash 4, pandas, pytest (`conda run -n nf-core python -m pytest`); Nextflow 26.04 + nf-test for nanometanf.

**Spec:** the feedback review given in the session of 2026-11-24 (presentation `~/Downloads/Nanometalive_Barcelone_presentation.pptx`, run on v0.18.0). The findings this plan implements, numbered as in that review:

1. Reports tab "Total reads 596,019" and "Reads/sec" are a file-size estimate (`file_size * 4 / 4000`, nanometanf `subworkflows/local/realtime_monitoring/main.nf:759`) labelled as counts.
2. No read count before filtering for Chopper; the QC tab says "not recorded", so the operator cannot see how many reads the filter removed or compare with MinKNOW.
3. "High confidence" means >= 100 reads on Dashboard cards and >= 1000 on Organisms cards, shows no threshold, and reads as if confirmation was done.
4. A restarted app opened on a finished run's results shows STANDBY, "Click 'Start Analysis'", run time 00:00:00.
5. MinKNOW's `unclassified` barcode folder is listed among a detection's samples with nothing saying it holds reads without a barcode.
6. Base statistics (SeqKit, ~49,900 reads) and read counts (Kraken2, 76,642) come from different read sets with no indication on screen.
7. (Slide 2, needs data) Which readiness checks failed, and why the start stayed in STANDBY: answered by the triage script plus owner actions below.

## Global Constraints

- No Unicode in Nextflow files (`.nf`, `.config`, nf-test files): ASCII only.
- Modest scientific language in code, comments, UI text and documentation.
- nanometanf work is committed to `dev` only; never merge to `master` outside a release.
- No back-compat shims: drop the `high_confidence_reads` / `medium_confidence_reads` config reads outright.
- Every module-level cache is wired into both `clear_all_loader_caches` (`nanometa_live/core/utils/loader_utils.py:264`) and `reset_caches` (`scripts/perf/instrument.py:147`); `tests/test_cache_inventory.py` is the fence.
- `dashboard_tab.py` must not take `Input("sample-selector", ...)` (fence `tests/test_dashboard_metrics_trigger.py`); read `selected-sample`.
- Code-size gate: `python scripts/check_code_size.py` must pass; shrink the baseline with `--update` only when a function got smaller.
- Each task adds its own line under `## [Unreleased]` in the repository's `CHANGELOG.md`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A run in progress must never be described as a previous run.** `previous_run_status` is consulted only in the STANDBY fallback; a test in Task 6 drives `update_status_display` with `running: True` and a completed metadata file and expects the running text.
2. **A Chopper counts file that is still being written** (empty, or no "Kept" line yet) is skipped this poll and not cached, so it counts on the next poll. Test in Task 3.
3. **A run continued into the same results folder** sums the counts of both runs, matching the cumulative Kraken2 report it is shown beside. Test in Task 3 (two stamps for one sample both summed).
4. **A run with no Chopper counts at all** (fastp, filtlong, a pre-1.13 nanometanf) renders exactly as today. Test in Task 4.
5. **Zero reads** gives read support "none" and no badge text claiming support. Test in Task 5.

---

### Task 1: Reports tab labels the pipeline's read estimate as an estimate

**Files:**
- Modify: `nanometa_live/app/tabs/reports_helpers.py:17-22` (`_kpi_tile`), `:100-104` (KPI row), `:113-116` (trend axis)
- Test: `tests/test_reports_helpers.py` (create)

**Interfaces:**
- Produces: `_kpi_tile(value: str, label: str, icon: str, title: Optional[str] = None) -> dbc.Col`; `ESTIMATE_NOTE: str` in `reports_helpers.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_estimated_reads_tile_is_labelled_as_estimate():
    panel = build_realtime_performance_panel({"totals": {"total_estimated_reads": 596019},
                                              "performance": {"reads_per_second": 168.0}})
    text = _all_text(panel)          # small helper: flatten component children to one string
    assert "Reads (estimated)" in text
    assert "Est. reads/sec" in text
    assert "Total reads" not in text

def test_estimate_tiles_carry_the_explanation_as_title():
    panel = build_realtime_performance_panel({"totals": {"total_estimated_reads": 10}})
    assert ESTIMATE_NOTE in _all_titles(panel)
```

- [ ] **Step 2:** Run `conda run -n nf-core python -m pytest -q -n0 tests/test_reports_helpers.py` and confirm both fail.
- [ ] **Step 3: Implement.** `_kpi_tile` puts `title` on its outer `html.Div`. Labels: `"Est. reads/sec"`, `"Reads (estimated)"`; trend `yaxis_title="Reads (estimated)"`. `ESTIMATE_NOTE = "Estimated by the pipeline from file size, not counted. Counted reads are on the Quality Control tab."`, passed as `title` to both read tiles.
- [ ] **Step 4:** Re-run the test file; expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit: `fix(reports): label the pipeline's file-size read estimate as an estimate`.

---

### Task 2 (nanometanf): CHOPPER records its read counts

Work in `~/Code/nanometanf` on `dev`.

**Files:**
- Modify: `modules/nf-core/chopper/main.nf` (recorded as an nf-core patch), `conf/modules.config:148-175` (`withName: 'CHOPPER'`)
- Create: `tests/chopper_read_counts.nf.test`, fixture `tests/fixtures/chopper/three_reads.fastq.gz` (two reads >= 10 bp, one of 4 bp)
- Modify: `CHANGELOG.md`, `docs/output.md` (chopper section)

**Interfaces:**
- Produces: new output `tuple val(meta), path("*.chopper_counts.txt"), emit: counts`. Each file holds Chopper's own stderr, whose summary line is `Kept <kept> reads out of <total> reads` (verified for chopper 0.12.0b; Step 2 verifies 0.14.1). Published to `${params.outdir}/chopper/${meta.id}/counts/${meta.id}.<stamp>.chopper_counts.txt`, where `<stamp>` is built exactly like the SeqKit batch publish (`[meta.batch_time, meta.batch_id].findAll { it != null }.join('_')`, else `batch_${task.hash}`). Task 3 reads this layout.

- [ ] **Step 1: Write the failing nf-test** `tests/chopper_read_counts.nf.test` (tag `fast`): run process `CHOPPER` on the fixture with `ext.args2 = '--minlength 10'`. Assert `process.success`, one `counts` file, and that its text contains `Kept 2 reads out of 3 reads`.
- [ ] **Step 2:** Run `nf-test test tests/chopper_read_counts.nf.test --profile test,conda`. Expect failure on the missing `counts` output. While the conda env exists, confirm chopper 0.14.1 prints the same summary line; if the wording differs, use 0.14.1's wording everywhere below.
- [ ] **Step 3: Implement.** In the script, add `trap 'cat ${prefix}.chopper_counts.txt >&2 2>/dev/null || true' EXIT` as the first line and redirect Chopper's stderr with `2> ${prefix}.chopper_counts.txt`. The trap keeps Chopper's messages in `.command.err` when the task fails. The stub writes `Kept 0 reads out of 0 reads` to the file. Add the `counts` output. Record the patch with `nf-core modules patch chopper`. Turn the CHOPPER `publishDir` into a list: the existing entry gets `pattern: '*.fastq.gz'`, and a second entry with `pattern: '*.chopper_counts.txt'` uses the path and stamped `saveAs` above.
- [ ] **Step 4:** Re-run the nf-test (PASS), then `nf-test test --tag fast --profile test,conda` and the lint job's checks (`nf-core pipelines lint` offline where possible). The lost-input marker test must still pass, since the afterScript is unchanged.
- [ ] **Step 5:** Document the file in `docs/output.md` and add a CHANGELOG line. Commit to `dev`: `feat(chopper): record the read counts Chopper reports`.

---

### Task 3: Loader for Chopper read counts

**Files:**
- Create: `nanometa_live/core/utils/chopper_counts.py`
- Modify: `nanometa_live/core/utils/loader_utils.py:264` (`clear_all_loader_caches`), `scripts/perf/instrument.py:147` (`reset_caches`)
- Test: `tests/test_chopper_counts.py`

**Interfaces:**
- Consumes: Task 2's published layout `chopper/<sample>/counts/*.chopper_counts.txt`.
- Produces:
  - `class ChopperCounts(NamedTuple): reads_in: int; reads_kept: int; files: int`
  - `load_chopper_counts(main_dir: str, sample: Optional[str]) -> Optional[ChopperCounts]`. `sample` None or `"All Samples"` sums every sample. Returns None when no readable file exists.
  - `clear_chopper_counts_cache() -> None`

- [ ] **Step 1: Write the failing tests:**
  - `test_sums_batches_of_one_sample`: two files for `barcode01` (`Kept 80 reads out of 100 reads`, `Kept 40 reads out of 50 reads`) give `ChopperCounts(150, 120, 2)`.
  - `test_all_samples_sums_every_sample`.
  - `test_absent_directory_returns_none`.
  - `test_file_without_summary_line_is_skipped_and_not_cached`: write an empty file, expect None; then write the line (same path, newer mtime) and expect the counts.
  - `test_unchanged_file_is_not_reopened`: monkeypatch `builtins.open` to count calls, load twice, and expect one open per file.
  - `test_clear_all_loader_caches_clears_it`.
- [ ] **Step 2:** Run `pytest -q -n0 tests/test_chopper_counts.py` and confirm it fails (ImportError).
- [ ] **Step 3: Implement.**
  - Parse with `re.compile(r"Kept (\d+) reads out of (\d+) reads")`, taking the last match in the file.
  - Cache per file in `_COUNTS_CACHE: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]]` keyed by realpath, with value `((st_mtime_ns, st_size), (reads_in, reads_kept))`. Cache only parses that found the line, so an unfinished file is read again next poll.
  - Find files with a glob: `chopper/<sample>/counts/*.chopper_counts.txt`, or `chopper/*/counts/*.chopper_counts.txt` for the aggregate.
  - Wire `clear_chopper_counts_cache` into both reset functions.
- [ ] **Step 4:** Run the new tests plus `tests/test_cache_inventory.py`; expect PASS.
- [ ] **Step 5:** Commit `feat(loaders): read Chopper's own read counts`.

---

### Task 4: The QC tab uses the read count before filtering when Chopper recorded one

**Files:**
- Modify: `nanometa_live/app/tabs/qc_tab_helpers.py` (new helper), `nanometa_live/app/tabs/qc_tab.py:362-392` (stat lines), `:850-893` (stage strip), `:1020-1050` (`update_qc_action_guidance`)
- Test: `tests/test_qc_tab_helpers.py`, `tests/test_qc_tab_callbacks.py`

**Interfaces:**
- Consumes: `load_chopper_counts` (Task 3); `load_fastp_data(main_dir, sample) -> dict` (existing).
- Produces: `prefilter_read_count(main_dir: str, sample: Optional[str], fastp_stats: Optional[dict] = None) -> Optional[int]`. It returns fastp's `total_reads_before` when that is > 0, otherwise Chopper's `reads_in`, otherwise None.

- [ ] **Step 1: Write the failing tests:**
  - Helper: `test_prefilter_prefers_fastp`, `test_prefilter_uses_chopper_counts`, `test_prefilter_none_without_either`.
  - Callback (via `get_callback_fn`): build a tmp results tree with a Kraken2 report of 120 reads and Chopper counts of 150 in / 120 kept. Expect the stage strip to show `150` in the READS PROCESSED slot and no "not recorded" text. Expect the stat lines to contain `Raw reads (before filtering): 150` and `Total reads removed: 30 (20.0%)`.
  - Review Focus 4: the same tree without `chopper/` renders the current "not recorded" text.
- [ ] **Step 2:** Run the two test files and confirm the new tests fail.
- [ ] **Step 3: Implement** `prefilter_read_count` and call it at the three sites:
  - Stage strip: pass `raw_reads=` and set `is_chopper` False when a count exists.
  - Stat lines: replace the hard `tot_reads_pre_filt = 0` in the SeqKit fallback.
  - `update_qc_action_guidance`: `pre_filter=`.
  - No other wording changes. The existing `compute_qc_stat_lines` and `qc_guidance_issues` already handle a real pre-filter count.
- [ ] **Step 4:** Run the QC test files (`tests/test_qc_tab*.py`); expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit `fix(qc): show reads before filtering when Chopper recorded them`.

---

### Task 5: One definition of read support, labelled as read support

**Files:**
- Create: `nanometa_live/core/utils/read_support.py`
- Modify:
  - `nanometa_live/app/tabs/dashboard_helpers.py:394-425`: `compute_detection_confidence` and `_card_confidence` delegate.
  - `nanometa_live/app/tabs/main_tab.py:505-548` and `:688-697`: use the helper; remove the `high_confidence_reads` / `medium_confidence_reads` reads.
  - `nanometa_live/app/components/organism_components.py:276-300`, `:430-443`: labels and title.
  - `nanometa_live/app/components/pathogen_alert.py:264`, `:468`, and the `:510` card: card text.
  - `nanometa_live/app/layouts/main_layout.py:323`: help text.
  - `nanometa_live/app/app.py:709`: modal label.
  - `core/export/templates/report.html`: only if it prints the word "confidence" for a detection (grep first).
- Test: `tests/test_read_support.py` (create); update existing tests that assert "confidence" text (`git grep -n -i "confidence" tests | grep -i "high\|moderate"`).

**Interfaces:**
- Produces:
  - `READ_SUPPORT_HIGH = 100`
  - `READ_SUPPORT_MODERATE = 20`
  - `read_support_level(reads) -> str`, one of `"high"`, `"moderate"`, `"low"`, `"none"`. Unparseable input or 0 gives `"none"`.
  - `READ_SUPPORT_LABELS = {"high": "High read support", "moderate": "Moderate read support", "low": "Low read support", "none": "No reads"}`
  - `READ_SUPPORT_TOOLTIP = "100 or more classified reads is high, 20 to 99 moderate, fewer low. This counts reads only; it does not confirm the identification (see the Validation tab)."`

- [ ] **Step 1: Write the failing tests:**
  - `test_read_support_boundaries`: 0 gives none, 1 and 19 give low, 20 and 99 give moderate, 100 gives high, `"x"` gives none.
  - `test_organism_card_and_alert_card_agree_at_150_reads`: both rendered components contain "High read support".
  - `test_organism_card_at_500_reads_is_high`: today this is "medium", because the Organisms tab used 1000.
  - `test_no_card_says_confidence`: neither component's text contains "confidence".
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3: Implement.** Keep `compute_detection_confidence`'s return words ("High", "Moderate", "Low", "N/A"), because the report and modal code compare on them; it maps from `read_support_level`. The organism card's "medium" key becomes "moderate". Alert cards render `f"{READ_SUPPORT_LABELS[level]}"` with `title=READ_SUPPORT_TOOLTIP`.
- [ ] **Step 4:** Run the full suite `conda run -n nf-core python -m pytest -q` (wording changes ripple); expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit `fix(ui): one read-support rule on every card, named for what it measures`.

---

### Task 6: A reopened finished run is shown as that run, not STANDBY

**Files:**
- Create: `nanometa_live/app/utils/previous_run.py`
- Modify:
  - `nanometa_live/app/callbacks/status.py`: `update_status_display`. Add `State("results-dir-path", "data")`, and use the helper in the final STANDBY return at line 348.
  - `nanometa_live/app/tabs/dashboard_tab.py`: `update_verdict_banner`. Add the same State; when the backend is not running and the helper returns a run, fill `dashboard-time-elapsed` and `dashboard-run-state-badge` from it.
- Test: `tests/test_previous_run.py` (create), `tests/test_dashboard_tab_callbacks.py`

**Interfaces:**
- Consumes: `read_final_run_status(results_dir) -> dict` (`nanometa_live/core/export/run_status.py:126`), plus `written_at` from `.nanometa.run.json` (written at Start, `backend_manager.py:804`).
- Produces:
  - `@dataclass(frozen=True) class PreviousRun: run_state: str; started_at: Optional[str]; ended_at: Optional[str]; duration_s: Optional[int]; stop_reason: Optional[str]`
  - `previous_run_status(results_dir: Optional[str]) -> Optional[PreviousRun]`. Returns None unless `run_state` is `completed`, `stopped` or `error`.
  - `previous_run_header(prev: PreviousRun) -> Tuple[str, str, str]`, giving (colour, text, details). Colours: completed "blue", stopped "orange", error "red". Text: `"LAST RUN"`. Details, for example: `"Completed at 14:02 (ran 3 h 12 min). Results shown are from that run; Start Analysis begins a new one."`
  - `format_duration(seconds: Optional[int]) -> str`, `HH:MM:SS`, or `"--:--:--"` for None.

- [ ] **Step 1: Write the failing tests:**
  - A tmp results dir with `.nanometa.run.json` (`final_status: completed`, `written_at: 2026-10-05T09:00:00`, `ended_at: 2026-10-05T12:12:00`) gives `PreviousRun("completed", ..., duration_s=11520, ...)`.
  - The header text contains "Completed at 12:12" and "ran 3 h 12 min".
  - No metadata gives None. Metadata without a terminal status gives None. Missing `written_at` gives `duration_s=None` and details without "ran".
  - Review Focus 1: `update_status_display` with `status={"running": True, ...}` and that dir returns the running text.
  - The verdict callback with `backend-status` idle and that dir sets time-elapsed to `03:12:00` and the badge to `COMPLETED`.
- [ ] **Step 2:** Run them and confirm they fail.
- [ ] **Step 3: Implement** the helper module and the two call sites. The helper only replaces the final STANDBY branch. Running, error, completed-this-session and stopped branches are untouched.
- [ ] **Step 4:** Run the new tests plus `tests/test_dashboard_tab_callbacks.py`, `tests/test_startup_callbacks.py` and `tests/test_verdict_banner_callback.py`; expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit `fix(header): a reopened results folder shows the run that produced it`.

---

### Task 7: The `unclassified` barcode folder is named for what it holds

**Files:**
- Create: `nanometa_live/core/utils/sample_labels.py`
- Modify:
  - `nanometa_live/app/callbacks/samples.py:333`: selector label; the value is unchanged.
  - `nanometa_live/app/components/attribution.py:41+`: chip text and popover list.
  - `nanometa_live/core/utils/attribution.py:282+`: `_attribution_phrase` names.
  - The System Alerts pathogen line ("detected (N reads) in ..."). Locate it with `git grep -n "reads) in" nanometa_live`.
- Test: `tests/test_sample_labels.py` (create), `tests/test_attribution.py`

**Interfaces:**
- Produces: `UNASSIGNED_SAMPLE = "unclassified"`; `display_sample_name(sample: str) -> str`. Returns `"unclassified (no barcode)"` for exactly `"unclassified"` and the input unchanged otherwise. Display only: never apply it to a value used as a key, a path or a Store entry.

- [ ] **Step 1: Write the failing tests:**
  - `display_sample_name("unclassified") == "unclassified (no barcode)"` and `display_sample_name("barcode11") == "barcode11"`.
  - `_attribution_phrase` for JEV with samples `["unclassified", "barcode11"]` contains `"unclassified (no barcode), barcode11"`.
  - The selector option for `unclassified` has `label` `"unclassified (no barcode)"` and `value` `"unclassified"`.
- [ ] **Step 2:** Run them and confirm they fail.
- [ ] **Step 3:** Implement the helper and apply it at the listed display sites only.
- [ ] **Step 4:** Run the new tests plus `tests/test_attribution.py`, `tests/test_pathogen_alert_attribution.py` and `tests/test_sample_selector_*.py`; expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit `fix(ui): say that the unclassified barcode folder holds reads without a barcode`.

---

### Task 8: QC base-statistics cards state which reads they describe

**Files:**
- Modify: `nanometa_live/app/tabs/qc_tab_helpers.py` (new helper), `nanometa_live/app/tabs/qc_tab.py:627` (`update_base_quality_card`), `:736` (`update_read_statistics_card`)
- Test: `tests/test_qc_tab_helpers.py`, `tests/test_qc_tab_callbacks.py`

**Interfaces:**
- Consumes: `summarize_seqkit_rows(df)["total_reads"]` (`core/utils/qc_loaders.py:543`); `get_classification_stats(kraken_df)`.
- Produces: `read_set_note(seqkit_reads: int, kraken_reads: int) -> Tuple[str, Optional[str]]`, giving (caption, mismatch).
  - Caption: `f"Based on {seqkit_reads:,} reads measured by SeqKit"`.
  - Mismatch: None when either count is 0 or `abs(diff) <= max(10, 0.01 * kraken_reads)`. Otherwise `f"Kraken2 classified {kraken_reads:,} reads. The two counts come from different files and do not describe the same set of reads."`

- [ ] **Step 1: Write the failing tests:**
  - `read_set_note(49860, 76642)` returns the caption plus a mismatch containing "76,642".
  - `read_set_note(76642, 76600)` returns mismatch None.
  - `read_set_note(0, 5)` returns mismatch None.
  - Callback test: the base-quality card on a tree with SeqKit at 100 reads and Kraken2 at 200 shows both texts.
- [ ] **Step 2:** Run them and confirm they fail.
- [ ] **Step 3:** Implement the helper. Render the caption as small muted text under each card's title, and the mismatch as a small warning line below it, on both cards.
- [ ] **Step 4:** Run the QC test files; expect PASS.
- [ ] **Step 5:** Add the CHANGELOG line and commit `fix(qc): the base-statistics cards say which reads they describe`.

---

### Task 9: Field-run triage script

**Files:**
- Create: `scripts/field_run_triage.py`
- Test: `tests/test_field_run_triage.py`

**Interfaces:**
- Consumes: `load_kraken_data`, `get_classification_stats`, `load_seqkit_stats`, `load_chopper_counts` (Task 3), `read_final_run_status`, `load_realtime_stats`.
- Produces: `triage(results_dir: str) -> dict` with:
  - `samples`: a list of `{sample, kraken_reads, seqkit_merged_reads, seqkit_batch_reads, chopper_in, chopper_kept}`. `seqkit_merged_reads` comes from `seqkit/<s>.tsv`, and `seqkit_batch_reads` is the sum over `seqkit/<s>/batch_stats/*.tsv`.
  - `run`: `{run_state, failed_tasks, lost_inputs, estimated_reads}`.
  - The CLI is `python scripts/field_run_triage.py RESULTS_DIR [--json]`. It prints a table, plus one line per sample whose SeqKit and Kraken2 counts differ beyond Task 8's tolerance.

- [ ] **Step 1: Write the failing test:** a tmp tree with one sample has Kraken2 at 120 reads, a merged SeqKit file at 80 reads and batch files summing to 120. `triage()` reports those three numbers, and the CLI output names the sample as mismatched (merged vs Kraken2).
- [ ] **Step 2:** Run it and confirm it fails.
- [ ] **Step 3:** Implement the script with an argparse CLI and no network.
- [ ] **Step 4:** Run the test; expect PASS. Also run the script on `/tmp/nanometa_test_datasets/` output to check it handles a batch tree.
- [ ] **Step 5:** Commit `feat(scripts): triage a field run's read counts, failures and lost inputs`.

---

### Task 10: Whole-branch verification

- [ ] Full suite `conda run -n nf-core python -m pytest -q` passes; `python scripts/check_code_size.py` passes.
- [ ] Live check with the smoke-test-app skill, on a results tree that has Chopper counts, a `.nanometa.run.json` with `final_status: completed`, and an `unclassified` sample:
  - The header reads LAST RUN.
  - The run-time tile shows the duration.
  - The Reports tiles say "estimated".
  - The QC stage strip shows reads before filtering.
  - Cards say "read support".
  - Chips say "unclassified (no barcode)".
  - The browser console is clean.
- [ ] Push nanometa_live `dev` and nanometanf `dev` only when the user asks.

## Owner Actions (not code)

- Ask the exercise team for:
  - A screenshot of the Watchlist & Preparation checklist as it stood before Start (which 8 of 27 failed).
  - `.nextflow.log`, `pipeline_info/`, `seqkit/`, `kraken2/`, `chopper/` and `realtime_stats/` from `Barcelone_run_11`.
  - The config they used, in particular `chopper_minlength` and `chopper_quality`.
- Run `scripts/field_run_triage.py` on their results (Task 9) to settle item 6 and the STANDBY delay.
- Before the next exercise, note that 0.20.0 refuses Start while any CRITICAL readiness check fails. Walk the pre-departure checklist (`docs/OPERATOR_GUIDE.md`) offline until every CRITICAL row passes, or agree on `start_without_readiness: true` deliberately.
