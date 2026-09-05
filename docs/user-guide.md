# Nanometa Live user guide

## Overview

Nanometa Live is a real-time visualisation dashboard for Oxford Nanopore metagenomic sequencing. It displays taxonomic classification results, quality metrics, and interactive visualisations as a sequencing run progresses.

## Installation

### Prerequisites

- Python 3.11 or higher
- Conda or Mamba (the canonical and supported pipeline profile)
- Nextflow 26.04.0 or newer (the version nanometanf floors at)
- A Kraken2 database
- The nanometanf release named in the README compatibility table

### Install with pip

```bash
# Create virtual environment
python -m venv nanometa_env
source nanometa_env/bin/activate

# Install
pip install nanometa-live
```

### Install with conda

```bash
conda create -n nanometa "python>=3.11"
conda activate nanometa
pip install nanometa-live
```

### Install from source

```bash
git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
pip install -e .
```

### Network exposure

The dashboard listens on `127.0.0.1` and is reachable only from the machine
it runs on. It has no user accounts or authentication. Starting it with
`--host 0.0.0.0` makes it reachable from the network, and anyone who can
reach the port can start and stop runs, change the configuration and read
results; the application prints a warning when a non-loopback host is
chosen. For a shared laboratory server, place an authenticating reverse
proxy (for example nginx with client certificates or basic authentication)
in front of it and keep the application itself on loopback.

## Quick start

### View existing results

If you already have nanometanf pipeline output:

```bash
nanometa-live --main_dir /path/to/results
```

Open http://localhost:8050 in your browser.

### Run new analysis

To analyse new sequencing data:

```bash
nanometa-live --config my_config.yaml
```

## Input data

### Supported input formats

| Format | Description | Example |
|--------|-------------|---------|
| Barcoded directories | Each barcode in subdirectory | `barcode01/`, `barcode02/` |
| Flat FASTQ | All files in one directory | `*.fastq.gz` |
| nanometanf output | Pre-analyzed results | `kraken2/`, `fastp/` subdirs |

### Barcoded data structure

```
input_directory/
├── barcode01/
│   ├── reads_001.fastq.gz
│   └── reads_002.fastq.gz
├── barcode02/
│   └── reads_001.fastq.gz
└── unclassified/
    └── reads.fastq.gz
```

### Flat directory structure

```
input_directory/
├── sample_001.fastq.gz
├── sample_002.fastq.gz
└── sample_003.fastq.gz
```

## Dashboard tabs

### Dashboard tab

Operator-facing summary view. Four zones, top to bottom:

- **Zone 1 — Clinical verdict banner**. A full-width card whose background color is the answer: green "ALL CLEAR", red "ACTION REQUIRED", amber "MONITORING", blue "SCREENING IN PROGRESS", grey "STANDBY". Shows run state, elapsed time, last-updated timestamp, and (when applicable) a "pending confirmatory validation" qualifier.
- **Zone 2 — Pathogen alert cards** (shown only when alerts exist). Each alert card names the detected organism, read count and abundance, confidence level, and a "DETECTED IN:" row with per-sample chips indicating which samples the pathogen was found in. Chips are colored by severity tier. Samples marked as negative controls appear as flat gray chips with an `(NC)` suffix.
- **Zone 3 — Supporting metrics** (four cards): Sequences Analyzed, Sample Quality (Excellent / Good / Fair / Poor with Q-score subtitle), Species Detected, Run Time.
- **Zone 4 — Sample Details** (collapsed accordion). Per-sample table with plain-language column names: "Sequences Analyzed", "Sample Quality", "Read Length", "Match Rate".

### Organisms tab

Detected organisms and classification results:

- **Organism cards**: each detected organism with abundance bars and confidence badges
- **Summary card**: total organisms, DNA sequences (cumulative across all batches), classification rate
- **Watchlist matches**: organisms matching active watchlist entries are highlighted
- **On-demand validation**: validate unexpected organisms with BLAST
- **Rank filter**: Species, Subspecies, Genus, Family. Subspecies is off by
  default -- see [Subspecies and strains](#subspecies-and-strains)

### Quality Control tab

Quality control metrics:

- **Stage Strip** at top: horizontal `Raw → Quality-filtered → Classified` with counts, tool subtitles, arrows, and a classification-rate delta beneath. For Chopper pipelines the Raw slot shows a dashed "Not available" placeholder because Chopper has no pre-filter stage.
- **Read Quality** card: Avg Q, Q20, Q30, GC with color-coded thresholds (Q30 green ≥45%, amber 25–44%, red <25%)
- **Read Length** card: N50, average length, total bases
- **Sample Breakdown** table: per-sample filtered reads, classification rate, and average Q score with tool-source tooltips
- **Advanced** sections (accordion): detailed processing charts and technical statistics

### Taxonomy tab

Interactive taxonomic visualizations:
- **Sankey Diagram**: Flow visualization of taxonomic hierarchy
- **Sunburst Chart**: Radial hierarchical view
- Filters for minimum reads, domains, and taxonomy levels
- **Subspecies / strain** is available as a level, and as the "Subspecies
  Focus" preset -- see [Subspecies and strains](#subspecies-and-strains)

### Validation tab

Organism identity verification:
- **BLAST Sub-tab**: Read-centric validation with identity scores, filtering, and statistics
- **Coverage Sub-tab**: Genome-centric minimap2 coverage plots (depth, cumulative, histogram)
- Species selector and mapping quality filters

### Watchlist & Preparation tab

Pathogen monitoring management (watchlist selection and pre-run preparation are
combined in this single tab):
- Browse and activate the 9 built-in watchlists (clinical_pathogens, cdc_bioterrorism, who_priority, foodborne, respiratory, who_drinking_water, nosocomial_eskape, wastewater_surveillance, zoonotic_one_health)
- Upload custom watchlist YAML files
- Toggle individual pathogen entries on/off
- Kraken2 taxid mapping for database compatibility

### Configuration tab

Analysis settings:
- Input/output directories
- Kraken2 database selection
- Processing mode (batch/real-time)
- Start/stop analysis controls

### Preparation (part of the Watchlist & Preparation tab)

Pre-run setup, in the lower section of the Watchlist & Preparation tab:
- Reference genome downloads for watchlist pathogens
- BLAST database preparation
- Genome management status

### Reports tab

Run-level HTML artifacts, each openable in any browser:
- **Run Report** — the operator summary (verdict, pathogen screening with
  per-organism action guidance, validation, QC), written automatically to
  `<results directory>/report/report.html` when a run completes or is
  stopped (disable with `auto_report: false`)
- MultiQC report, Nextflow execution report / timeline / trace

## Run report after closing the app

The Run Report is fully self-contained (no server or network needed), so the
run's verdict remains viewable after Nanometa Live is closed: open
`<results directory>/report/report.html` directly, or copy that single file
anywhere.

To (re)generate a report later without launching the dashboard:

```bash
nanometa-report --results /path/to/results
```

By default the pathogen screen uses the watchlists recorded by the run in
`.nanometa.run.json`; override with `--watchlist <ids>` or force an
unscreened report with `--watchlist none`. The Dashboard's Export Results
button produces the same report to a directory of your choice, optionally
bundling raw result files.

## Subspecies and strains

Some Kraken2 databases resolve below species. A flextaxd field build, for
example, splits *Francisella tularensis* into four subspecies:

| Rank | Organism | Reads |
|------|----------|-------|
| S  | *Francisella tularensis* | 9,602 |
| S1 | *F. t.* holarctica | 6,184 |
| S1 | *F. t.* novicida | 6 |
| S1 | *F. t.* tularensis | 4 |
| S1 | *F. t.* mediasiatica | 2 |

The distinction can matter clinically -- subspecies *tularensis* (Type A) is
markedly more virulent than *holarctica* (Type B), which is the lineage the
LVS vaccine strain derives from.

### Where subspecies appear

| Where | How to see them |
|-------|-----------------|
| Dashboard verdict and alerts | Automatic, if a watchlist entry names the subspecies |
| Organisms tab | Tick **Subspecies** in the rank filter, then Apply Filters |
| Taxonomy tab | Add **Subspecies / strain** to the levels, or pick the **Subspecies Focus** preset |
| Exported report | Automatic -- a separate "Subspecies and strains" table per sample |

### Why they are off by default

A species row's read count **already includes its subspecies**. In the table
above, 9,602 is not 9,602 *plus* the four rows beneath it: 3,406 reads were
assigned at species level and 6,196 to the subspecies, and 3,406 + 6,196 =
9,602.

So switching subspecies on does not add organisms to a list -- it splits rows
that are already there. In the Sankey that is exactly right, and you see the
flow divide. In a flat list it is easy to misread as two separate findings,
which is why you have to ask for it.

For the same reason the exported report keeps subspecies in their **own**
table rather than mixing them into the organism ranking. Ranking a species
against its own children invites adding percentages that already contain each
other.

### Watching a subspecies

Add the subspecies to a watchlist by name (`Francisella tularensis
tularensis`) or by its taxid in the database. It is then screened like any
other entry and can raise the verdict banner on its own.

Set its `alert_threshold` deliberately. Subspecies counts are a subset of the
species count and are often much smaller -- Type A above has 4 reads where the
species has 9,602 -- so a threshold copied from the parent species may never
trigger.

## Processing modes

### Batch mode

Processes all existing FASTQ files once:

1. Set Processing Mode to "Batch"
2. Select your input directory
3. Click "Start Analysis"
4. Results appear after pipeline completes

Best for: Completed sequencing runs, re-analysis

### Real-time mode

Continuously monitors for new files:

1. Set Processing Mode to "Real-time"
2. Point to your sequencing output directory
3. Click "Start Analysis"
4. Results update as new data arrives

Best for: Active sequencing runs, live monitoring

## Sample handling

### By barcode

Use when your data is in barcode subdirectories:
- Automatically detects `barcode01/`, `barcode02/`, etc.
- Each subdirectory becomes a separate sample
- Use sample selector to view individual barcodes

### Single sample

Use when all files belong to one sample:
- All FASTQ files merged for analysis
- Enter a sample name in the configuration
- Good for non-multiplexed runs

### Per file

Use when each file is a separate sample:
- Sample names derived from filenames
- Each file processed independently
- Useful for plate-based experiments

## Assembly

Assembly is optional and off by default. Switch it on in Configuration under
Processing Settings, and choose what to assemble: the whole sample, a detected
watchlist organism, or both.

In a live run you do not have to pick a moment to assemble. The sample's reads
accumulate and the assembly is re-attempted as they grow, with a final attempt
when the session ends, so it happens once there is enough sequence to be worth
it.

**What you will usually see is a decline, and that is the feature working.**
Assembling a genome needs deep sequencing of that organism — roughly 30 times
its length. A metagenomic sample spreads its reads across everything present,
so a single organism often reaches a small fraction of that. Rather than
publish contigs that would look like a genome, the run measures what is
available and reports it:

> barcode06, taxid 4007169 — insufficient depth
> 0.43 Mb assigned; 0.23x of a 1.87 Mb reference. 30x is needed for a usable
> draft, about 56 Mb more.

The bar beside each target shows how far along you are. If the organism
matters, keep sequencing: the figure tells you how much more is needed.

The Reports tab distinguishes five states, so an empty panel never means
"something went wrong silently":

| What you see | What it means |
|---|---|
| Assembly not enabled | The switch is off |
| Not enough sequence to assemble | Measured and declined, with the reason per target |
| Assembly is enabled; no results yet | Running |
| Assembly failed | A task died; the run continued without it |
| Contig statistics | An assembly was produced |

When contigs are produced, read the **median depth** tile first. Below about
10x the panel says outright that the contigs are fragments rather than a
genome, whatever the contig count and N50 suggest.

If you want the fragments anyway — to see what is there rather than to report
a result — switch on "Assemble below the floor anyway". Everything produced
that way is labelled as a low-depth draft.

## Status indicators

### Header status

- **Status light**: Green (running), Gray (idle), Red (error)
- **Timer**: Countdown to next data refresh
- **Elapsed time**: Time since analysis started
- **Current stage**: Active pipeline process

### Pipeline progress

When analysis is running:
- Stage name (Chopper, Kraken2, SeqKit, etc.)
- Process counts (completed/total)
- Batch number (in real-time mode)

### Dashboard verdict states

The Dashboard verdict banner color is the primary signal:

| State | Color | Meaning |
|-------|-------|---------|
| ALL CLEAR | Green | Watched pathogens were screened at adequate depth and none was found. The subtitle states how many organisms were screened and over how many reads |
| ACTION REQUIRED | Red | A critical or high-risk watched pathogen was detected — follow your safety protocol |
| MONITORING | Amber | Only moderate-risk watched species detected |
| INSUFFICIENT READS | Amber | Screening ran, but over too few reads for the result to mean anything. **This is not a negative result** — see below |
| NOT SCREENED | Amber | No watchlist was active, so nothing was checked. **This is not a negative result** |
| SCREENING IN PROGRESS | Blue | Run is active; first batch not yet processed |
| STANDBY | Grey | No run active |

### The two states that are not "all clear"

`INSUFFICIENT READS` and `NOT SCREENED` both mean the same thing in practice:
**no screening result was produced.** They are deliberately distinct from ALL
CLEAR, and deliberately not green, because an absence of detections is only
meaningful when there was something to detect it in.

- **NOT SCREENED** — no watchlist was active. Enable pathogens on the
  *Watchlist & Preparation* tab and the screen will run against the existing
  results; the pipeline does not need re-running.
- **INSUFFICIENT READS** — a watchlist was active, but too few reads survived
  QC. The banner states the actual depth, and when the sample is shallower than
  the highest alert threshold in your watchlist it says so: at that depth the
  organism could not have been called even if every read were it. Check the
  Quality Control tab for why so few reads passed.

The threshold is 10 reads, matching `min_reads_for_validation`: if a detection
needs that many reads to be worth confirming, an absence measured over fewer is
not worth reporting as clear.

Note the banner covers **all samples together**. An individual sample that
produced no output is flagged in the sample selector with a "no data" badge
rather than in the banner, because the banner's job is to catch a detection in
any sample, including one you are not currently looking at.

## Configuration file

Save your settings for reuse:

```yaml
analysis_name: "My Analysis"
nanopore_output_directory: "/data/sequencing/run_001"
results_output_directory: "/data/results/run_001"
kraken_db: "/databases/kraken2_standard"

processing_mode: "realtime"
sample_handling: "by_barcode"
update_interval_seconds: 30

pipeline_profile: "conda"
blast_validation: false

# Watchlists are managed via the watchlist tab in the GUI
# 9 built-in watchlists: clinical_pathogens, cdc_bioterrorism, who_priority,
# foodborne, respiratory, who_drinking_water, nosocomial_eskape,
# wastewater_surveillance, zoonotic_one_health
```

## Tips

### Performance

- Use a fast SSD for the Kraken2 database
- Enable `kraken_memory_mapping` for large databases
- Adjust `update_interval_seconds` based on your needs (30-60s typical)

### Troubleshooting

**No samples detected:**
- Check that your directory structure matches the selected sample handling mode
- Verify FASTQ files have `.fastq` or `.fastq.gz` extension

**Visualizations not updating:**
- Ensure the backend is running (check status indicator)
- Verify the results directory contains expected output files

**Pipeline errors:**
- Verify the conda environment is activated and `nextflow -version` reports 25.10 or newer
- Verify Kraken2 database path is correct
- Review Nextflow logs in the results directory

## Next steps

- [Configuration reference](configuration.md) -- all available options
- [Operator guide](OPERATOR_GUIDE.md) -- field-deployment reference and decision trees
- [Developer guide](developer-guide.md) -- extending Nanometa Live
