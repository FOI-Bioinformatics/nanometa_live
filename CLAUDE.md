# CLAUDE.md

Developer guidance for **Nanometa Live v2.0**, a real-time visualization dashboard for Oxford Nanopore sequencing analysis.

## Architecture

```
Input FASTQ -> nanometanf Pipeline -> Output Files -> Data Loaders -> Dash Callbacks -> Visualizations
                     ^                    |
              BackendManager <-- Status Polling (5s)
                     |
              NextflowManager
```

Top-level layout:

```
nanometa_live/
├── app/         # Dash app: app.py, callbacks.py, components/, layouts/, tabs/, utils/
├── core/
│   ├── config/      # Config loading, parameter mapping, built-in watchlist YAMLs
│   ├── parsers/     # PAF coverage parser, BLAST validation parser
│   ├── taxonomy/    # Kraken2 DB indexer, NCBI/GTDB API, taxid mapping
│   ├── utils/       # Data loaders, sample detector, genome manager, alert engine
│   ├── watchlist/   # Watchlist loader, manager (singleton), taxonomy matcher
│   └── workflow/    # Backend, Nextflow, bundle, on-demand validator, readiness
└── docs/        # Active docs at top; archive/ for historical
```

Loader package: import directly from the leaf module that owns the symbol
(`classification_loaders`, `qc_loaders`, `validation_loaders`,
`canonical_loaders`, `loader_utils`).

### Processing Modes

| Mode | Use Case |
|------|----------|
| Batch | One-time processing of existing FASTQ; samplesheet generated, runs to completion |
| Real-time | Continuous monitoring via Nextflow `watchPath`; incremental Kraken2, cumulative reports refreshed on interval |

### Sample Handling

| Mode | Input Structure |
|------|-----------------|
| `by_barcode` | `barcode01/`, `barcode02/` subdirs (multiplexed) |
| `single_sample` | Flat directory, all files = one sample |
| `per_file` | Flat directory, each file = one sample |

## Development

### Running locally

```bash
# Visualization only (no pipeline)
python -m nanometa_live.app --main_dir /path/to/results --port 8050

# Full mode with config
python -m nanometa_live.app --config config.yaml

# Debug
DASH_DEBUG=true python -m nanometa_live.app --main_dir /path/to/results
```

### Packaging

Metadata lives in `pyproject.toml` (PEP 621); there is no `setup.py`. Version
and dependencies stay dynamic (`nanometa_live.__version__` and
`requirements.txt`) so each has one place to edit. Console scripts:
`nanometa-live`, `nanometa-prepare`, `nanometa-report`.

`nanometa_live_env.yml` includes Nextflow (`>=26.04.0`) — without it the
environment yields a working dashboard and a pipeline that fails the moment
Start Analysis is pressed. `nanometa-prepare doctor` is the config-free
post-install check (Python, Nextflow + floor, conda, container runtimes, data
dirs); `nanometa-prepare check --config` is the run-specific one. Every CLI
subcommand except `verify` calls `NanometaPaths.ensure_dirs()` before
dispatch, so a never-launched install no longer reports CRITICAL failures
whose real cause is "the GUI was never started".

### Adding a new tab

Layout in `app/layouts/`, callbacks in `app/tabs/`, wire both in `app/app.py`.
Full walkthrough: [`docs/developer-guide.md`](docs/developer-guide.md).

### Key Stores

| Store ID | Purpose |
|----------|---------|
| `app-config` | Current configuration dict |
| `backend-status` | Pipeline status (running, stage, processes) |
| `selected-sample` | Currently selected sample name |
| `available-samples` | List of detected samples |
| `validation-data-store` | Validation results (BLAST/minimap2) |
| `taxmap-collection` | Kraken2 taxid mapping data |
| `watchlist-tab-state` | Watchlist UI state trigger |
| `watchlist-entries-snapshot` | Watchlist entries hydrated from main process for background workers |

**Background callback isolation:** Dash `DiskcacheManager` runs background callbacks
in a separate OS process, so Python singletons (e.g. `WatchlistManager`) are empty there.
Share state via a `dcc.Store` populated in a main-process callback and read via `State`.
Concretely: any background callback that needs the watchlist MUST take
`State("watchlist-entries-snapshot", "data")` and use it instead of
`get_watchlist_manager()`. The readiness checker is one such case —
`update_readiness_state` (`app/callbacks/readiness.py`) passes the snapshot into
`ReadinessChecker.check_readiness(..., watchlist_entries=...)`; without it the
worker's empty singleton makes every watchlist check report "not enabled". The
snapshot carries `enabled` per entry (set in `hydrate_watchlist_entries_snapshot`)
so the checks can filter to the active set.

**Update cadence and session writes.** A single global
`dcc.Interval(id='update-interval')` drives all polling: 10 s while a
run is active (`update_interval_seconds`), backing off to 60 s when
nothing is running (`idle_update_interval_seconds`). The adaptive
switch lives in `app/callbacks/interval_offline.py:update_interval`,
keyed on `backend-status`. Heavy I/O (kraken2/fastp/seqkit/
blast scans) is gated on the `results-fingerprint` store rather than
on raw interval ticks; ~13 callbacks share a uniform 2 s
`should_skip_update()` debounce so an interval tick that finds
nothing new is a microsecond-cost short-circuit. Session-state
writes to `~/.nanometa/configs/last-session.yaml` happen only on
Apply Settings (`config_tab.py:876`) and watchlist edits
(`watchlist_tab.py:38`); pipeline Start, Stop, and finish do NOT
auto-persist. Boot is fresh by design (the Resume/Discard banner
makes session restore an explicit choice, see commit `8bb4290`).
The Start callback writes an optimistic
`{running: True, starting: True}` to the `backend-status` store on
click so the verdict banner flips within ~30 ms instead of waiting
for the next poll; the next real status poll overwrites with the
authoritative value.

**Run metadata on disk:** every successful pipeline start writes
`<results_output_directory>/.nanometa.run.json` (see
`BackendManager.write_run_metadata`). It carries a sha256 fingerprint over the
input-identifying config keys (`nanopore_output_directory`, `sample_handling`,
`processing_mode`, `kraken_db`) so the next launch can detect when the
operator is about to point a different input at a populated outdir. The
collision modal renders a red mismatch banner in that case. Companion helpers:
`compute_input_fingerprint`, `read_run_metadata`, `fingerprint_matches`.

## Output File Formats

### Kraken2 Reports

Loader priority order (cumulative beats per-batch), resolved PER SAMPLE and
unioned in the "All Samples" aggregate — a directory-wide tier choice silently
dropped every barcode still on a lower tier from the frame the verdict banner
reads (audit 2026-08-16, finding L1):

1. `*.cumulative.kraken2.report.txt` (real-time cumulative)
2. `*.kraken2.report.txt`

The pre-current `*.kreport2.txt` / `*.kreport2` naming was retired in the
2026-06-02 sunset pass; only the current nanometanf `*.kraken2.report.txt`
naming is recognised.

Per-batch reports `*_batch*.kraken2.report.txt` are excluded — `load_kraken_latest_batch()`
selects the highest-numbered batch and never sums across them.

**Authoritative taxonomy:** `apply_authoritative_taxonomy()` in `app/tabs/kraken2_helpers.py`
parses `inspect.txt` from the Kraken2 DB to correct parent_taxid for Sankey/Sunburst.

**Sequences-analyzed metric:** the dashboard tile uses
`get_classification_stats(kraken_df)` from `app/utils/callback_helpers.py` —
which returns `(classified_reads, unclassified_reads, rate)` from
`root.cumul_reads + unclassified.cumul_reads`. Do not use `kraken_df['reads'].sum()`;
the per-rank assignment column collapses to 0 when every read is parked at
root level (the degenerate single-read input case caught by the audit).

**Cache-scope invariants (do not regress).** Three rules keep per-poll cost
from growing with the barcode count. The 2026-07-25 scaling pass measured a
*quiet* 24-sample realtime poll — one where nothing changed — at 74,462
`stat()` calls and 772 ms; it is now 2,119 calls and 59 ms, and the scaling
exponent dropped from O(N^1.65) to O(N^0.91). Regression-covered by
`tests/test_loader_cache_transparency.py` and the `per-poll-cost` CI job.

- **A per-sample cache entry must be fingerprinted against that sample's own
  files.** `_sample_fingerprint_paths` (`classification_loaders.py`) and
  `_seqkit_fingerprint_paths` (`qc_loaders.py`) return the sample-scoped path
  list; only an aggregate ("All Samples") load may pass the whole directory.
  Passing the shared directory for a per-sample key costs a full recursive
  walk on *every* lookup — N lookups over a tree of O(N x batches) files is
  quadratic — and makes one sample's new batch invalidate all the others.
- **The freshness epoch is the once-per-poll authority.** `check_data_freshness`
  bumps `_freshness_epoch` when the tree changes; `_check_mtime_cache` returns
  a cached entry with no filesystem call when the entry was stored in the
  current epoch. A poll issues roughly 3N + 2 `load_kraken_data` calls, so
  without this each one repeated the same fingerprint work. Epoch 0 means
  `check_data_freshness` has never run (CLI, report generation, tests), and
  those callers stay on the unconditional path check so they can never be
  served stale data.
- **A `stale` mtime verdict must not fall through to the TTL cache.**
  `_mtime_cache_state` returns `hit` / `stale` / `absent` precisely so callers
  can tell "no entry yet" (TTL is a fair fallback) from "the files
  demonstrably changed" (TTL is by definition older than that change). The
  earlier code collapsed both into `None` and consulted the TTL cache either
  way, so a report that advanced was ignored for up to `CACHE_TTL_SECONDS`
  (30 s) even though the loader had already detected it. Note this makes a
  genuine full-refresh poll *slower* than the pre-fix measurement, because
  the pre-fix run was skipping the re-parse it should have done.

`sample_detector.get_available_samples` consults its mtime cache *before* the
canonical manifest for the same reason — the manifest check re-parses
`_manifest.json` on every call, and the function runs several times per poll.
`canonical/` is in `_WATCHED_SUBDIRS` so a rewritten manifest still
invalidates the cache.

**Loader hot-path invariants (do not regress).** The Kraken2 loaders run on
every poll, so per-element pandas access is the dominant cost on a large
report. The 2026-06-05 perf pass (cProfile, 6 samples × ~3100 taxa) took the
per-poll loader work from ~2 s to <0.1 s; keep these contracts:

- **Report discovery is sorted.** `_find_kraken_reports` sorts at its existing
  realpath-dedup step. `glob.glob` returns filesystem enumeration order, and
  the accumulation order sets the row order of the aggregated frame — so what
  an operator saw in "All Samples" depended on the filesystem rather than the
  data. It was stable on APFS and not on the CI runner:
  `test_aggregation_preserves_first_occurrence` passed on the Python 3.11 job
  and failed on 3.12 in the same run, same code, two containers. One sort over
  a short file list; no extra filesystem work.
- **No per-row `df.iloc[idx][col]` in a parse loop.** `_parse_kraken2_report`
  builds `parent_taxid` by iterating `df["name"].tolist()` / `df["taxid"].tolist()`,
  not `df.iloc`. Each `df.iloc[idx]` materialises a cross-section Series
  (`fast_xs`); on 3000 rows that alone was ~98% of loader time.
- **Use `.tolist()`, not `.values`, for string columns in row loops.** Under
  pandas 3.0 `.values` on the arrow-backed `name`/`rank` columns returns an
  ExtensionArray whose per-element `[i]` goes through arrow `__getitem__`.
  `_accumulate_kraken_df` extracts every column with `.tolist()` for this
  reason. Numeric columns are unaffected but use `.tolist()` there too for
  consistency.
- **Single-report path skips accumulation.** `_parse_kraken_data_uncached`
  (per-sample branch) parses into `parsed_frames` and returns the lone frame
  directly when only one report contributes; `_accumulate_kraken_df` /
  `_aggregate_to_result_df` run only for genuine multi-file aggregation.
- **`get_sample_statistics_summary` parses each sample once when it safely can.**
  `latest_batch_equals_cumulative(main_dir, sample)` (glob/stat only, no parse)
  returns True only when the sample has neither a cumulative report nor any
  per-batch report — the case where `load_kraken_data` and
  `load_kraken_latest_batch` resolve to the same standard
  `<sample>.kraken2.report.txt`. The summary reuses `cumul_df` then; otherwise
  it loads the latest-batch horizon independently (the horizons legitimately
  differ once a cumulative or batch report exists). Regression-covered in
  `tests/test_qc_loaders_horizon.py`.

- **Per-file parsed-frame cache (`_report_frame_cache`).** `_parse_kraken2_report`
  is a thin wrapper over `_parse_kraken2_report_uncached` that memoises the parsed
  frame on `(realpath, st_mtime_ns, st_size)`. Within one poll the same physical
  report is otherwise parsed 2-3x — the aggregated "All Samples" load, the
  per-sample load, and `get_sample_statistics_summary` each go through this choke
  point under different higher-level cache keys (cProfile, 6 samples × ~3100 taxa:
  12 parses for 6 files in one fresh-data poll). The cache collapses that to one
  parse per changed file and, in realtime mode, makes an *incremental* poll
  re-parse only the sample whose report advanced. Measured on the per-poll
  harness: full-refresh poll 137 → 89 ms, incremental poll → 63 ms. Safe because
  parsed frames are read-only for every consumer (`apply_authoritative_taxonomy` /
  `recalculate_cumulative_reads` copy before mutating, `_accumulate_kraken_df`
  only reads). Only successful (non-None) parses are cached; an unstable/empty
  file returns None and is retried next poll (its mtime is unchanged once it
  stabilises, so the key alone cannot distinguish "unstable then" from "stable
  now"). `check_stability=False` (test-only) bypasses the cache so the two
  stability modes never share an entry. Regression-covered in
  `tests/test_classification_loaders.py::TestPerFileParseCache`.

All five were behaviour-preserving (loader output is byte-identical, verified
by sha256 over the full frame incl. `parent_taxid`).

**Species includes subspecies.** `core/taxonomy/ranks.py` owns `SPECIES_RANKS`
(`S`, `S1`, `S2`, `S3`) and is the single definition; before it there were
three disagreeing rules — `== "S"` in the verdict and attribution paths,
`{"S","S1","S2"}` in the Organisms tab's watchlist matching, and a
`normalize_ranks` table that mapped `S1/S2/S3 -> S` and **was never called**.
The consequence was that a subspecies watchlist entry was watchable on the
Organisms tab and could never reach the verdict banner.

The distinction is clinical: a Bioshield report resolves *F. tularensis* into
holarctica (Type B, the LVS lineage), tularensis (Type A, markedly more
virulent), novicida and mediasiatica, all at `S1`.

**Reads are not double counted by including them, but summing across ranks
would be.** Kraken2's `reads` is what was assigned directly at a node and
`cumul_reads` is that node plus descendants: on that report the species row is
3,406 direct / 9,602 cumulative and its four children sum to 6,196, which the
cumulative figure already contains. Per-taxon consumers (watchlist matching,
attribution, organism cards) treat each row as an independent taxid and are
safe. `report_generator._top_organisms` stays species-only on purpose — listing
a species beside its own subspecies in a "most abundant" ranking reads as
double counting even where the arithmetic is right.

The Taxonomy tab offers `S1` as a selectable level plus a "Subspecies Focus"
preset (`G, S, S1`); the Organisms tab's rank filter offers it too. Both are
OFF by default, because the species node's value already contains its children
— adding the level splits that flow rather than adding to it, which is right
for a Sankey and misleading in a flat list. The Sankey and Sunburst needed no
change: both resolve parents by walking the taxid parent chain rather than
assuming rank order, so an `S1` node hangs off its species correctly. Only the
UI was hiding the level.

**Sunburst node cap (visualization invariant).** `create_sunburst_data`
(`app/tabs/classification_helpers.py`) takes `max_taxa_per_level` and keeps the
top-N taxa by recalculated cumulative reads at each rank, mirroring
`create_sankey_data`. The classification callback passes the same `max_taxa`
value to both views, so they stay consistent. The default is `0` (= no cap) so
existing callers and tests are unchanged; the callback's own default is the
shared `max_taxa` (10, with 0 mapped to "no limit"). The cap is not only a
readability control: ~60% of an uncapped sunburst build is plotly's
per-element trace validation, which scales with node count (~3100 species nodes
on a GTDB run took ~57 ms; capped ~15 ms). A node whose direct parent is capped
out reparents to its nearest still-present ancestor (or `root`) via
`_resolve_sunburst_parent`, so capping never orphans a node. Regression-covered
in `tests/test_sunburst_tax_levels.py`.

### PAF Files (minimap2 validation)

```
{outdir}/validation/minimap2/{sample}_taxid{taxid}.paf       # pipeline
{outdir}/on_demand_validation/{sample}_{taxid}_ondemand.paf  # on-demand
```

Coverage uses cols 5/6 (tname/tlen), 7/8 (tstart/tend), 11 (mapq).

### nanometanf Output Layout

```
results/
├── kraken2/                           # *.kraken2.report.txt, *.cumulative.kraken2.report.txt
├── fastp/         OR   seqkit/        # mutually exclusive, depends on qc_tool
├── taxpasta/
├── validation/
│   ├── blast/                         # *.blast.tsv
│   └── minimap2/                      # *_taxid*.paf
├── on_demand_validation/
└── pipeline_info/                     # execution_trace_*.txt, report.html, timeline.html
```

Notes:
- `fastp/` and `seqkit/` are mutually exclusive; QC loaders try fastp first, fall back to seqkit.
- `seqkit/<sample>.tsv` is the current flat layout (plus the incremental `seqkit/<sample>/batch_stats/*.tsv`). The older nested `seqkit/<sample>/stats/*.tsv` layout was retired in the 2026-06-02 sunset pass.
- Nextflow trace lives at `pipeline_info/execution_trace_*.txt` (per `nextflow.config:407` in nanometanf). The GUI's NextflowManager redirects its own copy to `~/.nanometa/logs/trace.txt` for status polling, but the canonical pipeline emit is under `pipeline_info/`.

## Configuration

```yaml
# Input/Output
nanopore_output_directory: "/path/to/fastq"
# results_output_directory is COMPUTED (see outdir_resolution below); the
# operator's explicit results-folder choice goes in results_dir_override.
results_dir_override: ""
kraken_db: "/path/to/kraken2/db"

# Processing
processing_mode: "batch"        # or "realtime"
sample_handling: "by_barcode"   # or "single_sample", "per_file"

# Pipeline
pipeline_profile: "conda"       # always conda for nanometanf
# Upstream nanometanf has no `main` branch -- use `remote:dev` (active
# development), `remote:master` (legacy default), or a local checkout path.
pipeline_source: "remote:dev"   # or "/Users/.../nanometanf"

# Validation
blast_validation: true
min_reads_for_validation: 10
validation_identity_threshold: 90   # the only identity key; see below
e_val_cutoff: 0.01

# Samples that are negative controls. A watched organism found in one is
# reported alongside the detection with its read count and share of the
# positives; it is never listed as a triggering sample and never suppresses
# a detection. Under by_barcode input the name is the barcode directory.
negative_control_samples: []

update_interval_seconds: 30
```

### Run output directory is derived, not configured

`app/utils/outdir_resolution.py:resolve_run_outdir` decides where a run
writes: a non-empty `results_dir_override` verbatim, otherwise
`<project>/results/<slug(analysis_name)>`. It deliberately ignores
`results_output_directory` — that key holds the *computed* run dir, written
back at Start so the viewer follows it. A hand-written config that sets only
`results_output_directory` is silently redirected to the derived folder
(observed on the 2026-08-18 release check); use `results_dir_override` for an
explicit custom analysis folder.

### Kraken2 sizing belongs to nanometanf, not the generated `-c` config

`create_nextflow_config` deliberately emits NO `withName: 'KRAKEN2_KRAKEN2'`
block: the `-c` file outranks every pipeline config layer, and the retired
pin (`cpus = 1` from the old `kraken_cores` default, `memory = '8.GB'`) made
every GUI-launched classification single-threaded regardless of nanometanf's
`max(4, max_cpus/forks)` scaling (2026-08-18 audit). The GUI instead passes
`--kraken2_memory_gb` sized from the measured `hash.k2d` (+4 GB, floor 12)
and `kraken2_memory_mapping` resolved by `_resolve_kraken2_memory_mapping`
(explicit config value wins, else True everywhere — ARM included; mmap is
proven under Rosetta and nanometanf drops the flag on retry). Neither
`kraken_cores` nor `kraken_memory_mapping` is written by
`create_default_config` any more; a default there turns an "explicit
override wins" resolver into dead code (the `min_perc_identity` pattern).
The readiness checklist warns when `kraken_db` sits on a removable/network
volume (mmap random access over USB is pathological; the content-derived
`db_hash` makes a local copy free of re-preparation).

### Parameter mapping (non-obvious renames)

`core/config/parameter_mapping.py` translates config keys to Nextflow params:

- `nanopore_output_directory` -> `--input` (samplesheet) or `--nanopore_output_dir`
- `kraken_db` -> `--kraken2_db`
- `processing_mode: realtime` -> `--realtime_mode`
- `validation_identity_threshold` -> `--blast_perc_identity` AND
  `--validation_identity_threshold`. **One key, both params.** The legacy
  `min_perc_identity` was read first as a back-compat shim whose comment
  claimed "New configs only carry the latter" — but `create_default_config`
  wrote it into every config and no widget could change it, so the shim was
  the only path and the GUI slider was decorative. Retired 2026-08-08 from the
  defaults, the shipped config.yaml, the validator and the mapping. The
  dangerous direction was downward: lowering the slider to catch a divergent
  strain left BLAST filtering at 90 and said nothing.

### Path lifecycle

Every path-bearing config key is canonicalised at write time
(Configuration tab save) and at load time (`ConfigLoader.load_config`)
via `core/utils/path_utils.normalise_path`. Stripping, `~` expansion,
and `os.path.abspath` apply uniformly. Sentinel values are
deliberately preserved: `remote:...`, `http(s)://`, `git@`, and the
bundle-relative `./pipeline_source` / `./nextflow_plugins` strings
are returned unchanged so the bundle import-rebase logic continues to
work. The full set of normalised keys is `PATH_CONFIG_KEYS` in the
same module; consumers should call `normalise_config_paths(config)`
rather than reimplementing the loop.

`report_missing_paths(config)` returns `{key: path}` for every
path-bearing key whose value is set but does not exist on disk. A
startup callback (`warn_about_missing_paths_on_startup` in
`app/callbacks.py`) emits a single combined toast on app load so the
operator sees the stale path without having to read the terminal log.

`core/utils/kraken_utils.py` is the single source of truth for "is
this a valid Kraken2 database?". `KRAKEN_REQUIRED_FILES` lists the
canonical filenames; `check_kraken_db(db_path) -> (bool, list[str])`
returns a missing-file list for the caller to format. Configuration
tab save validation, `parameter_mapping.validate_nextflow_params`
(the launch-time gate), and `readiness_checker._check_kraken_db` all
delegate. Adding a new required file (e.g. `accmap.k2d`) is a
single-edit change.

### Config form: save / load / dirty-state symmetry

The Configuration tab has three field lists that must stay in lock-step,
or the form silently mis-reports: `apply_config_changes` (States that build
the saved config), `initialize_form_from_config` (Outputs that repopulate the
form), and `detect_form_changes` (Inputs that drive the "Modified" badge).
When you add a form field, wire it into all three. The dirty check delegates
to the pure `config_form_dirty(snapshot, form=...)` helper in
`config_tab_helpers.py`, fed the full saved field set keyed exactly as
`build_config_from_form` writes it (with `pipeline_source` reconstructed from
the three source widgets via `_pipeline_source_from_form`); a field missing
there means edits to it never flag the form modified, so the operator can
forget to Apply and launch with stale config. Form-loader `.get(key, default)`
fallbacks must match `create_default_config` — a divergent default (e.g.
`validation_method`, `sample_handling`) only surfaces when a key is absent, a
latent trap since `load_config` merges defaults on read.

**A control must do something.** The 2026-08 pass found three that did not,
and treated them on their merits rather than uniformly:

- **Removed** `danger_lower_limit` ("Alert Threshold (reads)"). No consumer
  anywhere, while its tooltip promised "Lower values are more sensitive" —
  an explicit false claim about detection sensitivity. Alerting is driven by
  each watchlist entry's own `alert_threshold`, which superseded this global.
- **Removed** `remove_temp_files` ("Clean temp files"). No consumer; it was
  only boolean-coerced in two places. Wiring it to Nextflow's `cleanup` would
  have started deleting work directories for every existing install and broken
  `-resume`, so promising less was the honest fix. The defensive coercion of
  an inherited key stays, since old configs still carry it.
- **Wired** `default_reads_per_level` and `gui_port`, which had obvious
  consumers. The first now seeds the Taxonomy tab's min-reads control (the
  12+-barcode aggregate heuristic takes `max(configured, 5N)`, so a configured
  floor is a floor). The second: `--port` now defaults to `None` so main can
  resolve flag > `gui_port` > 8050 — it used to assign argparse's 8050 over
  the config unconditionally, so the port field was saved, reloaded and
  ignored on every launch.

Before adding a form field, decide what reads it. Before removing one, check
whether the functionality exists elsewhere (as with the per-entry
`alert_threshold`) or whether wiring it would be destructive.

**Form-draft autosave.** Switching tabs re-fires `refresh-form-trigger`
(`trigger_initial_form_load` on `tabs.active_tab` change), so
`initialize_form_from_config` re-runs and would discard unsaved edits. To keep
edits across a tab switch, `detect_form_changes` also writes the in-progress
`form` dict to the session Store `config-form-draft` (the dict it already
builds for the dirty check — same `build_config_from_form` keys), and
`initialize_form_from_config` overlays that draft on top of the saved config
(`config = {**config, **draft}`). The draft is the *fourth* writer of the form
state and must stay key-compatible with the other three lists above. It is
cleared (`None`) on Load and Reset so those authoritative actions win; Apply
needs no clear because the draft already equals the applied config. Edits are
still only persisted to `last-session.yaml` on Apply — the draft is a
session-scoped convenience, not a saved config.

## Watchlist System

**Large-watchlist invariants (2026-08-21 audit; do not regress).** The
129-entry Bioshield list froze Chrome via three independent mechanisms;
each now has a guard and a test:

- **Matching is index-based, O(rows + entries).** `TaxonomyMatcher.
  build_entry_index` / `match_row_indexed` replace the per-(row x entry)
  loop; only the alert-relevant tiers (score >= 0.7) are indexed because
  the 0.7 alert floor makes lower tiers unobservable. `check_organisms_split`
  / `check_organisms_with_mapping_split` return (above, below) from ONE
  pass; the old entry points are wrappers. `_check_pathogens_both`
  (dashboard_helpers) memoizes on (organisms digest,
  `WatchlistManager.watchlist_signature()`, mapping signature) and returns
  per-call copies — the validation overlay mutates alert dicts in place.
  The signature is content-derived so edits invalidate by construction.
  Equivalence + scaling pinned in `tests/test_watchlist_matching_equivalence.py`
  (incl. N=500 x M=5000) and `tests/test_pathogen_check_memo.py`.
- **The DOM holds roughly the visible set, not the watchlist.** Accordion
  pathogen rows render on expand and unmount on collapse
  (`toggle_watchlist_expand`); the pathogens table paginates
  (`WATCHLIST_TABLE_PAGE_SIZE`, row ids keyed by taxid so ALL/MATCH
  callbacks are page-agnostic); organism cards use native `title=` not
  `dbc.Tooltip`; not-detected watched cards render from
  `not-detected-species-store` on first open; `update_genome_stats` skips
  tab switches away from the Watchlist tab. A collapsed `dbc.Collapse`
  MOUNTS its children — never pre-render bulk content into one. Budgets
  pinned in `tests/test_component_budgets.py`.
- **Lazily added pattern-matching components re-fire ALL callbacks.**
  Dash fires an ALL callback when matching components are ADDED, with
  their current values. `toggle_nested_pathogen` ignores fires whose value
  equals the entry's current state and fires whose taxid the manager
  cannot resolve; without both guards, expanding a list bumped tab-state
  and the resulting re-render wiped the expanded content. Apply the same
  guard style to any new value-carrying ALL input that lazy rendering can
  add.
- **Watchlist import is the worker/Store/finalize split** (`handle_upload`
  stages to `watchlists/.pending/`, `import_watchlist_worker` validates
  with progress and copies, `finalize_watchlist_import` owns the session
  side effects). `validate_and_parse` returns the parsed data; one import
  parses the YAML at most twice (pinned in `tests/test_watchlist_upload.py`).
  The collision confirm keeps only {path, filename} in the pending Store.

**Scale invariants, round 2 (2026-08-24 audit; do not regress).** Round 2
added the barcode axis (24-96 samples) with two acceptance criteria: the
interface never freezes, and the operator always sees progress. The guards:

- **Per-tick work is built once and shared.** Loader cache capacity scales
  with the detected sample count (`set_cache_capacity` in `loader_utils`,
  called from `sample_detector`; a fixed cap of 100 evicted two thirds of
  ~300 live keys at 96 barcodes on every cleanup). Per-sample organism
  attribution goes through `app/utils/organisms_memo.py` — the verdict
  banner, alert panel, dashboard alerts, modal breakdown and popover fill
  all read the one memo (epoch + negative-control keyed; epoch 0 bypasses).
  The validation parser is shared per results dir
  (`get_validation_parser`); construct `BlastValidationParser` directly
  only in tests. Pinned in `tests/test_tick_call_counts.py` (S=96: one
  organisms build across three call sites, zero parser constructions on a
  warm tick, zero globs for the processed count) and
  `tests/test_cache_capacity_scaling.py`.
- **The fingerprint keys on `results-dir-path`, not app-config.**
  `derive_results_dir` (callbacks/status.py) emits only when the resolved
  dir actually changes; `compute_results_fingerprint` takes that Store as
  Input with app-config demoted to State. A watchlist toggle must never
  re-walk the results tree (the old app-config Input made every toggle
  fire the whole fingerprint cascade). Pinned in
  `tests/test_fingerprint_dir_gate.py` and the walk-count test in
  `test_tick_call_counts.py`.
- **Browser stores are slim; disk files are full.** `export_config(
  slim=True)` (six fields, ~125 B/entry) is what every `dcc.Store` writer
  ships — the full form was 96-99% of a 189-721 kB app-config re-uploaded
  by 24 per-tick callbacks. `_save_last_session` re-fattens the custom
  block from the live singleton via `_full_watchlist_block` and never
  writes slim data over a full persisted block. The taxmap store ships
  `slim_mapping_store_payload`. Budgets pinned in
  `tests/test_payload_budgets.py`.
- **Click paths never block the request thread without feedback.** Export
  Results, QC plot export, taxonomy lookup, the path pickers and watchlist
  import are `background=True`; Start/Stop run main-process daemon threads
  (`start_async`/`stop_async` — BackendManager owns subprocess handles a
  DiskcacheManager worker process cannot hold) with a transition guard and
  a terminal toast via `surface_backend_transition`. Enable/Disable All
  persists once per batch (`set_entries_enabled`), and watchlist discovery
  consults its corpus-fingerprint cache. Every `background=True` callback
  must declare `running=` or `progress=` —
  `tests/test_background_callback_contract.py` is the fence.
- **Tab gating is display-only.** Sankey/Sunburst, QC figures, the
  per-sample QC table and QC cards skip while their tab is hidden and
  render fresh on activation. The detection chain (status cache, verdict
  banner, alerts, alert panel, readiness, fingerprint) is NEVER gated on
  the visible tab; `tests/test_tab_gating.py` introspects the callback map
  to enforce both directions permanently.
- **Caps hide cards, never state.** The alert panel caps at
  `ALERT_PANEL_CARD_CAP` (30, threat-sorted) with an explicit "…and N
  more" row; attribution popovers fill on open (MATCH callback from the
  memo); overflow organism cards ship as data and render on the Show-more
  click. The verdict banner stays uncapped and aggregate-scoped.

**Round-3 invariants (2026-08-24/25 audit; do not regress).** The
data-volume, memory and truthfulness pass, verified live on a real
realtime run plus failure drills:

- **The verdict knows about run health.** `select_verdict` takes
  `pipeline_error` (from backend `pipeline_status == "error"`; a user
  Stop clears it), `results_dir_lost` (dir previously fingerprinted,
  now unreadable) and `stale_samples` (from `core/utils/staleness.py`,
  fed by the loader's last-good fallback path). Precedence: a detection
  always wins (error noted in its subtitle); `pipeline_error` outranks
  every other state INCLUDING `overall_status_starting` (a crash during
  startup must not show eternal SCREENING); the ERROR run-state
  bypasses the banner's render gate like ACTIVE (the first post-crash
  render is transitional and must not freeze). The exported report has
  the same branch, reading `final_status` that
  `_apply_terminal_workflow_status` records into `.nanometa.run.json`.
  Staleness scopes normalize with realpath (macOS /tmp symlink).
- **No background callback may take a per-tick Input.** DiskcacheManager
  spawns an OS process per invocation and leaks parent-side pipe fds
  (~5/spawn, measured 4,500+ pipes in 2 h). Per-tick work runs behind a
  synchronous main-process gate that bumps a due Store
  (`readiness-recompute-due`, `main-results-due`, `qc-stats-due`), and
  the periodic readiness probes run in a daemon thread with no spawn.
  `tests/test_readiness_spawn_gate.py` greps every background decorator
  and fails on `update-interval` Inputs.
- **Batch-axis loaders are cached on immutability.** seqkit batch TSVs
  and kraken batch reports are write-once: per-file frame caches
  (`seqkit_batch_cache`, `_report_frame_cache`) plus the per-sample
  accumulation cache (`report_accumulation.py`, byte-identical via
  contiguous-segment merge with an interleaved-names fallback) make a
  rebuild O(changed sample). The latest-batch path and the validation
  batch-id enumeration memoize on directory mtimes (adding a file bumps
  the dir mtime; in-place rewrites bump the FILE mtime and are covered
  by per-file keys -- do not swap one for the other).
- **Caches are byte-budgeted and inventoried.** The frame caches honor
  `NANOMETA_FRAME_CACHE_MB` (default 2048) with eager same-path
  supersession; `_cache_and_return` stores ONE shared frame (consumers
  copy before mutating); every module-level cache must be wired into
  BOTH `clear_all_loader_caches` and `instrument.reset_caches` --
  `tests/test_cache_inventory.py` greps for unwired cache-shaped
  assignments and is the fence.
- **A saturated fingerprint degrades, never freezes.** Past
  `_MAX_FINGERPRINT_FILES` the stat pass stops but the TTL time-bucket
  is folded into the fingerprint, so both cache layers re-validate
  every `CACHE_TTL_SECONDS` instead of serving a late in-place rewrite
  stale forever.

Sources searched in priority order:

1. Project: `{project_dir}/watchlists/*.yaml`
2. User: `NanometaPaths.watchlists` (custom uploads persist here) —
   `<data_dir>/watchlists`, or `<project_dir>/.nanometa/watchlists` when a
   project is set
3. Built-in: `core/config/data/watchlists/*.yaml`

**One watchlist directory, resolved in one place.** The user tier resolves
through `get_watchlists_dir_from_env()` (`core/utils/paths.py`), exposed as
`WatchlistLoader.user_watchlist_dir`. The loader's search path, the GUI upload
callback (`watchlist_tab.handle_upload`), and `BundleManager.export_bundle`
all read it. When all three hard-coded `~/.nanometa/watchlists` instead, a run
started with `--data-dir`/`--project-dir` wrote uploads somewhere the exporter
never looked and the bundle silently shipped without them. `import_watchlist`
refuses a destination filename that already exists or that shadows a built-in
stem (a watchlist is keyed by file stem, so either collision replaces a list
invisibly); pass `overwrite=True` to force. An uploaded entry with neither
`taxid_ncbi` nor `db_taxid` gets a synthetic key from `_stable_pseudo_taxid`
and can never match a Kraken2 report — `find_entries_without_taxid` surfaces
those at upload time. `build_watchlist_yaml` is the inverse (session entries →
v2.0 YAML) behind the Watchlist tab's Download-as-YAML control; it never emits
a synthetic key as `taxid_ncbi`.

Format examples live in `core/config/data/watchlists/` — see any built-in YAML
for the v2.0 schema (pathogens with `taxid_ncbi`, `threat_level`, `bsl_level`,
`alert_threshold`, etc.).

### Taxonomy resolution

`TaxidMapper.generate_mappings()` (`core/taxonomy/taxid_mapping.py`) tries strategies
in order: ExactTaxid -> ExactName -> Variant -> Reclassification -> Fuzzy -> ParentTaxon.
Includes GTDB suffix variants (`_A`...`_Z`) and prefers species-level matches.

Genome download by kingdom: Bacteria/Archaea use GTDB representative genomes
(`isGtdbSpeciesRep`); other kingdoms use NCBI RefSeq. Downloads via NCBI Datasets CLI,
output to `~/.nanometa/genomes/{taxid}.fasta`.

### API circuit breaker and taxonomy auto-selection

GTDB and NCBI taxonomy clients in `core/taxonomy/taxonomy_api.py`
share a class-level per-host circuit breaker. After
`_CIRCUIT_FAILURE_THRESHOLD` (default 3) consecutive failures, the
host is short-circuited for the remainder of the process and
subsequent calls return `None` immediately. Default HTTP timeout is
5 s. The breaker is in-memory only — a transient outage does not
persist a disabled flag. The Verify Taxonomy IDs callback in
`watchlist_tab.py` skips the API that cannot resolve the loaded
database's names, so an NCBI run does not stall on a degraded GTDB
endpoint. It reads the *detected* nomenclature via
`_apis_for_database` → `load_profile_for_db`, not a config key; an
undetectable database queries both, since a guess there is what
would strand the run. Operators can still tick both checkboxes for
explicit cross-validation.

### One database profile, two axes

`core/taxonomy/database_profile.py` holds everything the app knows
about a loaded Kraken2 database's taxonomy, in two independent
fields, both detected from the database itself:

- `taxids_are_ncbi` (bool) — may a raw taxid comparison be trusted?
  Gates `ExactTaxidStrategy`, the `db_is_ncbi` shortcuts in both
  `check_organisms` paths, and the confidence scorer's
  `taxid_verified` weight. **Defaults to False**, because trusting an
  unverified taxid names the *wrong organism*, while distrusting a
  good one only skips a shortcut — name matching still runs.
- `nomenclature` (`ncbi` | `gtdb` | `unknown`) — which service can
  resolve these names? Drives the Verify API choice, the genome
  `kingdom="Bacteria"` hint, and whether the GTDB genus-suffix
  variants are generated. **UNKNOWN narrows nothing**: query both,
  generate variants anyway.

This replaced four disagreeing axes — the `kraken_taxonomy` config
key, `DatabaseTaxonomyType`, `TaxonomyType`, and the watchlist YAML's
`taxonomy_mode`. `MIXED` was never read by anything precisely because
one axis was trying to answer both questions; the pair can express it
(`taxids_are_ncbi=False, nomenclature=ncbi`).

Detection lives in `database_indexer._detect_taxids_are_ncbi` (probes
19 well-known taxids, ALL must match) and `_detect_nomenclature`
(a GTDB rank prefix or a single `Genus_A` polyphyly suffix is
conclusive; samples up to 5000 species nodes, *not* an
insertion-order head). `_nomenclature_hints_from_files` is the
fallback for signals the inspect dump lacks. Deliberately not
detected: the directory name, and any default-to-GTDB.

The profile rides `{db_hash}_index.json` (cache version 2.0; a v1
file is discarded and rebuilt, since it holds no name evidence to
migrate from) and is copied onto `{db_hash}_mappings.json`, which is
kept rather than rebuilt because it carries operator verifications.
That copy is load-bearing: background workers load the mappings file
standalone against an empty index singleton. An operator override
lives in a *sibling* `{db_hash}_profile_override.json` so it survives
the index rebuild.

**GTDB variant gating.** GTDB splits polyphyletic genera and suffixes
the parts alphabetically (`Bacillus_A`), and which suffix a genus got
is not derivable, so matching an NCBI name to its GTDB counterpart
means trying all 26 — 78 strings per name. These are no longer built
eagerly: `NormalizedName.variants` keeps ~5 cheap forms and the GTDB
set is a lazy `gtdb_genus_variants` property, appended only via
`all_variants(include_gtdb=profile.generates_gtdb_variants)`. The
three `match_strategies` call sites gate on that. UNKNOWN counts as
"generate": a misdetected GTDB database must still match its
organisms, and a false positive costs only CPU, whereas a false
negative is a missed detection. Measured saving on an NCBI database
(13 of the 14 shipped): 156k fewer string builds per 2000 names.
Regression-covered in `tests/test_database_profile.py`.

**flextaxd / hybrid databases are the normal case.** The in-house field
databases (Bioshield and similar) are built with flextaxd: an NCBI
backbone with finer-resolution clades grafted in, then minimized to fit
a field laptop's RAM. Three consequences the code must respect:

- **The taxid space is hybrid.** Backbone taxa keep real NCBI taxids
  (9606, 2697049); grafted nodes get new ids from a high block
  (4,000,000+ in Bioshield, cleanly separated by a ~300k gap). Nothing
  is renumbered, so `taxids_are_ncbi` is correctly True and the
  exact-taxid shortcut is safe *and valuable* — on a real run it
  rescued four detections whose names have legitimately diverged
  (ICTV renamed SARS-CoV-2 to *Betacoronavirus pandemicum*, *Candida
  auris* to *Candidozyma auris*). **Do not add name verification to
  `ExactTaxidStrategy`** — it would break exactly those.
- **Pathogens live in the grafted region under GTDB names.**
  *Bacillus anthracis* is `Bacillus_A anthracis` at 4005020, not NCBI
  1392. So detection depends on the GTDB genus-suffix variants, which
  is why `nomenclature` detection and variant gating are load-bearing
  here rather than cosmetic.
- **Minimization prunes organisms.** A watchlist entry may not exist
  in the database at all, and an ALL CLEAR for it is not a negative
  result — it is no result. `core/taxonomy/coverage.py`
  (`analyse_coverage`) classifies every watchlist entry as detectable
  / genus-only / ambiguous / absent and the Preparation tab reports it
  after a scan. Measured on a real Bioshield build against the shipped
  watchlists: 108/116 detectable, 3 genus-only, 4 shared nodes, 5
  absent. Entries that name a family (`Adenoviridae`) are not flagged
  as genus-only — a broad match is what they asked for, and crying
  wolf trains operators to skip the report.

`_build_db_taxid_index` returns **all** watchlist keys that resolve to
a database node, not one, because last-writer-wins silently dropped
the rest and made the survivor arbitrary. The first is the match; the
others become `ambiguous_with` on the alert and are rendered by the
verdict banner as "X or Y". This matters clinically: GTDB treats
*Burkholderia mallei* as a lineage within *pseudomallei*, so a
melioidosis case would otherwise be announced as glanders. It is an
upstream taxonomy limitation, unresolved in the flextaxd workflow as
of 2026-07, so the app reports it rather than pretending to resolve
it.

**One pseudo-taxid definition.** `core/taxonomy/pseudo_taxid.py` owns
`PSEUDO_TAXID_BASE`, `is_real_ncbi_taxid` and `stable_pseudo_taxid`.
The constant previously existed in four modules independently. Entries
with no NCBI identity are keyed in this reserved band so an
NCBI-by-taxid call can refuse them — esummary returns HTTP 400 for a
nonexistent taxid, which would trip the shared per-host circuit
breaker for every other organism in the run.

### Database registry: bundled + operator-managed

The Kraken2 download manifest is loaded from two sources on startup
and merged into the picker store:

1. `nanometa_live/kraken2_databases.yaml` (bundled defaults; public
   `genome-idx` URLs).
2. `~/.nanometa/kraken2_databases.local.yaml` (operator-managed;
   same schema).

Local entries win on key collision. A missing local file is silently
skipped; a malformed one logs and continues with the bundled
defaults. Use the local file to register private mirrors or in-house
custom builds without forking the package.

## Validation System

Two validation sub-tabs:
- **BLAST** — read-centric: identity scores, distribution plot, stats table
- **Minimap2/Coverage** — genome-centric: depth chart, cumulative curve, histogram, mapq filter

**Result-loading priority** (`ValidationParser.get_validation_results`): the
aggregate `validation/validation_results.json` is authoritative for the
`(sample, taxid, method)` tuples it lists, but it does **not** short-circuit the
on-disk scan. The parser seeds its result list from the aggregate, then ALWAYS
also scans the individual per-(sample, taxid) files — `blast/*.blast.tsv` *and*
`minimap2/*.minimap2_stats.json` — and merges in any `(sample, taxid, method)`
the aggregate did not already cover (method class = "minimap2" vs everything-else
= "blast"). BLAST and minimap2 are distinct methods for the same pair, so the
disk files supplement the aggregate rather than dedup against it across methods.

This symmetry is load-bearing: nanometanf's aggregator
(`aggregate_validation_results`) keys entries by stats-file glob, so a
`(sample, taxid)` whose blast stats did not reach the aggregator work dir — or
whose blast key was dropped by a realtime cumulative join — appears as a
**minimap2-only** entry in `validation_results.json` while its `blast.tsv` still
lands on disk. The earlier code returned the aggregate whole the moment it was
non-empty (`if aggregate_results: return`), so a minimap2-only aggregate hid the
on-disk BLAST entirely: Coverage sub-tab populated, BLAST sub-tab empty — the
exact "users don't see BLAST validation" report. The minimap2 individual-file
path (`core/parsers/minimap2_stats.py`, added in the 2026-06-02 audit after the
Coverage tab went blank mid-run) already ran unconditionally and deduped only
against existing *minimap2* entries by `(sample, taxid)`; the blast.tsv scan now
does the same, deduping only against existing *blast*-class entries so a
minimap2 entry never blocks a blast.tsv. Regression-covered in
`tests/test_blast_validation_parser.py::TestAggregateWinsHidesBlast` (minimap2-
only aggregate + on-disk blast.tsv must surface both) and the synthetic
`barcode05/263` fixture (`tests/validation/`), which carries exactly that shape.

### Realtime cumulative validation + per-batch drill-down

In realtime mode the pipeline keeps a run-so-far cumulative view per
`(sample, taxid)` instead of overwriting each batch (the prior behaviour, where a
later empty batch reset a confirmed organism to 0). Layout:

- **Cumulative (canonical flat):** `validation/{minimap2,blast}/<sample>_taxid<tid>.{paf,blast.tsv,*_stats.json}`
  — kept current each batch by nanometanf's `validation_cumulative_aggregator`
  module (each aggregation receives the complete batch set seen so far —
  scan/state, no publish-dir read-back — so a concurrent batch cannot erase an
  earlier one; coverage breadth is recomputed since it is not additive,
  `total_reads` summed over the batch stats). The GUI reads these by default.
  The aggregate `validation/validation_results.json` is different: with the
  default `validation_aggregate_interval = 0` it is written ONCE at session
  end. The GUI stays live mid-run through the per-pair files above (the
  ValidationParser always scans them, and its cache fingerprint tracks their
  in-place rewrites).
- **Per-batch (preserved):** `validation/{minimap2,blast}/batch/<sample>_taxid<tid>_<batch_id>.*`
  — every batch retained for drill-down. `batch_id` is the realtime batch index.

GUI side: a "View: Cumulative / Single batch" toggle (hidden unless a `batch/`
dir exists) drives `get_validation_results(batch_id=…)` and
`_load_real_coverage(batch_id=…)`; batch results come from
`core/parsers/validation_batch.py`. In batch processing mode (no `meta.batch_id`)
nothing changes — the flat file is the result and the aggregator is skipped.
Added 2026-06-02 (nanometanf + nanometa_live `validation-cumulative-realtime`).

### On-demand validation

`OnDemandValidator.validate_organism()` invokes `nextflow run -resume --validation_only`
against the existing pipeline outdir. Previously-validated `(sample, taxid)` pairs hit
the Nextflow work cache; only newly-added taxids run end-to-end.

**The launch must share the main run's resume context** (2026-08-18): `-resume`
resolves through `<launch dir>/.nextflow/history` and the `-work-dir` task
cache, so `resolve_launch_context` launches from `data_dir` with
`-work-dir <data_dir>/work`, exactly matching `NextflowManager`. Sharing only
the outdir shares nothing `-resume` reads. The GUI's aggregate-scope
`sample="all"` token is mapped to "no filter" before the result read-back
(`_normalise_sample_filter`) — used verbatim it is a sample name matching
nothing, and a successful run was reported as failed. Every failure path
writes the command, cwd and stdout/stderr to `<results>/logs/` via
`write_failure_log`, because the launcher runs in a background worker whose
logger output reaches no file.

Genome list `<outdir>/on_demand_validation/pathogen_genomes.json` is cumulative
across calls (atomic `.replace()`), seeded on first call from the main run's
`pipeline_input/pathogen_genomes.json`. The seed is load-bearing: nanometanf's
aggregator rebuilds `validation_results.json` over exactly the taxids it is
handed, so an unseeded first call shrank the aggregate to its single taxid.
On the pipeline side, `--validation_only` discovers samples from
`*.kraken2.classified.fastq.gz` in `--kraken2_output_dir` (stem = sample id,
matching the subworkflow join); the `--reads_dir` flat glob is only a
fallback and cannot see `by_barcode` subdirectories.

On load, an on-demand result *supersedes* the pipeline result for the same
`(sample, taxid, method)` in `ValidationParser.get_validation_results` (it is an
explicit operator re-check, so it wins in place); a method the on-demand run did
not cover is left untouched. `OnDemandValidator._save_results` derives its
`validation_status` from `ValidationResult.determine_status` rather than a private
threshold copy, so the two paths cannot drift. Both changed in the 2026-06-02
validation audit.

Requirements: `pipeline_source` configured, `save_reads_assignment: true`,
original FASTQ accessible. `pipeline_source` is now mandatory: missing config
or a `None` return from `validate_via_nanometanf` produces a failed
`ValidationResult` with a descriptive `error_message` instead of silently
running a parallel subprocess path. The legacy local-subprocess fallback was
removed in the 2026-05-07 audit pass (commit `4c7c284`).

### Durable invariants in the validation pipeline

- `subworkflows/local/validation/main.nf` coerces `taxids_to_validate` to string before `.split()`. Nextflow's CLI parser silently promotes all-digit single values to `Integer` regardless of schema; coercion is required for single-taxid GUI calls.
- `modules/local/minimap2_validation/main.nf` double-escapes `\\n` in the awk JSON writer because bare `\n` in a Groovy triple-quoted string expands at parse time.
- `modules/local/blastn_validation/main.nf` deduplicates BLAST hits by `qseqid` so `hit_rate` stays bounded to `[0, 1]`. Counting raw HSPs produces hit rates above 1.

## Offline Deployment

Three concerns:

1. **Bundle export/import** (`BundleManager`). Ships pipeline source, plugins,
   watchlists, genomes/BLAST DBs, conda cache, and `manifest.json` with `build_platform`.
   Kraken2 DB excluded by size — transferred separately. `import_bundle` rewrites
   relative paths to absolute and warns on platform mismatch.

   The pre-copy checks (manifest version, recorded `export_warnings`,
   per-file checksums, DB hash, tool/Nextflow versions, build platform) live
   in `_verify_extracted_bundle`, shared by `import_bundle` and the
   non-mutating `verify_bundle` / `nanometa-prepare verify --bundle <path>`.
   Add a new check there, not in the import path, or the dry run stops
   matching what the import will do. Blockers are forcible unless marked
   `fatal`; `stop_on_blocker` reproduces the import's short-circuit ordering.
   `_load_container_images` returns a report (not a count) so the import can
   distinguish "the bundle is short of images" (build machine) from "this
   machine has no working Docker" (field machine) — the two need opposite
   remedies and the old single message named the wrong one.

   **An import must not report success over a problem it found.** Three rules,
   all added 2026-08-14 after an air-gapped rig run:
   - A supplied `--db` that is not a usable database sets `kraken_db_invalid`
     and warns, naming the missing files. The pre-existing `kraken_db_unset`
     fires only on an EMPTY path, so a typo, an unmounted drive or a moved
     directory imported in silence though it fails the run identically. The
     two keep separate flags: importing first and pointing the database later
     is a supported flow and must not start reporting an invalid path. Export
     checks the same thing through the same `check_kraken_db`, because the
     `db_hash` it records is derived from that path and a hash over nothing
     makes the import's compatibility check meaningless.
   - A failure writing the rebased config sets `success = False` and
     `config_write_failed`. It used to append a warning and leave `success`
     True, shipping an installation whose config still held `${KRAKEN_DB}` and
     `./pipeline_source`.
   - Blocker messages state the condition, not the consequence. They opened
     with "Import aborted:", which is false in `verify_bundle` (a dry run) and
     in a forced import that completes — both observed in the rig.

   **Note the config-rebase block is skipped entirely when the bundle carries
   no `config.yaml`**, including the `offline_mode` assignment, without
   comment. `_make_minimal_bundle` in the tests takes `extra_files` so a test
   can build a bundle that reaches it; the default minimal bundle does not,
   which is why the first version of those tests passed against unfixed code.

2. **Subprocess env injection** (`NextflowManager._build_nextflow_env`). When
   `config['offline_mode']` is true:
   ```
   NXF_OFFLINE=true             # literal "true", not "1"
   NXF_DISABLE_CHECK_LATEST=true
   NXF_PLUGINS_PATH=<dir>       # suppresses registry probe
   NXF_PLUGINS_DIR=<dir>        # legacy install-target alias
   NXF_CONDA_CACHEDIR=<dir>
   ```
   `validate_pipeline_source` rejects `remote:` / `https://` / `git@` sources when offline,
   before any `git ls-remote` fires. `_build_nextflow_env` starts from
   `os.environ.copy()`, so any `NXF_*` variable exported by the shell that
   launched `python -m nanometa_live.app` propagates to GUI-spawned pipeline
   runs without code changes.

   **Singularity offline wiring invariant (do not regress).** A
   docker/singularity export pulls every pipeline module image into the
   bundle's `pipeline_containers/` (`_BUNDLED_PIPELINE_CONTAINERS_DIRNAME`),
   and three pieces must stay in lock-step for an air-gapped singularity run
   to reuse them instead of re-pulling (which fails offline):
   - **Import restores the dir.** `import_bundle`'s copy loop MUST include
     `_BUNDLED_PIPELINE_CONTAINERS_DIRNAME` so the images land under
     `<home>/pipeline_containers/`; it then `docker load`s any `.tar` and, when
     `.img`/`.sif` are present, sets `result["singularity_cache_path"]` and
     writes `nxf_singularity_cachedir` into the imported config. The same name
     must also appear in the post-copy `_copied_roots` prefix tuple — those
     images are the largest files in the bundle and therefore what an
     interrupted copy truncates first, yet they were the one thing the
     re-verify skipped.
   - **Env injection points Nextflow at them.** `_build_nextflow_env` sets
     `NXF_SINGULARITY_CACHEDIR` and `NXF_SINGULARITY_LIBRARYDIR` from
     `config['nxf_singularity_cachedir']` (symmetric with the conda-cache
     block). nanometanf sets no `singularity.cacheDir`, so this env var is the
     only hook.
   - **Filename must match Nextflow's cache convention.**
     `_pull_one_singularity_image` names images via
     `_singularity_cache_name` — Nextflow's `SingularityCache.simpleName`
     (strip scheme at `://`, replace `:` and `/` with `-`) plus `.img`. Any
     other name makes Nextflow re-pull. Verified against the `SingularityCache`
     class in the bundled Nextflow jar; stable across 22.x–26.x — keep it in
     lock-step. Regression-covered in
     `tests/test_bundle_manager.py::TestSingularityBundleWiring` and
     `test_nextflow_manager.py::TestBuildNextflowEnv`. `import_bundle` also
     cross-checks the loaded image count against the manifest's
     `pull_result.image_count` and flags a partial set (`incomplete_image_set`).

   **Conda pre-warm invariants (2026-08-27 audit; do not regress).** The
   audit found pre-warmed bundles dead-on-arrival even same-OS/same-arch; four
   guards now make conda mode real:
   - **Envs are relocatable via a recorded padded build prefix.** Pre-warm
     builds the cache under a >=180-char prefix (recorded as
     `manifest.pre_warm_conda_envs.build_prefix`); import rewrites it to the
     restored path — text replace, NUL-padded in-place for binaries, symlink
     retarget (`core/workflow/conda_cache_utils.relocate_conda_cache`).
     Conda envs embed the build prefix in shebangs/binaries, so without this
     every env fails exit-127 at first use. Absolute symlinks are made
     relative at export (tarfile's `data` filter aborts on absolute link
     targets); import copies symlinks as symlinks. **Every patched Mach-O is
     ad-hoc re-signed** (`_resign_macho`, `/usr/bin/codesign -s -`): the byte
     rewrite invalidates the code signature and Apple Silicon SIGKILLs the
     binary at exec (exit 137 — proven live: every python process died while
     unpatched C tools ran; conda-pack re-signs for the same reason). Pinned
     in `tests/test_conda_cache_relocation.py`.
   - **Scenarios drive real pipeline params via a typed `-params-file`.**
     Under the NF 26 strict parser CLI `--flag value` params arrive as
     strings and nf-schema rejects them, so booleans/ints must travel as
     JSON. Every scenario gets a runner-written stub Kraken2 DB (VALIDATION
     is nested inside the classification gate); validation scenarios set
     `save_reads_assignment`+`save_output_fastqs`; realtime is one bounded
     scenario (`max_files: 1`). All 8 verified against the real pipeline via
     `nextflow -preview`; `-stub` env creation proven live. Pinned in
     `tests/test_prewarm_scenarios.py`.
   - **Export outcomes reach the operator.** `export_bundle` returns
     `ExportResult` (path/warnings/manifest); pre-warm and container-pull
     warnings fold into `export_warnings` so GUI (amber alert), CLI and
     verify/import all replay them. Broken envs are pruned pre-tar; import
     cross-checks env count (`incomplete_conda_cache`, mirror of
     `incomplete_image_set`).
   - **The effective cache is guarded at launch.**
     `NextflowManager._sweep_conda_caches` purges broken envs from BOTH
     `work_dir/conda` and the configured `nxf_conda_cachedir` (env dirs are
     `env-*` OR any dir with `conda-meta/` — named envs exist); offline mode
     with a configured-but-missing cache REFUSES to launch instead of
     attempting a network solve.

   **Deployment GUI invariants (same audit).** A docker/singularity (or
   conda+pre-warm) export without a resolvable local pipeline checkout is
   blocked in the GUI (it silently produced a bundle with zero images); the
   pre-export readiness gate checks the runtime for the SELECTED engine
   (`pipeline_profile` override); `finalize_import` pushes
   `result["imported_config"]` into `app-config` and reloads the live
   WatchlistManager (the running app used to keep the pre-import config until
   restart); `verify_bundle` has a GUI button; the wizard single-step callback
   is `background=True`; readiness enforces the real Nextflow floor
   (`_NEXTFLOW_MIN_VERSION`) plus offline plugins/conda-cache checks. Pinned
   in `tests/test_deployment_gui_fixes.py` and
   `tests/test_readiness_offline_checks.py`. GUI component gotcha: the
   Deployment tab's export stage line is `bundle-export-progress` —
   `export-progress` is TAKEN by the Export Results watchdog
   (`dashboard_layout.py`), and reusing it broke the Dash renderer at load.

3. **Offline-mode propagation** to NCBI/GTDB callers. `GenomeManager` methods and watchlist
   Validate / Add-custom-species callbacks read `offline_mode` and short-circuit network calls.
   Caches (`TaxonomyCache` / `OfflineTaxonomyCache`) are consulted first either way.
   Callers must reach `GenomeDownloadManager` through the shared
   `get_genome_manager()` singleton (which carries the live `offline_mode`), not
   by constructing a fresh instance — a direct `GenomeDownloadManager()`
   defaults to `offline_mode=False` and downloads over the network even in
   offline mode. `OnDemandValidator.genome_manager` was the one bypass; it now
   delegates to the singleton.

### Toolchain floor (Nextflow 26.04.0)

`nanometanf` floors at `nextflowVersion = '>=26.04.0'` (manifest in
`nanometanf/nextflow.config`). The matching `nf-core` conda env ships
Nextflow 26.04.0 / nf-core/tools 4.0.2 / nf-test 0.9.5. The pipeline
parses cleanly under the strict v2 grammar (default in 26+) — no
`NXF_SYNTAX_PARSER` opt-in needed. Verification is in
`docs/audit/realtime-2026-05-09.md` sections 13 and 14.

One known upstream wrinkle: **`nf-core/tools 4.0.2 pipelines lint`
crashes** with `LiveError` from `rocrate.parse_manifest_contributors`.
Pin `nf-core==3.5.2` for local lint runs until the rich progress-bar
nesting is fixed upstream. This is unrelated to the runtime path —
pipelines run normally under 4.0.2.

The 25.10.x watchPath JVM cleanup hang (the historical reason for the
`NXF_VER=25.04.7` workaround) was resolved upstream in 26.04.0.

### Cross-platform restriction

Conda envs built by Nextflow embed absolute build-machine paths and per-arch binaries.
The PATH half is handled since 2026-08-27: import relocates the recorded build
prefix into the restored cache (see the conda pre-warm invariants above), so a
same-platform machine-to-machine move works regardless of directory layout.
The ARCHITECTURE half is physics: **build and field machine must share OS and
CPU architecture** (and, practically, a compatible glibc generation on Linux —
the platform check cannot see distro drift). Cross-platform deployment means
docker or singularity mode.

### What the air-gapped rig proved (2026-08-14)

An Ubuntu 24.04 + apptainer 1.5.3 container, `--privileged`, on a Docker named
volume, verified air-gapped (loopback only, no DNS, no outbound TCP) before any
result was trusted. Rebuild recipe in the `offline-audit-rig` memory. Verified
end to end, not by unit test:

- **Container reuse, the assertion that matters.** With `NXF_OFFLINE=true` and
  `NXF_SINGULARITY_CACHEDIR` pointing at the imported `pipeline_containers/`,
  Nextflow logged `SingularityCache - Singularity found local library for
  image=…; path=…` and made **zero pull attempts** with zero network errors.
  The `_singularity_cache_name` convention holds against Nextflow 26.04.6.
- The bundle built on an **arm64** host pulled **amd64** images
  (`target_platform: linux/amd64` honoured), recorded
  `observed_architectures: ['amd64']` from real SIF headers, and
  `verify_bundle` on the arm64 rig correctly **refused** the import.
- Import restored 25 images, rebased `pipeline_source` absolute with `main.nf`
  present, set `offline_mode: True`, and wired the singularity cachedir.
- The GUI served air-gapped: HTTP 200, **no external URLs**, and both icon
  fonts resolved (130,396 / 176,032 bytes).

**Not proven, and not to be reported as such:** amd64 execution (the rig is
arm64 — the run failed exactly there with "the image's architecture (amd64)
could not run on the host's (arm64)", which is this restriction confirmed
rather than worked around), setuid apptainer, a real field kernel/distro, a
pipeline run to completion, and conda-profile bundles with pre-warmed envs.

The export unions singularity URLs with docker fallbacks (~30% of nf-core
modules ship only a `community.wave.seqera.io` tag), so a singularity bundle
holds ~25 images, not the 14 that `unique_container_refs(entries,
"singularity")` alone reports. Sizing a bundle from that call under-counts.

### Backend hardening

Three guards run on every pipeline launch and shape what an operator sees when
something goes wrong:

- **Half-built conda env purge** (`NextflowManager._purge_broken_conda_envs`).
  Sweeps `<work_dir>/conda/env-*/` before each conda-profile run, removing any
  env directory missing `conda-meta/history` (the marker conda writes last on
  successful build). Without this, a SIGTERM-killed env build leaves a stub
  directory that Nextflow's cache treats as ready -- the next run activates an
  empty env and the first process needing it exits 127 (`command not found`).
- **Loader nested-mtime walk** (`_get_path_fingerprint` in
  `core/utils/loader_utils.py`). Bounded recursive walk (5000 files) so the
  kraken2 cache fingerprint advances when realtime-mode files land under
  `kraken2/<sample>/batch_reports/`. The non-recursive predecessor saw zero
  direct files in `kraken2/`, locked in an empty result on the first poll,
  and the dashboard sat at 0 sequences for the entire run.
- **Output-collision modal** (`detect_existing_results` +
  `archive_existing_results` in `BackendManager`). Pre-run scan of
  `RESULT_SUBDIRS`; modal offers Archive (`_archive_<ts>/`), Continue (with
  `-resume`), or Cancel. The fingerprint above tags the modal red when the
  new input differs from what the prior run wrote.

**Polling-tick backstop on results-driven callbacks.** Lead callbacks
in `dashboard_tab.py` (verdict banner + status cache),
`main_tab.py` (Organisms), `qc_tab.py` (QC plots),
`classification_tab.py` (Sankey/Sunburst), and `validation_tab.py`
(Validation data store) take `update-interval` as an Input alongside
`results-fingerprint`. Without the backstop, a tab visited after the
first fingerprint tick on a quiet outdir leaves the operator looking
at the empty initial layout because the fingerprint never advances
again. The 2-second `should_skip_update("...")` debouncer or the
`get_trigger_type(ctx) == "interval"` guard keeps the new Input from
multiplying work — the backstop fires at most once per tick.

**A verdict must never claim a result it did not earn.** Three of the defects
found in the 2026-07 campaign were one defect: the system rendering "we did not
check" identically to "we checked and it is fine". The verdict banner said ALL
CLEAR with no watchlist loaded while *F. tularensis* sat at 54.2% of reads; the
exported report said NO WATCHED ORGANISMS DETECTED in the same situation; and a
sample whose reads were unreadable was offered like a healthy one. For a
biothreat tool those are opposite statements — a missing measurement versus a
negative result an operator may act on.

Three guards now enforce the distinction; keep them:

- `select_verdict` returns **NOT_SCREENED** when `n_watched == 0` and
  **INSUFFICIENT_READS** when `total_reads < low_read_floor` (default 10,
  anchored to `min_reads_for_validation`, and passed from the config by
  `update_verdict_banner` so the banner, the Organisms caveat and the
  exported report cannot disagree about the same depth). Both are amber, not green: wording
  alone is insufficient when a green banner reads as reassurance on its own.
  The genuine ALL CLEAR states its own depth so it cannot be confused with a
  shallow one.
- `select_verdict` takes `total_reads`; `total_reads=None` means "not
  determined" and preserves the old behaviour. Never treat unknown depth as
  zero — that turns every caller that cannot compute it into a false
  INSUFFICIENT READS. A detection always wins over shallow depth.
- The report template (`core/export/templates/report.html`) has the matching
  `{% elif not data.watched_results %}` branch, and since 2026-08-08 the
  sibling depth branch as well. Only NOT_SCREENED had been ported; a one-read
  run with 35 organisms loaded still rendered the green "NO WATCHED ORGANISMS
  DETECTED", in the artifact that leaves the building. `_collect_data` supplies
  `total_reads` and `low_read_floor` for it.

The same distinction has since been carried to two more surfaces, because a
guard on one screen is not a guard on the tool:

- **The Organisms panel** qualifies its "Not Detected (N)" list below the
  floor (`not_detected_caveat` in `main_tab_helpers.py`). The caveat renders
  ABOVE the collapsed list — inside it, it would be invisible in the default
  view being misread. Nothing is hidden; the list still renders in full.
- **An alarm states its own depth** (`_shallow_depth_clause`). A detection
  always outranks depth and every depth from one read up still returns
  ACTION_REQUIRED — but a real negative control carrying 6 reads out of 11
  read identically to the same run's 34,096-read detection until the banner
  started saying "on only 11 reads total".

All three anchor `low_read_floor` to `min_reads_for_validation`, so the
dashboard, the Organisms panel and the exported report cannot drift apart on
what counts as too shallow.

The banner is **aggregate-scoped on purpose** — it loads `"All Samples"` and
takes no `selected-sample` input. Do not make it follow the selection: that
would hide a detection in a sample the operator is not currently viewing. A
single sample that produced nothing is flagged in the selector instead, by
comparing `available-samples` against `sample-file-mapping` (see below).

**`_manifest.json` predicts output files; it does not verify them.**
`bin/write_manifest.py` derives `<sample>.classification.json` and
`<sample>.qc_stats.json` from the sample list and active tools, because
MANIFEST_WRITER runs in its own work directory and cannot see the publishDir.
Since the 2026-08-16 audit, `failed_samples` is derived from QC output
INTERSECTED with classification reports (when classification ran), so a
sample whose QC or whole-sample Kraken2 failed under
`conf/error_isolation.config` IS named as failed. What the manifest still
cannot see is a PARTIAL failure — batches 1–5 classify, batch 6 dies — and
`sample_detector._samples_from_manifest` returns the sample list verbatim.
The GUI compensates: the sample selector marks samples present in
`available-samples` but absent from `sample-file-mapping`, which is built
from files on disk. Marked rather than hidden — hiding loses the fact that
the barcode was attempted. The exported report carries the same
attempted-but-no-output marking.

**Verdict-banner decision logic is a pure function.** The safety-critical
clinical verdict (ACTION REQUIRED / MONITORING / ALL CLEAR / INSUFFICIENT READS
/ NOT SCREENED / SCREENING / STANDBY) is decided by `select_verdict()` in
`app/tabs/dashboard_helpers.py`, which returns a `VerdictDescriptor` from the
input booleans and the watchlist hit list — no file I/O, no component build.
The `update_verdict_banner` callback only gathers inputs (Kraken load,
`_check_pathogens_with_mapping`), delegates the state choice, runs per-sample
attribution when `descriptor.needs_attribution` is set (ACTION REQUIRED only),
and renders via `_make_banner_content` / `_verdict_banner_style`. The precedence
is fixed: no-config → starting → data-driven → running-no-data → standby; note
a missing results dir yields STANDBY even while the pipeline runs. Every branch
is unit-tested in `tests/test_verdict_selector.py`; keep new states in the pure
function so they stay testable without a running app. This mirrors the broader
`*_tab.py` → `*_helpers.py` split (pure logic in helpers, thin callback wiring
in the tab module) used across the dashboard, main, qc, and validation tabs.

**Per-sample attribution has one resolver: `core/utils/attribution.py`.** A
watchlist detection carries two taxids — `taxid` (the NCBI taxid on the
watchlist entry) and `detected_taxid` (the Kraken2 report taxid it matched) —
while `_load_per_sample_organisms` keys its dict by the *report* taxid. On an
NCBI database the two coincide, so looking a detection up by the wrong one
fails only on GTDB/custom databases, and it fails silently: a detection with no
resolved samples renders identically to one that legitimately spans none.
Never index `taxid_to_samples` directly; call `samples_for_detection(detection,
taxid_to_samples)` (tries `detected_taxid`, then `taxid`). Both watchlist match
paths emit `detected_taxid` — `check_organisms_with_mapping` always did,
`check_organisms` since the 2026-07-25 pass. `build_pathogen_attribution` pairs
each detection with its own samples and applies the entry's `alert_threshold`
per sample: the verdict is decided on the aggregate, so without that gate ten
barcodes at 50 reads each are all named for a pathogen with a threshold of 100.
Samples that clear only the discovery floor render as "aggregate across N
samples". When attribution is attempted and resolves nothing, the verdict
banner says so explicitly (`attribution_failed`) rather than omitting the line.
**Attribution counts `cumul_reads`, not the per-rank `reads` column.** Both
`_species_df_to_organisms` and the `PER_SAMPLE_DISCOVERY_FLOOR` filter above it
use it, and they must use the SAME column — gating on one and displaying the
other let a sample sit on both sides of the threshold. Measured on a real
Bioshield run: `barcode11` reads=29,721 / cumul=34,096 (the difference sitting
at *F. tularensis holarctica*), so the dashboard attributed 29,721 to a
detection the Organisms tab reported as 34,096; and `barcode16` reads=4 /
cumul=6, which put the run's negative control below a floor of 5 so its
contamination appeared nowhere at all. Both sites fall back to `reads` when the
column is absent. Regression-covered in `tests/test_attribution_read_column.py`.

**Real-time attribution fails in ways batch mode does not** (audit
2026-09-01, `docs/audit/realtime-attribution-2026-09-01.md`). Three guards,
all pinned in `tests/test_realtime_attribution.py`:

- **A sub-threshold sample is named, not just counted.** The verdict is
  decided on the aggregate, which crosses a watchlist entry's
  `alert_threshold` before any single barcode does; a batch run's barcodes
  are complete when the verdict appears, a realtime run's aggregate leads
  every barcode for most of the run. `_attribution_phrase` names the top
  samples alongside the aggregate qualifier rather than rendering a bare
  count. Measured at threshold 500: the completed batch run named
  barcode06/07/05 for *F. tularensis*, the realtime run named none.
  The threshold gate itself must NOT be removed -- ten barcodes at 50 reads
  each are not each positive for a pathogen with a threshold of 100.
- **A detection resolving no samples gets a second look without the
  discovery floor.** `PER_SAMPLE_DISCOVERY_FLOOR` (5) is correct for the
  general build and wrong for a taxon the aggregate already called above
  threshold, because the aggregate reaches that threshold by summing exactly
  the sub-floor counts the filter discards. On a real run *B. anthracis* sat
  at 4/3/3 reads across three barcodes: ACTION REQUIRED for a select agent,
  attributed to nobody, while the exported report (which applies no floor)
  named all three correctly. `augment_attribution_for_unresolved` is the
  single entry point and is used by the verdict banner, the alert panel AND
  the modal breakdown -- fixing one surface alone produced a banner naming
  barcodes above a card showing none. It returns the input unchanged when
  nothing needs filling in, and a COPY otherwise: the input is the shared
  per-tick memo. **Never pair built attributions against the detection list
  by position** to find what failed to resolve: `build_pathogen_attribution`
  deduplicates by label and re-sorts by read count, so the Nth attribution is
  not the Nth detection. Ask per detection with `samples_for_detection`.
- **An unread sample is not a clean sample.** `_load_per_sample_organisms`
  separates "no report on disk yet" and "report mid-rewrite" from "measured
  and carries nothing"; realtime lists a sample as soon as its directory
  appears and rewrites its cumulative report every batch, so both windows
  recur all run. `unmeasured_samples` exposes the gap and the banner names
  it. It reports a PARTIAL gap only -- when nothing is readable the
  verdict's own no-data states already say so.

A multi-sample moderate-tier alert card names its highest-count sample plus a
"+N more" pill (`_render_sample_attribution`). Chips per barcode stay
suppressed for the component budget, but a bare count pill told the operator a
detection spanned barcodes without saying which.

`tests/fixtures/realtime_attribution/` is the only fixture in the suite shaped
like a realtime results tree (progressive cumulative report, per-batch reports,
incremental-layout markers); every other attribution test writes a flat
`<sample>.kraken2.report.txt` and therefore cannot see any of the above. Use
`scripts/audit_realtime_attribution.py <results_dir> --config <config.yaml>` to
diagnose a live or captured outdir hop by hop.

**How a real-time run ends is part of the verdict** (round-4 audit,
`docs/audit/realtime-round4-2026-09-02.md`; do not regress). The audit drove
three real-time runs, three Stop drills, two Continue drills and a hard kill
with nanorunner and found the end of a run to be the least truthful moment:

- **A stopped run is recorded and rendered as stopped.** `stop()` and the
  inactivity backstop call `_mark_stop_intent` BEFORE signalling Nextflow
  (the monitor thread polls every 5 s and would otherwise classify the dying
  process as completed or errored), then `_finish_stopped_locked`, which
  writes `final_status: stopped`, `stop_reason`, `ended_at`,
  `files_processed` and `input_files_at_end` into `.nanometa.run.json`.
  `get_status()` exposes `stopped_run`; the header says "Stopped (reason)",
  the banner badge STOPPED, and `with_failure_clauses` appends "run stopped
  ... counts are partial". `pipeline_status == "stopped"` alone means idle
  as well, so a real stop is the one with a `stop_reason`.
- **The report reads the run state.** `read_final_run_status` returns
  `run_state` (completed / stopped / error / active / unknown); `active`
  means the metadata was written at Start, no terminal status exists and
  `.nanometa.lock` is present, i.e. an export taken mid-run. The template's
  `run_clause` qualifies every decision banner; it is set ABOVE the
  `<!-- DECISION BANNER -->` comment because `test_report_read_depth_gate`
  slices the template from that comment to the banner's first matching
  `endif`.
- **The real-time timeout is a wall-clock timer, and the text says so.**
  nanometanf schedules one timer at `realtime_timeout_minutes` plus the
  grace period from the start of monitoring; files that land afterwards are
  never classified and the run is reported complete. The form text
  describes exactly that, the auto-stop chip counts to timeout plus grace,
  and `_unprocessed_input_note` states the inbox-minus-processed gap for a
  finished real-time run (header and report). The GUI backstop remains a
  genuine inactivity timer on task progress and is a separate mechanism.
- **Failed-and-ignored tasks are named.** `processes_failed` reaches the
  header ("N tasks failed (skipped)") and the verdict subtitle; the reads of
  an isolated failure are absent from every count and nanometanf's own
  `aggregation_stats.json` cannot see a QC-stage failure because batch ids
  are assigned after QC.
- **Every launch path resolves the outdir the same way.** The collision
  handler (Continue / Archive) used the app-config State as is; a tab whose
  Store never carried `results_output_directory` launched into a fresh
  `~/.nanometa/data/analysis_<ts>` while the modal promised the described
  folder. It now resolves via `resolve_run_outdir` and pins the directory
  the modal showed. Root cause still open: `app.layout` is static, so a new
  tab hydrates app-config from the boot-time config, not the session's.
- **Continue into a populated outdir shows the continued run.**
  `get_available_samples` unions the manifest with disk discovery (the
  manifest is written once, at session end, and describes the previous
  run); `load_kraken_data` takes the canonical JSON for a named sample only
  when `_canonical_is_current` (no older than the sample's reports); the
  no-data mapping globs `kraken2/<sample>/batch_reports/` too. nanometanf's
  `-resume` cannot cache-hit in real time (every file's meta carries a
  wall-clock stamp), the cumulative writer restarts from zero and the
  batch tree doubles: the modal's "skip already-completed steps" wording is
  not true for a real-time run and is still to be fixed.
- **A watchlist the config names must exist.** `unresolved_watchlist_ids`
  (`watchlist_manager.py`) is the single question the CRITICAL readiness
  check "Watchlist Files" and the startup toast both ask. `bioshield_agents`
  is not a package built-in: a config copied under a new filename gets a new
  project dir with an empty watchlist folder and used to load zero entries
  silently.
- **RESULTS UNAVAILABLE needs `dir_seen`.** The fingerprint string hashes
  the path and is never empty; the Store carries a sticky `dir_seen` and
  `_fingerprint_marks_dir_seen` decides. A never-created results directory
  is STANDBY.
- **A served last-good frame is transient; so is a tier fallback.**
  `_parse_kraken2_report` marks realpaths it served from `_last_good_frame`
  in `_fallback_served_paths`; the per-sample branch, the aggregate plain
  loop and `report_accumulation.aggregate_with_sample_cache` (via
  `is_transient`) refuse to cache a result built on one. Report discovery
  keeps the previous tier for one poll when a cumulative report is inside
  its first stability window with no last-good behind it
  (`_cumulative_readable_now`, `_tier_fallback_paths`,
  `_has_pending_cumulative`). The stability window closes by time passing,
  which changes no mtime and therefore no cache key: caching a stand-in
  under the new fingerprint served it until the next rewrite (five polls
  on the replay) and the parse path that clears the staleness registry was
  never reached again (the "1 sample serving stale data" that sat on a
  COMPLETE banner). Reproduce with `scripts/audit_replay_snapshots.py`;
  tests must advance the loaders' clock, never touch the mtime.
- **On-demand validation waits for the run to end.** It shares the live
  run's launch dir, work dir and outdir and adds a bare `-resume`; the
  modal explains instead of arming a launch while `backend-status.running`.

Measurement traps from the same audit: a Chrome MCP tab covered by another
window is `document.hidden` and stops polling entirely (use the Playwright
MCP browser for operator-view readings); the demo launcher's `conda run`
swallows the app's stdout and stderr; `conda run` does not forward heredoc
stdin; `unmeasured_samples()` is a cached lookup that only the attribution
build refreshes.

**Negative controls.** `is_negative_control` reads the config's
`negative_control_samples` list first, then falls back to name patterns:
`NTC` / `neg_ctrl` / `blank`, fused numeric suffixes (`NTC1`, `blank2`,
`neg1`), and "negative" beside a *sample identifier*
(`negative_barcode16`, `neg_01`). The identifier rule is what distinguishes a
control from `negative_strand_test`, where "negative" describes a molecule
rather than naming a sample. Note the fallback cannot help under `by_barcode`
input, where the sample is `barcode16` and the prefix never leaves the FASTQ
filename — declaring it is the only route, which is why there is now a
multi-select for it in the Configuration tab (Essential Settings). Its options
are the detected samples UNIONED with the saved values: a `dcc.Dropdown` drops
any value with no matching option, so without the union a control declared
before the run produced data would be erased silently.

A control that carries a detection is **reported, never acted on**.
`build_pathogen_attribution` fills `negative_control_samples` /
`_reads` / `_fraction`, and the banner appends "— also in negative control
barcode16 (6 reads, 0.02% of positives)". Two limits, both test-pinned: it
states the observation and never the cause (crosstalk, carryover and a
genuinely contaminated control are indistinguishable from here), and it never
weakens the detection — controls are excluded from the triggering-sample list
but a detection carried only by a control still resolves, as "(negative
control only)". Regression-covered in `tests/test_attribution.py`,
`tests/test_negative_control_naming.py`,
`tests/test_negative_control_reporting.py`,
`tests/test_negative_controls_form_field.py` and
`tests/test_verdict_banner_callback.py`.

**Pathogen Report modal references are built dynamically.** The report's
external links come from `build_reference_links()` in `dashboard_helpers.py`,
which never emits a link to a wrong or nonexistent record: NCBI Taxonomy only
for a real NCBI taxid (`_is_real_ncbi_taxid`) or a resolved `ncbi_link`; GTDB
only when a resolved `gtdb_link` exists (never reconstructed from a name);
Federal Select Agent Program (`SELECT_AGENTS_URL`,
`https://www.selectagents.gov/sat/list.htm`) always. The old CDC
`niosh/topics/emres/chemagent.html` link was dead (404) and topically wrong
(chemical agents) — do not reintroduce a CDC bioterrorism-category URL; CDC
retired that tree in 2024. Confidence in the report is `compute_detection_confidence`
(read-support bands, not a statistical CI), and `build_detection_meta` labels
the watchlist `validated` flag as "Taxonomy ID" validation so it is not
confused with the confirmatory BLAST/minimap2 results on the Validation tab.

**Export Results report generator** (`core/export/report_generator.py`). The
report's decision banner and Watched Organisms table are driven entirely by
`watched_results`, so `_screen_watchlist` must iterate
`get_active_entries()` — a `Dict[int, WatchlistEntry]`, NOT a list of dicts —
via `.values()` with attribute access, matching by `db_taxid` → NCBI `taxid` →
name. Iterating it wrong silently empties the threat screen (a false negative
in the archived artifact); regression-covered in `tests/test_report_generator.py`.
Classification counts delegate to `get_classification_stats`; organism abundance
uses species (`S`) rank only with Kraken2's `%` column (never `reads.sum()` —
double-counts genus and over-states). Subspecies get their OWN table rather than joining the organism ranking:
`_extract_organisms(df, ranks=...)` is called twice per sample, once for `S`
and once for `S1/S2/S3`. Mixing them would rank a species against its own
children — *F. tularensis* at 99.87% beside *F. t. holarctica* at 30.9% —
which invites the reader to add rows that already contain each other. The
section is omitted entirely when the database resolves nothing below species.
Raw files copied are `_RAW_SUBDIRS`
(kraken2/fastp/seqkit/taxpasta/validation/on_demand_validation/pipeline_info),
AppleDouble-filtered, skipped above `export_max_raw_bytes` (default 5 GiB).
Plotly is inlined for offline self-containment; `offline_mode` suppresses the
CDN fallback so an offline report never emits a dead `<script src>`. The export
runs as a `background=True` worker with staged `set_progress` (since round 2,
2026-08-24; it previously ran synchronously because a worker's
`WatchlistManager` singleton is empty). That objection no longer holds:
`_screen_watchlist` self-hydrates its empty local singleton via
`wm.load_config(self.config)` — the second sanctioned worker pattern in
`tests/test_background_callback_contract.py`. The export modal STAYS OPEN
during the run showing the progress bar, and the terminal status renders
inside it plus a page toast; never mutate the LIVE singleton from the worker.

### macOS bind-mount gotcha

macOS writes AppleDouble (`._*`) sidecar files when writing to non-HFS+ filesystems,
including Docker bind-mounts. These break Nextflow when `NXF_HOME` lands on such a volume
(e.g. `Operation not permitted` on `._.gitattributes`). Fix: set `NXF_HOME` to a
Linux-native path (Docker volume or `/root/.nextflow`); short-term workaround is
`COPYFILE_DISABLE=1` and removing existing `._*` files.

## Testing

**CI runs on `dev`, and did not until 2026-07-29.** The nanometanf nf-test
workflow fired only on pushes to `master` and on pull requests, while all
development happens on `dev`, so no job had run for weeks. The first run after
enabling it failed 20 of 155 tests. Three defects that shipped in that window
were exactly what the suite exists to catch. A suite that does not run is not a
safety net.

**Test fixtures must be tracked, and a guard asserts it.** `.gitignore` carried
a blanket `test_*`, which matches at any depth and silently excluded thirteen
fixtures under `tests/fixtures/validation/`,
`modules/local/validation_cumulative_aggregator/tests/fixtures/` and
`tests/realtime_test_data/`. Every affected test passed locally, where the files
exist, and failed on a fresh clone — which is what CI is. This pattern had
already bitten twice before (`testing*` hid `docs/development/TESTING.md`; two
per-directory whitelists had been added by someone who hit it earlier).
`tests/lib/fixtures_are_tracked.py` now runs in CI before the suite and fails if
any `$projectDir` path an nf-test references is untracked. It also **refuses to
pass when it finds nothing to check** — its first version matched the runner's
`/home/runner/work/...` checkout with an absolute-path skip, reported
"0 fixture paths", and exited 0.

**A test for a guard must state its own precondition.** `conf/test.config` sets
`save_output_fastqs` and `save_reads_assignment` to true, so a test asserting
that validation *refuses* without them could never fire the guard under
`--profile test` — which is what CI runs. It asserted a failure that could not
happen. Set the triggering state explicitly rather than inheriting a default a
profile may override. For the same reason, verify new nf-tests under
`--profile test,conda` locally, not `conda` alone.


```bash
pytest                                              # full suite, parallel (pytest-xdist)
pytest -n 0                                         # serial, for pdb/print debugging
pytest --cov=nanometa_live --cov-report=term-missing   # with the coverage gate
```

The `nanometa` conda env has Dash but neither `pytest-xdist` nor `pytest-cov`,
so run the plain suite there with `-o addopts=""` and the coverage gate from
the `nf-core` env, which has both.

4284 tests as of 2026-08-25 (~128 skipped by default; measured coverage ~76%).
`pytest.ini` enforces a
`fail_under = 74` floor on coverage runs only (the default `pytest` dev loop
does not load coverage); the floor ratchets up as coverage rises — keep it ~1
point below the measured total, never lower it. Also
`filterwarnings = error::DeprecationWarning:nanometa_live` (our own deprecations
fail the build), and the `unit` / `callback` / `integration` markers. CI runs the
suite and the gate on Python 3.11 and 3.12 for every push and PR to `main` /
`dev` (`.github/workflows/tests.yml`). Tests marked `slow` need Nextflow/conda
and are skipped by default.

Synthetic datasets are auto-generated under `/tmp/nanometa_test_datasets/` by
`conftest.py` via `scripts/generate_test_datasets.py`. Mock Kraken2/FASTP
generators live in `core/testing/mock_data_generator.py`;
`generate_test_dataset(dir, scenario=MockDataScenario.PATHOGEN_DETECTED,
num_samples=N)` writes a realistic results tree (`kraken2/`, `fastp/`, `qc/`,
`multiqc/`) that drives populated-data callback/loader tests — back-date the
files (`os.utime` to ~30s ago) so the loaders' file-stability checks pass.

**Callback tests.** Dash callbacks are tested by registering on a throwaway
`Dash` app and extracting the unwrapped function with
`tests/dash_test_utils.get_callback_fn(app, output_id, input_contains=...)`
(walks `app.callback_map`, unwraps `spec["callback"].__wrapped__`); pass
`input_contains` to disambiguate when several callbacks share an output (e.g. the
many `toast-message`/`tabs.active_tab` writers). Invoke the extracted function
directly with realistic store values and assert the returned component structure
+ content, not just `is not None`. **`ctx` gotcha:** `dash_test_utils.ctx_with`
patches `dash.ctx`, which only reaches callbacks that reference `dash.ctx` at call
time; modules that did `from dash import ctx` (main_tab, qc_tab, classification_tab,
dashboard_tab) bind a module-local name, so patch `<module>.ctx` instead. Pure
helpers and module-level guards inside `register_*` are closures — re-register the
app (function-scoped fixture) to reset a once-per-session guard. Background
(`background=True`) callbacks and subprocess managers (`nextflow_manager`,
`on_demand_validator`) are intentionally light on unit coverage — testing them
needs DiskcacheManager/`set_progress`/subprocess harnessing that yields brittle
wiring-only tests; prefer covering the pure helpers they delegate to.

Real test data:
```
/Users/andreassjodin/Desktop/ONT/demodata_ONT/data/nanometa_testdata/
├── multiple_fastq/    # Barcoded
└── single_fastq/      # Flat
Kraken2 DB: /Users/andreassjodin/Desktop/ONT/demodata_ONT/database/kraken2.gtdb_bac120_4Gb
```

## Documentation

| Document | Content |
|----------|---------|
| `docs/quickstart-with-nanorunner.md` | End-to-end demo using simulated input |
| `docs/user-guide.md` | Operator usage |
| `docs/OPERATOR_GUIDE.md` | Field deployment |
| `docs/configuration.md` | All config options |
| `docs/developer-guide.md` | Architecture details |
| `docs/api-reference.md` | Parser and loader APIs |
| `docs/MIGRATION_GUIDE_V2.md` | v1 to v2 migration |
| `docs/archive/` | Audits, plans, migration notes (not maintained) |

## Links

- [nanometanf Pipeline](https://github.com/FOI-Bioinformatics/nanometanf)
- [Dash Documentation](https://dash.plotly.com/)
- [Original Nanometa Live](https://github.com/FOI-Bioinformatics/nanometa_live) — legacy reference
