# Local / server test guide (pre-release)

A hands-on checklist for exercising the **dev** branch of Nanometa Live on a
server before a release. It drives the real `nanometanf` pipeline under conda,
with simulated reads from
[nanorunner](https://github.com/FOI-Bioinformatics/nanorunner), and covers both
processing modes (batch and real-time). No sequencer required.

This complements the lighter
[Quick start with nanorunner](quickstart-with-nanorunner.md); use this guide
when the goal is release validation rather than a first look.

> Modest by design: a small mock community plus a real Kraken2 database is
> enough to confirm the whole chain (QC -> classification -> validation ->
> dashboard). Biological realism is not the point; wiring and stability are.

---

## 1. Prerequisites

Two conda environments and a few inputs.

```bash
# Environments (see quickstart-with-nanorunner.md for first-time creation):
conda env list      # expect: nanorunner, nf-core

# nf-core hosts BOTH the Nextflow backend (with a bundled JVM) and the Dash
# frontend. Confirm the toolchain resolves inside it:
conda run -n nf-core nextflow -version    # expect 26.04.0+
conda run -n nf-core python -c "import dash; print(dash.__version__)"   # 4.x
```

Set the inputs as shell variables (adjust to your server):

```bash
# A real Kraken2 database directory (must contain hash.k2d, opts.k2d, taxo.k2d).
# A small DB loads faster; an 8 GB pluspfp-class DB classifies common pathogens.
export KRAKEN_DB=/path/to/kraken2_db

# Pipeline source: a local nanometanf checkout (fastest for dev testing) or a
# remote branch. Local avoids a git fetch and lets you test pipeline changes.
export PIPELINE_SRC=$HOME/Code/nanometanf      # or: remote:dev

# A scratch PROJECT directory for this test session. Per-run results land in
# <PROJECT>/results/<run name>/ and project state in <PROJECT>/.nanometa/.
export PROJECT=/tmp/nm_test
mkdir -p "$PROJECT"

# Reuse an existing conda cache so the pipeline does not rebuild every tool
# environment on the first run. Point at a directory that already holds
# env-<hash>/ dirs (e.g. a previous nanometanf run), or omit to build fresh.
export NXF_CONDA_CACHEDIR=$HOME/Code/nanometanf/work/conda   # optional
```

`KRAKEN_DB` not on hand? Any small Kraken2 DB works. The stub DB under
`nanometanf/tests/fixtures/kraken2_db` is **not** usable for a real run (it is a
placeholder for unit tests).

---

## 2. Generate simulated reads (nanorunner)

`nanorunner generate` pulls reference genomes for a named mock community and
simulates nanopore reads from them. The output is one barcode subdirectory per
species, i.e. a `by_barcode` layout.

```bash
# ~2000 reads across 5 nosocomial pathogens (fast, meaningful):
conda run -n nanorunner nanorunner generate \
  --mock quick_pathogens \
  --target "$PROJECT/input_batch" \
  --read-count 2000 \
  --output-format fastq.gz

# Inspect:
find "$PROJECT/input_batch" -maxdepth 1 -type d | sort   # barcode01 .. barcode05
```

Other mock communities (`conda run -n nanorunner nanorunner list-mocks`):
`quick_3species` (smallest/fastest), `eskape`, `respiratory`, `zymo_d6300`,
`who_critical`. First use downloads genomes from NCBI (network required); they
are cached under `~/.nanorunner/genomes/`.

For a **flat single-sample** input instead of barcodes, generate to a temp dir
and flatten, or stream with `--output-structure flat` (see real-time below).

---

## 3. Launch the app (full / pipeline mode)

Run inside `nf-core` (it provides Nextflow + JVM + Dash). The `--project` flag
sets where this session's results and state live; `--data-dir` is the shared
global cache (genomes, taxonomy cache, downloaded DBs).

```bash
cd "$PROJECT"      # cwd defaults the project dir; --project makes it explicit
conda run --no-capture-output -n nf-core \
  python -m nanometa_live.app \
    --project "$PROJECT" \
    --data-dir "$HOME/.nanometa" \
    --port 8050
# (equivalent console entry point: `nanometa-live --project ... --port 8050`)
```

Open `http://<server>:8050` (use an SSH tunnel for a remote server:
`ssh -L 8050:localhost:8050 user@server`). On boot the app is intentionally
fresh: no auto-resume, no results loaded.

`--config <file>` pre-fills settings instead of clicking through the form; a
minimal config is shown in [Appendix A](#appendix-a-minimal-configyaml).

---

## Scenario A -- Batch

1. **Configuration tab**
   - Run name: `batch_run` (this becomes the results folder
     `<PROJECT>/results/batch_run/`).
   - Nanopore Sequence Data Folder: `<PROJECT>/input_batch`.
   - Species Identification Database: `$KRAKEN_DB`.
   - Processing Mode: **Batch**; Sample Handling: **by_barcode**.
   - How tools are run: **Conda**.
   - Advanced -> Pipeline Source -> Local Path: `$PIPELINE_SRC`
     (or leave Remote with branch `dev`).
   - Confirmation Testing: **on** (or off for a faster classification-only pass).
   - Leave "Results folder" empty so it derives `results/<run name>`.
   - Click **Apply Settings**. Expect a "Viewing: .../results/batch_run" line.

2. **Watchlist & Preparation tab** -- click a built-in list that covers the mock
   species (e.g. **Clinical Pathogens**). Confirm the active count is non-zero.

3. **Same tab (Prepare for Analysis section)** -- click **Start Preparation**. This builds the DB
   taxonomy index + taxid mappings, downloads the watched species' reference
   genomes, and builds validation indexes. Wait for "Preparation complete";
   the readiness badge should turn **Ready** and Start should enable.

4. Click **Start Analysis** (header). Expect: no collision (fresh folder), the
   verdict banner flips to SCREENING within ~30 s, the status poller advances
   through pipeline stages, then the run completes.

**Verify (batch):**

```bash
# Backend: outputs present
find "$PROJECT/results/batch_run" -maxdepth 1 -type d | sort
#   expect: kraken2/ chopper(or fastp/seqkit)/ taxpasta/ validation/ pipeline_info/
ls "$PROJECT/results/batch_run/validation/validation_results.json"
tail -3 ~/.nanometa/logs/nextflow.log     # "Pipeline completed successfully"
```

- **Frontend:** Dashboard shows status **Complete**, a verdict (ACTION REQUIRED
  when watched pathogens are detected), Sequences Analyzed > 0, Species
  Detected > 0. Organisms lists the mock pathogens; Taxonomy renders the
  Sankey/Sunburst; Validation shows confirmation results (if enabled).
- Browser console: zero errors; no `/_dash-update-component` 500s.

---

## Scenario B -- Real-time

Real-time mode watches a directory and processes files as they arrive. Start
the run against an (initially empty) watch directory, then stream reads in.

1. Prepare an empty watch directory with the expected barcode structure:

   ```bash
   rm -rf "$PROJECT/input_rt"
   mkdir -p "$PROJECT/input_rt"/barcode0{1,2,3,4,5}
   ```

2. **Configuration tab** -- change Run name to `realtime_run`, Processing Mode
   to **Realtime**, Nanopore folder to `<PROJECT>/input_rt`, and set a
   **Realtime Timeout** (e.g. 5 minutes) so the run ends on its own. **Apply**.
   (The watchlist and Preparation artifacts from Scenario A are reused.)

3. Click **Start Analysis**. The pipeline begins watching `input_rt`.

4. In a second terminal, stream the previously generated reads in, one file
   every 12 s:

   ```bash
   conda run -n nanorunner nanorunner replay \
     --source "$PROJECT/input_batch" \
     --target "$PROJECT/input_rt" \
     --interval 12 --batch-size 1 \
     --operation copy --output-structure preserve
   ```

**Verify (real-time):**

```bash
# Reports accumulate batch-by-batch as files arrive:
watch -n 10 'ls "$PROJECT"/results/realtime_run/kraken2/**/*report* 2>/dev/null | wc -l'
ls "$PROJECT/results/realtime_run/"     # incl. realtime_reports/ realtime_stats/
```

- **Frontend:** the Dashboard "Sequences Analyzed" grows across successive
  polls; Organisms/Taxonomy update incrementally. The run stops cleanly on the
  timeout (or use **Stop Analysis**), leaving results in
  `<PROJECT>/results/realtime_run/`.

---

## 4. Variations worth covering before a release

- **Sample handling:** repeat batch with `single_sample` (flat input: generate
  to one dir or `nanorunner replay --output-structure flat`) and `per_file`.
- **Validation off vs on:** confirm a classification-only run is faster and the
  Validation tab shows an empty state; then on, with confirmations.
- **Named runs / re-runs:** after a run, change the Run name and Apply -- the
  next run must write to a new `results/<new name>/` folder (the old one is
  preserved). Reusing a name should trigger the archive/resume collision modal.
- **Open Results:** use the secondary-bar "Open Results" picker to switch
  between `batch_run` and `realtime_run` and confirm each loads.
- **Offline mode:** toggle Offline in the header; confirm the OFFLINE badge and
  that taxonomy/genome lookups stop hitting the network.
- **Stop / restart:** stop a run mid-flight and confirm the app returns to a
  clean non-running state.

---

## 5. Troubleshooting (environmental vs app bugs)

Distinguish environment problems from regressions: an app bug is an HTTP 500 on
`/_dash-update-component` or a Python traceback in the app log; the items below
are environmental.

- **`Unable to locate a Java Runtime`** when Nextflow starts -- run the app
  inside `nf-core` (its activation sets `JAVA_HOME` to the bundled JVM). The
  app inherits the launching shell's environment.
- **First run is slow / "Creating env using conda"** -- expected when the conda
  cache misses. Set `NXF_CONDA_CACHEDIR` (section 1) to reuse prebuilt envs.
- **Readiness shows "NCBI API unreachable" / "GTDB ... SSL"** -- these probe a
  REST endpoint; genome downloads via the `datasets` CLI can still succeed.
  Treat as a warning unless Preparation reports 0 genomes downloaded.
- **Start stays disabled** -- the DB Taxonomy Index / Taxid Mappings checks are
  CRITICAL; run **Start Preparation** (with a watchlist enabled) to build them.
- **ARM (Apple Silicon) servers:** the pipeline auto-disables Kraken2
  memory-mapping to avoid a known SIGSEGV; this is logged, not an error.

App log: `~/.nanometa/logs/nextflow.log` and the launch terminal. Per-run
Nextflow detail: `<PROJECT>/results/<run>/pipeline_info/`.

---

## 6. Cleanup

```bash
# Stop the app and any streamer:
pkill -f "nanometa_live.app"; pkill -f "nanorunner replay"
# Free the scratch (results + project state); keep ~/.nanometa/genomes to reuse:
rm -rf "$PROJECT" ~/.nanometa/work
```

---

## Appendix A: minimal config.yaml

Pass with `--config config.yaml` to skip the Configuration form. The watchlist
and Preparation steps (Scenario A, steps 2-3) are still required for validation.

```yaml
analysis_name: batch_run            # becomes results/<run name>
nanopore_output_directory: /tmp/nm_test/input_batch
results_output_directory: ""        # empty = derive results/<run name>
kraken_db: /path/to/kraken2_db
processing_mode: batch              # or: realtime
sample_handling: by_barcode         # or: single_sample, per_file
pipeline_profile: conda
pipeline_source: /home/you/Code/nanometanf   # or: remote:dev
blast_validation: true
validation_method: minimap2
kraken_memory_mapping: true
project_dir: /tmp/nm_test
realtime_timeout_minutes: 5         # realtime only
update_interval_seconds: 10
```
