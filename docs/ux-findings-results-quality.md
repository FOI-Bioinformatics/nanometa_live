# UX Findings: Results Quality (QC Tab & Validation Tab)

**Evaluator:** results-quality specialist
**Date:** 2026-03-15
**Scope:** QC tab, Validation tab, Coverage plots
**Target users:** Scientists, first-responders, soldiers with basic lab literacy but no bioinformatics expertise

---

## Audit Summary

### What was already good

The existing implementation had several well-designed elements:

- **KeyMetricsSummaryCard** with color-coded pass rate and classification rate bars
- **BaseQualityCard** with nanopore-calibrated Q20/Q30 thresholds (not Illumina defaults)
- **FilteringBreakdownVisual** with stacked bar chart and removal reason breakdown
- **Per-sample table** with conditional color styling based on quality thresholds
- **Validation result cards** with clear Confirmed/Partial/Low Confidence/No Data status badges
- **Collapsible advanced sections** to avoid overwhelming operators with technical detail
- **Help section** at the bottom of the QC tab

### Issues identified and fixed

#### QC Tab (7 fixes)

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | No action guidance when quality is poor | High | Added dynamic `qc-action-guidance-container` with callback that generates contextual alerts (green/amber/red) with plain-language next steps |
| 2 | Q20/Q30 labels are jargon ("bases >= Q20") | Medium | Changed sub-labels to plain-language verdict ("Good"/"Fair"/"Poor"), added "(99% accurate)" / "(99.9% accurate)" inline explanation |
| 3 | Base Quality card header lacks context | Medium | Added subtitle: "How accurate is each letter of the DNA sequence?" |
| 4 | Read Statistics card header lacks context | Medium | Added subtitle: "How long are the DNA sequences?" |
| 5 | N50 is unexplained jargon | Medium | Added "(length metric)" inline label, changed sub-label from raw bp to "Good"/"Fair"/"Short" verdict |
| 6 | Section headings lack context for operators | Low | Added descriptive sub-headings: "How good is the raw data?", "How many sequences passed quality checks?", "Individual results for each barcode/sample" |
| 7 | Help section lacked actionable "what to do" content | Medium | Rewrote help section with two-column layout: "Key Terms" (Q20, Q30, N50, GC explained) and "What To Do" (specific actions for each problem) |

**Per-sample table column improvements:**
- "Quality" -> "Avg. Quality" with expanded tooltip
- "Classified" -> "Identified" with better tooltip
- "Status" tooltip expanded with plain-language meanings

#### Validation Tab (9 fixes)

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | Tab labels use tool names ("BLAST", "minimap2") | High | Changed to "Sequence Matching" and "Genome Coverage" |
| 2 | Page title/description uses technical jargon | High | Rewrote: "Species Confirmation Results" with plain explanation of what confirmation means |
| 3 | Result card shows "TaxID" in footer | Medium | Removed TaxID from card footer (kept only Sample) |
| 4 | Result card metric labels are technical | Medium | "Validated" -> "Confirmed", "Identity" -> "Match Quality", "Reads" -> "Sequences", "MapQ" -> "Alignment Score", "Coverage" -> "Genome Covered" |
| 5 | No status explanation on result cards | Medium | Added one-line plain-language interpretation below header (e.g., "Strong match to reference genome") |
| 6 | Help section uses bioinformatics jargon | Medium | Rewrote with "What The Status Means" and "What To Do" columns, with specific actions per status |
| 7 | Identity distribution accordion title is technical | Low | Changed to "Match Quality Chart (Advanced)" |
| 8 | Stats table column headers are technical | Low | Changed to plain labels with tooltips: "Total Seqs", "Confirmed", "Confirmed %", "Match %", "Genome Covered" |
| 9 | MapQ filter label is jargon | Low | Changed "Min MapQ filter" to "Confidence filter" with rewritten tooltip |

#### Coverage Plots (5 fixes)

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | Stats summary uses raw jargon ("Breadth", "Mean Depth") | High | Changed to "Genome Covered", "Avg. Depth", "Typical Depth", "Peak Depth", "Genome Size" with hover tooltips |
| 2 | No interpretation of coverage results | High | Added color-coded interpretation alert below stats (Good/Partial/Low coverage with actionable text) |
| 3 | Coverage depth figure title is technical | Medium | Changed to "How deeply each part of the genome is covered" |
| 4 | Axis labels are jargon | Medium | Changed to "Position along genome", "Number of overlapping sequences", etc. |
| 5 | Cumulative coverage and histogram titles/axes are technical | Low | Rewritten with descriptive, plain-language labels |

---

## Verification

- Smoke test: `create_app()` succeeds with 180 callbacks (no regressions)
- No callback Input/Output/State decorators were modified (no MATCH wildcard risk)
- No `persistence=True` added to any `dbc.Tabs`
- No `styles.css` modifications
- All changes are layout text, component labels, and one new callback (`update_qc_action_guidance`)

## Files Modified

- `app/layouts/qc_layout.py` - Section headings, table tooltips, help section rewrite
- `app/tabs/qc_tab.py` - New action guidance callback
- `app/components/organism_components.py` - BaseQualityCard and ReadStatisticsCard plain-language labels
- `app/layouts/validation_layout.py` - Tab labels, page description, result card simplification, help rewrite, table headers
- `app/tabs/validation_tab.py` - Chart titles and threshold annotations
- `app/components/coverage_plots.py` - Stats summary labels, interpretation alert, figure titles/axes

## CSS Changes Needed (Not Implemented - Document Only)

No CSS changes were required. All improvements were achieved through inline styles and component text changes.

## Remaining Recommendations

1. **Glossary tooltip system**: Consider a persistent glossary panel (or popover) that operators can reference for all technical terms. The current per-component tooltips help, but a centralized reference could reduce cognitive load further.

2. **Confidence threshold configuration**: The current thresholds (Q20 >= 65%, Q30 >= 45%, pass rate >= 60%) are hardcoded. Field operators in different environments may need different thresholds. Consider making these configurable in the Configuration tab.

3. **Print-friendly report**: The export buttons generate CSV files, which are not suitable for field reporting. Consider adding a "Print Summary" button that generates a single-page HTML report with the quality verdict, key metrics, and validation summary - suitable for printing or sharing.
