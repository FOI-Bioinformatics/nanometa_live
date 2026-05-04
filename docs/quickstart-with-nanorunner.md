# Quick start: Nanometa Live with nanorunner

A minimal end-to-end walkthrough that drives Nanometa Live with simulated
input from
[nanorunner](https://github.com/FOI-Bioinformatics/nanorunner). Two
terminals, two conda environments. No real sequencer required.

## Prerequisites

- Conda or Miniconda
- A Kraken2 database (any small reference database works for testing)
- Roughly 5 GB of free disk space for the demo work directory

## Installation

This walkthrough uses two conda environments:

- `nanorunner` -- the simulator
- `nf-core` -- the host environment for Nanometa Live and nanometanf
  (Nextflow, nf-core, nf-test, and the Python frontend)

```bash
# nanorunner
conda create -n nanorunner python=3.10 -c conda-forge ncbi-datasets-cli psutil
conda activate nanorunner
pip install git+https://github.com/FOI-Bioinformatics/nanorunner.git@v3.0.0

# Nanometa Live (and Nextflow, used by the nanometanf backend)
conda create -n nf-core -c bioconda -c conda-forge nextflow nf-core nf-test python=3.10
conda activate nf-core
pip install git+https://github.com/FOI-Bioinformatics/nanometa_live.git
```

If you have local clones, replace the `pip install ...` lines with
`pip install -e /path/to/clone`.

## 1. Choose a working directory

```bash
DEMO=/tmp/nanometa_demo
mkdir -p "$DEMO/watch" "$DEMO/results"
```

`$DEMO/watch` is the directory the simulator writes into. The pipeline
watches the same directory.

## 2. Write a configuration file

```yaml
# /tmp/nanometa_demo/config.yaml

nanopore_output_directory: "/tmp/nanometa_demo/watch"
results_output_directory: "/tmp/nanometa_demo/results"
kraken_db: "/path/to/kraken2_database"

processing_mode: "realtime"
sample_handling: "single_sample"   # use "by_barcode" if generating multiplex output
pipeline_profile: "conda"

update_interval_seconds: 10
```

Replace `kraken_db` with the absolute path to your Kraken2 database (the
directory containing `hash.k2d`, `opts.k2d`, `taxo.k2d`).

## 3. Terminal A -- launch the dashboard

```bash
conda activate nf-core
nanometa-live --config /tmp/nanometa_demo/config.yaml --port 8050
```

Open <http://localhost:8050>. In the **Configuration** tab, click
**Start Pipeline**. nanometanf starts in real-time mode and begins
watching `$DEMO/watch`.

## 4. Terminal B -- feed reads with nanorunner

Pick one of the following.

### Option A: synthetic reads from a mock community

This requires no genome files; nanorunner downloads them on first use.

```bash
conda activate nanorunner

nanorunner generate --mock quick_3species \
    --target /tmp/nanometa_demo/watch \
    --interval 10 \
    --read-count 2000 \
    --reads-per-file 200 \
    --force-structure singleplex
```

`quick_3species` is a small three-species mock chosen for fast tests.
Replace with `zymo_d6300`, `eskape`, etc. for richer communities --
see `nanorunner list-mocks`.

### Option B: replay existing FASTQ files

```bash
conda activate nanorunner

nanorunner replay \
    --source /path/to/existing/fastq \
    --target /tmp/nanometa_demo/watch \
    --interval 10 \
    --timing-model uniform
```

`--interval 10` releases one batch every ten seconds. Increase the
interval if the pipeline cannot keep up; decrease it to stress-test
throughput.

For multiplexed input, organise the source as
`barcode01/`, `barcode02/`, ... and set `sample_handling: by_barcode`
in the config.

## 5. Observe the dashboard

The Dashboard tab should begin populating within a minute:

- **Sequences Analyzed** climbs in the supporting-data strip.
- **Organisms** tab fills in as Kraken2 reports are written.
- **Quality Control** tab shows per-sample chopper statistics.
- **Validation** tab activates once a watched pathogen exceeds its
  read threshold (configurable per pathogen).

If the dashboard remains in **STANDBY**, check Terminal A for
nanometanf errors. The most common causes on a first run are:

- An incorrect `kraken_db` path (must point to the directory holding the
  `.k2d` files).
- The conda environment for a pipeline process taking time to resolve.
  The first run may pause for several minutes while environments are
  built; subsequent runs reuse the cache.

## 6. Stop cleanly

- Ctrl+C in Terminal B for nanorunner. The simulator performs a
  graceful shutdown and prints a summary.
- Click **Stop Pipeline** in the Configuration tab, then Ctrl+C
  Terminal A.

## Visualisation only (no pipeline run)

To inspect an existing results directory without launching the
pipeline, skip nanorunner entirely:

```bash
conda activate nf-core
nanometa-live --main_dir /path/to/existing/nanometanf/results --port 8050
```

This loads whatever Kraken2 reports and QC files are already on disk
and renders them, without orchestrating any analysis.

## Where to go next

- [User guide](user-guide.md) -- full operator reference
- [Configuration reference](configuration.md) -- every option
- [Operator guide](OPERATOR_GUIDE.md) -- field-deployment workflow
- [nanorunner README](https://github.com/FOI-Bioinformatics/nanorunner#readme) --
  full simulator reference, including timing models, parallel processing,
  and species / mock community generation
