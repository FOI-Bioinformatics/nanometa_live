# UX Evaluation Design -- Nanometa Live

**Date:** 2026-03-15
**Goal:** Evaluate and improve all Nanometa Live tabs for scientists, first-responders, and soldiers who need fast decisions without bioinformatics knowledge.

## Context

Nanometa Live is a Dash 4 web application for real-time Oxford Nanopore sequencing analysis. Target users operate in both field (rugged, gloves, small screens, minutes-level time pressure) and lab (standard laptop, moderate time pressure) settings. Users have basic lab literacy (DNA, bacteria vs. virus, sample quality) but not bioinformatics expertise.

## Team Structure

6 members, domain-split with cross-cutting field UX review.

### Members

| Role | Agent Type | Focus |
|------|-----------|-------|
| **ux-lead** | ui-designer | Coordination, consistency, conflict resolution, final report |
| **dashboard-ux** | ui-designer | Dashboard tab |
| **results-organisms** | nanometa-dash | Organisms + Taxonomy (Classification) tabs |
| **results-quality** | nanometa-dash | Quality Control + Validation tabs |
| **setup-ux** | nanometa-dash | Configuration + Watchlist + Preparations tabs |
| **field-ux** | ui-designer | Cross-cutting field deployment review (all tabs) |

### Workflow

- **Phase 1** (parallel): All 5 specialists audit and fix their assigned tabs simultaneously
- **Phase 2** (sequential, blocked on Phase 1): ux-lead reviews all changes, resolves conflicts (especially styles.css), verifies consistency, runs smoke test, writes final report

## Technical Constraints (Dash 4)

Agents MUST be aware of these known issues:

1. **Callback graph fragility**: A single MATCH wildcard mismatch can break ALL callbacks in the entire app. Do not add or modify callback Input/Output/State decorators without verifying the callback graph loads.
2. **MATCH + plain-ID mixing forbidden**: Dash 4 does not allow mixing MATCH-wildcard Outputs with plain-ID Outputs in the same callback. Use `set_props()` for the plain-ID update instead.
3. **dbc.Tabs persistence conflict**: `persistence=True` on Tabs can conflict with callbacks that write `active_tab`. Do not add persistence to Tabs components.
4. **Use dash-ag-grid, not dash_table**: All DataTables have been migrated to dash-ag-grid. New tables must use ag-grid.
5. **Smoke test after changes**: Every agent must verify their changes load correctly by running: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

## Evaluation Criteria

### Decision Support
- User can reach go/no-go decision within 30 seconds of opening
- Threat indicators unmistakable
- Visual hierarchy: threats > status > details

### Lab Literacy
- Technical terms explained via tooltips or replaced with plain language
- "Read count," "species," "quality" clear without training
- No raw bioinformatics jargon (taxid, k-mer, N50) without context

### Field Readiness
- Touch targets >= 44x44px for gloved operation
- Font sizes: body >= 16px, labels >= 14px
- WCAG AA contrast ratios (4.5:1 text, 3:1 UI components)
- Critical info above fold without scrolling
- Color-blind safe palettes (not red/green only)
- Works on 13-inch laptop and tablet screens
- Dark mode/low-light readability (app has theme toggle)

### Consistency
- Consistent card styles, button patterns, color coding across tabs
- Same interaction patterns (collapse, expand, select) across tabs
- Predictable layout structure

### Robustness
- Empty states and error states handled gracefully across all tabs
- Remains usable with realistic data volumes (50+ organisms, 20+ barcodes)

## File Assignments

### dashboard-ux
**Read & modify:**
- `app/layouts/dashboard_layout.py`
- `app/tabs/dashboard_tab.py`
- `app/components/modern_components.py`
- `app/components/pathogen_alert.py`
- `app/components/watchlist_manager_ui.py`
- `app/components/watchlist_modal.py`
- `app/components/header.py`

**Read-only:**
- `app/app.py`
- `app/callbacks.py`
- `app/utils/chart_builders.py`

**Focus:** Pre-flight checklist clarity, traffic light status visibility, pathogen screening prominence, metrics card labels, sample table scannability, alert panel severity colors, header branding.

### results-organisms
**Read & modify:**
- `app/tabs/main_tab.py` (Organisms)
- `app/tabs/classification_tab.py`
- `app/tabs/kraken2_helpers.py`
- `app/layouts/classification_layout.py`
- `app/components/organism_components.py`

**Read-only:**
- `app/callbacks.py`
- `app/utils/chart_builders.py`
- `app/utils/plotly_theme.py`

**Focus:** Organism list readability, Sankey/Sunburst utility for non-experts, read count labels, taxonomy hierarchy visualization, donut chart clarity, empty states.

### results-quality
**Read & modify:**
- `app/tabs/qc_tab.py`
- `app/layouts/qc_layout.py`
- `app/tabs/validation_tab.py`
- `app/layouts/validation_layout.py`
- `app/components/coverage_plots.py`

**Read-only:**
- `app/callbacks.py`
- `app/utils/plotly_theme.py`
- `app/utils/export_utils.py`

**Focus:** QC metric translation (Q20/Q30/N50 to quality ratings), pass rate prominence, FASTP stats column reduction, validation result clarity (confirmed/unconfirmed), coverage visualization, action guidance for poor quality.

### setup-ux
**Read & modify:**
- `app/tabs/config_tab.py`
- `app/layouts/config_layout.py`
- `app/tabs/watchlist_tab.py`
- `app/layouts/watchlist_layout.py`
- `app/tabs/preparation_tab.py`
- `app/layouts/preparation_layout.py`
- `app/components/config_form.py`
- `app/components/taxid_mapping_ui.py`

**Read-only:**
- `app/callbacks.py`

**Focus:** Settings grouping, dangerous option guarding, watchlist enable/disable intuitiveness, quick-start discoverability, preparation wizard step sequence clarity, readiness checklist pass/fail visibility, error states, terminology (replace "params" with "settings").

### field-ux
**Read & modify:**
- `app/assets/styles.css` (sole owner -- other agents must not modify this file)
- `app/components/modern_components.py` (sizing/contrast changes only)
- `app/components/sample_selector.py`

**Read-only (audit all):**
- All layout files
- All tab files
- `app/components/header.py`
- `app/assets/custom.js`

**Focus:** Touch target sizing, font sizes, WCAG AA contrast, above-fold critical info, color-blind safety, dark mode readability, responsive behavior on 13-inch screens and tablets. Constrained to sizing, contrast, and touch-target changes only -- no functional or layout-structural changes.

### CSS Conflict Resolution

**`styles.css` is owned exclusively by field-ux.** Other agents must not modify it directly. If a tab-specific agent needs a CSS change, they should:
1. Add inline styles or scoped `className` props in their Python layout files
2. Document any CSS changes they would like field-ux to make in their findings

The ux-lead resolves any remaining conflicts in Phase 2.

### Shared Files

- **`app/app.py`** and **`app/layouts/main_layout.py`**: Owned by ux-lead only (Phase 2). Read-only for all Phase 1 agents.
- **`app/callbacks.py`**: Read-only for all agents. If a callback change is needed, document it for ux-lead to implement in Phase 2.

## Deliverable

Consolidated report at `docs/ux-evaluation-report.md` containing:
1. Per-tab issue inventory with severity ratings (critical/major/minor)
2. Changes implemented with file and line references
3. Remaining items too large for this pass
4. Field-readiness scorecard

## Success Criteria

- Scientist/first-responder identifies threats within 30 seconds of opening Dashboard
- No bioinformatics jargon without tooltip or plain-language label
- All interactive elements >= 44px touch targets
- WCAG AA contrast throughout
- Consistent visual language across all tabs
- All changes preserve existing callback functionality (no regressions)
- Smoke test passes: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`
