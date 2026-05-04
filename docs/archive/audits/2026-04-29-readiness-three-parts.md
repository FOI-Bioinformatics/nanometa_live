# Three-Part Production Readiness Audit -- 2026-04-29

This audit scores the three components of the Nanometa Live stack
on production-readiness across multiple sub-dimensions. It is
intentionally sweeping rather than focused: prior audits covered
specific concerns (offline deployment, throughput at 24 barcodes,
short-amplicon support, container URLs); this one rolls them up
plus the gaps they did not touch into a single comparison.

## Headline scores

| Component | Score | Strongest dimension | Weakest dimension |
|---|---|---|---|
| **nanorunner** | **82/100** | Atomic write semantics (10), packaging (10) | Performance/scale guidance (7) |
| **nanometanf** | **96/120** | Real-time monitoring (9), modules.json (9), local-module labels (9) | nf-core conformance verification (6) |
| **nanometa_live** | **80/100** | Concurrency safety (9), offline deployment (9), docs (9) | Frontend dead code, oversize tab files (7) |

The three components share a complementary readiness profile:
nanorunner is the most mature individual artefact (clean
abstractions, comprehensive tests, packaging done right) but ships
inconsistent POD5 references that cloud the FASTQ-only product
narrative. nanometanf has strong architectural fundamentals
(scalable streaming, watchPath F6 fix, three-engine
containerization) but several documentation and schema-precision
gaps that bite operators reading params.json or the validation
output contract. nanometa_live has the deepest recent
hardening (per-key parse lock, FanoutCache, expandable alert pill,
amplicon-aware Advanced Settings) but carries ~2,000 lines of
documented dead code and oversize tab files that the recent
throughput cycle did not clean up.

---

# Part 1: nanorunner -- 82/100

The simulator that drives empirical tests of the nanometa_live +
nanometanf stack. It replays FASTQ into a watch directory at
controlled rates, with multiplex barcode handling and atomic-write
semantics matched to nanometanf's watchPath consumer.

## CLI & argument parsing -- 9/10

Typer-based CLI at `cli_replay.py:28-149` with panel-grouped flags
(Required / Simulation Configuration / Timing Models / Parallel
Processing / Monitoring). Short forms exist for the common flags
(`-s/--source`, `-t/--target`). Help text is structured and
descriptive. **Weakness:** the `--source` help string at
`cli_replay.py:35` and the `replay` docstring at `cli_replay.py:150`
still mention POD5 as supported despite the product having moved
to FASTQ-only, creating documentation drift the operator sees.

## Replay simulation logic -- 9/10

`manifest.py:155-195` correctly batches files by `i // batch_size`
at line 192-193. The reads-per-file rechunker at `manifest.py:188-189`
calls `_rechunk_entries` which interleaves chunks across barcodes
via `zip_longest` (the round-robin fix mentioned in CLAUDE.md
fixing the earlier sequential-per-barcode bug that exhausted
barcode01 before barcode02 received any files). The executor's
atomic-write path uses `_atomic_tmp_path` from `nanopore_simulator/
io/fastq.py:13-15` (path slightly different from the audit's
spelling but correct content). One leftover concern: POD5
references in `manifest.py:244` ("files (e.g. POD5) are passed
through as-is") suggest behaviour that no longer exists.

## Multiplex / barcode handling -- 9/10

Barcode detection at `detection.py:74-90` matches `barcode\d+` and
`BC\d+` patterns. Multiplex builder at `manifest.py:214-231`
produces MinKNOW-faithful `target_dir / barcode_name / filename`
output. Per-barcode chunk planning at `manifest.py:256-276`.
**Weakness:** no explicit 24-barcode integration test; the round-
robin code should handle it but is not stress-tested.

## Output structure correctness -- 10/10

Atomic rename across every write path. Tmp-file + rename pattern
in `_copy_file` (`executor.py:67-82`), `_generate_file`
(`executor.py:95-129`), `_rechunk_file` (`executor.py:132-204`).
Exception handling cleans up tmp on failure (`executor.py:78-80`).
Matches nanometanf's atomic-write requirement
(CLAUDE.md F6 fix in nanometa_live's nanometanf).

## File format support -- 8/10

FASTQ + FASTQ.GZ (`.fastq`, `.fq`, `.fastq.gz`, `.fq.gz`) handled
correctly with gzip at `fastq.py:33-34, 72-74, 108-109`. **POD5
remains in `_SUPPORTED_EXTENSIONS` at `detection.py:20`** and is
referenced through several README + CLI help strings; no actual
POD5 reading code. The product has moved to FASTQ-only; these
references should be removed.

## Error handling -- 8/10

`ReplayConfig.__post_init__` (`config.py:85-108`) validates source
existence, operation choice, structure, rechunking constraints.
FASTQ malformed-file detection at `fastq.py:41-44` raises
`ValueError` on non-multiple-of-4 line counts (test
`test_fastq.py:25-29`). Empty files handled at `fastq.py:84-90`
with early break. **Weaknesses:** non-FASTQ files in source dir
silently filtered; missing source files only raise at execution
time (`executor.py:72-73`).

## Test coverage -- 9/10

**731 tests collected** (verified). 18 test files spanning unit
(test_manifest 570 lines, test_executor 241 lines) and integration
(test_integration 1134 lines). Conftest fixtures for sample FASTQ
+ temp dirs. **Gap:** no explicit 24-barcode stress test or
100k+ read integration test.

## Documentation -- 9/10

README.md is comprehensive with installation, usage examples.
CLAUDE.md documents project standards and dev workflow. `docs/`
has quickstart + troubleshooting + examples. **Weakness:** POD5
mentioned in README.md:10 and :20 inconsistently with FASTQ-only
direction.

## Performance / scale -- 7/10

Parallel processing via `runner.py:274-275, 320-329` with
configurable worker pool (`cli_replay.py:124-128`). Hardcoded 600 s
timeout (`runner.py:317`). **No documented benchmarks for
24-barcode runs**, no scalability guidance in docs, no stress
tests at the upper end of the multiplex spectrum.

## Packaging -- 10/10

`pyproject.toml` is well-structured (setuptools build, version 3.0.0,
typer dependency, optional psutil/numpy). Entry point declared.
Pip-installable from git or `-e .`. mypy + black + flake8 + pytest-cov
configured. Conda env `nanorunner` documented as the run target.

## P0 / P1 issues

- **P1**: POD5 references throughout (`cli_replay.py:35,150`,
  `detection.py:20`, `manifest.py:244`, `README.md:10,20`) -- product
  is FASTQ-only; remove for clarity.
- **P0** (per the audit): no high-throughput integration tests
  (24+ barcodes, 100k+ reads). The architecture supports it but
  there is no proof. Bench work to close.
- **P1**: missing performance benchmarks and scalability guidance.

---

# Part 2: nanometanf -- 95/120

The Nextflow pipeline that does the actual classification +
validation. Recent work (Wave 4 tuning, Wave 7 containerization
support indirectly via the audit) makes this the most actively
hardened of the three.

## Workflow architecture -- 8/10

`workflows/nanometanf.nf` (550+ lines) handles input mode routing
(realtime vs batch), validation gating, MultiQC deferred execution
via `.collect()` (lines 549-562). Value channels use `.first()`
(lines 328, 335) for streaming reusability. **Weakness:** top-
level workflow file is heavy on conditional logic; subworkflow-
level routing would shrink it.

## Module quality (local) -- 9/10

23 local modules, all referenced via include statements (no dead
code per the audit). KRAKEN2_OUTPUT_MERGER, KRAKEN2_REPORT_GENERATOR,
KRAKEN2_FINAL_AGGREGATOR implement the append-only batch storage
documented in CLAUDE.md:50-66. Every local module declares an
appropriate process label inside its own ``main.nf``: aggregators
and Python writers use ``process_single``, file-IO helpers
(extract_reads_by_taxid, kraken2_*_merger, seqkit_merge_stats,
nanoplot_compare) use ``process_low``, validation modules
(blastn_validation, minimap2_validation, fastp_streaming) use
``process_medium``, and the heavy Kraken2 paths
(kraken2_optimized, kraken2_incremental_classifier) use
``process_high``. The earlier readiness-audit pass scored 8/10 here
based on a grep for ``label:`` (with colon) that missed the Groovy
syntax ``label 'process_low'`` (without colon) -- corrected after
direct verification.

## Module quality (nf-core) -- 9/10

15 nf-core modules tracked in `modules.json` with git_sha pinning
on master branch. Two modules patched (blast/blastn, nanoplot)
indicating intentional upstream divergence. Container URL audit
(`docs/audit-2026-04-29-container-urls.md`) shows zero version
mismatches and zero unreachable URLs. **Weakness:** modules
tracked on `master` rather than a release tag; floating relative
to nf-core/modules HEAD.

## Resource declarations -- 7/10

`conf/base.config:42-62` defines four labels:
`process_low` (2/12 GB), `process_medium` (6/36 GB),
`process_high` (12/72 GB), `process_high_memory` (200 GB).
KRAKEN2_KRAKEN2 memory parameterised by `params.kraken2_memory_gb`
at `conf/modules.config:186` and again for the incremental
classifier at line 219 (W4-A from cycle 18). **Weakness:** zero
local-module `withLabel` declarations means the auto-tuning the
labels enable does not extend to the 23 local modules.

## Containerization -- 8/10

All 15 nf-core modules use the conditional Singularity / Docker
container pattern. 13 of 23 local modules are Python/shell
runtime-base; 10 ship `environment.yml`. Profiles: conda, docker,
singularity, apptainer, podman, shifter, charliecloud, wave, test,
test_full + arm (lines 200-332). nf-schema plugin declared at
`nextflow.config:436-437`. Cycle-18 W7-A audit confirmed zero
URL drift across all 40 modules. **Weakness:** local modules
without explicit Singularity directives fall back to conda in
singularity mode, missing the faster pre-built pull path.

## Real-time monitoring -- 9/10

`subworkflows/local/realtime_monitoring/main.nf:93` confirmed
`Channel.watchPath` (the prior audit's fabrication is closed).
F6 fix at lines 101-109 removed the settling filter that broke
MinKNOW / rsync / nanorunner atomic-write producers. Backpressure
via `max_concurrent_batches` and `max_classification_forks` at
lines 35-42. Sentinel-based timeout shutdown at lines 138-150.
Existing-file discovery uses round-robin interleaving by parent
directory (lines 56-76) for fair multi-barcode distribution.
**Weakness:** `batch_timeout` (line 41) is logged but not visibly
integrated into the emit logic at lines 87-96.

## Validation subworkflow -- 7/10

`subworkflows/local/validation/main.nf` covers BLAST + minimap2
paths. Pathogen genomes JSON parsing with relative-path
resolution (lines 35-71). Taxid filtering supports auto/all/CSV
(lines 76-80). AGGREGATE_VALIDATION_RESULTS + CANONICAL_VALIDATION_WRITER
emit JSON for nanometa_live consumption. **Weakness:** the JSON
schema for `validation_results.json` is not documented in
`assets/`; nanometa_live infers structure from code rather than a
contract, which is the same class of risk as the throughput
audit's "operator-side validation defaults" gap.

## Configuration / params -- 7/10

~190 params in `nextflow.config`, ~807 schema entries in
`nextflow_schema.json` (with `$defs` sections per category).
**Weaknesses:** `max_concurrent_batches`, `max_classification_forks`,
`adaptive_batching`, `batch_size_factor` lack schema documentation
despite being critical for streaming tuning. CLAUDE.md claims
"96/100 nf-core Compliance" without a verifiable conformance
report artefact.

## nf-core conformance -- 6/10

`nextflow.config:436-437` declares `nf-schema@2.4.2` plugin.
manifest block at lines 414-433 has name + contributors +
homepage + nextflowVersion (>=25.04.7) + version (1.5.1dev). The
pipeline is structurally compliant. **Weakness:** `nf-core
pipelines lint` cannot be run because of an upstream CLI version
mismatch (4.0.1 vs installed 3.5.2 incompatibility). Conformance
score is unverified.

## Test coverage (nf-test) -- 8/10

**600 .nf.test files** (verified). Key tests: `main_workflow.nf.test`
(175 lines), `chopper_specific.nf.test` (140), `full_pipeline_stubmode.nf.test`
(152), `qc_tool_integration.nf.test` (168), `realtime_processing.nf.test`
(86). `conf/test.config` + `conf/test_full.config` provide profiles.
**Weakness:** `modules/local/*/tests/` directories absent; no
module-level nf-test isolation; coverage relies on integration tests.

## Documentation -- 8/10

`README.md` (205 lines), `CLAUDE.md` (80+ lines), `docs/user/output.md`
(1016 lines documenting per-tool output contracts), `docs/`
includes meta_fields, production-readiness-report, development/
and user/ subtrees. Operator guidance for minion / promethion_8 /
promethion / field profiles. **Weakness:** validation_results.json
schema not documented; testing patterns and debugging guidance
thin.

## Output contract / consumer interface -- 7/10

`conf/modules.config:11-36` documents frontend-critical paths:
kraken2/, kraken2/{sample}/batch_reports/, fastp/, nanoplot/,
seqkit/, validation/blast/, validation/minimap2/,
validation/validation_results.json. Publish paths set per QC
tool. **Weaknesses:** path stability not versioned; incremental-
mode changes the publish tree (seqkit/{sample}/batch_stats added
2026-03-14 per modules.config:77-97) requiring nanometa_live
updates without a versioning contract. validation_results.json
JSON schema not in `assets/schema_*.json`.

## P0 / P1 issues

- **P1**: `nextflow_schema.json` -- `max_concurrent_batches`,
  `max_classification_forks`, `adaptive_batching`,
  `batch_size_factor` lack schema entries despite being critical
  streaming-tuning knobs. Operators using `--help` or the
  schema-validation UI cannot discover them.
- **P1**: validation_results.json schema not documented; the
  nanometa_live consumer reverse-engineers the contract.
- **P1**: 23 local modules have zero `withLabel` declarations;
  Python/shell helpers run with `cpus=1, mem=6GB` defaults
  regardless of the resource tiers available.
- **P2**: modules.json tracks `master` rather than release tags;
  floating versions risk downstream incompatibility.
- **P2**: CLAUDE.md "96/100 nf-core Compliance" claim not backed
  by a conformance report; lint blocked by upstream CLI version
  mismatch.

---

# Part 3: nanometa_live -- 80/100

The Dash 4 web GUI. The most heavily-iterated component this
cycle (Waves 1-7 + amplicon support landed in cycles 18 + 19).

## Frontend architecture & callback hygiene -- 7/10

8 tabs, layout/callback split. Per-tab files are large:
`dashboard_tab.py` 2303 lines, `preparation_tab.py` 2024,
`classification_tab.py` 1471, `qc_tab.py` 1343, `main_tab.py`
1311. Callbacks now serialise concurrent Kraken2 parses through
the per-key lock at `core/utils/loader_utils.py:46-65` (W1-A).
LRU-bounded debounce dict at `app/utils/debounce.py:23-39`.
FanoutCache at `app/app.py:33-41`. **Weaknesses:** dashboard_tab
holds much of the domain logic in one file; ~2,000 lines of dead
code across eight modules flagged in
`docs/audit-2026-04-28-nanometa-live-code.md` mostly remain.

## Backend manager / Nextflow integration -- 8/10

`core/workflow/backend_manager.py:_update_file_counts` caches with
5 s TTL (W2-B). Build-platform manifest at
`core/workflow/bundle_manager.py:412-417`. Three-engine offline
deployment at `bundle_manager.py:361-393` (W7-B): conda / docker
/ singularity, picked at build time, written into bundled
`pipeline_profile`. `_build_nextflow_env` injects
`NXF_OFFLINE="true"` (string discipline from cycle 17).
**Weakness:** docker/singularity image-pull paths
(`_pull_pipeline_containers`) tested via mocked subprocess only;
empirical pull on real macOS / Linux build host pending Wave 5.

## Data loaders / parser robustness -- 8/10

`load_kraken_data` enforces the per-key parse lock.
`load_fastp_per_sample` (`core/utils/qc_loaders.py:79-128`,
W2-A from cycle 18) avoids the FASTP-dir rescan in
`update_qc_plots`. `BlastValidationParser` instances cache parsed
results on validation-dir mtime fingerprint
(`core/parsers/blast_validation_parser.py:182-199`). Parser
hardening from cycle 3 still holds (PAF bounds checks, FASTP JSON
validation). **Weakness:** canonical-loader waterfall is invoked
sparingly; many code paths still call per-format loaders directly.

## Concurrency & cache safety -- 9/10

Per-key parse lock at `loader_utils.py:_get_parse_lock` is
double-checked-locking-correct. Test at
`tests/test_classification_loaders.py::TestLoadKrakenDataParseLock`
spawns 8 concurrent threads, asserts exactly one parse executes.
Debounce LRU bound at `_DEBOUNCE_MAX_KEYS=512`
(`app/utils/debounce.py:36`). No findings.

## GUI clinical-safety compliance -- 8/10

4-zone Dashboard layout per CLAUDE.md. WCAG AA-compliant text
colours, locked type scale, 8px radius site-wide. Expandable
"+N more" pill (`app/components/pathogen_alert.py:_build_attribution_popover`,
W1-B) and verdict-banner triggering-sample subhead
(`dashboard_tab.py:_make_banner_content`, W1-B) close the two
clinical-safety P0s. QC Stage Strip handles Chopper correctly.
**Weaknesses:** Q30 thresholds at
`organism_components.py:1177-1182` and classification-rate bands
at `qc_tab.py:120-128` still tuned for long ONT reads -- amplicon
runs show false amber/red. Documented in
`docs/audit-2026-04-29-short-amplicons.md`; deferred.

## Configuration management -- 8/10

`config.yaml` single source of truth. Cycle 19 added six
amplicon-friendly Advanced Settings controls (chopper_minlength,
chopper_quality, filtlong_min_length,
validation_identity_threshold, kraken2_confidence,
kraken2_minimum_hit_groups), wired through three callback
chains. minimap2 preset dropdown gained `sr` short-read option.
Defaults preserve long-read behaviour. **Weakness:**
`config_validator.py` only does boolean validation; new amplicon
numeric inputs land without server-side range clamping.

## Watchlist system -- 8/10

`core/watchlist/watchlist_manager.py` singleton with
project/user/built-in priority. 6 built-in watchlists. TaxidMapper
strategy chain (ExactTaxid -> ExactName -> Variant ->
Reclassification -> Fuzzy -> ParentTaxon, with GTDB suffix
variants). check-organisms-with-mapping handles GTDB and PlusPF
correctly. Offline-mode propagation through
`validate_entry_via_api / bulk_validate_entries / lookup_species`
landed in cycle 17. **Weakness:** the cycle-18 P0 fix
(`download_kraken_database` callback bypass) shows the same class
of bug recurs in unaudited callbacks; a generalised
"offline-mode-aware" decorator would prevent repetition.

## Validation system -- 8/10

Two sub-tabs (BLAST + minimap2/Coverage). `OnDemandValidator` for
ad-hoc validation. PAF parser produces depth arrays compatible
with the three coverage figures. Cycle-18 W3-C added pagination
to result-card lists and grouped the coverage species selector.
**Weakness:** coverage plots assume WGS-shape reference;
amplicon-target validation shows breadth across the full genome
(P2-A03 in short-amplicon audit; deferred).

## Offline deployment -- 9/10

Wave 7 ships three engines (conda / docker / singularity), GUI
radio auto-disables engines whose CLI is missing on the build
host. Bundle's emitted `config.yaml` carries matching
`pipeline_profile`. `tests/test_bundle_manager.py::TestContainerizationModes`
covers the three modes with mocked subprocess. NXF_OFFLINE="true"
injection, manifest build-platform fields, pipeline-source +
plugins bundling all verified. **Weakness:** empirical fresh-
machine offline run pending Wave 5 (operator-driven).

## Test coverage -- 8/10

633 tests collected across 33 test files. End-to-end scenarios at
`tests/test_e2e_scenarios.py`. **Weaknesses:** 16 modules without
test files flagged in cycle-18 audit (genome_manager, alert_engine,
on_demand_validator, mobile_lab_preparer); cycle 19 closed some
but not all. No UI integration tests (Selenium/Playwright);
structural tests verify component IDs but not actual interaction.

## Documentation -- 9/10

CLAUDE.md current to 2026-04-28. `docs/` has 8 audit reports +
implementation plan + production-readiness synthesis. Operator
guide covers 4-zone Dashboard, traffic-light system, high-
throughput tuning. configuration.md lists every parameter
including cycle-19 amplicon section. **Weakness:** developer guide
not re-walked since cycle 17.

## P0 / P1 issues

- **P1**: Q30 + classification-rate bands hardcoded for long-read
  ONT (`organism_components.py:1177-1182`, `qc_tab.py:120-128`);
  amplicon runs show false amber/red.
- **P1**: ~2,000 lines of dead code across `core/utils/data_utils.py`,
  `database_utils.py`, `safe_path.py`, `app/components/tooltip_components.py`,
  `app/components/watchlist_manager_ui.py`, `ConfigManager` class.
- **P1**: `core/config/config_validator.py` does not range-validate
  the new amplicon numeric fields (HTML5 form constraints only).
- **P2**: 16 modules without test files (cycle-18 audit list).
- **P2**: developer guide pre-Wave-7.

---

# Cross-cutting observations

## Shared themes across the three components

**Schema / contract documentation is the weakest dimension everywhere.**
nanometanf does not document the validation_results.json schema
nanometa_live consumes. nanometa_live does not document the QC
plot contract its callbacks expect. nanorunner does not document
the multiplex output layout it produces (operators must read
detection.py to know what barcode patterns are recognised).
Closing this triangle would prevent the entire class of
silent-contract-drift bugs that show up after upstream changes.

**Clean-up work pending across all three.** POD5 references in
nanorunner, dead local modules in nanometanf and dead Python
modules in nanometa_live all share the same root: each repo had
a focused-cleanup branch (refactor/remove-pod5-dorado-2026-04-21
in nanometanf, the pod5 cosmetic removal in nanometa_live) that
landed the headline removal but left scaffolding behind.

**Empirical end-to-end verification is uniformly deferred.** Wave
5 of the throughput plan, the operator-driven empirical run for
the offline deployment (Wave 5 in the same plan), and a 24-barcode
stress test for nanorunner are all bench work waiting for real
hardware time. Without that round, several of the scores above
are theoretical.

## Strengths to preserve

**nanorunner's atomic-write discipline** (10/10) is the contract
that lets the realtime_monitoring subworkflow's F6 fix work.
Removing tmp-rename semantics anywhere in nanorunner would
silently break nanometanf.

**nanometanf's container audit** (cycle-18 W6-A) verified zero
drift across all 40 modules. This is the foundation that the
three-engine offline deployment can rely on -- if the audit had
returned mismatches, Wave 7's docker/singularity paths would be
unreliable.

**nanometa_live's per-key parse lock** (cycle-18 W1-A) closed the
thundering-herd race that the throughput audit predicted at 24
barcodes. Without it, the entire offline-cycle scoring above for
nanometa_live drops by 5-10 points.

## Recommended next-cycle priorities

In order of risk-weighted impact:

1. **Document the validation_results.json contract** -- DONE
   2026-04-29. JSON Schema lives at
   ``nanometanf/assets/schema_validation_results.json``;
   ``nanometa_live/core/parsers/blast_validation_parser.py``
   docstring references it as the source of truth.
2. **Add `withLabel` to the 23 nanometanf local modules** -- already
   shipped. The earlier audit's claim was a false positive (grep for
   ``label:`` with colon missed the Groovy syntax
   ``label 'process_low'``). Every local module already declares the
   appropriate label; module-quality score corrected from 8 to 9.
3. **Remove POD5 from nanorunner** -- DONE 2026-04-29 on branch
   ``cleanup/remove-pod5-2026-04-29``. CLI help, detection.py constant,
   adapters.py patterns, manifest.py docstring, README, CLAUDE.md,
   pyproject.toml keywords, plus 5 tests inverted. 730 tests pass.
4. **Empirical Wave 5 run** of the full stack at 12 barcodes
   on real hardware. **Still operator-driven; deferred.** Closes the
   largest set of "theoretical score" gaps in one operator session.
5. **Amplicon-aware Q30 / classification-rate band reinterpretation**
   in nanometa_live -- DONE 2026-04-29. New helper
   ``qc_tab._is_amplicon_mode(config)`` detects amplicon intent from
   ``chopper_minlength`` / ``filtlong_min_length`` <500. When active,
   ``BaseQualityCard`` and the QC Stage Strip relax their bands:
   Q30 green floor 45 -> 25, Q20 green floor 65 -> 40, classification-
   rate green floor 80 -> 50. Long-read defaults unchanged when
   amplicon_mode is False.

## Aggregate readiness

Treating each component score on a 0-100 scale (nanorunner: 82,
nanometanf: 95/120 normalised to 79, nanometa_live: 80) gives a
**stack average of ~80/100**. The components are individually
production-grade for same-platform field deployment with
operator-driven verification. The cross-component
schema/contract gap is the largest systemic risk; the second is
the overhang of clean-up work each repo carries.
