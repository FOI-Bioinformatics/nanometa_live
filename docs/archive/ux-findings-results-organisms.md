# UX Findings: Organisms & Classification Tabs

**Evaluator:** results-organisms specialist
**Date:** 2026-03-15
**Scope:** Organisms tab (main_tab.py, main_layout.py, organism_components.py) and Taxonomy/Classification tab (classification_tab.py, classification_layout.py, kraken2_helpers.py)
**Target users:** Scientists, first-responders, and field operators with basic lab literacy but no bioinformatics expertise.

---

## Summary

The Organisms and Classification tabs were already in reasonable shape for operator use. The main issues were residual bioinformatics jargon in labels, hover text, and table columns. Visualizations (Sankey, Sunburst) had appropriate designs but lacked orientation cues for non-experts. All identified issues have been addressed with targeted fixes.

**Overall UX score before fixes:** 7.5/10
**Overall UX score after fixes:** 8.5/10

---

## Issues Found and Fixed

### 1. Detailed data table column jargon (main_layout.py)

**Problem:** The "Rank" column displayed raw single-letter codes (S, G, F) that are meaningful only to bioinformaticians. The "Taxonomy ID" column header uses database-specific terminology.

**Fix:**
- Renamed "Rank" to "Classification Level" with a JS valueFormatter that converts codes to full names (Domain, Kingdom, Phylum, Class, Order, Family, Genus, Species).
- Renamed "Taxonomy ID" to "Database ID" and set `hide: True` by default (accessible via column menu for power users).
- Reordered columns: Name, Classification Level, DNA Sequences, Abundance, (hidden) Database ID.

### 2. Classification tab jargon (classification_layout.py)

**Problem:** Several labels used terms unfamiliar to non-experts:
- "Max Taxa Per Level" -- "taxa" is a bioinformatics term
- Taxonomy level dropdowns showed "D - Domain", "P - Phylum" etc. with single-letter codes
- "Advanced Filter Options" was too generic

**Fix:**
- Changed "Max Taxa Per Level" to "Organisms Per Level", options from "5 taxa" to "5 organisms"
- Changed dropdown labels from "D - Domain" to "Domain (broadest)", "G - Genus" to "Genus (closely related)", "S - Species" to "Species (most specific)" -- adding orientation context
- Changed accordion title to "Advanced Settings (Domain filters, taxonomy levels)" for discoverability
- Added subtitle under main header: "Shows how detected organisms are related to each other in the tree of life"
- Renamed visualization toggle labels: "Sankey Diagram" to "Flow View (Sankey)", "Sunburst Chart" to "Ring View (Sunburst)"

### 3. Sankey/Sunburst hover text uses "Reads" (classification_tab.py)

**Problem:** Hover tooltips on nodes and links used "Reads" and "Rank" -- terms that mean nothing to a lab technician or soldier.

**Fix:**
- Node hover: "Rank:" changed to "Level:", "Reads:" changed to "DNA sequences:"
- Link hover: Changed arrow notation to "contains" (e.g., "Bacteria (Domain) contains Firmicutes (Phylum)"), "Reads:" to "DNA sequences:"
- Sunburst hover: "Level:" prefix added to rank display, "Reads:" to "DNA sequences:", "Of parent:" to "Of parent group:"

### 4. Chart titles and legends (classification_tab.py)

**Problem:** Chart titles ("Taxonomic Classification Flow", "Taxonomic Classification") used formal taxonomy terminology. Color legends just listed rank names without orientation cues.

**Fix:**
- Sankey title: "How Organisms Are Classified"
- Sunburst title: "Organism Classification Overview"
- Sankey legend: Added "(broad)" and "(specific)" markers at legend edges
- Sunburst legend: Changed prefix to "Classification levels (center=broad, outer=specific):"

### 5. Organism card "Rank" label (organism_components.py)

**Problem:** OrganismCard showed "Rank: Species" -- the word "Rank" is jargon without context.

**Fix:** Changed to "Identified at Species level" -- immediately communicates the precision of identification.

### 6. Confidence badge lacks explanation (organism_components.py)

**Problem:** "High Confidence", "Medium Confidence", "Low Confidence" badges had no explanation of what determines confidence. Non-experts would not know this is based on read count.

**Fix:** Added a dbc.Tooltip to the confidence badge: "Based on the number of matching DNA sequences. More sequences means higher confidence that this organism is truly present in the sample."

### 7. Summary card "Classification Rate" (organism_components.py)

**Problem:** "Classification Rate" is opaque to non-bioinformaticians. What is being "classified"?

**Fix:**
- Changed label to "Sequences Identified"
- Added tooltip: "Percentage of DNA sequences that could be matched to a known organism. Higher is better. Values below 50% may indicate database limitations or novel organisms."
- Changed "DNA Sequences" to "DNA Sequences Analyzed" for clarity.

### 8. Sankey node label truncation too aggressive (classification_tab.py)

**Problem:** Species names were truncated at 25 characters, which cuts off important binomial names (e.g., "Staphylococcus epidermidis" becomes "Staphylococcus epidermid...").

**Fix:** Increased MAX_LABEL_LEN from 25 to 30 characters. Full names remain available in hover tooltips.

### 9. Empty state messages not actionable (classification_tab.py)

**Problem:** Empty states said "No Classification Data" without guidance on what to do.

**Fix:**
- Main empty state: "No Classification Data Yet" with message "This view will show how detected organisms are grouped and related once analysis results are available. Check that a sample is selected and the pipeline is running."
- Missing ranks: Removed raw rank codes from user-facing message, replaced with "Try adjusting filter settings or selecting a different preset view."
- Need-more-levels: Changed "Sankey diagram requires at least 2 taxonomy levels" to "The flow diagram needs at least 2 classification levels to show relationships" with suggestion to try Ring View.

### 10. chart_builders.py hover text (chart_builders.py)

**Problem:** Pathogen abundance chart hover used "Reads" and "Rank" labels.

**Fix:** Changed to "DNA sequences" and "Level" for consistency across all visualizations.

---

## Items NOT Changed (Assessed and Deemed Acceptable)

1. **Sankey/Sunburst complexity:** These visualizations are inherently complex, but the existing help section (collapsible accordion with reading instructions) provides adequate guidance. No structural changes needed.

2. **kraken2_helpers.py constants:** RANK_NAMES, RANK_NORMALIZATION, and color schemes are internal constants not shown directly to users. No changes needed.

3. **Organism card layout:** Already uses "DNA sequences" language, visual abundance bars, and color-coded confidence badges. Well designed for operator use.

4. **Watched species section:** Alert banners, detected/not-detected split, and BLAST validation badges are clear and actionable.

5. **Export report text format:** Already uses plain language abbreviations (Sp., Gen., Fam.) with a legend at the bottom.

6. **Filter controls:** "Minimum DNA Sequences" and "Minimum Abundance (%)" are already clear.

---

## CSS Change Requests

No CSS changes needed. All fixes were implemented via inline styles, className props, and component properties. The existing styles.css supports the changes.

---

## Files Modified

| File | Changes |
|------|---------|
| `app/layouts/main_layout.py` | Table columns: renamed Rank to Classification Level with formatter, hid Taxonomy ID, reordered |
| `app/layouts/classification_layout.py` | Labels: taxa->organisms, rank codes->full names, added subtitle, renamed view toggle labels, improved accordion title |
| `app/tabs/classification_tab.py` | Hover templates: Reads->DNA sequences, Rank->Level, chart titles, legend annotations, empty states, label truncation |
| `app/components/organism_components.py` | Confidence tooltip, rank display text, summary card labels and tooltips |
| `app/utils/chart_builders.py` | Hover text: Reads->DNA sequences, Rank->Level |

---

## Verification

- Smoke test: `create_app(config={}, data_dir='/tmp', backend_manager=None)` -- PASSED
- All module imports verified -- PASSED
- No callback signatures modified (only layout and display text changes)
- No new component IDs added to callback Input/Output/State decorators
- Pattern-matching ID `{"type": "confidence-badge", "taxid": ...}` added for tooltips only (not used in any callback)
