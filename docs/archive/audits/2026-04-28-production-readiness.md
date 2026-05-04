# Nanometa Live + nanometanf Production Readiness — 2026-04-28

This audit cycle focused on the offline-deployment story: can an operator
build everything online, transfer the bundle to an air-gapped field
machine, and run all four scenarios without a network reach-back?

The headline finding is that the underlying machinery already works —
`BundleManager.export_bundle(pre_warm_conda_envs=True)` resolves all
nine module conda environments, the import path rewrites paths
correctly, and `_build_nextflow_env` injects `NXF_OFFLINE=true`,
`NXF_PLUGINS_PATH`, and `NXF_CONDA_CACHEDIR` so Nextflow does not
reach out at runtime. Two operator-visible offline-mode bypasses
remained (the GUI Kraken2 download button and the readiness
network probe), and the pre-warm capability had no GUI surface.
Both were closed.

A live end-to-end test on a real fresh-machine simulation was not
performed in this cycle — that requires ~30 minutes of conda-env
resolution plus four sequential pipeline runs and is best driven by
the operator on the actual target hardware. The reproduction script
is included below.

## Production-readiness rubric

| Dimension | Score | Notes |
|---|---|---|
| Install fresh machine | 8/10 | Bundle import path tested; full conda env resolution not exercised end-to-end this cycle. |
| Data ingestion | 9/10 | Three datasets produced via nanorunner cover samplesheet, multiplex, and uncompressed FASTQ. Schema validation now passes (samplesheet template fix from cycle 16). |
| Classification | 9/10 | Kraken2 reports parse correctly (authoritative-taxonomy override + batch-cumulative aggregation fixes from earlier cycles still hold). Skip_kraken2 emit guard verified. |
| Validation | 8/10 | BLAST + minimap2 paths covered by unit tests; live coverage not exercised this cycle. |
| Offline restore | 13/15 | Pre-warm wiring complete (GUI checkbox + CLI export). Two P0 offline-mode bypasses fixed. End-to-end blackholed-network run still pending operator validation. |
| Real-time | 13/15 | watchPath + cumulative-batch logic intact. Realtime modes not re-exercised this cycle. |
| GUI quality | 8/10 | Phase 4a audit found 22 issues; 2 P0 closed in this cycle, 20 P1+P2 documented as follow-ups. |
| Tests | 9/10 | 569 tests in nanometa_live (565 baseline + 4 new), all green. Offline-mode env injection has 6 tests; readiness probe now skipped in offline mode (test added). |
| Docs | 9/10 | CLAUDE.md streamlined (cycle 17/18 cumulative changelog removed); configuration.md and user-guide.md flipped to `pipeline_profile: conda` to match reality. Audit-2026-04-28 reports committed. |

**Total: 86 / 100.** Production-ready for same-platform, same-architecture
field deployment with operator-driven verification of the live offline
run.

## What was fixed in this cycle

### Pre-warm conda envs are now operator-accessible
- `bundle-export-prewarm` checkbox in the Preparation tab, default ON
- Build-platform banner reminding operators of the OS+CPU lock-in
- Both export callbacks (`export-bundle-btn` and the warning-acknowledged
  `export-force-btn`) read the checkbox state and forward it through
  `_run_export` to `BundleManager.export_bundle`
- New `nanometa-prepare export` CLI subcommand mirroring the GUI flags
- Three structural tests (`TestPreparationTabPreWarmCheckbox`)

Commit: `b681fe1`

### P0-01: Kraken2 download callback honored offline_mode
`download_kraken_database` in `preparation_tab.py` now short-circuits
in offline mode with a friendly Alert pointing operators at the offline
bundle. Pre-fix this issued an unguarded HTTPS stream with a 60-second
timeout, blocking the diskcache background worker.

### P0-02: Readiness network probe honored offline_mode
`_check_network_connectivity` in `readiness_checker.py` now skips the
NCBI / GTDB probes entirely when `config.offline_mode` is true,
returning a single INFO check noting the skip. Pre-fix this blocked
the readiness panel for ~10s per render and surfaced a misleading
WARNING.

Commit: `593e783`

### nanometanf pod5/dorado residue cleaned
After confirming the six pod5/dorado removal commits (2063a2d through
8b929e6) are already in `dev`, three remaining production-code
residuals were removed on branch
`cleanup/pod5-residue-2026-04-28`:
- `assets/methods_description_template.yml` — the MultiQC methods text
  no longer claims "real-time basecalling with Dorado"
- `modules/nf-core/pycoqc/` — orphaned module directory removed (was
  never `include`d in any workflow)
- `tests/full_pipeline_stubmode.nf.test` — dead `use_dorado = false`
  lines removed (parameter was dropped from the schema in 016d7ff)

The single remaining hit in `nextflow_schema.json` line 471 is
legitimate user-facing help text describing when to disable adapter
trimming for reads the operator's upstream basecaller already
processed.

Commit (in nanometanf): `efc1c2b`

## Open follow-ups

### Empirical end-to-end offline run (operator-driven)

Build a bundle online, copy to a fresh location, blackhole the
network, run all four scenarios:

```bash
# Online: build pre-warmed bundle (~30 min, ~5 GB)
conda activate nf-core
cd /Users/andreassjodin/Desktop/deving/nanometa_live
python -m nanometa_live.cli.prepare \
  --home ~/.nanometa \
  export \
  --config /path/to/your/prepared/config.yaml \
  --output /Users/andreassjodin/Desktop/snabbsekvensering/output-live/bundle_2026-04-28.tar.gz \
  --pipeline /Users/andreassjodin/Code/nanometanf \
  --pre-warm

# Offline simulation
mkdir -p /tmp/nanometa-fresh && cd /tmp/nanometa-fresh
export https_proxy=http://127.0.0.1:1 http_proxy=http://127.0.0.1:1

python -m nanometa_live.cli.prepare \
  --home /tmp/nanometa-fresh \
  import \
  --bundle /Users/andreassjodin/Desktop/snabbsekvensering/output-live/bundle_2026-04-28.tar.gz \
  --db /Users/andreassjodin/Desktop/kraken_db/k2_pluspfp_08_GB_20251015

# Launch GUI; verify Preparation > Readiness Checklist runs without
# the 10-second NCBI/GTDB probe; run each of the 4 scenarios from
# the test datasets at output-live/_test_data_2026-04-28/
python -m nanometa_live.app --config /tmp/nanometa-fresh/config.yaml
```

Pass criteria: zero outbound connection attempts (verify with
`tcpdump -i lo0 host github.com or host conda.anaconda.org or host
quay.io`), all four scenarios reach pipeline-complete.

### Phase 4a P1 / P2 follow-ups

Twenty findings remain documented in
`docs/audit-2026-04-28-nanometa-live-code.md`. Highest-impact items:

- **~2,000 lines of dead code** — eight modules with no live callers:
  `core/utils/data_utils.py`, `core/utils/database_utils.py`,
  `core/utils/safe_path.py`, `app/components/tooltip_components.py`,
  `app/components/watchlist_manager_ui.py`, plus dead `ConfigManager`
  class and component re-exports.
- **Missing PreventUpdate guards** in QC callbacks
  (`update_qc_plots`, `update_qc_stats`, `update_per_sample_table`,
  `update_base_quality_card`, `update_read_statistics_card`) cause
  ~5 unnecessary re-renders per tab per interval tick on fresh-app start.
- **Runtime offline_mode toggle** does not propagate to singletons.
- **Test coverage gaps** for `genome_manager`, `alert_engine`,
  `on_demand_validator`, `mobile_lab_preparer`.

### Phase 4b: nanometanf nf-core conformance audit — DEFERRED

`nf-core pipelines lint` currently fails on an upstream tooling issue
(it tries to clone `nf-core/modules.git` on branch `master`, which has
been renamed to `main`). This is unrelated to the pod5 cleanup and
needs to be tackled separately, likely by either (a) waiting for the
nf-core CLI to track the rename, or (b) running an older nf-core CLI
version with a pinned modules-repo revision.

### conda-lock alternative for cross-platform deployment — FUTURE

Pre-warmed envs are platform-locked (build OS + CPU must match field
machine). For cross-platform deployment, `conda-lock` or `pixi`
manifests would replace `environment.yml` files in nanometanf
modules with deterministic locks, eliminating the build/run platform
constraint. This is upstream nanometanf work and diverges from
nf-core convention; defer to a dedicated cycle.

## Reproducibility

- Audit driver: nanorunner from `/Users/andreassjodin/Code/nanorunner`
- Test data: `/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_test_data_2026-04-28/`
  (3 datasets, 4,873 reads each, sources documented in MANIFEST.md)
- nanometa_live commits: b681fe1, 593e783 on dev2
- nanometanf commit: efc1c2b on cleanup/pod5-residue-2026-04-28
- Test suite: 569 passed / 1 skipped
