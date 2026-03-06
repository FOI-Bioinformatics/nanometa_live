# Offline Deployment Design

Date: 2026-03-06
Status: Approved

## Context

Nanometa Live must operate in air-gapped field labs and secure facilities with no internet. Operators prepare everything at base (with internet), transfer via USB/pre-configured laptop, and run analysis entirely offline. Results are exported as self-contained HTML reports for transfer back.

## Requirements

- Field lab with no internet (military, first responders)
- Air-gapped secure facilities (USB-only data transfer)
- Pre-configured laptop + USB drives for import/export
- Support Docker, Singularity, and Conda (detect and package what's available)
- CLI + GUI for preparation workflow
- Results export: self-contained HTML report + raw files

## Design

### 1. Offline Mode Configuration

Global `offline_mode` setting propagated through the stack:

- **Config**: `offline_mode: true` in app-config store / config YAML
- **taxonomy_api.py**: Check OfflineTaxonomyCache first, skip network calls entirely
- **genome_manager.py**: Disable download buttons, show "Offline -- use Import"
- **Header**: Prominent "OFFLINE MODE" banner
- **Preparation tab**: Hide internet options, show import-from-USB options
- **Auto-detection**: Lightweight NCBI ping on startup; suggest offline mode on failure

### 2. Preparation Wizard (GUI + CLI)

GUI wizard in Preparation tab with 8 steps:

1. Select watchlists (checkboxes for built-in options)
2. Verify Kraken2 database (path, inspect.txt, size)
3. Download genomes (batch, existing functionality)
4. Build BLAST databases (batch, existing functionality)
5. Cache taxonomy (export OfflineTaxonomyCache snapshot)
6. Cache container images (detect runtime, pull and save)
7. Readiness check (ReadinessChecker pass/fail)
8. Export bundle (package to USB/directory)

CLI entry point `nanometa-prepare`:

```bash
nanometa-prepare deploy \
  --watchlists clinical_pathogens,cdc_bioterrorism \
  --db /path/to/kraken_db \
  --output /Volumes/USB/deployment_bundle

nanometa-prepare check --db /path/to/db

nanometa-prepare import --bundle /Volumes/USB/deployment_bundle
```

Both interfaces use the same MobileLabPreparer engine.

### 3. Container Image Caching

New module `core/workflow/container_cacher.py`:

- **Discovery**: Parse nanometanf `modules/` for container directives
- **Docker**: `docker pull` then `docker save` to `.tar.gz`
- **Singularity**: `singularity pull` to `.sif` files
- **Conda**: Verify environments resolve, export `conda-lock.yml`
- **Import**: `docker load` / copy `.sif` to `NXF_SINGULARITY_CACHEDIR`

nanometanf `offline` profile in nextflow.config:

```groovy
profiles {
    offline {
        params.offline_mode = true
        singularity.enabled = true
        singularity.autoMounts = true
        env.NXF_OFFLINE = 'true'
    }
}
```

### 4. Bundle Import/Export and Manual Genome Provision

Bundle structure:

```
deployment_bundle/
  genomes/           # Pre-downloaded reference genomes
  blast/             # Pre-built BLAST databases
  mappings/          # Taxid mapping collections
  cache/             # Taxonomy cache snapshot
  watchlists/        # Selected watchlist YAMLs
  containers/        # Docker tars or Singularity .sif files
  config.yaml        # App config with ${NANOMETA_HOME} placeholders
  manifest.json      # MD5 checksums, DB hash, creation date, tool versions
  README_FIELD.md    # Quick-start for the field operator
```

Kraken2 DB transferred separately (8+ GB).

Manual genome provision:

- "Import Genomes" button in Preparation tab
- Accepts directory of FASTA files or zip/tar.gz archive
- Files named `{taxid}.fasta` auto-recognized
- Other names: mapping dialog (name to taxid)
- Auto-build BLAST databases after import

USB import workflow:

1. Plug in USB, open Preparation tab, click "Import Bundle"
2. Select bundle directory
3. BundleManager validates manifest checksums
4. Extracts to `~/.nanometa/`, rebases paths
5. Loads container images into local runtime
6. Sets `offline_mode: true`
7. Runs readiness check

### 5. Results Export with HTML Report

Export structure:

```
results_export_2026-03-06/
  report.html          # Self-contained, any browser
  raw/
    kraken2/           # Classification reports
    fastp/             # QC JSON files
    validation/        # BLAST/minimap2 results
  summary.json         # Machine-readable summary
  metadata.json        # Run info, config, watchlists, samples
```

HTML report:

- Inline CSS/JS, Plotly charts as embedded JSON with bundled plotly.min.js
- Status banner (SAFE / ACTION REQUIRED)
- Pathogen screening results table
- Per-sample classification charts
- QC metrics summary
- Watchlist alerts with confidence levels
- Print-friendly layout

New `core/export/report_generator.py` using Jinja2 templates.

## Team Structure (5 members)

| Role | Focus | Key Files |
|------|-------|-----------|
| offline-config | Wire offline_mode, API cache-first, header banner | taxonomy_api.py, offline_cache.py, header.py, app config |
| prep-wizard | GUI wizard + CLI nanometa-prepare | preparation_tab.py, preparation_layout.py, cli/prepare.py |
| container-cacher | Image discovery, cache, import/load, NF profile | new container_cacher.py, nanometanf nextflow.config |
| bundle-engineer | Enhanced BundleManager, manual genome import, USB workflow | bundle_manager.py, genome_manager.py, preparation_tab.py |
| report-exporter | HTML report generator, export UI | new report_generator.py, new template, dashboard_tab.py |

## Existing Code to Reuse

- `core/utils/offline_cache.py` (581 lines) -- OfflineTaxonomyCache with snapshot export/import
- `core/workflow/mobile_lab_preparer.py` (359 lines) -- 8-stage preparation orchestrator
- `core/workflow/bundle_manager.py` (226 lines) -- Bundle export/import with checksums
- `core/workflow/readiness_checker.py` (200+ lines) -- Critical/warning validation
- `core/utils/genome_manager.py` (1800+ lines) -- Genome downloads, BLAST DB building

## Verification

1. Prepare deployment bundle on internet-connected machine
2. Transfer to a machine with no internet (or disable networking)
3. Import bundle, verify readiness check passes
4. Run nanorunner simulation, pipe through nanometanf, view in Nanometa Live
5. Export HTML report, verify it opens in a browser with all charts/data
6. Verify no network calls made during entire analysis
