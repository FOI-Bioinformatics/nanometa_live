# Audit Follow-Ups — 2026-05-02

This document tracks the audit findings that were **NOT** landed
inline by the opus reviewer pass. Each item lists severity,
blast radius, a one-line repro path, and where in the audit it
was raised so the next cycle can pick it up without re-doing
discovery.

The companion files are:

- `docs/audit-2026-05-02-frontend.md` — Auditor 1 (Nanometa Live)
- `docs/audit-2026-05-02-backend.md` — Auditor 2 (nanometanf)
- `docs/audit-2026-05-02-nanorunner-and-compat.md` — Auditor 3
- `docs/audit-2026-05-02-synthesis.md` — opus synthesis pass

The inline-fix pass that did land sits on
`audit/inline-fixes-2026-05-02` (merged into `dev2` in commit
`c87a6b0` on 2026-05-02). It covered the genome_manager singleton
race, the `datetime.utcnow()` deprecation, six dead Stores plus
one dead clientside callback, three silent-failure logging
fixes, and smoke tests for the locked singleton.

---

## High-priority follow-ups

### F0 — `MULTIQC_NANOPORE_STATS` filename collision in realtime mode -- DONE

**Status:** fixed in nanometanf commit `68d08c4`, merged at
`e1e3f98` on 2026-05-02. The re-run of Phase C Mode 2 with
the fix in place completed cleanly.

The fix changes the input declaration from
`path(stats_files)` to `path(stats_files, stageAs: '?/*')`
so each per-batch TSV/JSON is staged in its own numbered
subdirectory under the task work dir, avoiding the
"input file name collision" abort. The Python script was
updated to glob `*/*.tsv` and `*/*.json` recursively and
key by sample_id with later batches overwriting earlier --
the realtime contract is "show the operator the latest
per-sample stats", which this implements.

The fix mirrors the upstream nf-core MULTIQC module's
pattern at `modules/nf-core/multiqc/main.nf:11`.

### F1 — Route silent failures through `notification-trigger`

**Severity:** medium. **Blast radius:** small (per call site).

The inline-fix pass added `logging.exception` / `logging.warning`
calls so silent failures surface in the terminal. The auditor
recommended routing the same failures through the existing
`notification-trigger` Store so the operator sees a toast in the
browser. This requires `allow_duplicate=True` plumbing on each
involved callback's Output list and a small helper that converts
exceptions into the `{title, message, color}` shape the toast
component expects.

Affected sites (already cite-noted in the audit):
- `app/tabs/main_tab.py:683-694` (`sync_watchlist`).
- `app/tabs/main_tab.py:1015-1023`
  (`reload_on_demand_results`).
- `app/tabs/dashboard_helpers.py:701-709`
  (`compute_qc_stats_for_zone3`).

Repro: stop the `WatchlistManager` from loading (e.g. corrupt
the YAML at `~/.nanometa/watchlists/clinical_pathogens.yaml`
with a parse error), launch Nanometa Live, click Organisms tab.
Today the tab is silently empty; with F1 the operator sees a
toast pointing at the broken file.

### F2 — Mark dashboard estimator fallbacks as estimated -- OBSOLETE

**Status:** obsolete. The auditor's recommendation referenced a
"Zone 3 classification-rate stat" that does not exist in the
current 4-zone Dashboard architecture (CLAUDE.md "Dashboard
Architecture": Zone 3 has Sequences Analyzed, Sample Quality,
Species Detected, Run Time -- no classification-rate card). The
estimator fallback in
`app/tabs/dashboard_helpers.py:_generate_alerts` only feeds
`alert_engine.generate_alerts`, not a user-visible stat label.

The terminal-side WARNING log added in commit `3270785` is the
right surface for this case. If a future cycle reintroduces a
classification-rate stat to Zone 3, re-open this item.

### F3 — Wire or remove the cancel UI for genome download / BLAST build

**Severity:** medium (operator-facing; abandoned half-feature).
**Blast radius:** Preparation tab, ~150 LOC across button +
callback.

The `download-cancel-flag` and `blast-cancel-flag` Stores were
removed inline because they were dead. The operator still has no
way to abort a 30-minute genome download or a multi-hour BLAST
DB build mid-flight. Wiring up the cancel button to set the
flag, having `genome_manager` and the BLAST builder poll it on
each long-running step, and reporting cancellation back to the
UI is the right scope for this follow-up.

### F4 — `nanorunner` singleplex chunk-filename bug

**Severity:** high (data-correctness in nanorunner output).
**Blast radius:** nanorunner replay singleplex path.

Auditor 3 confirmed the bug surfaced during fixture build:
`nanorunner replay --force-structure singleplex` rechunks reads
from EVERY source file (no data is dropped), but every output
chunk filename uses the alphabetically-first source's stem. An
operator listing the output dir sees what looks like one giant
input. Auditor 3 proposed the one-line fix at
`nanopore_simulator/manifest.py:300` using
`source_paths[src_file_idx]` per chunk.

Repro: stage two FASTQs into a source dir; run
`nanorunner replay --force-structure singleplex --target out/
--reads-per-file 100`; observe `ls out/` shows only one stem.

The fixture builder at `bin/build-test-fixtures.sh` works around
this by running nanorunner once per sample with a single-file
staging directory.

### F5 / F6 — Empty source: silent zero-exit -- DONE

**Status:** fixed in nanorunner commit `93037b4`, merged at
`8755a25` on 2026-05-02. F5 (the auditor's broader
"rich-progress monitor swallows exit codes" claim) was
partially refuted in the synthesis pass; the genuine silent-
zero-exit path was the empty-manifest case in
`runner.py:186-188`.

The fix:

- New `EmptySourceError(RuntimeError)` in
  `nanorunner/nanopore_simulator/runner.py`. `run_replay`
  raises it on empty manifest with a message naming the
  offending source dir; `run_generate` raises it when no
  genome input is given.
- `cli_replay.py` and `cli_generate.py` catch
  `EmptySourceError` and exit with code **3** (distinct from
  the generic code 1 so CI pipelines can branch on the
  cause).
- Three new CliRunner cases pin exit-code 3, the message
  naming the offending path, and that a missing-source
  error path stays distinct (not exit 3). Plus the
  inverted assertion in the existing
  `TestRunReplayEmpty::test_empty_source_raises`.

Test count moved from 726 to 729.

### F7 — Schema drift: `max_avg_file_age_minutes`

**Severity:** low (today; would block strict schema validation).
**Blast radius:** one parameter mapping line.

GUI emits `max_avg_file_age_minutes` at
`nanometa_live/core/config/parameter_mapping.py:788` but
nanometanf's `nextflow_schema.json` does not declare it. The
nanometanf side reads it from `params` indirectly inside
`update_cumulative_stats`; declaring it in the schema would make
strict validation pass and surface the param to the GUI's
Advanced Settings.

---

## Medium-priority follow-ups

### F8 — Add tests for `core/utils/alert_engine.py` -- DONE

**Status:** landed in commit `e676dd5` on `dev2` (2026-05-02).

21 tests covering Alert.to_dict shape, generate_alerts under
five scenarios (no samples, low quality, error counts above and
below threshold, healthy samples, dangerous pathogens), severity
ordering, alert history retention and capping, deduplication,
and the singleton thread-safety guard. Test count moved from
781 to 802.

### F9 — Add tests for `core/utils/auto_detect.py` -- DONE

**Status:** landed in commit `84f8689` on `dev2` (2026-05-02).

18 tests covering detect_sample_handling (missing dir,
file-instead-of-dir, barcoded layout, empty-barcode
fallthrough, case-insensitive regex, flat-dir-no-fastq,
fastq-in-non-barcode-subdirs, distinct sample prefixes,
sequential names, many uniform files, few distinct files),
get_barcode_list (missing dir, only barcodes-with-FASTQ
returned, sort order, unclassified excluded), and
detect_file_format (missing dir, compressed, uncompressed,
recursive walk). Test count moved from 802 to 820.

### F10 — Document `127.0.0.1` binding -- DONE

**Status:** documented in
`docs/OPERATOR_GUIDE.md` (network-access section near the end)
and in `docs/developer-guide.md` (new "Operations" section).
Both note the default `127.0.0.1` binding, the SSH-tunnel
recommendation, and the `--host 0.0.0.0` escape hatch with the
"trusted network only" caveat.

### F11 — `bin/run-nf-tests.sh` NXF_VER pin documentation -- DONE

**Status:** documented in
`docs/developer-guide.md` "Operations" section. Explains why
`NXF_VER=25.04.7` is pinned (Nextflow 25.10.4 watchPath
DirWatcherV2 cleanup hang), how to use the wrapper rather
than `nf-test` directly, and which upstream issue to track
before lifting the pin.

---

## Lower-priority polish

### F12 — Pre-warm conda envs at install time -- DONE

**Status:** documented in `docs/developer-guide.md`
"Operations" section. The pre-warm machinery already exists
in `BundleManager.export_bundle(..., pre_warm_conda_envs=True)`
from cycle 18 (2026-04-28); this followup just made the
documentation discoverable and links the build-platform
restriction (Linux x86_64 vs macOS arm64 cannot share envs).

### F13 — Operator-facing error messages in `parameter_mapping.create_nextflow_params`

**Severity:** low. **Blast radius:** one helper.

Validation errors today read like internal exception strings.
Polish them so a bench operator can act on them without reading
Python tracebacks.

---

## Index

| ID | Title | Severity | From |
|---|---|---|---|
| F0 | MULTIQC_NANOPORE_STATS collision | DONE | Phase C Mode 2 |
| F1 | Notification-trigger routing | DONE | frontend §3 |
| F2 | Mark estimator stats | OBSOLETE | frontend §5 |
| F3 | Cancel UI for downloads | medium | frontend §1 |
| F4 | nanorunner chunk filenames | **high** | compat §1.4 |
| F5 | nanorunner exit code | DONE | compat §1.2 |
| F6 | nanorunner empty source | DONE | compat §1.3 |
| F7 | Schema drift | low | compat §2.2 |
| F8 | alert_engine tests | DONE | frontend §6 |
| F9 | auto_detect tests | DONE | frontend §6 |
| F10 | Operator-guide host doc | DONE | frontend §7 |
| F11 | NXF_VER pin doc | DONE | backend §7 |
| F12 | Conda pre-warm | DONE | (general) |
| F13 | parameter_mapping error UX | low | frontend §3 |

The `backend §...` references will resolve once the
backend audit lands; this index will be updated then.
