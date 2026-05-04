# UX Evaluation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate and fix all Nanometa Live tabs for scientists, first-responders, and soldiers making fast decisions without bioinformatics knowledge.

**Architecture:** Team of 6 agents -- 5 domain specialists running in parallel (Phase 1), then 1 lead synthesizing and resolving conflicts (Phase 2). Each specialist audits their assigned tabs, documents issues by severity, and implements fixes directly. The lead reviews all changes, resolves CSS/consistency conflicts, and writes the final report.

**Tech Stack:** Python Dash 4, dash-bootstrap-components, dash-ag-grid, Plotly, CSS

**Spec:** `docs/superpowers/specs/2026-03-15-ux-evaluation-design.md`

**Base path:** `/Users/andreassjodin/Desktop/deving/nanometa_live/nanometa_live`

---

## Dash 4 Technical Constraints (ALL AGENTS MUST READ)

These constraints apply to every agent. Violating any of them can break the entire application.

1. **Callback graph fragility**: A single MATCH wildcard mismatch can break ALL callbacks in the entire app. Do not add or modify callback Input/Output/State decorators without verifying the callback graph loads.
2. **MATCH + plain-ID mixing forbidden**: Dash 4 does not allow mixing MATCH-wildcard Outputs with plain-ID Outputs in the same callback. Use `set_props()` for the plain-ID update instead.
3. **dbc.Tabs persistence conflict**: `persistence=True` on Tabs can conflict with callbacks that write `active_tab`. Do not add persistence to Tabs components.
4. **Use dash-ag-grid, not dash_table**: All DataTables have been migrated to dash-ag-grid (v33.3.3). New tables must use ag-grid.
5. **Existing tooltip_components.py**: Check `app/components/tooltip_components.py` before creating new tooltip patterns -- reuse existing components where possible.
6. **Smoke test after changes**: Every agent must verify: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

---

## Chunk 1: Phase 1 -- Parallel Specialist Audits

All 5 tasks in this chunk run simultaneously. Each agent works independently on their assigned files.

### Task 1: dashboard-ux (Dashboard Tab Evaluation & Fixes)

**Agent type:** ui-designer
**Skill:** nanometa-dash

**Files:**
- Modify: `app/layouts/dashboard_layout.py` (1133 LOC)
- Modify: `app/tabs/dashboard_tab.py` (2509 LOC)
- Modify: `app/components/modern_components.py` (872 LOC)
- Modify: `app/components/pathogen_alert.py` (574 LOC)
- Modify: `app/components/watchlist_manager_ui.py` (535 LOC)
- Modify: `app/components/watchlist_modal.py` (408 LOC)
- Modify: `app/components/header.py` (195 LOC)
- Read-only: `app/app.py`, `app/callbacks.py`, `app/utils/chart_builders.py`

**Context for agent:**
- Target users: scientists, first-responders, soldiers with basic lab literacy (DNA, bacteria vs. virus, sample quality) but NO bioinformatics expertise
- Must work in field (gloves, small screens, time pressure) AND lab settings
- The Dashboard is the first thing users see -- must enable go/no-go decision within 30 seconds
- Pre-flight checklist was just made collapsible (dbc.Collapse with id="preflight-collapse")
- App uses dash-ag-grid (NOT dash_table), dash-bootstrap-components, Plotly
- Do NOT modify `app/assets/styles.css` -- use inline styles or className props. Document CSS changes needed for field-ux agent
- Smoke test after changes: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

**Evaluation checklist:**

- [ ] **Step 1: Read all assigned files**
  Read every file listed above to understand current layout, callbacks, and component structure.

- [ ] **Step 2: Audit -- Decision support**
  Evaluate: Can a user identify threats within 30 seconds? Is the visual hierarchy threats > status > details? Are traffic light indicators unmistakable at a glance? Document each issue with severity (critical/major/minor).

- [ ] **Step 3: Audit -- Lab literacy**
  Scan all user-facing text for bioinformatics jargon. Check: metric card labels, alert messages, table column headers, button labels, tooltip text. Flag any term a first-responder would not understand. Document each issue.

- [ ] **Step 4: Audit -- Empty/error states**
  Check what the dashboard shows when: no results exist yet, pipeline is not running, no pathogens detected, no samples found. Are empty states helpful and actionable?

- [ ] **Step 5: Audit -- Component consistency**
  Check: card styles consistent? Button patterns consistent? Color coding consistent with other tabs? Status indicators follow same pattern?

- [ ] **Step 6: Implement fixes -- Layout and labels**
  Fix all critical and major issues found in steps 2-5. For each fix:
  - Replace jargon labels with plain language (add dbc.Tooltip for technical detail)
  - Improve visual hierarchy (threats prominent, status clear, details secondary)
  - Improve empty states with actionable guidance
  - Ensure traffic light status is unmistakable

- [ ] **Step 7: Implement fixes -- Header**
  Review `header.py` for branding clarity, navigation discoverability, and field readability.

- [ ] **Step 8: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`
  Expected: No errors. App object created successfully.

- [ ] **Step 9: Write findings**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-findings-dashboard.md` with:
  - Issue inventory (severity, description, file:line, status: fixed/deferred)
  - CSS changes requested for field-ux
  - Summary of all changes made

---

### Task 2: results-organisms (Organisms + Taxonomy Tab Evaluation & Fixes)

**Agent type:** nanometa-dash

**Files:**
- Modify: `app/tabs/main_tab.py` (1245 LOC) -- Organisms tab
- Modify: `app/tabs/classification_tab.py` (1415 LOC) -- Taxonomy/Classification
- Modify: `app/tabs/kraken2_helpers.py` (375 LOC)
- Modify: `app/layouts/classification_layout.py` (298 LOC)
- Modify: `app/components/organism_components.py` (1564 LOC)
- Read-only: `app/callbacks.py`, `app/utils/chart_builders.py`, `app/utils/plotly_theme.py`

**Context for agent:**
- Target users have basic lab literacy but NO bioinformatics expertise
- These tabs show organism detection results: species lists, taxonomic trees, Sankey diagrams, sunburst charts, donut charts
- Users need to quickly answer: "What organisms are in my sample?" and "Are any of them dangerous?"
- Kraken2 reports use whitespace-indented taxonomy with rank codes (D, P, C, O, F, G, S) -- users should not need to know these codes
- Do NOT modify `app/assets/styles.css` -- use inline styles or className props
- Do NOT modify callback Input/Output/State decorators without verifying callback graph loads
- Smoke test: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

**Evaluation checklist:**

- [ ] **Step 1: Read all assigned files**
  Read every file listed above. Pay attention to how organism data is displayed, what labels are used, and how visualizations are configured.

- [ ] **Step 2: Audit -- Organism list readability**
  Can a non-expert parse species names? Are scientific names accompanied by common names where possible? Is the organism table scannable? Are read counts labeled meaningfully (e.g., "DNA fragments matched" not just "reads")?

- [ ] **Step 3: Audit -- Visualization utility**
  Evaluate Sankey, sunburst, and donut charts: Are they useful or confusing for non-bioinformaticians? Do legends make sense? Are segments readable? Does the taxonomy hierarchy visualization explain parent-child relationships?

- [ ] **Step 4: Audit -- Jargon and labels**
  Scan all user-facing text: column headers, axis labels, tooltips, empty states. Flag any bioinformatics jargon (taxid, rank codes, k-mer, clade, etc.) without plain-language context.

- [ ] **Step 5: Audit -- Empty states**
  What happens when no organisms detected? When classification is still running? When a sample has no data yet? Are these states helpful?

- [ ] **Step 6: Implement fixes -- Labels and tooltips**
  Replace jargon with plain language. Add dbc.Tooltip components where technical detail is needed. Make rank codes human-readable (S -> Species, G -> Genus, etc.) in user-facing displays.

- [ ] **Step 7: Implement fixes -- Visualizations**
  Improve chart readability: larger labels, clearer legends, meaningful hover text. If Sankey or sunburst is confusing for non-experts, add explanatory text or simplify default view.

- [ ] **Step 8: Implement fixes -- Empty states**
  Add clear, actionable empty state messages for all no-data scenarios.

- [ ] **Step 9: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`
  Expected: No errors.

- [ ] **Step 10: Write findings**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-findings-results-organisms.md` with issue inventory, CSS change requests, and summary of changes.

---

### Task 3: results-quality (QC + Validation Tab Evaluation & Fixes)

**Agent type:** nanometa-dash

**Files:**
- Modify: `app/tabs/qc_tab.py` (1265 LOC)
- Modify: `app/layouts/qc_layout.py` (460 LOC)
- Modify: `app/tabs/validation_tab.py` (717 LOC)
- Modify: `app/layouts/validation_layout.py` (625 LOC)
- Modify: `app/components/coverage_plots.py` (283 LOC)
- Read-only: `app/callbacks.py`, `app/utils/plotly_theme.py`, `app/utils/export_utils.py`

**Context for agent:**
- Target users have basic lab literacy but NO bioinformatics expertise
- QC tab shows sequencing quality metrics: Q20/Q30 scores, N50, read lengths, pass rates
- Nanopore-specific thresholds (NOT Illumina): Q20 >=65% is good, Q30 >=45% is good
- Validation tab shows species confirmation via BLAST/minimap2 alignment
- Users need to answer: "Is my data good enough?" and "Are the species identifications confirmed?"
- Do NOT modify `app/assets/styles.css`
- Smoke test: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

**Evaluation checklist:**

- [ ] **Step 1: Read all assigned files**

- [ ] **Step 2: Audit -- QC metric comprehension**
  Can a non-expert understand Q20, Q30, N50, read length distribution? Are these translated to plain language (e.g., "Data Quality: Good/Fair/Poor")? Is the pass rate prominent and traffic-light colored?

- [ ] **Step 3: Audit -- QC table columns**
  Are FASTP stats columns reduced to essentials for operators? Can a first-responder identify which columns matter? Are column headers self-explanatory?

- [ ] **Step 4: Audit -- Validation clarity**
  Does the validation tab clearly show "confirmed" vs. "unconfirmed" species? Or does it show raw alignment statistics that operators cannot interpret? Is coverage visualization meaningful for non-experts?

- [ ] **Step 5: Audit -- Action guidance**
  When quality is poor, does the UI tell the user what to DO? (e.g., "Low quality detected -- consider re-sequencing" or "Insufficient data -- continue sequencing")

- [ ] **Step 6: Implement fixes -- QC translation**
  Add quality rating badges/indicators alongside raw metrics. Translate Q20/Q30 to "Quality: Good/Fair/Poor" with color coding. Make pass rate the most prominent element. Add tooltips for technical details.

- [ ] **Step 7: Implement fixes -- Validation simplification**
  Reframe validation results as "Confirmed"/"Unconfirmed"/"Pending" with plain-language explanations. Simplify coverage plots for non-experts. Add action guidance for poor quality states.

- [ ] **Step 8: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

- [ ] **Step 9: Write findings**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-findings-results-quality.md`

---

### Task 4: setup-ux (Configuration + Watchlist + Preparations Tab Evaluation & Fixes)

**Agent type:** nanometa-dash

**Files:**
- Modify: `app/tabs/config_tab.py` (1599 LOC)
- Modify: `app/layouts/config_layout.py` (314 LOC)
- Modify: `app/tabs/watchlist_tab.py` (1322 LOC)
- Modify: `app/layouts/watchlist_layout.py` (1522 LOC)
- Modify: `app/tabs/preparation_tab.py` (1875 LOC)
- Modify: `app/layouts/preparation_layout.py` (1050 LOC)
- Modify: `app/components/config_form.py` (709 LOC)
- Modify: `app/components/taxid_mapping_ui.py` (633 LOC)
- Read-only: `app/callbacks.py`

**Context for agent:**
- Target users have basic lab literacy but NO bioinformatics expertise
- Setup tabs are used BEFORE a sequencing run to configure the system
- Configuration: pipeline settings, directory paths, tool selection
- Watchlist: pathogen monitoring lists (Clinical Pathogens, Foodborne, Water, etc.)
- Preparations: readiness checklist, database downloads, genome downloads, BLAST DB building
- Users need clear step-by-step guidance. "What do I do first? What do I do next?"
- Dangerous settings (e.g., deleting databases) must be guarded with confirmation
- Replace "params" with "settings," "taxid" with contextual explanations
- Do NOT modify `app/assets/styles.css`
- Known issue: Enable/Disable All watchlist can cause 30s+ UI freeze with 69 pathogens
- Smoke test: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

**Evaluation checklist:**

- [ ] **Step 1: Read all assigned files**

- [ ] **Step 2: Audit -- Configuration clarity**
  Are settings grouped logically? Are dangerous options guarded with confirmation dialogs? Are labels self-explanatory? Is there guidance for which settings to change vs. leave at defaults?

- [ ] **Step 3: Audit -- Watchlist usability**
  Is enable/disable intuitive? Is the quick-start feature discoverable? Can a user understand what a watchlist does without training? Are pathogen names clear?

- [ ] **Step 4: Audit -- Preparation workflow**
  Is the step sequence clear and ordered? Is progress visible? Does the readiness checklist show pass/fail obviously? Are fix instructions actionable? What happens when downloads fail?

- [ ] **Step 5: Audit -- Terminology**
  Scan all user-facing text for jargon: "params," "taxid," "BLAST DB," "index," "reference genome." Flag and propose plain-language replacements.

- [ ] **Step 6: Implement fixes -- Configuration**
  Group settings logically with section headers. Add confirmation for dangerous operations. Replace jargon labels. Add "recommended" badges for default settings. Add help text for non-obvious settings.

- [ ] **Step 7: Implement fixes -- Watchlist**
  Improve enable/disable UX. Make quick-start more discoverable. Add plain-language descriptions for each built-in watchlist. Add tooltips for pathogen names.

- [ ] **Step 8: Implement fixes -- Preparations**
  Improve step sequence clarity. Add progress indicators. Improve readiness checklist pass/fail visibility. Add actionable error messages for failed downloads. Improve guidance text.

- [ ] **Step 9: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

- [ ] **Step 10: Write findings**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-findings-setup.md`

---

### Task 5: field-ux (Cross-Cutting Field Deployment Review & Fixes)

**Agent type:** ui-designer

**Files:**
- Modify: `app/assets/styles.css` (2848 LOC) -- sole owner
- Modify: `app/components/modern_components.py` (872 LOC) -- sizing/contrast only
- Modify: `app/components/sample_selector.py` (121 LOC)
- Read-only (audit all):
  - `app/layouts/dashboard_layout.py`, `app/layouts/classification_layout.py`, `app/layouts/qc_layout.py`, `app/layouts/validation_layout.py`, `app/layouts/config_layout.py`, `app/layouts/watchlist_layout.py`, `app/layouts/preparation_layout.py`, `app/layouts/main_layout.py`
  - `app/tabs/dashboard_tab.py`, `app/tabs/main_tab.py`, `app/tabs/classification_tab.py`, `app/tabs/qc_tab.py`, `app/tabs/validation_tab.py`, `app/tabs/config_tab.py`, `app/tabs/watchlist_tab.py`, `app/tabs/preparation_tab.py`
  - `app/components/header.py`
  - `app/assets/custom.js`

**Context for agent:**
- This is a CROSS-CUTTING review across ALL tabs, focused exclusively on field deployment readiness
- Users include soldiers and first-responders operating in field conditions: gloved hands, small screens, low light, time pressure
- App has a theme toggle (light/dark mode) -- both modes must be field-ready
- You own `styles.css` exclusively. Other agents will request CSS changes through their findings docs
- Constrain changes to sizing, contrast, touch-targets, and responsive behavior ONLY -- no functional or layout-structural changes
- Use Dash 4 CSS selectors (`.dash-dropdown .dash-dropdown-menu` not `.Select-menu-outer`)
- Smoke test: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

**Evaluation checklist:**

- [ ] **Step 1: Read styles.css and all layout files**
  Build a mental model of the current CSS structure, component sizing, and responsive behavior.

- [ ] **Step 2: Audit -- Touch targets**
  Scan all buttons, links, dropdowns, checkboxes, radio buttons, and interactive elements across all tabs. Flag any with click/touch area < 44x44px. Check spacing between adjacent interactive elements (min 8px gap).

- [ ] **Step 3: Audit -- Font sizes**
  Check all text sizes. Body text must be >= 16px, labels >= 14px, headings appropriately scaled. Flag any text that would be unreadable at arm's length in field conditions.

- [ ] **Step 4: Audit -- Contrast ratios**
  Check all text-on-background combinations for WCAG AA compliance (4.5:1 for normal text, 3:1 for large text and UI components). Check BOTH light and dark themes. Flag failures.

- [ ] **Step 5: Audit -- Color-blind safety**
  Check if any status indicators rely solely on red/green distinction. Verify that color is supplemented with icons, text, or patterns. Check traffic light indicators, pass/fail badges, severity colors.

- [ ] **Step 6: Audit -- Above-fold critical info**
  On a 13-inch screen (1280x800 viewport), check each tab: is the most important information visible without scrolling? Flag tabs where critical info is below fold.

- [ ] **Step 7: Audit -- Responsive behavior**
  Check layout at 1280px, 1024px, and 768px widths. Flag elements that overflow, overlap, or become unusable at smaller sizes.

- [ ] **Step 8: Implement fixes -- styles.css**
  Fix all critical and major issues. Organize changes by category:
  - Touch target sizing (min-height, min-width, padding)
  - Font size overrides
  - Contrast fixes (both themes)
  - Color-blind safe indicators (add icons/borders alongside color)
  - Responsive breakpoints
  - Dark mode contrast fixes

- [ ] **Step 9: Implement fixes -- Components**
  Fix sizing/contrast issues in `modern_components.py` and `sample_selector.py` that cannot be addressed via CSS alone.

- [ ] **Step 10: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

- [ ] **Step 11: Write findings**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-findings-field.md` with:
  - Field-readiness scorecard (per-tab scores for touch, contrast, font, responsive)
  - All CSS changes made (with line references)
  - Issues deferred

---

## Chunk 2: Phase 2 -- Lead Synthesis & Report

This chunk is blocked on all 5 tasks in Chunk 1.

### Task 6: ux-lead (Synthesis, Conflict Resolution & Final Report)

**Agent type:** ui-designer

**Files:**
- Read: All 5 findings docs (`docs/ux-findings-*.md`)
- Modify: `app/app.py` -- if structural changes needed
- Modify: `app/layouts/main_layout.py` -- if tab ordering/grouping changes needed
- Modify: `app/callbacks.py` -- implement callback changes documented by Phase 1 agents
- Modify: `app/assets/styles.css` -- resolve any CSS conflicts
- Modify: Any file if conflict resolution needed
- Create: `docs/ux-evaluation-report.md` -- final consolidated report

**Context for agent:**
- You are the UX lead. All 5 specialists have completed their audits and fixes.
- Read all 5 findings documents to understand what was done, what was deferred, and what conflicts exist.
- Your job: resolve conflicts, verify cross-tab consistency, and write the final report.
- Pay attention to `styles.css` changes from field-ux and inline style additions from other agents -- ensure they are compatible.
- Check that CSS change requests from other agents (documented in their findings) have been addressed by field-ux. If not, implement them.
- Smoke test: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`

- [ ] **Step 1: Read all 5 findings documents**
  - `docs/ux-findings-dashboard.md`
  - `docs/ux-findings-results-organisms.md`
  - `docs/ux-findings-results-quality.md`
  - `docs/ux-findings-setup.md`
  - `docs/ux-findings-field.md`

- [ ] **Step 2: Check cross-tab consistency**
  Verify: Are card styles consistent across tabs? Do buttons follow the same pattern? Is color coding consistent (e.g., red always means critical, green always means good)? Are tooltips formatted consistently?

- [ ] **Step 3: Resolve CSS conflicts**
  Check if field-ux's CSS changes conflict with inline styles added by other agents. Check if CSS change requests from dashboard-ux, results-organisms, results-quality, and setup-ux were addressed. Implement any missing CSS changes.

- [ ] **Step 4: Review unaddressed CSS requests**
  Read CSS change requests from each agent's findings doc. Implement any that field-ux did not handle.

- [ ] **Step 5: Implement documented callback changes**
  Check each findings doc for callback changes that Phase 1 agents could not make (callbacks.py is read-only for them). Implement these changes in `app/callbacks.py`, following Dash 4 constraints (no MATCH + plain-ID mixing, no dbc.Tabs persistence conflicts).

- [ ] **Step 6: Verify consistency fixes**
  If inconsistencies found in Step 2, implement fixes. This may involve modifying layout files or component files.

- [ ] **Step 7: Smoke test**
  Run: `conda run -n nf-core python -c "from nanometa_live.app.app import create_app; create_app()"`
  Expected: No errors.

- [ ] **Step 8: Write final report**
  Create `/Users/andreassjodin/Desktop/deving/nanometa_live/docs/ux-evaluation-report.md` containing:

  ```markdown
  # UX Evaluation Report -- Nanometa Live

  **Date:** 2026-03-15
  **Team:** 6 agents (ux-lead, dashboard-ux, results-organisms, results-quality, setup-ux, field-ux)
  **Target users:** Scientists, first-responders, soldiers with basic lab literacy

  ## Executive Summary
  [2-3 sentences on overall findings and improvements made]

  ## Per-Tab Issue Inventory
  ### Dashboard
  | Severity | Issue | Status | File:Line |
  |----------|-------|--------|-----------|
  | ... | ... | Fixed/Deferred | ... |

  ### Organisms
  [same format]

  ### Taxonomy (Classification)
  [same format]

  ### Quality Control
  [same format]

  ### Validation
  [same format]

  ### Configuration
  [same format]

  ### Watchlist
  [same format]

  ### Preparations
  [same format]

  ## Field-Readiness Scorecard
  | Tab | Touch Targets | Contrast | Font Sizes | Responsive | Overall |
  |-----|--------------|----------|------------|------------|---------|
  | Dashboard | X/10 | X/10 | X/10 | X/10 | X/10 |
  | ... | ... | ... | ... | ... | ... |

  ## Changes Implemented
  [Summary of all changes with file references]

  ## Remaining Items
  [Issues deferred or too large for this pass]

  ## Consistency Audit
  [Cross-tab patterns verified or fixed]
  ```

- [ ] **Step 9: Clean up findings docs**
  The 5 individual findings docs can remain as reference, or be consolidated into the final report appendix.
