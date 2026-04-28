# UX Findings: Dashboard Tab

**Evaluator:** dashboard-ux specialist
**Date:** 2026-03-15
**Scope:** Dashboard tab, header, pathogen alerts, watchlist UI, modern components
**Target users:** Scientists, first responders, and field operators with basic lab literacy but no bioinformatics training

---

## Issue Inventory

| # | Severity | Description | File(s) | Status |
|---|----------|-------------|---------|--------|
| 1 | **Major** | Metric card "Sequences" label is bioinformatics jargon | dashboard_layout.py:439 | FIXED -- renamed to "DNA Sequences" with explanatory tooltip |
| 2 | **Major** | Metric card "Organisms" unclear for non-technical users | dashboard_layout.py:479 | FIXED -- renamed to "Species Found" with tooltip |
| 3 | **Major** | "Quality Score" metric lacks context for field users | dashboard_layout.py:457 | FIXED -- renamed to "Data Quality" with tooltip explaining 0-100 scale |
| 4 | **Major** | Sample table columns use jargon: "Reads", "N50", "Class. Rate" | dashboard_layout.py:574-603 | FIXED -- renamed to "Sequences", "Fragment Length", "ID Rate"; headers updated with plain tooltips |
| 5 | **Major** | Sample table status values use bracket prefixes ("[+] Good", "[OK] Complete") | dashboard_tab.py:2162-2173 | FIXED -- changed to plain labels: "Good", "Complete", "Needs Review", "Issue Detected", "Error" |
| 6 | **Major** | Biohazard icon on "Pathogen Screening" card alarming even when safe | dashboard_layout.py:337 | FIXED -- changed to shield-exclamation icon with neutral grey colour, renamed to "Threat Screening" |
| 7 | **Major** | "CDC Category A agent(s)" in threat subtitle is regulatory jargon | dashboard_tab.py:955 | FIXED -- changed to "critical pathogen(s) detected - immediate action required" |
| 8 | **Major** | "FAULT" status label is technical/mechanical language | dashboard_tab.py:2056-2064 | FIXED -- changed to "ERROR - Check setup" throughout |
| 9 | **Minor** | "No CDC/WHO priority pathogens detected" uses regulatory jargon | dashboard_tab.py:938 | FIXED -- changed to "No dangerous organisms detected from your watchlist" |
| 10 | **Minor** | Screened summary uses jargon: "X of Y species above threshold" | dashboard_tab.py:935 | FIXED -- changed to "X species screened, none on watchlist" |
| 11 | **Minor** | Header tooltip: "nanopore sequence data" is jargon | header.py:148 | FIXED -- changed to "analysing DNA samples for organisms of interest" |
| 12 | **Minor** | Watchlist empty state says "Settings tab" (wrong tab name) | dashboard_layout.py:727 | FIXED -- corrected to "Watchlist tab" |
| 13 | **Minor** | "Sequencing Quality Metrics" section header is technical | dashboard_layout.py:757 | FIXED -- renamed to "Detailed Quality Indicators" |
| 14 | **Minor** | Quality metric labels: "Mean Q-Score", "Read Length N50", "Classification Rate", "Total Bases" | dashboard_layout.py:763-835 | FIXED -- renamed to "Read Accuracy", "Fragment Length", "Identification Rate", "Total Data" with updated plain-language tooltips |
| 15 | **Minor** | Pathogen alert badges say "sequences" (jargon) | pathogen_alert.py:109 | FIXED -- changed to "DNA matches" |
| 16 | **Minor** | "reads" in HighRiskPathogenAlert and WatchedSpeciesAlert | pathogen_alert.py:293,351 | FIXED -- changed to "DNA matches" and "matches" |
| 17 | **Minor** | Confidence bar label "Confidence" is vague | pathogen_alert.py:196 | FIXED -- changed to "Detection certainty" |
| 18 | **Minor** | Pathogen database action text uses "biosafety officer" and "biosafety protocols" | pathogen_alert.py:22,31 | FIXED -- changed to "safety officer" and "safety protocols" |
| 19 | **Minor** | Watchlist threshold badge "T:10" is cryptic | watchlist_manager_ui.py:434 | FIXED -- changed to bell icon + number with tooltip "Alert triggers after N DNA matches" |
| 20 | **Minor** | Watchlist modal "Taxid:" label and "reads" threshold | watchlist_modal.py:147,306,368,370 | FIXED -- changed to "ID:", "Database ID:", "DNA matches" |
| 21 | **Minor** | Watchlist modal "Alternative Names (for GTDB matching)" header | watchlist_modal.py:317 | FIXED -- simplified to "Alternative Names:" |
| 22 | **Minor** | Quick add species placeholder says "taxid" | watchlist_manager_ui.py:275 | FIXED -- changed to "database ID" |
| 23 | **Minor** | Help modal metric description says "reads processed, quality pass rate, classification rate" | dashboard_layout.py:80-82 | FIXED -- plain language: "DNA sequences processed, data quality, species identified, alerts" |
| 24 | **Minor** | Help modal sample selection talks about "barcode" | dashboard_layout.py:84-88 | FIXED -- plain language about viewing single sample data |
| 25 | **Minor** | AG Grid status column styling uses indexOf for bracket-prefix values | dashboard_layout.py:546-571 | FIXED -- updated conditions to match new plain-text status values; added blue styling for "Processing" |
| 26 | **Minor** | Watchlist panel threshold label says "threshold: N" | dashboard_tab.py:1429 | FIXED -- changed to "alert at N matches" |
| 27 | **Deferred** | "Input Files" metric tooltip could mention FASTQ format | dashboard_layout.py:421 | DEFERRED -- tooltip added with plain description, no file format details |
| 28 | **Deferred** | Pathogen report modal "TaxID: X" label visible to operators | dashboard_tab.py:1204 | DEFERRED -- modal content changes would require callback refactor |

## CSS Changes Requested

No CSS changes required. All fixes use inline styles or Bootstrap className props as instructed.

## Summary of Changes

### Files Modified

1. **dashboard_layout.py** -- 14 changes:
   - Metric card labels renamed with tooltips (Input Files, DNA Sequences, Data Quality, Species Found)
   - Sample table column headers simplified (Sequences, Species, Data Size, Fragment Length, ID Rate)
   - AG Grid status column styling updated for new plain-text status values
   - Threat Screening card icon changed from biohazard to shield-exclamation
   - Quality metrics section renamed with plain-language labels and tooltips
   - Help modal text rewritten in plain language
   - Watchlist empty state corrected to reference "Watchlist tab"

2. **dashboard_tab.py** -- 9 changes:
   - Sample status values changed from bracket-prefix ("[+] Good") to plain text ("Good")
   - "FAULT" status renamed to "ERROR" throughout
   - "CDC Category A agent(s)" replaced with plain language
   - "CDC/WHO priority pathogens" replaced with plain language
   - Screened summary text simplified
   - Watchlist threshold label clarified
   - Comment updated to match new quality label format

3. **header.py** -- 1 change:
   - Start Analysis tooltip changed from "nanopore sequence data" to plain language

4. **pathogen_alert.py** -- 5 changes:
   - "sequences" badges changed to "DNA matches"
   - "biosafety officer/protocols" changed to "safety officer/protocols"
   - Confidence bar label changed to "Detection certainty"
   - "abundance" changed to "of sample" in high-risk alert

5. **watchlist_manager_ui.py** -- 2 changes:
   - "T:10" threshold badge changed to bell icon with tooltip
   - Quick-add placeholder changed from "taxid" to "database ID"

6. **watchlist_modal.py** -- 5 changes:
   - "Taxid:" labels changed to "ID:" and "Database ID:"
   - "reads" changed to "DNA matches" in threshold labels
   - "GTDB matching" removed from alternative names header
   - Alert threshold description rewritten in plain language

### Design Principles Applied

- **Threats first**: Visual hierarchy maintained -- pathogen alerts remain the most prominent element after status
- **Traffic light intact**: Green/amber/red colour coding unchanged and consistent across status indicator, sample table, and alerts
- **Jargon elimination**: All user-facing text reviewed; bioinformatics terms replaced with lab-literate equivalents
- **Progressive disclosure**: Technical details available via info-circle tooltips, not shown by default
- **Field readability**: Status values simplified to single-word labels visible at a glance
- **No callback changes**: All modifications are label/text/style only -- no callback signatures, IDs, or data flow altered
