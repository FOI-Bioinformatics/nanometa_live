# Testing guide: realtime validation + dashboard fixes

This guide explains how to verify the four changes shipped for the realtime
operator feedback:

1. **Realtime validation refreshes during the run** (nanometanf) — the
   cumulative `validation_results.json` is rewritten each batch instead of only
   at the timeout.
2. **Auto-stop countdown no longer freezes** (nanometa_live).
3. **"View Report" always opens the pathogen modal** (nanometa_live).
4. **Validation tab shows a diagnostic** explaining why it is empty
   (nanometa_live).

There are two layers: **automated tests** (fast, run anywhere) and a
**manual live run** against the real SAMMLA biothreat dataset (the only way to
exercise the full realtime pipeline end to end).

All Python/Nextflow commands run inside the `nf-core` conda env, which carries
`dash`, `nextflow`, and `nf-test`. Base Python lacks these.

---

## 1. Automated tests (start here)

### 1.1 nanometa_live unit + callback suite

```bash
cd /Users/andreassjodin/Code/nanometa_live

# Full suite (parallel). Expect ~2456 passed, 2 skipped.
conda run -n nf-core python -m pytest -q

# Just the files touched by this change set:
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_validation_status_helpers.py \
  tests/test_dashboard_tab_callbacks.py \
  tests/test_validation_tab_callbacks.py
```

What these assert:

- `test_validation_status_helpers.py` — every diagnostic state (disabled / no
  organisms / missing databases / running-realtime / running-batch / waiting /
  results) returns the right severity and wording.
- `test_dashboard_tab_callbacks.py::TestViewReportModalGuard` — a genuine click
  opens the modal; a re-render does not reopen it; a report-build exception
  still opens the modal with a legible error (no silent 500).
- `test_dashboard_tab_callbacks.py::TestVerdictCountdownRefresh` — while the
  pipeline runs the verdict banner re-renders on a redundant interval tick
  (countdown keeps moving); when idle it still debounces.

### 1.2 Code-size gate

```bash
conda run -n nf-core python scripts/check_code_size.py
# Expect: "OK: no new code-size violations"
```

### 1.3 nanometanf realtime aggregation (nf-test)

```bash
cd /Users/andreassjodin/Code/nanometanf
conda run -n nf-core nf-test test subworkflows/local/validation/tests/main.nf.test
# Expect 3/3 PASSED, including
#   "realtime-mode validation emits validation_results.json from cumulative stats"
```

This is the unit-level proof of fix #1: with `meta.batch_id` set (realtime),
the JSON is emitted from the cumulative-stats path rather than the end-of-run
`.collect()` barrier.

### 1.4 GUI smoke test (no pipeline)

Confirms no callback raises a 500 when the app is wired against real output
files. Drives all eight tabs in a headless browser.

```bash
cd /Users/andreassjodin/Code/nanometa_live
.claude/skills/smoke-test-app/scripts/launch_app.sh --dataset 06_pathogen_detected --port 8051
# wait for the READY line, then drive the tabs / check the network panel
# (see .claude/skills/smoke-test-app), then: kill <PID>
```

Pass criteria: all tabs render, every `/_dash-update-component` POST is 200/204
(zero 500s), zero console errors. Note: in viz-only mode the dashboard shows
ALL CLEAR / STANDBY (no enabled watchlist, no running pipeline), so the
countdown and the pathogen "View Report" button are not exercisable here — they
are covered by the unit tests in 1.1 and by the live run in section 2.

### 1.5 End-to-end validation (opt-in, slow, real data)

This actually runs a small `validation_method=both` job and asserts F.
tularensis (taxid 263) is BLAST-confirmed with a minimap2 result. It is gated
three ways so it never runs by accident (`@pytest.mark.slow`, the SAMMLA paths
must exist, and the opt-in env var must be set).

```bash
cd /Users/andreassjodin/Code/nanometa_live
NANOMETA_RUN_E2E=1 conda run -n nf-core python -m pytest -o addopts="" -m slow -q \
  tests/test_validation_e2e.py
# ~5 min with warm conda envs; SKIPPED if the dataset / DB / nanometanf checkout
# are absent.
```

---

## 2. Manual live test — realtime validation (the headline fix)

This is the test that reproduces the original operator complaint and proves it
is fixed. It uses the real SAMMLA dataset (not in the repo).

### 2.1 Prerequisites (paths on this machine)

| Purpose | Path |
|---------|------|
| Kraken2 DB (NCBI taxonomy) | `~/Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015/` |
| Input barcodes (LVS = F. tularensis 263) | `~/Desktop/SAMMLA-demo/watch/{barcode14,15,16,18}` |
| Data home (pre-staged genomes + BLAST DBs + warm conda) | `~/Desktop/SAMMLA-demo/datadir` |
| Pipeline source (must include this fix) | `/Users/andreassjodin/Code/nanometanf` (now on `dev`) |

The fix lives in nanometanf. Point `pipeline_source` at the **local checkout**
above (already updated) or at `remote:dev` once the branch is fetched. A
`remote:master` source will **not** have the fix.

### 2.2 Stream input like a live sequencer

Realtime mode watches a directory for new files. Use `nanorunner` (from base
miniforge, not the `nf-core` env — its import is broken there) to copy the
barcodes into a fresh `watch2` directory at a realistic cadence:

```bash
~/miniforge3/bin/nanorunner replay \
  -s ~/Desktop/SAMMLA-demo/watch \
  -t ~/Desktop/SAMMLA-demo/watch2 \
  --operation copy --output-structure preserve
```

Start this **after** you start the run (section 2.3) so the pipeline sees files
arrive over time.

### 2.3 Option A — through the GUI (closest to the operator experience)

```bash
cd /Users/andreassjodin/Code/nanometa_live
conda run -n nf-core python -m nanometa_live.app --port 8050
```

In the browser:

1. **Watchlist & Preparation** tab → enable the **CDC Bioterrorism** watchlist
   (includes F. tularensis, taxid 263, which has a pre-staged genome). Without
   an enabled organism, validation is correctly skipped — the new diagnostic
   will say exactly that.
2. **Configuration** tab → set:
   - Processing mode: **realtime**
   - Sample handling: **by_barcode**
   - Nanopore output directory: `~/Desktop/SAMMLA-demo/watch2`
   - Kraken2 database: the pluspfp path above
   - Taxonomy: **ncbi**
   - Validation: **enabled**, method **both**
   - Pipeline source: `/Users/andreassjodin/Code/nanometanf`
   - Data dir / genome cache: `~/Desktop/SAMMLA-demo/datadir`
   - A short `realtime_timeout_minutes` (e.g. 10) so the run ends on its own.
   - Apply Settings.
3. Click **Start Analysis**, then start the `nanorunner replay` from 2.2.

### 2.3 Option B — headless (scriptable, mirrors the GUI)

```python
# run inside: conda run -n nf-core python
from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
from nanometa_live.core.config.parameter_mapping import get_validation_species
from nanometa_live.core.workflow.backend_manager import BackendManager

get_watchlist_manager().enable_watchlist("cdc_bioterrorism")  # taxid 263 etc.

cfg = {
    "nanopore_output_directory": "<home>/Desktop/SAMMLA-demo/watch2",
    "results_output_directory": "/tmp/sammla_rt_results",
    "kraken_db": "<home>/Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015",
    "kraken_taxonomy": "ncbi",
    "processing_mode": "realtime",
    "sample_handling": "by_barcode",
    "pipeline_profile": "conda",
    "pipeline_source": "/Users/andreassjodin/Code/nanometanf",
    "data_dir": "<home>/Desktop/SAMMLA-demo/datadir",
    "genome_cache_dir": "<home>/Desktop/SAMMLA-demo/datadir/genomes",
    "blast_validation": True,
    "validation_method": "both",
    "save_reads_assignment": True,
    "realtime_timeout_minutes": 10,
}
assert "263" in [str(t) for t in get_validation_species(cfg)[0]], "F. tularensis must be a target"

bm = BackendManager(cfg["data_dir"]); bm.config = cfg
print(bm.start(profile="conda"))
# ...then start nanorunner replay in another shell, and poll bm.get_status()
```

### 2.4 What to observe (acceptance criteria)

1. **Validation JSON refreshes during the run** — the key fix. Watch the file:

   ```bash
   watch -n 5 'ls -l /tmp/sammla_rt_results/validation/validation_results.json 2>/dev/null; \
     python -c "import json,sys; d=json.load(open(\"/tmp/sammla_rt_results/validation/validation_results.json\")); \
     print(\"taxids:\", d[\"summary\"][\"total_taxids_validated\"], \"confirmed:\", d[\"summary\"][\"confirmed\"])" 2>/dev/null'
   ```

   Expected: the file appears **within a batch or two** of the first classified
   reads (a minute or two), and its mtime and counts advance over the run — not
   a single write at the 10-minute timeout. (Before the fix it stayed absent
   until the timeout.)

2. **Validation tab populates mid-run** — in the GUI, the Validation tab shows
   F. tularensis (263) as confirmed (BLAST ~97–99%, minimap2 coverage) while the
   run is still going, instead of a blank "Waiting…".

3. **Countdown decrements continuously** — on the Dashboard verdict banner the
   auto-stop countdown ticks down every refresh, including after Kraken2 has
   finished its first batches (when the results fingerprint is no longer
   changing). Before the fix it froze.

4. **View Report opens** — when F. tularensis raises an ACTION REQUIRED alert,
   click **View Report**: the modal opens immediately with the pathogen detail.
   It must open even if you click repeatedly during active refreshes.

5. **Diagnostic is honest when something is missing** — to see the diagnostic,
   start a realtime run with validation enabled but **no** organism enabled, or
   with a watchlist organism that has no genome: the Validation tab states the
   precise reason ("No watchlist organisms enabled…" / "N of M organisms lack a
   reference genome or BLAST database…") rather than a bare wait message.

---

## 3. Manual batch test

The batch path is unchanged by the realtime fix, but it is the simplest way to
confirm BLAST + minimap2 produce results end to end.

1. Same config as 2.3 but **processing mode: batch** and point the input at the
   barcodes directly (`~/Desktop/SAMMLA-demo/watch`); no `nanorunner` needed —
   batch builds a samplesheet and runs to completion.
2. Start Analysis. With warm conda the documented run is ~5 min.
3. On completion the **Validation** tab should show, for barcode14, F.
   tularensis (263): BLAST CONFIRMED (~98.7% / 97.0%) and minimap2 CONFIRMED
   (~98.1% / 99.8%, PAF breadth ~93% on ref NZ_CP009607.1). Negative controls
   read NO_DATA.

---

## 4. Per-fix verification checklist

| Fix | Fastest check | Live check |
|-----|---------------|------------|
| Realtime JSON each batch | nf-test 1.3 + e2e 1.5 | 2.4 step 1–2 (file mtime/counts advance) |
| Countdown unfreeze | unit `TestVerdictCountdownRefresh` (1.1) | 2.4 step 3 |
| View Report opens | unit `TestViewReportModalGuard` (1.1) | 2.4 step 4 |
| Validation diagnostic | `test_validation_status_helpers.py` (1.1) | 2.4 step 5 |

---

## 5. Troubleshooting

- **Validation still empty in realtime.** Confirm `pipeline_source` points at a
  nanometanf checkout/branch that has the fix (the local `dev` checkout does).
  Confirm an organism is enabled and has a genome — the Validation tab
  diagnostic now tells you which precondition is missing.
- **Headless run skips validation silently.** A fresh process has an empty
  `WatchlistManager` singleton; call
  `get_watchlist_manager().enable_watchlist("cdc_bioterrorism")` and verify
  `get_validation_species(cfg)` is non-empty before `bm.start`.
- **`nanorunner` import error.** Run it from base miniforge
  (`~/miniforge3/bin/nanorunner`), not the `nf-core` env.
- **Many AGGREGATE_VALIDATION_LIVE process runs in the trace.** Expected — one
  lightweight run per `validation_aggregate_interval` cumulative updates
  (default 1). Raise the interval to reduce executions on large watchlists; each
  run still rebuilds the complete JSON.
- **Tests can't import `dash`.** Use the `nf-core` env
  (`conda run -n nf-core …`); base Python does not have the runtime stack.
```
