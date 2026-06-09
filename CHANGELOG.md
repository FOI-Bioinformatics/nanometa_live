# Changelog

All notable changes to Nanometa Live are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
