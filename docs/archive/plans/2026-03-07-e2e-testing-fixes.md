# E2E Testing and Button Fix Session

Date: 2026-03-07
Status: Completed

## Context

After adding offline deployment features (2026-03-06) and fixing Dash 4.0 callback errors, all buttons in the app became unresponsive. A team of agents investigated, diagnosed, and fixed the issues.

## Root Causes Identified

### 1. Flask errorhandler swallowing KeyErrors (Critical)

**File:** `app/app.py` lines 573-580

A `@app.server.errorhandler(KeyError)` was added in commit `9a5f7ed` to handle stale dashboard combined-callback requests. However, Flask's `raise` inside an errorhandler does not propagate -- it either returns 500 or gets swallowed. This caused ALL KeyErrors in any callback to return 204 (No Content), making buttons appear dead.

**Fix:** Removed the errorhandler entirely and the unused `import flask`.

### 2. Orphaned taxmap callbacks (17 missing component IDs)

**File:** `app/tabs/watchlist_tab.py` lines 1264-1591

Seven callbacks were added for a taxmap mapping modal UI that was never built in any layout file. The callbacks referenced 17 component IDs (taxmap-mapping-modal, taxmap-kraken-search, taxmap-confirm-mapping-btn, etc.) with no corresponding layout components.

With `suppress_callback_exceptions=True`, these didn't crash the app but consumed callback registration slots and could cause confusion.

**Fix:** Removed all 7 orphaned callbacks, the `_create_suggestion_card` helper function, and unused imports (~407 lines removed).

### 3. Background callback missing manager

**File:** `app/tabs/preparation_tab.py` line 128

The `run_preparation` callback had `background=True` but was missing `manager=background_callback_manager`, unlike the other two background callbacks in the same file.

**Fix:** Added `manager=background_callback_manager` to the callback decorator.

### 4. Missing logging import

**File:** `app/tabs/config_tab.py`

Line 94 called `logging.debug()` but `logging` was never imported. Would crash on JSON parse errors.

**Fix:** Added `import logging` at the top of the file.

## Additional Fixes Applied

### Dashboard Tab
- Replaced fragile 21-element tuple-slice state functions with per-callback helpers (`_get_idle_status()`, `_get_error_status()`, etc.)
- Fixed traffic light CSS class conflict: `status-running` incorrectly forced green on all active states. Now uses correct classes per status (green/amber/red/blue)
- Fixed sample table column mismatch: layout defined columns that callbacks never populated, and vice versa
- Removed duplicate CSS class logic

### UX Improvements
- Increased dashboard header font sizes (14px -> 18px) for lab readability
- Increased alerts panel maxHeight (300px -> 450px) so operators can see all flagged pathogens
- Upgraded section headers from H6 to H5 for consistency
- Fixed watchlist footer misdirecting to "Configuration" instead of "Watchlist" tab
- Improved "No watchlist active" empty state with warning background and clearer text
- Added "Complete" and "Standby" status labels to the live indicator (was only "Idle")
- Increased live indicator dot size (10px -> 12px)

### Code Quality
- Replaced 7 `print()` error handlers with `logging.error()` in qc_tab.py

## Verification Results

### Data Flow (All Passing)
- All 6 built-in watchlists verified (Clinical, Foodborne, Water, Respiratory, CDC, WHO)
- Kraken2 cumulative report parsing correct for barcode01-03 test data
- Sample detection correctly identifies all barcodes
- Watchlist taxid matching works against kraken2 report taxids
- Alert generation produces correct severity levels and thresholds

### Visualization Review (All Passing)
- Sankey diagram: adaptive height, hover tooltips, color-coded legend
- Sunburst chart: proper drill-down with branchvalues="remainder"
- Classification donut: rate-colored center annotation
- QC charts: consistent styling, proper hover templates
- Coverage plots: area chart with range slider, threshold highlighting

### Callback Pattern Review (All Passing)
- No circular dependencies
- No global mutable state in callbacks
- Pattern-matching callbacks (ALL, MATCH) correctly used
- Background callbacks properly configured via DiskcacheManager
- `allow_duplicate=True` correctly used throughout
- `persistence=True` on tabs and sample selector

### Stale Combined-Callback Key
The browser cache holds the old combined callback signature from before the D3a/D3b/D3c/D3d split. This produces a 500 error on first page load but resolves after a hard refresh (Cmd+Shift+R). Cache-control headers in app.py prevent recurrence. No code change needed.

## Remaining Items

### Deferred (Low Priority)
- 4 files still use deprecated `dash_table.DataTable` (migration to dash-ag-grid deferred)
- pathogens.yaml line 192: E. coli O157:H7 uses generic species taxid 562 instead of serotype 83334
- Sample selector width can clip on small screens
- Tab group labels (0.6rem) could be larger for discoverability
- Confidence thresholds documented as "configurable" but hardcoded
- Footer links to GitHub may be unreachable in restricted lab networks

## Files Modified

| File | Changes |
|------|---------|
| `app/app.py` | Removed Flask errorhandler + unused import |
| `app/tabs/watchlist_tab.py` | Removed 7 orphaned taxmap callbacks (~407 lines) |
| `app/tabs/preparation_tab.py` | Added manager= to background callback |
| `app/tabs/config_tab.py` | Added import logging |
| `app/tabs/qc_tab.py` | Replaced 7 print() with logging.error() |
| `app/tabs/dashboard_tab.py` | Fixed tuple-slice helpers, traffic light CSS, duplicate logic |
| `app/layouts/dashboard_layout.py` | Fixed sample table columns, font sizes, section headers, alerts panel |
| `app/assets/styles.css` | Fixed traffic light colors, pulse animations, indicator size |
| `app/callbacks.py` | Added Complete/Standby status labels |
