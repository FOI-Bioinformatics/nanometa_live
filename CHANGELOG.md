# Changelog

All notable changes to Nanometa Live are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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

### Changed
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

## [0.1.0] - 2024-01-01

### Added
- Initial release
- Basic Kraken2 result visualization
- Simple species-of-interest tracking
- Command-line configuration
