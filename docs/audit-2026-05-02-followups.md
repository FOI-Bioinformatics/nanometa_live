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

### F2 — Mark dashboard estimator fallbacks as estimated

**Severity:** low. **Blast radius:** Zone 3 stat label.

When `compute_qc_stats_for_zone3` falls back to the
organism-count estimator (already logged after the inline fix)
the Zone 3 classification-rate stat looks plausible but is
synthetic. Append an `(estimated)` annotation to the stat's
label and downgrade the colour ramp by one tier so the operator
sees that the number is approximate.

Repro: temporarily rename `kraken2/` under
`results_output_directory` to `_kraken2/`, refresh the
dashboard. The estimator fires; today the resulting number
appears in the same colour as a real measurement.

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

### F5 — `nanorunner` exits 0 on visible errors

**Severity:** medium (CI defeat).
**Blast radius:** nanorunner CLI top-level.

Auditor 3 found that when the rich-progress monitor is the
default, errors print but the process exits with code 0
(`cli_replay.py:227-234`). CI pipelines that check `$?` cannot
catch failures.

### F6 — Empty source directory: nanorunner exits silently

**Severity:** low. **Blast radius:** `runner.py:186-188`.

`nanorunner replay --source <empty>` exits 0 with no output and
no warning. The operator has no signal that nothing was done.
Should error with a clear message.

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

### F10 — Document `127.0.0.1` binding in the Operator Guide

**Severity:** low (documentation gap, NOT a security
vulnerability). **Blast radius:** docs.

Auditor 1 noted that Nanometa Live binds to `127.0.0.1` only by
default — operators running on a head node who want to reach the
GUI from a different host need to set `--host 0.0.0.0` and
ideally tunnel via SSH. The Operator Guide does not yet say so
explicitly.

### F11 — `bin/run-nf-tests.sh` NXF_VER pin documentation

**Severity:** low. **Blast radius:** README + CI workflow doc.

The wrapper at `bin/run-nf-tests.sh` pins `NXF_VER=25.04.7` to
mitigate the watchPath JVM cleanup hang. The pin lives in the
script and a comment in `nf-test.config`; it should also be
called out in the developer guide so an unfamiliar contributor
running `nf-test` directly does not silently hit the hang.

---

## Lower-priority polish

### F12 — Pre-warm conda envs at install time

**Severity:** low. **Blast radius:** docs / install instructions.

First-run conda env creation can take several minutes. A
pre-warm step at install time would make first-run timing
predictable.

### F13 — Operator-facing error messages in `parameter_mapping.create_nextflow_params`

**Severity:** low. **Blast radius:** one helper.

Validation errors today read like internal exception strings.
Polish them so a bench operator can act on them without reading
Python tracebacks.

---

## Index

| ID | Title | Severity | From |
|---|---|---|---|
| F1 | Notification-trigger routing | medium | frontend §3 |
| F2 | Mark estimator stats | low | frontend §5 |
| F3 | Cancel UI for downloads | medium | frontend §1 |
| F4 | nanorunner chunk filenames | **high** | compat §1.4 |
| F5 | nanorunner exit code | medium | compat §1.2 |
| F6 | nanorunner empty source | low | compat §1.3 |
| F7 | Schema drift | low | compat §2.2 |
| F8 | alert_engine tests | DONE | frontend §6 |
| F9 | auto_detect tests | DONE | frontend §6 |
| F10 | Operator-guide host doc | low | frontend §7 |
| F11 | NXF_VER pin doc | low | backend §7 |
| F12 | Conda pre-warm | low | (general) |
| F13 | parameter_mapping error UX | low | frontend §3 |

The `backend §...` references will resolve once the
backend audit lands; this index will be updated then.
