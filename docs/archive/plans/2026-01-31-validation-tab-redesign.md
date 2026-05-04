# Validation Tab Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the Validation tab into two clear sub-tabs separating read-centric BLAST validation from genome-centric minimap2 coverage validation, and remove demo mode.

**Architecture:** Replace the single Validation tab content with `dbc.Tabs` containing "Read Validation" (BLAST) and "Coverage Validation" (minimap2) sub-tabs. Each sub-tab has its own summary cards, filters, result cards, and plots. Data flows from `validation-data-store` filtered by `validation_method`. Demo mode and on-demand validation UI are removed entirely.

**Tech Stack:** Dash, Dash Bootstrap Components, Plotly, Python 3.11+

---

### Task 1: Remove demo mode and on-demand validation UI wiring

**Files:**
- Modify: `nanometa_live/app/tabs/validation_tab.py`
- Modify: `nanometa_live/app/layouts/validation_layout.py`
- Modify: `nanometa_live/app/app.py`
- Modify: `nanometa_live/core/parsers/paf_coverage_parser.py`

**Step 1: Remove demo mode store from app.py**

Search `app.py` for `validation-demo-mode` store definition and remove it. If it's defined in the layout file instead, remove it there.

**Step 2: Remove demo code from validation_tab.py**

- Delete `toggle_demo_mode()` callback entirely
- Delete `_generate_demo_validation_data()` function entirely
- In `load_validation_data()`, remove the `demo_mode` parameter (State input), remove the `if demo_mode:` branch. Keep only the real data loading path.

**Step 3: Remove demo button from validation_layout.py**

- Remove the "Enable Demo Mode" button (`id='enable-validation-demo'`)
- Remove the `validation-demo-mode` dcc.Store component

**Step 4: Remove demo coverage generator from paf_coverage_parser.py**

- Delete `create_demo_coverage_data()` function
- Remove its import from any files that use it (check `validation_tab.py` coverage callbacks)

**Step 5: Remove on-demand validation button wiring**

- In `validation_tab.py`, remove or disable the pattern-matched callback for `{"type": "validate-organism-btn", ...}` if it exists
- In organism card components, the "Validate" button can remain dormant (no callback responds) or be removed in a separate cleanup

**Step 6: Verify the app still starts**

Run: `python -c "from nanometa_live.app.app import create_app; print('OK')"`
Expected: OK (no import errors)

**Step 7: Commit**

```bash
git add nanometa_live/app/tabs/validation_tab.py nanometa_live/app/layouts/validation_layout.py nanometa_live/app/app.py nanometa_live/core/parsers/paf_coverage_parser.py
git commit -m "refactor: remove validation demo mode and on-demand validation UI"
```

---

### Task 2: Rewrite validation layout with two sub-tabs

**Files:**
- Rewrite: `nanometa_live/app/layouts/validation_layout.py`

**Step 1: Write the new layout**

Replace `create_validation_layout()` with a new implementation containing `dbc.Tabs` with two sub-tabs.

**Read Validation sub-tab structure:**
```python
dbc.Tab(label="Read Validation (BLAST)", tab_id="blast-tab", children=[
    # Summary row: 4 stat cards (confirmed/partial/low/no_data)
    # id='blast-summary-container'

    # Filter controls row: status filter + sort dropdown
    # id='blast-status-filter', id='blast-sort-select'

    # Results cards container
    # id='blast-results-container'

    # Collapsible: Identity distribution plot
    # id='blast-identity-plot'

    # Collapsible: Detailed statistics table
    # id='blast-stats-table'

    # Empty state message
    # id='blast-empty-message'

    # Export button
    # id='export-blast-button'
])
```

**Coverage Validation sub-tab structure:**
```python
dbc.Tab(label="Coverage Validation (minimap2)", tab_id="coverage-tab", children=[
    # Summary row: 4 stat cards
    # id='coverage-summary-container'

    # Species selector dropdown
    # id='coverage-species-selector'

    # Coverage stats badges row
    # id='coverage-stats-container'

    # Coverage depth plot (full width)
    # id='coverage-depth-plot'

    # Cumulative + histogram (side-by-side)
    # id='coverage-cumulative-plot', id='coverage-histogram-plot'

    # MinMapQ filter input
    # id='coverage-mapq-filter'

    # Results cards container (minimap2 cards)
    # id='coverage-results-container'

    # Empty state message
    # id='coverage-empty-message'

    # Export button
    # id='export-coverage-button'
])
```

**Key component IDs to preserve or rename:**
- `validation-data-store` — keep, shared by both sub-tabs
- `classification-plot` style IDs — use new prefixed IDs (blast-* and coverage-*)
- Remove old combined IDs: `validation-status-filter`, `validation-method-filter`, `validation-sort-select`, `validation-results-container`, `validation-summary-container`, etc.

**Step 2: Keep the `create_validation_result_card()` helper**

Modify it to accept a `show_coverage_button` parameter (default False). BLAST cards never show it. Minimap2 cards show "View Coverage" button.

**Step 3: Keep `create_validation_status_card()` helper**

No changes needed — it takes counts as parameters.

**Step 4: Verify layout renders**

Run: `python -c "from nanometa_live.app.layouts.validation_layout import create_validation_layout; print('OK')"`
Expected: OK

**Step 5: Commit**

```bash
git add nanometa_live/app/layouts/validation_layout.py
git commit -m "feat: split validation layout into BLAST and minimap2 sub-tabs"
```

---

### Task 3: Rewrite validation callbacks for two sub-tabs

**Files:**
- Rewrite: `nanometa_live/app/tabs/validation_tab.py`

**Step 1: Rewrite `load_validation_data()` callback**

- Input: `update-interval` n_intervals
- State: `app-config` data
- Output: `validation-data-store` data
- Logic: Load from `BlastValidationParser`, no demo mode check. Return the full results dict.

**Step 2: Write BLAST-specific callbacks**

All filter by `result.get('validation_method') == 'blast'`:

- `update_blast_summary()` — Input: validation-data-store. Output: blast-summary-container. Counts confirmed/partial/low/no_data for BLAST results, renders `create_validation_status_card()`.

- `update_blast_cards()` — Inputs: validation-data-store, blast-status-filter, blast-sort-select. Output: blast-results-container. Filters and sorts BLAST results, creates result cards (no coverage button).

- `update_blast_identity_plot()` — Input: validation-data-store. Output: blast-identity-plot figure. Bar chart of identity % per species, BLAST only.

- `update_blast_table()` — Input: validation-data-store. Output: blast-stats-table children. Detailed table, BLAST only.

- `update_blast_empty_state()` — Input: validation-data-store. Output: blast-empty-message style (show/hide). Show message when no BLAST results.

- `export_blast_report()` — Input: export-blast-button. Output: download component. CSV of BLAST results.

**Step 3: Write minimap2-specific callbacks**

All filter by `result.get('validation_method') == 'minimap2'`:

- `update_coverage_summary()` — Same pattern as BLAST summary but for minimap2 results.

- `update_coverage_cards()` — Renders minimap2 result cards with "View Coverage" buttons.

- `populate_coverage_selector()` — Input: validation-data-store. Output: coverage-species-selector options. Populates dropdown with minimap2-validated species.

- `handle_view_coverage_click()` — Pattern-matched callback for "View Coverage" buttons. Sets coverage-species-selector value.

- `update_coverage_plots()` — Input: coverage-species-selector value, coverage-mapq-filter value. Outputs: coverage-depth-plot figure, coverage-cumulative-plot figure, coverage-histogram-plot figure, coverage-stats-container children. Parses PAF file and renders all 3 plots + stats badges.

- `update_coverage_empty_state()` — Show/hide empty message.

- `export_coverage_report()` — CSV of minimap2 results.

**Step 4: Verify all callbacks register**

Run: `python -c "from nanometa_live.app.app import create_app; print('OK')"`
Expected: OK

**Step 5: Commit**

```bash
git add nanometa_live/app/tabs/validation_tab.py
git commit -m "feat: split validation callbacks into BLAST and minimap2 sub-tab callbacks"
```

---

### Task 4: Update app.py store definitions and imports

**Files:**
- Modify: `nanometa_live/app/app.py`

**Step 1: Remove validation-demo-mode store**

Search for and remove the `dcc.Store(id='validation-demo-mode', ...)` if defined in app.py.

**Step 2: Verify validation-data-store still exists**

Confirm `dcc.Store(id='validation-data-store', ...)` is still present (shared by both sub-tabs).

**Step 3: Check download component**

Ensure a `dcc.Download` component exists for validation exports. May need two (one per sub-tab) or one shared.

**Step 4: Verify app starts and Taxonomy tab still works**

Run app, navigate to both Taxonomy and Validation tabs.

**Step 5: Commit**

```bash
git add nanometa_live/app/app.py
git commit -m "chore: clean up validation stores in app.py"
```

---

### Task 5: End-to-end verification

**Step 1: Generate test data**

```bash
python -c "from tests.validation.generate_synthetic_data import generate_all_synthetic_data; generate_all_synthetic_data('/tmp/nanometa_validation_data')"
```

**Step 2: Start the app**

```bash
python -m nanometa_live.app --main_dir /tmp/nanometa_validation_data --port 8050
```

**Step 3: Verify Read Validation sub-tab**

- Navigate to Validation tab
- "Read Validation (BLAST)" sub-tab should be visible
- If no BLAST results in test data: clean empty state message shown
- No demo mode button anywhere

**Step 4: Verify Coverage Validation sub-tab**

- Click "Coverage Validation (minimap2)" sub-tab
- If PAF files exist in test data: species selector populated, coverage plots render
- If no PAF data: clean empty state message shown
- No demo mode button

**Step 5: Verify no console errors**

Open browser dev tools, check for JavaScript errors or Dash callback errors.

**Step 6: Verify other tabs unaffected**

- Dashboard, Organisms, QC, Taxonomy tabs still work
- No broken imports or missing stores

**Step 7: Run tests**

```bash
pytest tests/ -v
```

Expect: pre-existing test failures may exist but no new failures from validation changes.

**Step 8: Commit any fixes**

```bash
git add -u
git commit -m "fix: address issues found during validation tab verification"
```

---

## Files to Modify Summary

| File | Action | Scope |
|------|--------|-------|
| `nanometa_live/app/layouts/validation_layout.py` | Rewrite | Two sub-tab layout structure |
| `nanometa_live/app/tabs/validation_tab.py` | Rewrite | Split callbacks by method, remove demo |
| `nanometa_live/app/app.py` | Minor edit | Remove demo store |
| `nanometa_live/core/parsers/paf_coverage_parser.py` | Minor edit | Remove demo data generator |

## Files NOT Modified

| File | Reason |
|------|--------|
| `core/parsers/blast_validation_parser.py` | Already method-aware, no changes needed |
| `app/components/coverage_plots.py` | Figure functions are clean, reused as-is |
| `core/workflow/on_demand_validator.py` | Kept dormant; no UI calls it but code stays for future use |
