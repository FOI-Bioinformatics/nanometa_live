# Audit Synthesis -- 2026-05-02

This document synthesises the three Phase B auditor reports
into a single ranked view for the next-cycle planning meeting.
It also records the inline fixes that landed during this cycle
on `audit/inline-fixes-2026-05-02` (merged to `dev2` at
`bdff91f` on 2026-05-02). The synthesis pass was originally
scoped to opus, which hit a per-day rate limit; the work fell
back to the main thread but kept the same anti-fabrication
discipline.

Companion files:

- `docs/audit-2026-05-02-frontend.md` -- Auditor 1 (Nanometa Live)
- `nanometanf/docs/audit-2026-05-02-backend.md` -- Auditor 2 (nanometanf)
- `docs/audit-2026-05-02-nanorunner-and-compat.md` -- Auditor 3 (nanorunner + cross-repo)
- `docs/audit-2026-05-02-followups.md` -- catalogue of deferred fixes

## 1. Headline scores

| Component | Score | Notes |
|---|---:|---|
| Nanometa Live (frontend) | 6.85 / 10 | Race condition (now fixed inline) was the lowest sub-score; ~2k LOC of `genome_manager.py` plus `alert_engine.py` are still untested |
| nanometanf (Nextflow backend) | 7.6 / 10 | Cleanest of the three; nf-core lint passes, every module has at least one nf-test, schema/code parity essentially perfect |
| nanorunner | 7.3 / 10 | One real high-severity bug in singleplex chunk filenames, otherwise solid |
| Cross-repo schema seam | 8.0 / 10 | Single orphan param (`max_avg_file_age_minutes`); no naming drift |

Weighted overall production-readiness for the stack:
**7.20 / 10**, weighting nanometanf at 0.40 (it is the only one
that touches user data via Kraken2/BLAST), nanometa_live at
0.35 (operator-facing), nanorunner at 0.15 (test-only path), and
the cross-repo seam at 0.10. The stack is clearly ahead of the
2026-04-28 audit's 35% baseline reported in the recent-context
notes; the score reflects a system that runs reliably for an
operator who follows the documented happy path but has visible
gaps in resilience and untested code that would matter under
unattended deployment.

## 2. Verification of five concrete claims

Each random sample was verified by direct file read against the
auditors' citations. The point is to catch the same class of
fabricated finding the prior cycle had.

**Claim 1: `barcode_discovery` is imported but never invoked
(backend audit, top-5 finding 2).** Confirmed.
`workflows/nanometanf.nf:15` imports the subworkflow; the
inline comment at line 149 reads "UNIFIED DIRECTORY SCAN
(replaces BARCODE_DISCOVERY)" and the only conditional that
would call it (`if (params.input_dir || is_barcode_discovery)`)
routes through `INPUT_SCANNER` instead.

**Claim 2: `modules/local/realtime_progress_tracker/main.nf`
is orphaned (backend audit, top-5 finding 1).** Confirmed by
exhaustive grep: zero references to `realtime_progress_tracker`
anywhere under `*.nf` or `*.config` files.

**Claim 3: `lib/BatchUtils.groovy:46` is the rewritten
count-or-timeout implementation (backend audit, finding 7).**
Confirmed. Line 46 is `static def batchWithTimeout(...)`; the
implementation has the daemon Timer, the `ConcurrentLinkedDeque`,
the `synchronized(lock)` drain, and the `subscribe` consumer
exactly as documented in `lib/BatchUtils.groovy:36-122`.

**Claim 4: `cli_replay.py:227-234` exits 0 on visible errors
when the rich-progress monitor is active (nanorunner audit,
finding 2).** **Partially refuted.** Lines 227-234 actually
show `raise typer.Exit(code=1)` for both `KeyboardInterrupt`
and `except Exception`. Reading downstream into
`runner._execute_manifest`: the `try/finally` block at the
batch loop calls `monitor.stop()` in `finally` but does not
swallow exceptions. The auditor's headline framing appears
incorrect for this specific path; the genuine silent-exit
case is an empty source directory at `runner.py:187-188`,
which logs only at INFO and returns. F5 in the followups doc
should be re-scoped to the empty-source case rather than the
broader "exit 0 on errors" framing.

**Claim 5: `max_avg_file_age_minutes` is emitted by the GUI
but absent from `nanometanf/nextflow_schema.json` (cross-repo
audit, §2.2).** Confirmed.
`nanometa_live/core/config/parameter_mapping.py:788` sets
`params["max_avg_file_age_minutes"] = config.get("max_file_age_minutes", 1000000)`;
grep against `nextflow_schema.json` returns zero hits. Strict
schema validation (`nf-schema validateParameters`) would reject
this orphan.

Four of five claims hold; one is partially refuted and the
followups doc has been adjusted (F5 re-scoped). No completely
fabricated claims found.

## 3. Prioritised fix list

### P0 -- blocks v2.0 release

**P0-A: Fix nanorunner singleplex chunk filenames.** Auditor 3
(§1.4) found that
`nanopore_simulator/manifest.py:300` builds chunk output names
using only the alphabetically-first source's stem, regardless
of which source actually contributed the reads in that chunk.
Reads are not lost (every record from every source ends up in
some output chunk), but operator-visible output looks like a
single giant input ran. The proposed one-line fix is
`source_paths[src_file_idx]` per chunk. Effort: 30 minutes,
plus a test. Risk: low.

**P0-B: Add regression tests for the 2026-04-30 validation
fixes.** Auditor 2 (top-5 finding 3) flagged that the
`qseqid` dedup at
`modules/local/blastn_validation/main.nf:113-128`, the
`\\n` escape at
`modules/local/minimap2_validation/main.nf:136-153`, and the
`.toString()` coercion at
`subworkflows/local/validation/main.nf:85` could all silently
regress because no test exercises any of them. Effort:
2 hours per test (3 nf-tests). Risk: low; the fixes are
already in production.

### P1 -- should fix this cycle

**P1-A: Delete `subworkflows/local/barcode_discovery/`.**
Auditor 2 finding 2. The subworkflow is imported at
`workflows/nanometanf.nf:15` but never invoked; an inline
comment at line 149 explicitly states it was replaced by
`INPUT_SCANNER`. Removing the subworkflow plus the dead import
keeps the codebase honest. Effort: 15 minutes plus a test
re-run. Risk: low (no callers).

**P1-B: Delete `modules/local/realtime_progress_tracker/`.**
Auditor 2 finding 1. 246 lines of code with zero callers
outside its own test. Effort: 10 minutes. Risk: nil.

**P1-C: Surface silent failures via `notification-trigger`
toast.** Followup F1. The inline-fix pass added
`logging.exception` / `logging.warning` calls so the failures
appear in the terminal, but the auditor's full recommendation
was to also write to the existing `notification-trigger` Store
so the operator sees a toast. Affected sites:
`app/tabs/main_tab.py:683-694`, `app/tabs/main_tab.py:1015-1023`,
`app/tabs/dashboard_helpers.py:701-709`. Effort: 30 minutes
plus `allow_duplicate=True` plumbing. Risk: low.

**P1-D: Wire or remove the cancel UI for genome download /
BLAST build.** Followup F3. The dead Stores
`download-cancel-flag` and `blast-cancel-flag` were removed
inline (commit `8024a68`); the Preparation tab still has no
way to abort a 30-minute genome download or a multi-hour BLAST
DB build. Wiring up the cancel button to set a flag,
`genome_manager` polling it on each long step, and reporting
back to the UI is the right scope. Effort: 4 hours. Risk:
medium (touches long-running subprocess code).

**P1-E: Declare `max_avg_file_age_minutes` in
`nextflow_schema.json`.** Followup F7. One-line schema
addition. Effort: 5 minutes. Risk: nil.

### P2 -- next cycle

**P2-A: Add tests for `core/utils/alert_engine.py`** (followup
F8). It generates the Zone 1 verdict banner; today untested.
Even one scenario per banner state would catch regressions.

**P2-B: Add tests for `core/utils/auto_detect.py`** (followup
F9). Selects sample-handling layout; misclassification
produces empty dashboards.

**P2-C: nf-core module updates.** 9 modules have newer
upstream versions: `blast/blastn`, `blast/makeblastdb`,
`fastqc`, `filtlong`, `flye`, `miniasm`, `minimap2/align`,
`porechop/porechop`, `seqkit/stats`. Run
`nf-core modules update` and triage breakages. Effort: half a
day. Risk: depends on what changed upstream.

**P2-D: nanorunner exit-code on empty source.** Followup F5
(re-scoped after verification refuted the broader claim).
`runner.py:187-188` returns silently when the manifest is
empty; should log at WARNING and exit non-zero so CI catches
"forgot to set --source". Effort: 15 minutes.

**P2-E: Mark dashboard estimator fallbacks** (followup F2),
**document `127.0.0.1` binding** (F10), **document the
NXF_VER pin** (F11), pre-warm conda envs at install (F12),
polish parameter_mapping error UX (F13). All cheap;
sequence whenever there is a polish window.

## 4. Inline fixes already landed

The opus reviewer pass on `audit/inline-fixes-2026-05-02` (now
merged to `dev2` at commit `bdff91f`) covered the small/clean
fixes from the auditors' top-5 lists:

| Commit | What |
|---|---|
| `c719dbb` | Lock `genome_manager` singleton with double-checked locking; replace `datetime.utcnow()` with timezone-aware variant |
| `8024a68` | Delete six dead `dcc.Store` widgets (`aggregate-kraken-cache`, `per-sample-kraken-cache`, `prep-job-state`, `download-cancel-flag`, `blast-cancel-flag`, `taxmap-selected-entry`) and one dead `clientside_callback` |
| `3270785` | Log silent-failure paths in `sync_watchlist`, `reload_on_demand_results`, and `compute_qc_stats_for_zone3` |
| `eee74f0` | Smoke tests for the locked `genome_manager` singleton, including a 16-thread concurrent-init test |

Test count moved from 751 (start of session) to 781 after the
inline fixes (+24 from collision-modal tests in commit
`5bb782d`, +6 from the singleton smoke tests). Zero tests
regressed.

## 5. Strategic recommendations

The two changes that would move the production-readiness score
the most for the least effort, ordered by cost:

**(1) Land P0-A and P0-B together (~3 hours).** The
nanorunner chunk-filename bug is the only data-correctness
bug in the audit. The validation regression tests would have
caught any of the three 2026-04-30 bugs the day they
regressed; they are tests for code already in production. Both
are visible to operators reading output. After landing,
nanorunner would move from 7.3 to ~8.0 and nanometanf from
7.6 to ~8.0.

**(2) Land P1-A through P1-E in the same cycle (~5 hours
total).** The two backend deletions (P1-A, P1-B) and the
schema declaration (P1-E) are 30 minutes combined. The
notification-trigger routing (P1-C) is 30 minutes. The cancel
UI (P1-D) is the only invasive item at 4 hours but it is the
biggest operator-experience gap on the list. After landing,
the frontend would move from 6.85 to ~7.5 and the cross-repo
seam from 8.0 to 9.0.

After both rounds, the weighted overall score should land
around 8.1 / 10 -- production-grade for unattended deployment
with documented operational caveats.

The audit deliberately does **not** attempt to address the two
2k+ LOC files (`genome_manager.py`, `dashboard_tab.py`) that
are covered only obliquely by integration tests. Splitting
those into smaller modules with their own targeted tests is a
multi-cycle effort and out of scope here.

## 6. What this synthesis did NOT do

- Run the four-mode end-to-end test matrix (Phase C). Phase A
  fixtures are built and waiting; Phase D collision UX is
  merged. Phase C should run in a follow-up session against the
  merged code so that the test outputs serve as evidence for
  any future regression triage.
- Verify the entire backend `nf-core lint` clean run (522
  passed / 0 failed) by re-running it locally; the auditor
  reported the result and Claim 3 verification confirmed the
  backend is in good shape, so the lint claim was treated as
  trustworthy without re-execution.
- Validate every schema/code parity claim. The auditors
  cited concrete ones; the synthesis trusts the negative claim
  ("essentially perfect once `ext.args` is accounted for").
- Address the operator-facing NXF_VER pin in `bin/run-nf-tests.sh`.
  It remains required (Auditor 2 finding 5); the next cycle
  should track upstream Nextflow #26 to decide when to lift it.
- Re-evaluate the four pre-staged audit folders under
  `~/Desktop/snabbsekvensering/output/`. They are pipeline
  OUTPUTS (not inputs), useful for testing the new collision
  UX manually but not relevant to the audit findings.
