# Changelog

All notable changes to Nanometa Live are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Round three of the hardening audits (2026-08-24/25): the data-volume axis
(large reports, hundreds of realtime batches, thousands of validation
pairs), memory and endurance on a field laptop, and truthfulness under
failure. Verified live: a 2h11m GUI-driven realtime run against the real
Bioshield database with the 129-entry watchlist, followed by failure
drills (kill -9, vanished results volume, corrupt reports, port
conflicts, double-clicks).

### Fixed
- The sample selector's "produced no output files" marker fired on healthy realtime samples: the file mapping recognised neither the cumulative Kraken2 report (written first in realtime mode) nor seqkit QC output, so a sample whose data was rendering in the Organisms tab was simultaneously labelled dataless. Both now count, and sample discovery also sees the realtime seqkit batch_stats layout. (Companion nanometanf fix: the unclassified/ bin is one sample, not one sample per chunk file.)
- **The verdict banner never lies about run health.** New PIPELINE ERROR
  and RESULTS UNAVAILABLE states (both amber/red, never green or grey):
  a pipeline killed mid-run rendered a green ALL CLEAR before, and an
  unplugged results volume rendered STANDBY. A detection still outranks
  the error, with "pipeline error - coverage is partial" appended.
  Samples served from the last-good fallback are counted in the
  subtitle ("N samples serving stale data") via a staleness registry
  the loader feeds; the exported report carries the same PIPELINE ERROR
  branch, reading the terminal status the backend now records into
  .nanometa.run.json. A fingerprint that saturates its stat cap
  degrades to TTL refresh instead of freezing forever; mid-write
  blast.tsv reads are gated; a corrupt toggle-state file warns and
  toasts instead of silently re-enabling everything.
- **Poll cost is O(changed data), not O(total data).** Measured on the
  extended perf harness: an incremental tick at 24 barcodes x 100
  batches dropped from 19.6 s / 2,414 file reads to 1.5 s / 119; a
  quiet tick at the 96-barcode envelope with 12,384 validation pairs is
  1.4 s with zero re-reads. Per-batch seqkit frames, the latest-batch
  path, per-sample aggregate accumulation (byte-identical, pinned by
  frame-equality tests), the validation parser and the main-tab
  validation loader are all cached on the standard mtime idiom; the
  batch drill-down selector is dir-mtime gated and capped with an
  explicit "latest N of M" row.
- **Memory plateaus on an overnight run.** The parsed-frame caches are
  byte-budgeted (default 2 GB; the envelope measured 3.8 GB resident
  before) with eager eviction of superseded report versions; each load
  stores one shared frame instead of three copies; the organisms memo
  keeps two epochs instead of four; the PAF-breadth, read-length and
  DB-taxonomy caches are bounded (all previously unbounded); old log
  rotation families are pruned at launch. A cache-inventory test fails
  on any module-level cache not wired into both reset paths.
- **No background worker spawns per tick.** Three background callbacks
  (readiness, Organisms rebuild, QC summary) had per-tick Inputs, so
  DiskcacheManager spawned OS processes every tick just to evaluate
  their guards -- measured live as a 28-34 fds/min pipe leak (4,500+
  after two hours). All three now run behind synchronous main-process
  gates; the periodic readiness probes run in a daemon thread with no
  spawn at all. A structural test fails any background callback that
  acquires a per-tick Input. Post-fix rate: ~2 fds/min under load.
- Operational resilience: a browser refresh mid-run restores the
  dashboard within one tick (the applied config is re-seeded from the
  live backend); Export/bundle/rescan workers are cancellable and a
  watchdog re-enables a modal whose worker died; Start is gated on a
  5 GB disk floor (override: NANOMETA_ALLOW_LOW_DISK=1); double-clicked
  Archive can no longer split results across two archive folders;
  port-in-use prints an actionable message; the realtime inactivity
  timeout uses the monotonic clock so a laptop lid-close cannot kill a
  healthy run on wake.

### Added
- Perf harness: taxa/batches/validation-pairs sweep axes, a validation
  fixture builder verified against the real parser, tracemalloc and
  cache-byte columns with a memory gate, and committed exercise-profile
  baseline cells at the 24- and 96-barcode envelopes.

## [0.12.0] - 2026-08-24

Round two of the large-scale hardening (2026-08-24): many barcodes (24-96)
and large watchlists together, with two acceptance criteria — the interface
never freezes, and the operator always sees progress. Measured on a
synthetic 96-barcode tree: the three per-tick attribution passes went from
283 ms to ~0 ms, a quiet 96-sample poll holds at 176 ms with no cache
cliff, and the per-tick browser upload drops roughly 35x.

### Fixed
- **Watchlist rows now address entries by the manager's storage key.** A
  fork entry (two Kraken2 database nodes sharing one NCBI taxid, such as
  the two *Burkholderia mallei* nodes) is stored under its `db_taxid`,
  while the UI addressed entries by the shared NCBI taxid: Disable All
  left 4 of 129 Bioshield entries active, Verify-all validated one of
  each pair twice and the other never, the fork rows carried duplicate
  component ids, and the accordion preview showed and toggled the
  sibling's state. Entry dicts now carry the storage key
  (`manager_key`), row component ids and bulk operations use it, and
  the NCBI taxid remains for display, reference links and genome
  lookups.
- **Per-tick server work no longer scales with barcode count several times
  over.** Loader cache capacity now scales with the detected sample count
  (a fixed cap of 100 evicted two thirds of ~300 live keys at 96 barcodes
  every cleanup); per-sample attribution is built once per tick and shared
  by the verdict banner, alert panel and dashboard alerts (was up to three
  full passes, the panel's unconditional); the validation parser is shared
  per results dir so its cache survives ticks; nanoplot gets the mtime
  cache every other loader had; freshness, file-mapping, processed-count
  and on-demand scans are single-scan or fingerprint-gated; a watchlist
  toggle no longer re-walks the results tree (the fingerprint keys on a
  derived results-dir Store instead of the whole config).
- **Every click path is de-frozen with visible progress.** Export Results
  runs in the background with a staged progress bar in the still-open
  modal (it ran minutes on the request thread and wrote its status into a
  closed modal); Start/Stop run in main-process threads with instant
  optimistic feedback and a terminal toast (failures included); Enable/
  Disable All persists once instead of once per entry (500 fsyncs);
  watchlist discovery finally consults its cache (three full YAML-corpus
  parses per toggle become cache hits); taxonomy lookup, QC plot export
  and the native path pickers are backgrounded with spinners; config path
  fields validate on blur, not per keystroke.
- **Wire payloads are slim.** The app-config Store carries a six-field
  watchlist form (~125 B/entry; the full form — 96-99% of the store — was
  re-uploaded by 24 per-tick callbacks, 4.4-16.9 MB per tick). Disk
  session files keep the full form. The taxmap store ships the 5 fields
  its consumers read; alert-card attribution popovers build their rows on
  open; overflow organism cards ship as data and render on the Show-more
  click.
- **Hidden tabs stop rebuilding.** The Sankey/Sunburst figure, QC figures,
  per-sample QC table and QC cards skip while their tab is hidden and
  render fresh on activation. The detection chain (status cache, verdict
  banner, alerts, alert panel, readiness, fingerprint) is never gated on
  the visible tab, enforced by a permanent introspection test.
- Progress gaps in existing background operations closed: database rescan
  reports its stages (the bar sat at 0%), Check Everything shows a spinner
  (was 15-20 s of dead air), BLAST database builds report per-item
  progress (was a silent plateau at 90%), single genome downloads show a
  note while running.

### Added
- Contract fence: every background callback must declare `running=` or
  `progress=`; per-tick call-count pins at 96 barcodes; payload budget
  tests; the perf benchmark axis extended to 48/96 barcodes with a
  regenerated baseline.

## [0.11.1] - 2026-08-21

A large-watchlist audit (2026-08-21): the 129-organism Bioshield watchlist
froze Chrome during import and made the dashboard sluggish afterwards. Three
independent causes were measured and fixed; watchlists up to 500 entries are
now covered by regression tests.

### Fixed
- **Per-poll matching cost no longer scales with watchlist size times report
  size.** The name-matching loop evaluated every (report row x entry) pair
  (~1.5 s per pass at 129 entries x 2000 rows), the verdict banner ran it
  twice per tick, the alert panel a third time, and nothing cached the
  result. A precomputed entry index (`TaxonomyMatcher.build_entry_index`),
  a single-pass above/below-threshold split, a content-keyed memo, and a
  cached builtin+custom pathogen merge take the same work to ~12 ms per
  tick. Behavior-identical, pinned by characterization tests against the
  previous loop semantics.
- **The browser no longer mounts the whole watchlist.** ~13,000 components
  (1.9 MB of component JSON) were live in the DOM at 129 entries: every
  watchlist's pathogen rows pre-rendered inside collapsed accordions, the
  full table, 129 tooltip instances, 129 missing-genome items rebuilt on
  every tab switch. Accordion rows now render on expand and unmount on
  collapse, the pathogens table paginates at 25 rows, organism-card
  tooltips are native `title` attributes, not-detected watched cards render
  on first open, detected cards share the existing show-more cap, and
  genome stats skip recomputing when the switch went to another tab.
- **Importing a watchlist shows progress instead of a frozen screen.** The
  upload ran synchronously on the request thread and parsed the YAML five
  to six times. It now runs in a background worker with the per-entry
  progress modal, parses at most twice (pinned by test), and no longer
  round-trips the decoded file through the browser on a filename collision.
- **Expanding a watchlist's pathogen list no longer collapses itself.** The
  lazily added checkboxes re-fired the nested-toggle callback, which
  treated the fire as an edit and re-rendered the file list over the
  expanded content. No-op and unresolvable-taxid fires are now ignored.

### Added
- Regression guards: component-budget tests for every large rendering
  surface, an O(rows + entries) matching-cost pin at the 500-entry /
  5000-row design target, a parse-count budget for imports, and memo
  isolation tests.

## [0.11.0] - 2026-08-20

A subspecies resolution exercise: seven barcodes of simulated nanopore reads
with known composition, run end to end against an in-house flextaxd database
that resolves *Francisella tularensis* into its four subspecies. Resolution
itself works -- Kraken2 named the correct subspecies in all four pure barcodes,
leading its nearest wrong sibling by 33-78x, and a 70/30 mixture of two
subspecies resolved into both components in the right order.

The path between a subspecies watchlist entry and its reference genome did
not. Before this release one of five entries obtained a usable genome; now all
five do, each carrying the right organism. Those fixes, and a change to where
the project directory lives, are what follow. No pipeline changes; nanometanf
stays at v1.7.0.

Minor rather than patch because the default project directory moves -- see
**Changed** first if you have an existing installation.

### Changed
- **The project directory no longer defaults to the working directory.** It
  was `os.getcwd()`, so launching from a clone wrote run results, taxid
  mappings, watchlist toggle state and operator watchlists *into the checkout*.
  Those paths are gitignored, so nothing was ever committed -- but `git clean
  -x` deletes them, `git add -f` commits them, and a project-local watchlist
  directory inside a repository is how several copies of one watchlist came to
  exist with no way to tell which was live. The default is now
  `~/nanometa-projects/<name>`, named from the analysis name, else the config
  file stem, else `default`.

  Existing installations that relied on the old behaviour will find a fresh,
  empty project on first launch. Pass `--project <dir>` (or set the project-dir
  environment variable) to keep using the previous location; both still take
  precedence over the default.
- Watchlist entries are keyed by database node rather than NCBI taxid. Four
  subspecies of one species share an NCBI parent taxid, so the previous key
  silently merged them and the last one loaded won. On the shipped Bioshield
  agent list this was the difference between 129 entries and 125: *B. mallei*
  collided with its own subsp. *mallei*, *B. melitensis* with subsp.
  *melitensis*, and three *E. coli* database nodes with each other.

### Fixed
- Reference genomes resolve for database-keyed entries, completing the
  fetch/cache split begun in 0.10.3. Three defects, all on the same path:
  - The batch download assigned `entry["taxid"]` the *cache* taxid and only
    then derived the fetch taxid from that same dict, so the flextaxd graft id
    went to NCBI -- exactly what `genome_fetch_taxid` documents it never does.
    A graft id sits below the pseudo-taxid band and so passes the "real NCBI
    taxid" check; only call order separates the two. Species entries were
    unaffected because the bacterial route tries a name-based GTDB lookup
    first, and GTDB has no rank below species -- which is why only subspecies
    exposed it.
  - Two "no reference genome" fallbacks wrote the FASTA under the NCBI taxid
    instead of the cache key, making the genome invisible to
    `has_genome(db_taxid)`: reported missing, and re-downloaded on every
    attempt.
  - An NCBI taxon query matches the whole subtree, so asking for the reference
    genome of *F. tularensis* (taxon 263) returned a *novicida* strain, the
    most sequence-divergent member of the group. Downloads and accession
    resolution now try `--tax-exact-match` first; the subtree remains a
    fallback, logged with the organism actually obtained rather than accepted
    in silence.
- Project watchlists are searched for in the project directory. The loader's
  contract names `<project_dir>/watchlists/` as the highest-priority source,
  but the manager was passing it the results directory, so two notions of
  "project" inside one class disagreed. Harmless while the two overlapped;
  with the project directory moved (above) they no longer do, and a watchlist
  placed where the documentation says it goes was never found. The results
  directory stays in the search path, because operator uploads saved to
  "project" have been landing there; the project directory wins on a filename
  collision.

### Added
- The Watchlist tab shows which file each watchlist was loaded from, as a
  truncated path with the full path on hover. A watchlist is keyed by file
  stem and can arrive built-in, from the project, or from an operator upload;
  when several copies of one stem exist there was previously no way to tell
  which was live.
- An example subspecies watchlist,
  `core/config/data/watchlists/examples/subspecies_francisella.yaml`: the
  *F. tularensis* species node plus its four subspecies, each carrying both
  `db_taxid` and `taxid_ncbi`. It is the worked example of why an entry below
  species needs both -- GTDB has no node below species, so an entry without
  `taxid_ncbi` has no route to a reference genome at all.
- `scripts/subspecies_exercise/`: the read generator, an evaluation script that
  judges pure, mixture, sister-species and negative-control barcodes by
  criteria appropriate to each, and the ground truth, so the exercise can be
  repeated against another database.
- Documentation: `docs/subspecies-resolution-test-plan.md` and
  `docs/audit/subspecies-2026-08-20.md`, the latter carrying the measured
  numbers and three findings deliberately left open -- a sister species
  raising a subspecies alert at the configured threshold, an absolute read
  threshold being the wrong instrument below species, and `confirmed` on the
  Validation tab not surviving the move below species.

### Known limitations
- **A subspecies `alert_threshold` cannot be set from species-level
  intuition.** Cross-assignment between the subspecies of one species runs at
  roughly 1-3% of clade reads, and that floor is a *fraction* of depth while an
  absolute threshold is not. At 10,000 reads per barcode it is 40-130 reads,
  above a threshold of 25. A related species can clear it too: *F.
  philomiragia*, containing no *F. tularensis*, put 45 reads on subsp.
  *novicida*.
- **`confirmed` on the Validation tab does not discriminate below species.**
  In a barcode containing only subsp. *holarctica*, all four subspecies return
  `confirmed`, which the current 10-read / 5%-breadth contract permits by
  design -- those floors separate a real organism from index-hop carryover,
  not two genomes that are 99.9% identical. The discriminating signal is
  present in the output (genome breadth separates 6-10x, while identity is
  useless at 99.60-99.84% across all four), but no verdict uses it that way
  yet. Read the breadth column, and treat a subspecies `confirmed` as
  confirmation of the species.

## [0.10.3] - 2026-08-19

Follow-on to 0.10.2 from the same live-testing campaign: a dilution series
(1%, 0.5%, 0.1% and below) simulated from Bioshield reference genomes, plus a
fresh-installation walkthrough. All three requested dilution levels were
detected, alarmed and confirmed by both validation methods; the fixes below
are what the exercise exposed on the way. No pipeline changes; nanometanf
stays at v1.7.0.

### Fixed
- Dashboard metric tiles no longer freeze mid-run. The sample selector
  embedded a second-resolution freshness age in its option labels, so the
  component was rewritten on every poll and stayed permanently pending; Dash
  defers every callback keyed on a pending component, which starved the
  `selected-sample` store and the tiles that follow it. Measured on a live
  run: zero calls in 35 seconds to either the selection or metrics callback
  while the status store already held 8,469 reads. The label now carries a
  coarse freshness bucket and the callback short-circuits when the option
  signature is unchanged; the precise age is still shown by the per-sample
  freshness pills. 0.10.2 addressed a symptom one hop downstream -- this is
  the cause.
- Reference genomes can be downloaded for database-keyed watchlist entries at
  all. The two roles of a taxid are now separate: fetch by the NCBI taxid
  (what a public database can answer) and cache under the database taxid
  (what every consumer looks up), via `genome_cache_taxid` /
  `genome_fetch_taxid`. Four call sites -- missing-genome and status queries,
  and the readiness checklist's genome and BLAST-database rows -- were
  reporting every Bioshield genome missing because they looked under the
  entry's synthetic taxid.
- The reference-genome guard compares at subspecies rank. It was genus-only,
  so a cached genome labelled *F. tularensis* subsp. *holarctica* that
  actually contained subsp. *novicida* passed silently and every Type B
  coverage figure was measured against the wrong reference. The guard now
  tolerates GTDB genus suffixes (`Bacillus_A`) and GTDB lumping (*B.
  pseudomallei* filed under *B. mallei*), so it does not cry wolf on correct
  field-database genomes.

### Changed
- The read-depth floor defaults to 10 instead of 50, and the verdict banner
  reads it from `min_reads_for_validation` like the Organisms tab and the
  exported report already did. The banner had a hard-coded 50, so with the new
  default the same detection would have been described three different ways.
- Watchlist hits below their alert threshold are shown rather than dropped,
  and never behind a green ALL CLEAR. A threshold decides whether a hit
  *alarms*, not whether it *exists*. Measured on a dilution barcode:
  *F. tularensis* subsp. *holarctica* at 8 reads and *Bacillus anthracis* at 7
  cleared the discovery floor but not their threshold of 10, and the Dashboard
  showed neither while the Organisms tab and the exported report both marked
  them DETECTED. Such hits now produce an amber BELOW ALERT THRESHOLD verdict
  naming the organisms and the depth. An above-threshold hit still wins
  outright and a genuinely clean screen is still green.

## [0.10.2] - 2026-08-19

Live-testing release. Every fix below was found by driving real realtime runs
against the Bioshield database -- first a sweep of every tab, then a focused
audit of the dashboard and top banner, then a synthetic multi-pathogen
exercise built from watchlist reference genomes (four barcodes, several
pathogens per sample, realistic nanopore reads). No pipeline changes;
nanometanf stays at v1.7.0.

### Fixed
- BLAST databases are prepared in the taxid space the genomes are cached in.
  A watchlist entry with no NCBI identity -- every bacterial Bioshield agent,
  76 of 129 -- is keyed by a synthetic taxid, while its reference genome is
  stored under the database taxid the reads are extracted for. Both
  launch-time guards received the entry taxids, so the database builder saw
  "no genome" for the entire set: a prepared reference reached the pipeline
  with no BLAST database and nothing in the log, leaving minimap2 coverage
  populated and the Sequence Matching sub-tab silently empty. The
  reference-mismatch guard was inert for the same reason, so a
  wrong-organism reference could be accepted without comment
- The Watchlist & Preparation tab counts prepared genomes correctly. It
  reported "0 downloaded / 129 missing" with eight reference genomes present
  in the configured cache, because it looked them up by the watchlist entry
  taxid rather than the database taxid the same entry already carries
- The dashboard metric tiles no longer freeze at zero. "Sequences Analyzed"
  and "Species Detected" read 0 for a whole realtime run while the verdict
  banner reported fourteen pathogens above threshold and the browser already
  held the real figures. The tiles were keyed on the sample-selector
  component, whose options are rebuilt on every poll from the per-sample
  freshness pills; a component with a pending output defers every callback
  keyed on it, so the tiles were starved for as long as data kept arriving.
  They now follow the shared selected-sample store, as every other tab does
- Cumulative counters no longer run backwards mid-run. The pipeline rewrites
  each sample's cumulative classification report per batch; a poll landing
  inside that write dropped the whole sample from the aggregate, so
  Sequences Analyzed stepped 3,943 -> 1,393 -> 9,394 and the
  above-threshold count flickered. The loader now serves the last good parse
  of a report while it is being rewritten
- The verdict banner shows completion promptly. It kept its ACTIVE state for
  over two minutes after a run finished, because the session-end files land
  before the status flip and the banner's refresh gate keys on file changes
  alone. A run-state change now bypasses that gate
- Coverage cards report the real mapping confidence. The session-end
  aggregate carries no mapping-quality field for its minimap2 entries, so
  cards showed "0 / 60" under a "30+ reliable" hint for near-perfect
  alignments; the per-pair statistics are now used to fill what the
  aggregate omits
- A panel that misses one browser update repairs itself within two minutes.
  The refresh gate used a server-side memo of what had been rendered, which
  diverges from the browser if a response is never applied -- on a quiet
  realtime run that froze the panel indefinitely. The memo now expires

## [0.10.1] - 2026-08-19

Field-bug-report release. A user running realtime analysis on a Bioshield
(flextaxd/GTDB) database reported three defects; each was reproduced against
a live realtime run before being fixed, and one further defect was found
during the reproduction. No pipeline changes -- nanometanf stays at v1.7.0.

### Fixed
- Realtime validation no longer freezes: the Validation tab's data store
  gated interval refreshes on an in-process "already rendered" memo, so a
  single store write the browser never applied left the panel stale for the
  rest of the run -- permanently once the run went quiet, since the results
  fingerprint stops changing then. The gate now uses a store-backed memo
  that rides the same response as the data, so a lost write self-heals on
  the next polling tick. The consensus store had the same gate and gets the
  same fix
- The pathogen report modal shows real read counts on GTDB and flextaxd
  databases. The alert card's View Report button carries the watchlist
  taxid (a pseudo-taxid for name-only entries), but the read/abundance
  lookup matched it against the Kraken2 report's database taxid; the two
  coincide only on an NCBI database, so the modal rendered N/A for
  organisms the dashboard showed at tens of thousands of reads. The lookup
  now tries candidate taxids: the clicked one, the entry's mapped database
  taxid, and the mapping collection's translation
- The View Report button works again when an organism is visible on both
  the Dashboard and the Organisms tab. Both surfaces emitted buttons under
  the same pattern-matching id type, so every watched detection produced
  two components with the same id; the duplicated id corrupted the click
  bookkeeping and the modal's reopen guard swallowed genuine clicks.
  Organism cards now use their own id type and the modal listens to both
- The dashboard no longer shows STANDBY over completed results when the
  app is reopened on a config that has not been through Start (for example
  a custom analysis folder set via `results_dir_override`). Twenty-six
  call sites across nine app modules resolved the results directory
  without the override fallback; all now use the shared resolver, and a
  contract test keeps the raw idiom from returning
- Verify Taxonomy IDs resolves entries again on GTDB-nomenclature
  databases (fix landed as `afc5e99` before this release; noted here
  because it is one of the three reported issues): the lookup no longer
  narrows the operator's NCBI/GTDB checkbox selection to the loaded
  database's detected nomenclature, which had disabled NCBI -- the only
  service that resolves name-only watchlist entries -- on every flextaxd
  field build

### Changed
- The watchlist table leads with detectability: the "In Database" column
  comes before the public-taxonomy lookup, the lookup is labelled
  "Name check" with a neutral badge instead of a green "Verified" tick,
  and the report modal's meta row matches. A name found in NCBI/GTDB says
  nothing about whether the loaded database can detect the organism

## [0.10.0] - 2026-08-19

Verification-driven release. Every change below was found or confirmed by
driving the real GUI operator flow against real Bioshield sequencing data --
a full batch release check, a realtime run fed by nanorunner, and a config
lifecycle audit -- rather than by unit tests alone. Pairs with nanometanf
v1.7.0; the two repositories are released together.

### Added
- Readiness check "Database Location": warns when the Kraken2 database sits
  on a removable or network volume, where memory-mapped random access is
  pathologically slow, and names the remedy (copy to local disk; the
  content-derived `db_hash` keeps cached indexes and mappings valid)
- On-demand validation failures write the command, working directory and
  captured stderr to `<results>/logs/` -- the directory the error message
  already told operators to check

### Changed
- Kraken2 resource sizing belongs to the pipeline: the generated `-c` config
  no longer pins `KRAKEN2_KRAKEN2` cpus/memory, so nanometanf's own scaling
  applies. GUI-launched runs classified single-threaded with an 8 GB cap
  regardless of hardware; the classification stage is now about 4x faster on
  the reference dataset (198 s to 44 s, whole run 14 min to 4m16s)
- `--kraken2_memory_gb` is derived from the measured database (hash size
  plus 4 GB headroom) instead of a flat default sized for MiniKraken
- Memory mapping defaults on for all platforms, ARM included; the retired
  ARM opt-out was dead code that also disagreed with the pipeline
- Apply Settings clears the "Modified" badge and rebases the dirty-check
  baseline, so the badge is a usable signal again

### Fixed
- A watchlist toggle no longer reverts applied settings: it persisted its
  whole in-memory config over `last-session.yaml`, and after a page reload
  that config is the boot config, silently undoing an applied change
- On-demand validation works end to end again: the Nextflow launch shares
  the main run's resume context (launch directory and work directory), the
  aggregate-scope `sample="all"` token no longer reads as a literal sample
  name, and the cumulative genome list seeds from the main run so the
  rebuilt `validation_results.json` keeps every previously validated pair
- The Validation tab resolves the results directory through the same
  override chain as the rest of the app; it previously reported "Results
  directory not found" for a live run whose files were in
  `results_dir_override`, and the batch drill-down selector came up empty
  for the same reason
- Genome lookup keys on the taxid reads are extracted for, so validation is
  possible on GTDB and custom databases
- The genome-coverage verdict considers real genome breadth, and confirmation
  requires read support; see the cross-repo contract below

### Testing
- Cross-repo contract tests pin what "confirmed" means (read and breadth
  floors, applied in the pipeline modules, including the realtime cumulative
  aggregator), the single-sourced Kraken2 memory-mapping decision and preload
  gate, and the per-batch progressive-report defaults that keep the dashboard
  live. Each fails if either repository drifts
- 3,785 tests

## [0.9.0] - 2026-08-17

Cumulative release covering the 2026-06 through 2026-08 development line,
including the 2026-08-16 cross-repo audit campaign (about 40 defects fixed in
this repository, with the matching pipeline fixes in nanometanf v1.6.1).

### Added
- Subspecies support end to end: S1-S3 ranks detectable and selectable in the
  Taxonomy and Organisms tabs, a dedicated subspecies table in the exported
  report, trinomial name variants in watchlist matching, and subspecies nodes
  reachable by the fuzzy/substring strategies
- Negative-control handling: declared controls (plus NTC/blank/fused NTC1
  name patterns) are annotated in per-sample attribution, the verdict banner,
  and the exported report; controls are reported, never suppressive
- Verdict integrity guards: NOT_SCREENED and INSUFFICIENT_READS states, a
  shallow-depth clause on detections, and dataless-sample marking, carried
  uniformly across the dashboard, Organisms panel, and exported report
- Realtime cumulative validation with per-batch drill-down, on-demand
  validation persistence across reloads, and a mid-run freshness signal from
  per-pair validation files
- Offline deployment hardening: singularity image bundling with Nextflow
  cache-name compatibility, import verification (checksums, architecture,
  partial-copy detection), and an air-gap-verified end-to-end flow
- PEP 621 packaging (pyproject.toml); code-size and per-poll-cost CI gates

### Changed
- Polling is adaptive: 10 s while a run is active, 60 s idle; heavy loaders
  are fingerprint-gated with per-sample cache scoping (quiet 24-sample poll
  cost reduced from O(N^1.65) to O(N^0.91))
- The multi-user run lock guards the real output directory
  (results_output_directory), not the internal analysis directory
- Dead configuration surfaces removed (unused validator/manager modules,
  inert form controls); config values are coerced to what nanometanf's
  schema accepts at launch time

### Fixed
- The "All Samples" aggregate resolves the Kraken2 report tier per sample, so
  a barcode still on batch reports is never dropped from the frame the
  verdict banner reads
- The aggregate discovery floor gates on cumulative reads (the column it
  reports), closing a false ALL CLEAR on subspecies-resolving databases
- A null realtime timeout reaches the pipeline as run-indefinitely instead of
  silently reverting to a 60-minute cutoff
- Disk-fallback BLAST results no longer claim 100% validation on an unknown
  denominator; ambiguous shared-node detections disclose the alternatives on
  the no-mapping path; GTDB-suffixed names clear the match threshold
- One malformed watchlist entry, alert record, or aggregate JSON entry costs
  only itself instead of truncating screening, alerts, or validation results
- Background callbacks gate their redundant work through stores that survive
  process isolation; readiness probes respect their TTL instead of running
  docker/nextflow checks every tick
- Stop reconciles a dead pipeline process instead of raising; an operator
  abort is announced as stopped, not completed; exported-report chart JSON
  cannot break out of its script element


## [0.8.0] - 2026-06-09

### Added
- BLAST-database build diagnostics: an honest built / already-present / failed breakdown with `makeblastdb` failure reasons, one automatic retry, and a launch-time guarantee that every validation taxid with a genome has a BLAST database
- Amplicon-aware coverage detection for multi-copy 16S and single-copy genes, with covered-region and local-depth metrics plus a cross-species 16S guard; TUL4 amplicon test fixture
- Validation result ordering: confirmed/validated detections sorted to the top of the BLAST cards, coverage cards, and stats table
- Reference-genome download-failure reporting, surfacing NCBI/GTDB-unreachable as the cause of a low genome/BLAST-database count
- Loading spinner on the reference-genome Refresh action
- Code-size ratchet (`scripts/check_code_size.py`) enforced in CI
- Canonical waterfall loading pattern (`canonical_loaders.py`): tries pre-computed JSON first, falls back to raw file parsing
- Manifest-based sample detection in `sample_detector.py` with glob fallback for backward compatibility
- `kraken2_helpers.py` module extracted from `classification_tab.py` (375 LOC of Kraken2-specific logic)
- 3 new built-in watchlists: Nosocomial/ESKAPE, Wastewater Surveillance, Zoonotic One Health
- 3 example custom watchlists: STI Pathogens, Neglected Tropical Diseases, Agricultural Plant
- Quick-start buttons for all 9 built-in watchlists
- Unmapped organism count displayed in Preparation tab taxid mapping
- `--host` CLI flag for controlling network binding (defaults to localhost)
- Log rotation (10MB main, 5MB API, with backups)
- Configuration documentation for watchlist v2.0 format
- Python 3.12 classifier in setup.py
- Pipeline crash detection in backend monitor (failed processes, unexpected termination)
- Realtime timeout enforcement (`realtime_timeout_minutes` now functional)
- Dashboard status cache (`dcc.Store`) to avoid redundant per-tick computation
- Path traversal protection in `delete_config()` and QC export callbacks
- Thread-safe locking on data loader caches and 7 singleton factories
- Thread-safe double-checked locking on `get_watchlist_manager()` singleton
- Thread-safe `_lock` on `WatchlistManager` entry mutations
- Custom watchlist persistence to `~/.nanometa/watchlists/` on import
- Custom watchlist delete button (user-created watchlists only)
- Upload validation feedback with detailed error messages
- `openpyxl` dependency for XLSX export
- `pipeline_profile` and `qc_tool` settings in default config.yaml
- "Remove All" button for bulk genome deletion with confirmation dialog

### Changed
- `pathogen_genomes.json` written to `pipeline_input/` instead of `validation/` so it survives the archive/rerun sweep (was causing a launch crash)
- QC stage-strip first box repurposed to "Reads Processed" in seqkit/chopper mode instead of showing N/A
- Coverage species dropdown enlarged and always labelled with a resolved species name
- Pipeline completion no longer switches away from a results tab the operator is viewing (only auto-navigates from a Setup tab)
- Header process counter shows "N done · M active" instead of a misleading "N/N"
- "Verify against DB" validation count reflects the enabled watchlist set
- Full dark-mode legibility pass: theme-aware inline-text colour variables and per-class `[data-theme="dark"]` overrides
- README, Installation, and tutorial tab references updated for the v2.0 tab layout (Watchlist & Preparation merged into one tab; Deployment tab added); Nextflow floor corrected to 26.04.0 and Python requirement to 3.11+
- `data_loaders.py` refactored from monolithic module (1,630 LOC) to re-export hub backed by `classification_loaders.py`, `qc_loaders.py`, `validation_loaders.py`, and `loader_utils.py`
- `sample_detector.py` updated to manifest-based detection with glob fallback
- `nanometa-sim` deprecated in favour of nanorunner (stub prints notice and exits)
- Default server binding from 0.0.0.0 to 127.0.0.1 (security)
- Dash version requirement from >=2.18.2 to >=4.0.0
- README requirements section updated to match actual dependencies
- `create_nextflow_config()` respects `pipeline_profile` setting (docker/singularity/conda)
- Default QC tool aligned to `chopper` across all config sources
- CI workflow updated: actions v4/v5, Python 3.12, removed nonexistent entry points
- `nanometa_demo.py` commands use list form instead of `shell=True`
- `_is_file_stable()` replaced blocking sleep with mtime-based check (non-blocking)

### Fixed
- Realtime config save rejecting an empty/watched input directory (by-barcode input-content checks now apply to batch mode only)
- Pathogen "View Report" modal reopening itself on a data refresh (pattern-matched button recreation re-firing the callback)
- Spurious "Validating 1/1" toast when merely selecting a watchlist
- "Data may be stale" badge persisting after a run completed
- BLAST validation empty while minimap2 worked, traced to missing BLAST databases for downloaded genomes
- Genome accession column showing placeholders (`virus_taxid_*`, `taxid_*`, `discovered`) instead of real NCBI accessions
- Offline deploy crash: `TaxidMapper.load_database()` called without required `database_path` argument
- `offline_mode` not propagated to API clients (NCBI, GTDB, genome manager) — network calls attempted in air-gapped mode
- `setup.py` install_requires failing due to unfiltered comments from requirements.txt
- Pathogen modal using wrong config key for results directory
- Redundant `_collect_samples_data()` calls (3-5x per tick reduced to 1x via status cache)
- Watchlist toggle state not persisted across restarts (now saved to `~/.nanometa/`)
- Pickle cache loading with type validation to reject corrupted or tampered caches
- `delete_config()` using undefined logger variable
- `fcntl` import crash on Windows
- `os.uname()` crash on Windows (replaced with `platform.node()`)
- Organism details modal showing "Unknown Organism" for non-watchlist species
- 3 circular callback dependencies (app-config self-reference, pathogen print, config alert)
- Parser double-counting from overlapping glob patterns and missing per-sample dedup
- Mutable cached Plotly figures in QC tab leaking state across requests
- `setup.py` `package_data` missing watchlist and pathogen YAML data files
- `MANIFEST.in` missing data files and `requirements.txt` for sdist builds
- Dashboard donut chart using `reads` column instead of `cumul_reads` (double-counting)
- `__main__.py` hardcoding `host="0.0.0.0"` bypassing localhost security default

### Removed
- Plugin system (`core/plugins/`) - unused scaffolding
- `core/utils/taxonomy_validator.py` - unused
- `core/utils/diversity_metrics.py` - unused
- `core/workflow/container_cacher.py` - unused
- `core/workflow/action_orchestrator.py` - unused
- `core/workflow/data_processor.py` - unused
- `app/utils/error_handler.py` - unused
- `nanopore_simulator.py`, `nanometa_demo.py` - replaced by nanorunner
- `generate_demo_data.py`, `verify_visualizations.py` (repo root) - unused scripts
- `DATA_SOURCE_REGISTRY` scaffolding from `sample_detector.py`
- 211 lines of dead CSS from `styles.css`
- Unused `scipy` dependency
- `pyfastx` dependency (only used by deprecated nanometa-sim)

## [0.6.1] - 2026-03-08

### Added
- Dash 4 migration: all DataTables converted to dash-ag-grid
- Orphaned button callbacks wired up (dashboard help/refresh, QC export, XLSX export)
- Config auto-persistence (auto-save on Apply, auto-load on startup)
- Readiness gating with pre-flight checklist and popover badge
- Input Files metric card on dashboard
- Hover popover on readiness badge showing check details

### Changed
- Donut chart empty state: axes hidden instead of showing artifacts
- CSS selectors updated for Dash 4 component rendering
- Footer badges and metric cards restyled for lab readability
- Font sizes increased for lab display readability (14px to 18px)
- Alert severity levels recalibrated (high-risk pathogens WARNING, low yield INFO)

### Fixed
- MATCH wildcard mismatch in preparation_tab.py breaking all callbacks app-wide
- Flask errorhandler(KeyError) swallowing all KeyErrors (buttons unresponsive)
- 17 orphaned taxmap callbacks referencing non-existent layout components removed
- Dashboard traffic light CSS class conflict forcing green on all states
- Clientside callback setTimeout returning from inner function
- Tab persistence conflicts with active_tab callback writes
- Sankey species label truncation
- QC and dashboard metrics not filtering by selected sample
- Watchlist quick-start not enabling entries on activation
- Watchlist merge not preserving enabled state
- Kraken2 report leading whitespace causing Sankey duplicate indices

## [0.6.0] - 2026-03-02

### Added
- Offline deployment capability for air-gapped field labs
- Bundle export/import via `nanometa-prepare` CLI
- Virus and fungi genome download support with taxid-based fallback
- Batch genome downloading
- ICTV 2024 binomial virus nomenclature
- Rank normalization for Kraken2 PlusPFP extended taxonomy
- 40 new tests (integration, PAF parser, UX component, E2E)
- Operator Guide for lab personnel
- Migration Guide for v1.x to v2.0 upgrade

### Changed
- Dashboard redesigned with 8 tabs (Dashboard, Organisms, QC, Taxonomy, Validation, Watchlist, Configuration, Preparation)
- Watchlist format upgraded to v2.0 (structured YAML with metadata and threat levels)
- 6 built-in watchlists audited and updated against authoritative sources

### Fixed
- ~4x read count inflation from duplicate batch report files
- BLAST column detection and minimap2 identity calculation in validation pipeline
- Spurious batch samples from recursive glob in sample detection
- Sankey layout positioning and composite key handling
- Watchlist expand chevron unreliable first-click

## [0.5.0] - 2025-12-15

### Added
- v2 dashboard with new tab-based layout
- Interactive Sankey and sunburst taxonomy visualizations
- BLAST and minimap2 validation tabs
- Pathogen watchlist system with threat-level alerts
- Real-time monitoring with dcc.Interval polling
- Multi-sample support for barcoded runs

### Changed
- Complete UI rewrite using Dash Bootstrap Components
- Configuration management via GUI instead of config files only

## [0.4.3] - 2024-01-22

### Fixed
- Remote access to the GUI

### Changed
- Installation and README documentation updates

## [0.4.2] - 2024-01-18

### Added
- In-GUI editing of BLAST cutoffs, the update frequency, the danger-colour threshold, and the dashboard headline

### Changed
- Snakefile, `config.yaml`, and `nanometa_gui.py` updates

## [0.4.1] - 2023-11-23

### Fixed
- Configuration bugs
- Error handling differing file timestamps

## [0.4.0] - 2023-11-19

### Added
- Support for external Kraken2 databases, with a bundled YAML of downloadable databases
- Buttons to save the Kraken2 report and species lists from the GUI
- Config variables editable via `nanometa-new`
- Requirement that the data path be set explicitly
- Demo dataset and an Installation guide

### Changed
- More robust config reading in the Snakefile
- Top-aligned main-tab sections

## [0.3.2] - 2023-10-04

### Fixed
- Dependency specifications

## [0.3.1] - 2023-10-01

### Added
- GTDB filtering
- Local-file processing (`process_local_files`)
- Batch and real-time processing modes

### Changed
- BLAST handling refactored

## [0.3.0] - 2023-09-28

### Added
- Temporary-file cleanup in the wrapper script (with a clean exit when the config file is missing or unparseable)
- Type hints on helper functions
- NCBI Datasets added to the conda environment

### Changed
- Major reorganisation of functions into modules
- Global `__version__` definition
- Renamed "live" to "runner"
- More flexible config handling

## [0.2.0] - 2023-09-07

### Added
- GitHub Actions continuous integration

### Changed
- Refactored the `new` and `sim` entry points
- Introduced the in-code `__version__` value

## [0.1.1] - 2023-06-29

### Added
- `-h` / `--help` for the command-line entry points
- `install_requires` in `setup.py`

### Changed
- Renamed the pipeline script to `nanometa-pipe`

## [0.1.0] - 2023-06-27

### Added
- Initial release: real-time Kraken2 result visualisation, species-of-interest tracking, and command-line configuration
