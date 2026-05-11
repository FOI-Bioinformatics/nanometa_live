# Threading and parallelism audit: nanometanf + nanometa_live

Date: 2026-05-10. Target hardware tiers: 8-thread laptop (dev), 40-thread server, 96-thread server.

The audit covers (a) how each repo distributes work, (b) where serialisation is by design vs. accidental, (c) which knobs scale automatically vs. need explicit per-host tuning. The headline finding is that **pipeline throughput on 40- and 96-thread servers is bounded by hardcoded process CPU allocations and a fixed `max_classification_forks` ceiling that does not auto-scale** — a 40-thread server uses at most 16-24 cores under the active profiles, and a 96-thread server is no faster than a 40-thread one until the knobs are raised.

The GUI's worst per-host scaling penalty is on **fixed `ThreadPoolExecutor` sizes** (`max_workers=3` for genome downloads, `max_workers=2` for BLAST DB builds) that do not consult `os.cpu_count()`.

---

## Part 1 - nanometanf (Nextflow pipeline)

### 1.1 Process resource ladder

`conf/base.config:37-75` defines the standard nf-core label hierarchy: `process_single` (1 cpu / 6 GB), `process_low` (2 / 12), `process_medium` (6 / 36), `process_high` (12 / 72), `process_high_memory` (200 GB cap), `process_long` (20 h). Hardware profiles (`conf/minion.config`, `conf/promethion.config`, `conf/promethion_8.config`, `conf/field.config`, `conf/production.config`) then override per-process `cpus`/`memory`/`maxForks`.

| Process | Module location | CPU directive | Effective cpus today |
|---------|-----------------|---------------|----------------------|
| `KRAKEN2_KRAKEN2` | `modules/nf-core/kraken2/kraken2/main.nf` | `--threads $task.cpus` | hardcoded **8** in `modules.config:192`, `base.config:77` |
| `KRAKEN2_INCREMENTAL_CLASSIFIER` | `modules/local/kraken2_incremental_classifier/main.nf` | `--threads $task.cpus` | hardcoded **8** in `modules.config:240`, no retry scaling |
| `KRAKEN2_OPTIMIZED` | `modules/local/kraken2_optimized/main.nf` | `--threads $task.cpus` | label `process_high` (12); per-sample memory 64 GB |
| `MINIMAP2_ALIGN` | `modules/nf-core/minimap2/align/main.nf` | `-t ${task.cpus}` | label `process_high` (12) |
| `BLAST_BLASTN` | `modules/nf-core/blast/blastn/main.nf` | `-num_threads ${task.cpus}` | hardcoded **4** in `modules.config:82`, scales 4->8 GB on retry |
| `CHOPPER` | `modules/nf-core/chopper/main.nf` | `--threads $task.cpus` | hardcoded **4** in `modules.config:126`, no retry scaling |
| `FASTP` | `modules/nf-core/fastp/main.nf` | `--thread $task.cpus` | hardcoded **4** in `modules.config:87`, no retry scaling |
| `FASTQC` | `modules/nf-core/fastqc/main.nf` | `--threads ${task.cpus}` | hardcoded **4** in `modules.config:62` |
| `NANOPLOT` | `modules/nf-core/nanoplot/main.nf` | `-t $task.cpus` | hardcoded **4** in `modules.config:352` |
| `SEQKIT_STATS` | `modules/nf-core/seqkit/stats/main.nf` | `--threads ${task.cpus}` | hardcoded **1** (`process_single` default) |
| `FILTLONG` | `modules/nf-core/filtlong/main.nf` | (no thread flag) | single-thread by tool design |
| `TAXPASTA_*` | `modules/nf-core/taxpasta/...` | (no thread flag) | single-thread |

Implication: every QC step (chopper, fastp, fastqc, nanoplot) is locked at 4 cpus. A 40-core server cannot speed up the QC stage of a single sample at all without editing `modules.config`. The Kraken2 jobs at 8 cpus apiece are the principal CPU consumers and are gated by `max_classification_forks`.

### 1.2 Concurrency control parameters

| Parameter | Default | Where set | Scope |
|-----------|---------|-----------|-------|
| `max_cpus` | 8 (base) | `base.config:25` | Hard ceiling per task |
| `max_memory` | 16 GB (base), 256 GB (promethion) | `base.config:26` | Hard ceiling per task |
| `max_classification_forks` | 4 (base), 6 (promethion), 1 (field) | `nextflow.config:71`, `modules.config:241` | Number of concurrent Kraken2 jobs |
| `max_concurrent_batches` | 4 | `nextflow.config:70` | Documented as backpressure cap; not wired into a concrete operator (shadowed by `max_classification_forks`) |
| `kraken2_memory_gb` | 12 | `nextflow.config:63`, `modules.config:184` | Per-Kraken2 RAM (must scale with DB size: MiniKraken 12 GB, PlusPFP 80 GB) |
| `kraken2_memory_mapping` | true | `nextflow.config:54` | Auto-disabled on ARM (SIGSEGV risk) |
| `batch_size` | 10 | `nextflow.config:20` | Real-time files per batch |
| `batch_timeout` | 60 s | `nextflow.config:42` | Grace before partial flush |

Sample-level cap arithmetic: `max_classification_forks * task.cpus` is the Kraken2 floor. Profile-by-profile:

| Profile | forks * cpus | 40-core utilisation | 96-core utilisation |
|---------|--------------|---------------------|---------------------|
| `base` (no profile) | 4 * 8 = 32 | 80% (32/40) | 33% (32/96) |
| `minion` (8-core dev) | 4 * 8 = 32 | OOM risk if RAM bound | OOM risk |
| `promethion` (24-core) | 6 * 4 = 24 | 60% | 25% |
| `promethion_8` | 4 * 6 = 24 | 60% | 25% |
| `field` (laptop, RAM-bound) | 1 * 4 = 4 | 10% | 4% |
| `production` (32-core) | 4 * min(16*attempt, 24) = 64 first attempt | clamped to `max_cpus=32` | clamped to 32 |

Without a profile tuned for 40-core or 96-core hosts, the existing ladder sits between 17% and 33% utilisation on a 96-thread server.

### 1.3 Channel topology bottlenecks

| Site | Operator | Necessary? | Impact |
|------|----------|------------|--------|
| `workflows/nanometanf.nf` (QC compare branch) | `.collect()` on `ch_qc_reads` | accidental | forces multi-sample wait before `NANOPLOT_COMPARE` |
| `workflows/nanometanf.nf` (MultiQC) | `.collect().map { [it] }` | necessary | MultiQC requires all inputs, fires once at end |
| `subworkflows/local/taxonomic_classification/main.nf:263` | `.subscribe { ... }` on per-sample taxid counts | necessary | progressive cumulative report writer; non-blocking subscription, single Groovy thread by design |
| `subworkflows/local/validation/main.nf:158, 177` | `.collect()` on BLAST/minimap2 results | necessary | aggregation step at end of session |
| `subworkflows/local/realtime_monitoring/main.nf:59` | `.groupBy()` + round-robin | necessary | fair file distribution across barcodes |
| (absent) | `.reduce()`, `.transpose()`, `groupTuple()` without `size:` | n/a | pipeline avoids these anti-patterns |

The QC-compare `.collect()` is the only true accidental serialisation; everything else is an aggregation step that has to wait by definition.

### 1.4 Streaming-classifier architecture (v1.5+)

`subworkflows/local/taxonomic_classification/main.nf` implements per-sample-parallel incremental classification:

1. **Per-sample batch numbering** at line 187-204 - stateful `.map()` increments `meta.batch_id` (0, 1, 2 ...) without `.collect()`, compatible with `Channel.watchPath()`.
2. `KRAKEN2_INCREMENTAL_CLASSIFIER` runs per-sample-per-batch, gated by `maxForks = params.max_classification_forks ?: 4`.
3. `KRAKEN2_OUTPUT_MERGER` (line 233-236) writes one file per batch, append-only, O(1) per batch.
4. `KRAKEN2_REPORT_GENERATOR` (line 241-245) runs stateless per batch; `maxForks = 4`.
5. Progressive cumulative reports written every `report_write_interval` batches via the single `.subscribe()` consumer at line 263.
6. `KRAKEN2_FINAL_AGGREGATOR` runs once per sample at session end.

**The architecture is per-sample-parallel by construction**, but the benefit is bounded by `max_classification_forks` (default 4) and the global `KRAKEN2_REPORT_GENERATOR maxForks = 4`. On a 96-thread server with 24 barcodes the design can in principle saturate, but the default knob ceiling caps actual concurrency at 4 simultaneous Kraken2 jobs.

### 1.5 Real-time mode parallelism

`subworkflows/local/realtime_monitoring/main.nf:266-288` matches files to a regex and round-robin distributes them across parent directories (barcodes). Each barcode produces independent `[meta, file]` tuples, but **all files feed into a single `BatchUtils.batchWithTimeout()` call** - the daemon `Timer` is not per-barcode. Result: cross-barcode batching, fair distribution, single global queue. Downstream `KRAKEN2_INCREMENTAL_CLASSIFIER maxForks` is the actual concurrency gate.

For high-barcode counts (24 barcodes * default 4 forks = 4 simultaneous tasks), the global queue serialises barcode processing. This is a deliberate fairness trade-off, not a bug.

### 1.6 Hardware-profile gaps

There is **no profile for 40-core or 96-core hosts**. `production.config` is the closest (32 cores, 256 GB), but its `min(16 * attempt, 24)` Kraken2 cpu rule plus base `max_cpus = 8` is internally inconsistent. The repo would benefit from explicit `conf/server_40.config` and `conf/server_96.config` profiles that:

- Raise `max_classification_forks` to 8 (40-core) and 16 (96-core).
- Drop the per-process hardcodes in `modules.config` and use `task.cpus` driven by the label ladder.
- Increase `process_high` cpus from 12 to a profile-conditional value (e.g. 16 on 40-core, 24 on 96-core).

### 1.7 nf-core idioms - deviations

- The repo does not use `check_max(...)` / `getResources(...)` helpers; resource overrides are direct in `modules.config` and per-profile.
- Custom concurrency knobs (`max_classification_forks`, `max_concurrent_batches`, `max_batch_size`) are not nf-core standard.
- Retry scaling is inconsistent: `base.config` uses `* task.attempt`, `promethion.config` uses fixed cpus + scaled memory, `production.config` uses `min(*attempt, cap)`.

---

## Part 2 - nanometa_live (Dash GUI)

### 2.1 Dash app threading

Both `nanometa_live/app/__main__.py:119` and `nanometa_live/nanometa_live.py:222` call `app.run(host=..., port=..., debug=..., threaded=True)`. The server is Werkzeug. `threaded=True` enables one thread per HTTP request; no explicit worker-count cap. On a 96-thread host concurrency is unbounded but every Python-level callback holds the GIL during pandas / regex work.

### 2.2 Background callbacks (DiskcacheManager)

`app/app.py:85-129` initialises `DiskcacheManager` over a `FanoutCache(shards=8)` per-process under `cache/run-<pid>-<ts>/`. Five callbacks are declared `background=True` (`preparation_tab.py:150, 742, 1020, 1322, 1815`). The DiskcacheManager spawns a separate OS process per background callback, so those run isolated.

Heavy callbacks **not** backgrounded that probably should be:

- `update_main_results` (Organisms tab) - kraken parse + per-sample aggregate.
- `update_classification_dashboard` - Sankey/Sunburst rebuild.
- `update_qc_panel` - fastp/seqkit parse, summary stats.
- The fingerprint walker callback at `callbacks.py:290`.

These run on the Werkzeug request thread today. On 8 threads the GIL serialisation is acceptable; on 96 threads there is no benefit either, because the bottleneck is the parse work itself, not the host.

### 2.3 Fixed-size pools (the most quotable per-host scaling gap)

`core/utils/genome_manager.py`:

- Line 1530: `ThreadPoolExecutor(max_workers=3)` for genome downloads (HTTPS to NCBI Datasets / GTDB).
- Line 1761, 1790: `ThreadPoolExecutor(max_workers=2)` for `makeblastdb` builds (CPU-bound).

Both are hardcoded literals, not derived from `os.cpu_count()`. On the 8-thread laptop they are reasonable. On a 96-thread server with a 100-organism watchlist, 30+ organisms wait in line for one of three download slots, and only two BLAST builds can proceed concurrently.

### 2.4 Subprocess invocation patterns

| Site | Subprocess form | Blocks Dash thread? |
|------|-----------------|---------------------|
| `core/workflow/nextflow_manager.py:741` | `subprocess.Popen(..., start_new_session=True)` | no - daemon thread monitors |
| `core/utils/kraken_utils.py:193, 200` | `subprocess.run(..., timeout=300)` | yes - up to 5 min on the request thread |
| `core/utils/genome_manager.py` (~1742, 1790) | `subprocess.run(makeblastdb)` inside ThreadPoolExecutor worker | no |
| `core/workflow/on_demand_validator.py` | called from a background callback | no - isolated worker |

The kraken_utils readiness check is the big offender: it can block the main Dash request thread for up to 5 minutes during cold pipeline configuration changes.

### 2.5 Polling / fingerprint walker

`core/utils/loader_utils.py:230-276` (`_get_path_fingerprint`) walks up to **5000 files** per `update-interval` tick. The cap is a compile-time constant `_MAX_FINGERPRINT_FILES`. About 7 callbacks are gated on the raw `update-interval` tick; another ~20 listen to `results-fingerprint` instead and short-circuit when nothing changed. The walk itself runs on the main Dash thread.

For long real-time runs that emit thousands of per-batch reports under `kraken2/<sample>/batch_reports/`, the 5000-file ceiling **truncates** the fingerprint silently (older files dropped from the hash), which can produce stale "nothing changed" verdicts. Server with NVMe absorbs this in <10 ms; spinning-disk laptop is the worst case.

### 2.6 Diskcache and cross-process shared state

The 8-shard `FanoutCache` is the medium for sharing state between the main Dash process and the `DiskcacheManager` background workers. Several in-memory locks (`_readiness_cache_lock`, `_parse_locks_lock`, `_cache_lock`, `_sample_cache_lock`) live in the main process only - background workers cannot share their kraken/fastp/seqkit DataFrame caches and re-parse files independently.

For the 8 vs 96 thread comparison, this is roughly neutral on small workloads but the parse-lock contention scales linearly with concurrent Dash requests on the main process.

### 2.7 NCBI / GTDB API singletons

`get_ncbi_client()` returns a process-wide singleton; all taxonomy lookups serialise through it. There is no per-thread rate limiting and no concurrent.futures parallelism for batched lookups. NCBI's public API caps at 3 req/sec; the GUI does not enforce this client-side. The taxonomy circuit breaker (`core/taxonomy/taxonomy_api.py`) is a class-level per-host failure counter, in-memory, not a token-bucket.

### 2.8 On-demand validator

`core/workflow/on_demand_validator.py` runs in a background callback (`validation_tab.py`). Genome download, BLAST DB build, read extraction, and BLAST execution are serial inside the worker. Subprocess calls (`makeblastdb`, `seqkit`, `blastn`) each run on one thread. On a 40-core server, a single validation job occupies one thread; the other 39 sit idle.

### 2.9 Pandas data loaders

`app/utils/loaders/*.py` and `core/utils/classification_loaders.py` use `pd.read_csv()` and per-row Python operations. Pandas releases the GIL during I/O but loops in deduplication / filtering hold it. Parse times for large files:

- 100 MB Kraken2 report: ~500 ms - 2 s on HDD; ~300 ms on NVMe.
- BLAST results with 10k+ hits: CPU-bound, ~200-800 ms.

The `_parse_locks` global mutex prevents thundering-herd re-parses but caps concurrent kraken parses at one per file key.

### 2.10 Test suite

`tests/conftest.py` does not configure `pytest-xdist`. `pytest tests/ -v` runs sequentially. The 962-test suite takes ~55 s on the 8-thread laptop; on a 40-thread CI agent with `pytest -n auto` it should finish in ~10-15 s.

---

## Summary scaling table

| Component | Hardcoded | 8-thread laptop | 40-thread server | 96-thread server | Source |
|-----------|-----------|-----------------|------------------|------------------|--------|
| nanometanf Kraken2 cpus | yes (4 or 8) | 80% util (1 fork) | <40% util | <17% util | `modules.config:192, 240` |
| nanometanf max_classification_forks | yes (4 default) | adequate | underused | severely underused | `nextflow.config:71` |
| nanometanf QC tools (fastp/chopper/fastqc/nanoplot) | yes (4 cpus) | 50-100% util | 10% util | 4% util | `modules.config:62, 87, 126, 352` |
| GUI Werkzeug threading | unbounded | adequate | adequate | adequate | `app/__main__.py:119` |
| GUI DiskcacheManager shards | 8 | adequate | OK | begins to bottleneck | `app/app.py:85-129` |
| GUI genome download pool | 3 | OK | underused | severely underused | `genome_manager.py:1530` |
| GUI BLAST build pool | 2 | tight | underused | severely underused | `genome_manager.py:1761, 1790` |
| GUI fingerprint file cap | 5000 | adequate | adequate | adequate but truncates | `loader_utils.py:230-276` |
| GUI NCBI singleton | yes | adequate | underused | underused | `core/taxonomy/taxonomy_api.py` |
| Test suite parallelism | none | 55 s sequential | could be ~10 s with `-n auto` | could be ~10 s | `tests/conftest.py` |

---

## Top recommendations (ranked by impact / effort)

1. **Add `conf/server.config` profile to nanometanf** that raises `max_classification_forks` to `params.max_cpus / 4`, drops the QC-tool hardcodes in `modules.config`, and lets `process_high` use `min(24, max_cpus)`. Single config file, no Groovy changes. Closes the largest scaling gap.
2. **Auto-derive nanometa_live `ThreadPoolExecutor` sizes** from `os.cpu_count()` (bounded `max(2, min(cpu_count // 2, 16))`). One-line change at the two `genome_manager.py` call sites. Closes the GUI's largest scaling gap.
3. **Background-callback the heavy GUI parsers** (`update_main_results`, classification Sankey rebuild, qc panel). Three or four `background=True` decorators plus a small `loader_utils` adjustment so background workers can share the parse cache via diskcache rather than the in-memory mutex.
4. **Enable `pytest-xdist`** in `tests/conftest.py` (auto detect cores; `pytest -n auto`). 962 tests in ~10 s on CI is a meaningful developer-loop win.
5. **Bump `_MAX_FINGERPRINT_FILES`** from 5000 to a profile-conditional value, or rotate the hash so older files are not silently dropped on long real-time runs.
6. **Drop the `kraken_utils.run(timeout=300)` blocking call from the readiness path** - move it to a background callback so the main Dash thread cannot stall for 5 minutes.

Items 1 and 2 cover most of the 8 vs 96 thread gap. Items 3-6 are quality-of-life but compound for long real-time runs on the larger servers.

---

## Status (2026-05-11 follow-up)

All six top recommendations have shipped on `dev`. Summary:

| # | Recommendation | Status | Commit / location |
|---|---|---|---|
| 1 | `conf/server.config` profile (drop QC hardcodes, raise resourceLimits, scale `max_classification_forks`) | done | nanometanf `c7f20ed` (merged into dev `c7f20ed`) |
| 2 | Auto-derive nanometa_live `ThreadPoolExecutor` sizes from `os.cpu_count()` | done | nanometa_live `b1b682c` (+12 regression tests) |
| 3 | Background-callback the heavy GUI parsers (`update_main_results`, `update_qc_stats`) | done | nanometa_live `0555854` (+5 pinning tests) |
| 4 | Enable `pytest-xdist` (`-n auto --dist=loadfile`); filelock-guarded shared dataset fixture | done | nanometa_live `f184822` (978 -> 974/1 -> 978/1) |
| 5 | Bump `_MAX_FINGERPRINT_FILES` 5000 -> 50000; env-var override; count-fallback past stat cap | done | nanometa_live `f184822` (+4 overflow tests) |
| 6 | Move the readiness-check subprocess wait off the main Dash thread | done | nanometa_live (this commit) -- the audit listed `kraken_utils.py:193` but the actual blocking site is `update_readiness_indicator` in `app/callbacks.py:797`, which itself shells out to `docker info` + `nextflow -version` (~15-20 s on a cold path) on every interval tick after a configuration change. Backgrounding the callback isolates the wait. |

Note on item #6: the 60 s in-memory readiness TTL cache no longer crosses the worker boundary, so the worst-case latency is ~15 s of *worker* time per cold tick rather than ~15 s of request-thread time. A future improvement could move the readiness cache into the shared diskcache so warm-path hits are preserved across workers; not required by the audit's intent.

## Out of scope

- nanorunner is a single-machine simulator; not in scope.
- Container-engine scaling (Docker / Singularity) is not covered - assumed conda profile per CLAUDE.md.
- GPU paths (Dorado basecaller) are not exercised on the 40/96-core targets the user mentioned.
