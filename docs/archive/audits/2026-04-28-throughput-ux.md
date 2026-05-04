# Nanometa Live UI Scaling Audit -- 2026-04-28

## Scope

UX behavior at 12 to 24 barcodes streaming continuously. Focus on the 4-zone clinical
Dashboard, the QC Stage Strip, the per-sample AgGrid table, the Validation tab, the
Classification (Sankey/Sunburst) tab, and the Watchlist tab. Reviewed file:line citations
only; no live render of a 24-barcode test dataset was performed -- where the layout
behavior cannot be determined from source alone, the finding says so explicitly.

## Summary

- Total findings: 14 (P0: 2, P1: 7, P2: 5)
- 30-second-scan goal at 24 barcodes: **DEGRADED**
- Highest-impact UX issue: **P0-T01** -- the per-sample attribution row inside Zone 2
  pathogen alert cards is hard-capped at 3 chips with a non-expandable "+N more" pill
  (`pathogen_alert.py:69-112`). On a 24-barcode run where one critical pathogen is
  detected in 18 samples, the operator sees three barcode chips and "+15 more" with no
  way to expand, no tooltip on the pill, and no underlying list. The clinical question
  "which sample is contaminated?" is not answerable from the dashboard.

## P0 (clinically misleading or unusable)

### [P0-T01] Pathogen alert "+N more" chip pill is non-interactive

**Files:**
- `nanometa_live/app/components/pathogen_alert.py:69-112` (chip rendering with hard cap)
- `nanometa_live/app/components/pathogen_alert.py:100-112` ("+X more" pill)

**Issue:** `_render_sample_attribution()` slices the sample list to `max_inline=3` chips
plus a flat `+{overflow} more` pill. The pill is a plain `html.Span` with no `id`, no
`title` tooltip listing the omitted samples, no click handler, and no modal trigger. At
24 barcodes with a pathogen detected in 18 samples, the operator sees three barcode
chips and "+15 more" -- and there is no UI affordance anywhere on the Dashboard to enumerate
the remaining 15 (the pathogen modal at `dashboard_tab.py:806-870` opens per-organism but
does not show the per-sample list either; it pulls a *single* row from
`load_kraken_data(main_dir, selected_sample)` and reports that sample only).

**Impact:** Clinically misleading. The 30-second scan tells the operator "barcode01,
barcode02, barcode03 + 15 more" -- but the +15 pill could include a negative control, the
high-priority sample, or a contamination pattern. The operator must leave the Dashboard,
go to the Organisms tab, click the species, and cross-reference 24 per-sample
classifications by hand.

**Verify by rendering:** With 24 barcodes detecting the same pathogen, confirm the pill
has no hover affordance and no click target. Inspect DOM for any associated tooltip.

### [P0-T02] Verdict banner shows ACTION REQUIRED with no per-sample attribution in the banner itself

**File:** `nanometa_live/app/tabs/dashboard_tab.py:336-499` (`update_verdict_banner`)
**Verdict subhead construction:** `dashboard_tab.py:425-443`

**Issue:** When any critical or high-risk pathogen is detected in any of 24 barcodes,
the Zone 1 banner subhead reads `"{n_found} of {n_watched} monitored pathogens found
-- act now"` (line 427). It does not name the triggering sample(s). Per CLAUDE.md the
"per-sample attribution row inside the alert cards is sufficient" -- but with 24 barcodes
that row is itself capped at 3 chips (P0-T01 above), so the banner subhead is the *only*
place a clinician can read "from: barcode13" at a glance, and it does not contain that
information. At 1-of-24 detection, the verdict says ACTION REQUIRED with no sample
identifier visible in the 32px / 700 H3 banner that the 30-second-scan workflow stops at.

**Impact:** Clinically misleading. An operator scanning the dashboard sees the red
ACTION REQUIRED but cannot tell whether the alert is from one outlier barcode (likely a
real signal) or from many (likely contamination spread or a sample-prep failure)
without scrolling into Zone 2 and counting chips. At 24 barcodes the difference is
material to the response decision.

**Verify by rendering:** Run with one ACTION REQUIRED hit in barcode13 of 24. Confirm
that "barcode13" does not appear anywhere in Zone 1's rendered DOM.

## P1 (degrades 30-second scan)

### [P1-T01] Sample selector dropdown is not virtualized; no pagination, no keyboard search hint

**File:** `nanometa_live/app/components/sample_selector.py:43-55`

**Issue:** The `dcc.Dropdown` in `create_sample_selector` declares `clearable=False`,
`persistence=True`, `placeholder="Select a sample..."`. It does not set
`searchable` (defaults to `True` in dcc.Dropdown) but also does not set
`optionHeight`, `maxHeight`, or any virtualization. dcc.Dropdown 2.x renders the full
list to DOM; 24 barcode entries plus "All Samples" is fine, but the selector also
appears in compact form (`create_compact_sample_selector` line 80-91) at fixed
`minWidth: 250px` which truncates "barcodeXX" plus any descriptive suffix.
There is no visible label affordance telling the operator they can type to search
(unlike e.g. AgGrid's filter inputs that have a magnifier icon). On a 24-entry list the
type-to-filter feature is the difference between scanning and scrolling.

**Impact:** Annoyance, not blocking. At 24 entries the dropdown still scrolls and is
keyboard-navigable, but operators wearing PPE / using a touchscreen scroll a 24-row
list one entry at a time.

**Verify by rendering:** With 24 barcodes loaded, confirm the dropdown opens to a
scrollable 24-row list, that typing "barcode2" filters as expected, and that the
compact variant (`minWidth: 250px`) truncates long names.

### [P1-T02] Dashboard sample table page size 8 makes a 24-barcode run scroll three pages

**File:** `nanometa_live/app/layouts/dashboard_layout.py:304-309`

**Issue:** Zone 4 AgGrid uses `"paginationPageSize": 8`. With 24 samples that means three
pages with no page-size selector exposed (`paginationPageSizeSelector` not configured).
The "Sample Details" accordion is `start_collapsed=False` for the row count badge but
defaults closed visually because `dbc.Accordion(... active_item=None)` (line 345) means
the user must click to expand -- and once expanded, sees only 8 of 24 rows.

**Impact:** Dashboard's "click a row to filter all tabs" affordance (line 224 tooltip)
becomes a 3-page hunt. The 30-second clinical scan goal is broken whenever the operator
needs to drill into a specific barcode.

**Verify by rendering:** Confirm the page-size selector is absent and that paginating
to barcode15 requires two clicks.

### [P1-T03] QC sample breakdown table page size 10 + fixed 420px height clips at 24 rows

**File:** `nanometa_live/app/layouts/qc_layout.py:289-299`

**Issue:** `per-sample-table` declares `"paginationPageSize": 10` and a fixed
`style={"height": "420px", ...}`. The columnDefs include grouped headers
("Cumulative", "Latest batch") with `groupHeaderHeight=38` and `headerHeight=32`. On a
1080p / 1280x800 display, 420px container minus 70px header space leaves ~350px for
data rows; AgGrid Alpine default row height is 28px, so ~12 rows fit. With 24 barcodes
the operator must paginate to see the full set, *and* the table is below the Stage
Strip (which itself needs scrolling on smaller laptops -- see P1-T05). At-a-glance
comparison of barcode01 to barcode24 is not possible.

**Impact:** Comparison-by-eye is the QC operator's primary task. Pagination breaks it.

**Verify by rendering:** Confirm at 24 rows the table paginates and the page-size
selector is absent.

### [P1-T04] Classification Sankey/Sunburst default `min_reads=10` and `max_taxa=10` are tuned for one sample, not 24

**Files:**
- `nanometa_live/app/layouts/classification_layout.py:62-108` (defaults)
- `nanometa_live/app/tabs/classification_tab.py:174-178` (filter resolution)

**Issue:** The "Minimum DNA Sequences" filter defaults to `value=10` (layout line 71)
and "Organisms Per Level" defaults to `value='10'` (line 102). With 24 barcodes each
contributing 50-200 species and the aggregated view summing across them, the unfiltered
node count balloons. The 10-organisms-per-level cap helps the Sankey, but the 10-read
minimum is too low at high fanout: aggregating 24 samples means a per-sample 1-read
detection appears as 24 reads in the All-Samples view and survives filtering, even though
single-read calls are taxonomic noise. There is also no explicit per-sample view
toggle in this tab; the visualization is filtered by the global `sample-selector`
(callbacks read `selected_sample` State at classification_tab.py likely line ~115-117
based on the surrounding signature).

**Impact:** At aggregated 24-sample view, the Sankey/Sunburst risks rendering noise
chains that look real. The clinical scan does not benefit from the broader fanout.

**Verify by rendering:** Aggregated 24-sample dataset, count the nodes/links at
default filters; check whether single-sample 1-read species pass through.

### [P1-T05] QC Stage Strip vs. per-sample table -- visual hierarchy still works, but accordion-less plots push the table below the fold

**Files:**
- `nanometa_live/app/layouts/qc_layout.py:40-94` (Stage Strip + Read Quality cards)
- `nanometa_live/app/layouts/qc_layout.py:119-308` (Per-Sample table)
- `nanometa_live/app/assets/styles.css:3689-3691` (`.stage-strip-count` 28px / 700)

**Issue:** Stage Strip count is 28px / 700, matching `dashboard-metric-value` -- so the
Strip dominates visually as designed. But between the Strip and the per-sample table
sit the Read Quality + Read Length cards (qc_layout lines 60-94, two `md=6` columns,
no fixed height -- card body grows with content). On a 1280x800 viewport the
per-sample table (which carries the actionable per-barcode signal) starts roughly
720-800px down the page, requiring a scroll. With 24 barcodes the table itself adds
another 420px, so QC's actionable content lives entirely below the fold.

**Impact:** The visual hierarchy is correct (Strip > cards > table), but at 24 barcodes
the table is the *only* place the operator can see per-sample variance, and it is the
*last* element they reach.

**Verify by rendering:** Open QC tab on 1280x800, confirm `per-sample-table` is below
the fold.

### [P1-T06] Coverage species selector at 24 barcodes mixes species and sample names without grouping

**File:** `nanometa_live/app/tabs/validation_tab.py:531-558`

**Issue:** `populate_coverage_selector` builds dropdown options with label
`f"{species} ({sample_id})"` (line 550). With 24 barcodes and (say) 5 validated species
each, that is up to 120 entries in a single flat dropdown. There is no `optgroup`-style
grouping by species or by sample, no virtualization, no count badge, and no secondary
filter. Same dcc.Dropdown defaults as P1-T01 (searchable yes, virtualized no).
`coverage-species-selector` (validation_layout.py:268-273) does not set `optionHeight`,
`maxHeight`, or `style` for height. Type-to-filter helps, but the operator needs to
remember either the species name or the sample name to find an entry.

**Impact:** The "View Coverage" button on result cards
(validation_layout.py:635-642) sets the selector value programmatically, so the
common path works. But manually browsing 120 entries is the failure mode.

**Verify by rendering:** With 24 samples x 5 validated species, confirm the dropdown
renders 120 flat entries with no grouping.

### [P1-T07] BLAST result-card list and minimap2 result-card list have no virtualization

**Files:**
- `nanometa_live/app/layouts/validation_layout.py:151` (`blast-results-container`)
- `nanometa_live/app/layouts/validation_layout.py:371` (`coverage-results-container`)
- `nanometa_live/app/tabs/validation_tab.py:487-521` (card list construction)

**Issue:** Both result-card containers are plain `html.Div` populated by the callback
in a tight loop (`for result in results: cards.append(card)` at validation_tab.py
~487-519 -- card construction at `create_validation_result_card`,
validation_layout.py:487-644). With 24 barcodes x 5 species = 120 cards rendered in
DOM at once. Each card is a `dbc.Card` with header, body, footer, progress bar, badges
-- 120 of them is a heavy DOM. There is no pagination, no "Show more", no
virtualization (Dash + AgGrid has virtualization but card lists do not).

**Impact:** Initial render lag (~1-3s anecdotally on similar Dash card-grids; would need
benchmarking to confirm), and the 30-second scan goal is incompatible with a 120-card
scrollable list.

**Verify by rendering:** With a 120-card synthetic dataset, measure
TimeToInteractive on the Validation tab.

## P2 (polish)

### [P2-T01] Verdict banner subhead does not break out validation status per sample

**File:** `nanometa_live/app/tabs/dashboard_tab.py:425-443`

**Issue:** The "-- pending confirmatory validation" qualifier (line 430) is a single
suffix on the banner subhead. With 24 barcodes, validation runs per-sample-per-species;
some samples may have validated detections while others have not. The qualifier is all-
or-nothing (`validation_has_results = bool(validation_data and ... results)`, line
350-352).

**Impact:** Low. The qualifier is informational. Per-sample granularity belongs on
Zone 2 cards, not the banner.

### [P2-T02] Dashboard Zone 3 Sample Quality card aggregates across samples without saying so

**Files:**
- `nanometa_live/app/tabs/dashboard_tab.py:534-570` (`update_quality_card`)
- `nanometa_live/app/layouts/dashboard_layout.py:142-159` (card)

**Issue:** The Quality card pulls `nanoplot_stats.get("mean_read_quality")` from
`load_nanoplot_stats(main_dir)` with no sample argument (dashboard_tab.py:535) --
so it returns the run-wide aggregate. With 12 Excellent + 12 Poor barcodes, the user
sees one label and one Q-score; whether that is mean / median / mode is not
documented in the card label. The QC tab's per-sample table is the only place this
gets disambiguated.

**Impact:** Operator-confusing at high sample-count variance. A dataset with bimodal
quality distribution looks "Fair" on the dashboard.

**Verify by rendering:** With 12 Excellent + 12 Poor synthetic samples, capture the
card's displayed label.

### [P2-T03] Watchlist pathogens table fixed `maxHeight: 400px` is fine -- but the table is unrelated to barcode count

**File:** `nanometa_live/app/layouts/watchlist_layout.py:455-458`

**Issue:** `watchlist-pathogens-table` is `style={"maxHeight": "400px", "overflowY":
"auto"}`. The table lists *enabled pathogens*, not detected organisms; barcode count
is irrelevant. The Watchlist tab does *not* attempt to display detected organisms per
barcode. The audit question ("Built-in + user watchlists multiplied by 24 barcodes'
detected organisms") is moot because the multiplication does not happen here.

**Impact:** None at scale -- the tab manages configuration, not detection results. The
40+ entries from `clinical_pathogens.yaml` already make this 400px viewport scroll on a
fresh install regardless of barcode count.

### [P2-T04] No documented or implemented breakpoint for >12 barcodes

**Files:**
- `nanometa_live/app/assets/styles.css:2098-2120` (Zone 1 attribution row breakpoints)
- `nanometa_live/app/assets/styles.css:2349-2400` (small-screen Zone 3 stacking)
- `CLAUDE.md` Dashboard Architecture section, "Responsive" subheading

**Issue:** CLAUDE.md responsive guidance and styles.css breakpoints address screen-size
adaptation only (`<768px`, `<480px`). They do not address sample-count adaptation. For
example, the per-sample AgGrid pagination size (8 in dashboard, 10 in QC) is fixed; no
"if N samples > 12, expand to N rows" rule exists. With 24 barcodes on a 1920x1080
display the operator has plenty of pixels but the layout still paginates.

**Impact:** Clinical operator on a high-DPI desktop still gets a paginated 8-row
table.

### [P2-T05] Per-sample attribution chips rendered at 10px / 500 -- legible threshold concern at 3+ chips

**File:** `nanometa_live/app/components/pathogen_alert.py:58-66` (chip style base)

**Issue:** Chips are `fontSize: "10px"`, `fontWeight: "500"`, `padding: "2px 7px"`.
At 24-barcode scale the names "barcode01" ... "barcode24" are short, but a chip with
`(NC)` suffix (line 80-82) on a high-DPI screen pushes the chip to ~80-100px wide.
WCAG AA recommends 12px+ for body text; these chips likely fall just under the
recommended threshold for non-bold text. The threat tier color contrast is fine
(critical: `#721c24` on `#f8d7da`), but the *size* may not be.

**Impact:** Aesthetic / accessibility. Not blocking the 30-second scan, but a clinician
in PPE may not parse 10px text from arm's length.

## Per-component scaling notes

| Component | OK at 12 barcodes? | OK at 24? | Notes |
|---|---|---|---|
| Sample selector dropdown (`sample_selector.py:43-55`) | Yes | Borderline | Searchable but not virtualized; no count badge or grouping. Compact variant truncates at 250px (line 91). |
| Dashboard sample AgGrid (`dashboard_layout.py:218-311`) | Yes (1.5 pages) | No (3 pages) | `paginationPageSize=8` fixed (line 306). No page-size selector. Accordion collapsed by default. |
| QC sample breakdown AgGrid (`qc_layout.py:133-300`) | Yes (1.2 pages) | No (2.4 pages) | `paginationPageSize=10`, fixed `height: 420px`. Grouped headers consume vertical space. |
| Dashboard Zone 1 verdict banner (`dashboard_tab.py:336-499`) | Yes | Degraded | No per-sample attribution in banner subhead. ACTION REQUIRED at 1-of-24 looks identical to ACTION REQUIRED at 24-of-24. |
| Dashboard Zone 2 alert chips (`pathogen_alert.py:69-112`) | Yes (3 + "+9 more") | No (3 + "+21 more" non-expandable) | P0-T01: "+N more" pill is non-interactive. |
| Dashboard Zone 3 metric cards (`dashboard_layout.py:122-205`) | Yes | Yes | Run-wide aggregates; quality card does not name aggregation method (P2-T02). |
| Dashboard Zone 4 sample table | See Dashboard sample AgGrid | See Dashboard sample AgGrid | -- |
| QC Stage Strip (`qc_tab.py:41-147`, CSS `styles.css:3651-3704`) | Yes | Yes | Aggregate counts, dominates visually as designed. |
| Classification Sankey/Sunburst (`classification_layout.py:62-220`) | Yes | Degraded | Defaults `min_reads=10`, `max_taxa=10` -- low filter at 24-sample aggregation lets noise through (P1-T04). |
| Validation BLAST card list (`validation_layout.py:151`) | Yes (~60 cards) | No (~120 cards, no virtualization) | P1-T07. |
| Validation Coverage card list / species selector (`validation_layout.py:266-273`) | Yes (~25 entries) | Borderline (120 flat entries) | P1-T06. |
| Watchlist pathogens table (`watchlist_layout.py:455-458`) | Yes | Yes | Independent of barcode count. |

## Recommended UX adjustments for 24-barcode mode

1. **P0-T01 fix:** Make the "+N more" chip pill expandable. Either (a) attach a Bootstrap
   `dbc.Tooltip` listing all overflow sample names, or (b) make it a `dbc.Button(size="sm",
   color="link")` that opens a modal listing sample, reads, abundance, NC flag for every
   detected sample, sortable. Modal already exists pattern at `dashboard_tab.py:806-870`
   for per-organism reports; extend rather than introduce a new one.

2. **P0-T02 fix:** Append per-sample attribution to the verdict subhead. Format: "Action
   required -- detected in barcode13 (4521 reads, 3.62%)" for 1-of-N, or "Action required
   -- detected in 18 of 24 samples (top: barcode13, barcode07, barcode22)" for many-of-N.
   The data is already in scope at `dashboard_tab.py:425-443` -- `dangerous` carries reads
   and abundance, and `taxid_to_samples` (line 791) carries the per-sample list.

3. **P1-T01 fix:** Add a count badge "(N samples)" next to the selector label
   (`sample_selector.py:36`); use the existing `create_sample_info_badge` helper at line
   94 which already exists but is not wired into the layout.

4. **P1-T02, P1-T03 fix:** Replace fixed `paginationPageSize` with
   `paginationAutoPageSize: true` plus a sensible `style: {height: "calc(100vh - 600px)"}`
   so the table grows with the viewport. Or expose a page-size dropdown
   (`paginationPageSizeSelector: [10, 25, 50, 100]`).

5. **P1-T04 fix:** Make `classification-filter-input` default scale with sample count.
   Read `len(available_samples)` in the layout factory or initial callback and set the
   default to `max(10, len(samples) * 2)` so a 24-sample aggregate filters at >= 48 reads
   minimum.

6. **P1-T06 fix:** Add `optgroup` grouping to `coverage-species-selector` (group by
   species, samples nested) or split into two cascading dropdowns: "Species" -> "Sample".

7. **P1-T07 fix:** Page or virtualize the BLAST/coverage card lists. Simplest: render top
   N=20 by reads with a "Load more" button. Better: convert the card list to an AgGrid
   with custom cell renderers.

8. **P2-T02 fix:** Title the Quality card "Mean Sample Quality" or "Worst Sample Quality"
   explicitly. Better: render two badges -- best and worst -- when the bimodal range is wide
   (`max(q) - min(q) > 5`).

9. **P2-T04:** Document a 24-barcode-mode breakpoint in CLAUDE.md and styles.css. At minimum
   pin `paginationAutoPageSize` for both dashboard and QC tables.

10. **General:** Add a synthetic 24-barcode test dataset to
    `scripts/generate_test_datasets.py` (currently 8 scenarios per CLAUDE.md) so this
    regime is covered by `tests/test_frontend_integration.py`.

End of audit.
