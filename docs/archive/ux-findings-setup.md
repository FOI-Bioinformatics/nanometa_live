# UX Findings: Setup Tabs (Configuration, Watchlist, Preparation)

**Evaluator:** setup-ux specialist
**Date:** 2026-03-15
**Target users:** Scientists, first responders, and field operators with basic lab literacy but no bioinformatics training.

---

## Summary of Changes

30+ text and label changes across 8 files, plus 1 new UI feature (reset confirmation modal) and 1 layout restructuring (quick-start promoted from collapsed section). All changes are non-breaking; callback wiring was updated to match.

**Smoke test:** PASS

---

## 1. Configuration Tab

### Findings

| Issue | Severity | Status |
|-------|----------|--------|
| "Kraken2 Database" label is opaque to non-bioinformaticians | High | FIXED |
| "Required" badge on Essential Settings is alarming | Low | FIXED -> "Start here" |
| Tooltip for Nanopore Output Directory is too technical | Medium | FIXED |
| Results Output Directory tooltip references internal terms | Medium | FIXED |
| Reset button has no confirmation -- destructive action unguarded | High | FIXED |
| No first-time guidance for which fields to fill | High | FIXED -- added tip alert |
| "Minimum Reads per Level" is jargon | Medium | FIXED -> "Minimum Detection Count" |
| "Memory mapping for Kraken2" is opaque | Medium | FIXED -> "Low-memory mode" with Recommended badge |
| "Pathogen Validation" section title | Medium | FIXED -> "Confirmation Testing" with tooltip |
| BLAST/minimap2 method labels are toolnames, not concepts | High | FIXED -> "Sequence search"/"Genome alignment" |
| "Min Identity (%)" is technical | Medium | FIXED -> "Min. Similarity (%)" |
| "E-value Cutoff" is opaque | High | FIXED -> "Strictness Filter" |
| "minimap2 Preset" is toolname | Medium | FIXED -> "Sequencing Platform" |
| "Min Mapping Quality (MAPQ)" | Medium | FIXED -> "Alignment Confidence" |
| "Genome Cache Directory" | Low | FIXED -> "Reference Genome Storage" |
| "QC Tool" label | Low | FIXED -> "Quality Filter" |
| "Skip NanoPlot" is toolname | Medium | FIXED -> "Skip detailed QC report" |
| "Incremental classification" is jargon | Medium | FIXED -> "Running totals in live mode" |
| "Enable Krona plots" | Low | FIXED -> "Generate interactive taxonomy charts" |
| "Nanopore stats in MultiQC" | Low | FIXED -> "Include sequencing quality summary" |
| "Pipeline Options" heading | Low | FIXED -> "Analysis Options" |
| "GUI Port" label | Low | FIXED -> "Dashboard Port" |
| Advanced Settings accordion title is generic | Low | FIXED -> adds guidance text |

### Changes Made

- **config_form.py**: 15 label/tooltip rewrites, added Recommended badges on defaults, added QC tool tooltip
- **config_layout.py**: Added first-time tip alert, added reset confirmation modal with cancel/confirm buttons
- **config_tab.py**: Split reset callback into modal-open + confirmed-reset, updated source-tracking callback to use confirm button

---

## 2. Watchlist Tab

### Findings

| Issue | Severity | Status |
|-------|----------|--------|
| Quick-start presets buried in collapsed "Watchlist Files" accordion | High | FIXED |
| Quick-start buttons have no descriptions | Medium | FIXED |
| "BSL" column header unexplained | Medium | FIXED -> "Safety" with improved tooltip |
| "Validated" column header vague | Medium | FIXED -> "Verified" with tooltip |
| "DB Match" column header is jargon | Medium | FIXED -> "In Database" with tooltip |
| Genome column tooltip references BLAST | Low | FIXED -> "confirmation testing" |
| "Taxid:" prefix in pathogen rows | Low | FIXED -> "ID:" with title tooltip |
| Add Species "Taxid (optional)" label is jargon | Medium | FIXED -> "Taxonomy ID" with tooltip |
| Enable/Disable All has no performance warning | Medium | FIXED -- added title tooltips |
| Edit modal "NCBI Taxid" / "Kraken2 Taxid" labels | Medium | FIXED -> "Reference ID" / "Database ID" |
| Edit modal "BSL Level" has no risk descriptions | Medium | FIXED -> descriptive labels (Minimal/Moderate/High/Extreme risk) |
| Edit modal "Kraken2 Name" | Low | FIXED -> "Name in Database" |
| Intro text does not explain what watchlists are for | Medium | FIXED |

### Changes Made

- **watchlist_layout.py**: New `_create_quick_start_section()` with card layout, descriptions per preset, and gold left border for visual prominence. Removed duplicate buttons from collapsed section. Updated 10+ column headers and labels.

---

## 3. Preparation Tab

### Findings

| Issue | Severity | Status |
|-------|----------|--------|
| Header text lists technical operations | Medium | FIXED -> simplified |
| No recommended order guidance | High | FIXED -- added ordered alert box |
| "Download External Kraken2 Database" title | High | FIXED -> "Download Species Identification Database" |
| "Taxid Mapping (Rescan Database)" title | High | FIXED -> "Verify Watchlist Against Database" |
| "Rescan DB" button text | Medium | FIXED -> "Scan Database" |
| "0 species mapped" label | Low | FIXED -> "0 organisms matched" |
| "Genome Downloads for BLAST Validation" | High | FIXED -> "Reference Genomes for Confirmation Testing" |
| "with BLAST DB" status text | Medium | FIXED -> "with search index" |
| "Build BLAST DBs" button | Medium | FIXED -> "Build Search Index" |
| Reference genome info text references BLAST | Low | FIXED |
| Run Preparation description uses jargon | Medium | FIXED |
| Import Genomes "taxid" reference | Low | FIXED -> includes explanation |
| Readiness checklist button "Run Checks" is passive | Low | FIXED -> "Check Everything" (primary color) |
| Default checklist text references "Run Checks" | Low | FIXED -> updated to match new button text |
| Deploy Offline wizard step descriptions use jargon | Medium | FIXED (all 8 steps) |
| Export Bundle "Kraken2 database" reference | Low | FIXED -> "species database" |
| Import Bundle "Kraken2 DB" label | Low | FIXED -> "Species DB" |

### Changes Made

- **preparation_layout.py**: 17 label/text rewrites, added step-order guidance alert, promoted readiness button to primary color

---

## 4. Taxid Mapping UI

### Findings

| Issue | Severity | Status |
|-------|----------|--------|
| "Taxonomy ID Mapping Status" heading | Medium | FIXED -> "Organism Matching Status" |
| "Mapping Controls" heading | Low | FIXED -> "Database Scan Controls" |
| "Re-scan Database" button text | Low | FIXED -> "Scan Database" |
| "Manual Taxonomy Mapping" modal title | Medium | FIXED -> "Manual Organism Mapping" |
| "Watchlist Entry" label in modal | Low | FIXED -> "Organism to Map" |
| "NCBI TaxID" label in modal | Low | FIXED -> "Taxonomy ID" |
| "Search Kraken2 Database" heading | Medium | FIXED -> "Search Species Database" |
| "Watchlist Mappings" table heading | Low | FIXED -> "Organism Matches" |
| Column headers: NCBI Name, NCBI TaxID, Kraken TaxID, Kraken Name | Medium | FIXED -> Organism Name, Ref. ID, DB ID, Database Name |
| "Preserve manual overrides" checkbox | Low | FIXED -> "Keep my manual corrections" |
| Empty state text references "taxid" | Low | FIXED |

### Changes Made

- **taxid_mapping_ui.py**: 11 label/text rewrites removing all references to "Kraken2", "NCBI", "taxid" from user-facing text

---

## 5. Remaining Known Issues (Not Fixed)

| Issue | Reason |
|-------|--------|
| Enable/Disable All can freeze UI with 69 pathogens | Requires batch method in WatchlistManager (backend change, out of scope for UX layer) |
| Watchlist GTDB-to-NCBI name mapping | Feature backlog item |
| CSS changes needed for quick-start card styling | CSS file is out of scope per instructions; inline styles used instead |

---

## 6. CSS Recommendations (Not Applied)

The following CSS additions would further improve the setup tabs but were not applied per the constraint against modifying `styles.css`:

```css
/* Quick-start card hover effect */
.quick-start-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* Reset modal warning styling */
.reset-warning-modal .modal-header {
    background-color: #fff3cd;
}
```

---

## Files Modified

1. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/components/config_form.py`
2. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/layouts/config_layout.py`
3. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/tabs/config_tab.py`
4. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/layouts/watchlist_layout.py`
5. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/layouts/preparation_layout.py`
6. `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live/app/components/taxid_mapping_ui.py`

## Files NOT Modified (read-only or out of scope)

- `app/tabs/watchlist_tab.py` -- callbacks not changed, only layout labels
- `app/tabs/preparation_tab.py` -- callbacks not changed, only layout labels
- `app/callbacks.py` -- read-only
- `app/components/tooltip_components.py` -- read-only, existing patterns reused
- `app/assets/styles.css` -- per instructions, not modified
