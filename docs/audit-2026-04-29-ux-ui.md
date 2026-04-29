# nanometa_live UX audit -- 2026-04-29

Auditor: ui-designer agent. Scope: Dash 4 GUI in
`nanometa_live/app/`. All claims cite file:line.

## UX scoring (out of 10)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Visual consistency | 5/10 | Border-radius (3/4/6/8/12 px) and border-left thickness (3/4/6 px) are inconsistent across alert tiers and cards. Amber text token is split between `#664d03` (QC) and `#856404` (Dashboard, Validation). |
| Accessibility (WCAG AA) | 4/10 | `text-warning` (`#ffc107`) used as foreground on white in the validation summary and verification cards, ratio ~1.6:1 (fails AA even for large text). `HighRiskPathogenAlert` paints `#dc3545` text on `#f8d7da`, ratio ~3.6:1 (fails normal text). Five of seven layouts have zero ARIA roles. Workflow stepper has a fixed `maxWidth: 500px` that cramps on narrow viewports. |
| Responsive design | 5/10 | Only `dashboard_layout.py` uses `xs=` breakpoints. `main`, `qc`, `validation`, `classification` layouts use `md=` only -- they collapse to a single column at <768px instead of laying out in 2 columns at sm. CLAUDE.md's 480px Zone 3 1x4 stack is unimplemented (`xs=6` forces 2x2). The verdict-banner mobile icon hide uses `d-sm-inline` (576px) instead of the documented 768px breakpoint. |
| Information hierarchy / 30-second scan | 6/10 | Zone 1 verdict banner is implemented and prominent. Zone 2 alert cards inherit from `pathogen_alert.py` correctly. But the dashboard pads above the supporting strip with a "Last updated" badge that competes for top-of-fold attention, and the metric cards do not use `text-uppercase letter-spacing` consistently with the QC Stage Strip. Three "Help" / "Understanding This Page" cards (one per analysis tab) duplicate operator-guide content. |
| Copy / microcopy | 6/10 | Plain-language renames are inconsistent: dashboard says "Sequences Analyzed" (American), workflow stepper says "Analyse" (British). BLAST card uses "Match Quality" but the BLAST stats table calls the same metric "Match %". Validation tab is labelled "Sequence Matching" but cross-referenced as "BLAST" in card status text. |
| Empty / loading / error states | 4/10 | `EmptyStateMessage` is present in 3 of 7 layouts. Classification, Watchlist, Config, Preparation layouts have no consistent empty state. No tab has a top-level error container; a callback exception silently leaves placeholder text. The Dashboard verdict banner has no error verdict -- a missing Kraken2 DB renders as STANDBY, which is misleading for clinicians. |
| Alignment with CLAUDE.md doc | 5/10 | The verdict banner uses a 6px solid border on all sides, not the documented 6px left border. Zone 3 480px breakpoint not honoured. Zone 1 mobile icon breakpoint differs. Stage Strip's documented 8px radius is honoured (`stage-strip-slot` 8px, `assets/styles.css:3662`). |
| **Aggregate** | **35/70** | The framework is in place -- the four-zone Dashboard, the Stage Strip, and `EmptyStateMessage` exist and look intentional -- but the implementation has accumulated three classes of drift: tier-spec drift (each card author re-picked a border-radius), token drift (amber and red foregrounds split between two different hex codes for the same semantic role), and layer drift (the verdict banner lost its left-border identity to a full-border CSS shortcut). The accessibility floor is the most pressing issue: two foreground tokens used widely on the dashboard fail WCAG AA. |

## CLAUDE.md vs implementation gaps

- **Verdict banner border style.** CLAUDE.md states "8px radius, 6px
  left border". The implementation paints a full border:
  `nanometa_live/app/tabs/dashboard_tab.py:1591`
  (`"border": f"6px solid {border_color}"`) and the same on the
  initial layout, `nanometa_live/app/layouts/dashboard_layout.py:87`
  (`"border": "6px solid #6c757d"`). The visual identity of "color is
  the answer, accent is on the left" is therefore lost; users see a
  framed block that competes with cards below.
- **Zone 3 1x4 stack at <480px.** CLAUDE.md says "Zone 3 stacks 1x4"
  below 480px. The cards use `xs=6` so they collapse to 2x2 only:
  `nanometa_live/app/layouts/dashboard_layout.py:140,159,178,204`. The
  CSS file has a 480px media query block
  (`nanometa_live/app/assets/styles.css:2396`) but it targets
  `.key-metrics-summary-card` (a removed component referenced in
  CLAUDE.md as a former bug vector), not `.dashboard-metric-card`.
- **Zone 1 mobile icon breakpoint.** CLAUDE.md says hide the icon
  below 768px except for ACTION REQUIRED. The implementation hides at
  <576px (`d-sm-inline`):
  `nanometa_live/app/tabs/dashboard_tab.py:1509`. Tablets in the
  576-768px range therefore see the icon when the spec asks for it
  hidden.
- **Locked amber token.** CLAUDE.md QC Stage Strip section locks
  amber to `#664d03`. The Dashboard sample-table styleConditions and
  the Validation BLAST stats table use `#856404`:
  `nanometa_live/app/layouts/dashboard_layout.py:254`,
  `nanometa_live/app/layouts/validation_layout.py:211`. The QC layout
  uses the documented `#664d03`:
  `nanometa_live/app/layouts/qc_layout.py:176,221,247,269`.
- **Validation sub-tab label.** CLAUDE.md describes the sub-tab as
  "Read Validation (BLAST)". The implementation labels it
  "Sequence Matching": `nanometa_live/app/layouts/validation_layout.py:83`.
  The corresponding "minimap2" sub-tab is "Genome Coverage"
  (line 241), which is a reasonable plain-language rename, but the
  rename is undocumented in CLAUDE.md.

## Visual inconsistencies

- **Border-radius spread.** Five different radii on cards/alerts in
  the same flow: 3px (`pathogen_alert.py:74,621`), 4px
  (`pathogen_alert.py:552,818`; `validation_layout.py:644`), 6px
  (`organism_components.py:391,402`), 8px
  (`pathogen_alert.py:755`; `dashboard_layout.py:88,198,449`;
  `modern_components.py:865,872`), 12px
  (`organism_components.py:891,1127`). CLAUDE.md fixes the dashboard
  family to 8px; alert cards should consolidate to a 4px or 8px tier
  rule.
- **Border-left accent thickness.** Three different thicknesses on
  semantically equivalent components: 3px on
  `WatchedSpeciesAlert` (`pathogen_alert.py:620`), 4px on
  `HighRiskPathogenAlert` (`pathogen_alert.py:551`),
  `DecisionBanner` (`modern_components.py:865,872`),
  validation result cards (`validation_layout.py:644`), and Dashboard
  sample-table cells (`dashboard_layout.py:238,247,256,265`); 6px on
  `OrganismCard`/`WatchedOrganismCard`
  (`organism_components.py:1432,1642`) and Stage Strip slots
  (`assets/styles.css:3673,3677`). CLAUDE.md's locked tokens are 6px
  for the Stage Strip and the verdict banner; alert cards should
  converge to either 4px (Bootstrap default alert accent) or the 6px
  Dashboard family, picked once.
- **Verdict banner full-border vs stage strip left-border.** The
  verdict banner uses a full 6px border
  (`dashboard_tab.py:1591`) while the QC Stage Strip slots, which
  share the same colour palette, use a 6px left border
  (`assets/styles.css:3673`). Two adjacent zones (Dashboard banner,
  QC Stage Strip) speak different visual dialects of the same
  language.
- **Mixed alert vocabulary in `dashboard_layout.py:336-345`.** A
  centred "No Active Alerts" empty state inside the System Alerts
  accordion uses an icon at `fontSize: 36px`, while the same empty
  state in the alerts panel
  (`dashboard_layout.py:467-471`) uses 48px. Same intent, different
  size.
- **Amber/red foreground split.** Across the BLAST stats table
  (`validation_layout.py:211 #856404`), the QC table
  (`qc_layout.py:176 #664d03`), and the dashboard sample status
  cells (`dashboard_layout.py:254 #856404`), the same semantic
  amber-on-pale-yellow status uses two different hex codes. The
  red-on-pale-pink status is consistent at `#721c24` -- the amber
  token is the only colour that drifted.
- **Workflow stepper width.** `WorkflowStepper`
  (`modern_components.py:97`) is hard-pinned to `maxWidth: 500px`
  with no responsive scaling. On viewports <360px the four
  circle+label+arrow groups overflow; on viewports >1200px the
  stepper sits in a 500px island in the middle of a wide page.

## Accessibility issues

- **`text-warning` on white in the Validation Summary card.**
  `H2(str(partial), className="text-warning")`
  (`validation_layout.py:52`) renders `#ffc107` on white card body;
  contrast ~1.6:1, fails AA even for large text (3:1 minimum).
  Same problem in the validation result card status explanation:
  `className=f"text-{config['color']}"` resolves to `text-warning`
  for the `partial` status (`validation_layout.py:587`).
- **`HighRiskPathogenAlert` text colour fails AA.**
  `pathogen_alert.py:514` paints the "HIGH RISK" label in
  `#dc3545` on `#f8d7da` background; contrast ~3.6:1, fails AA for
  normal text. Same colour pairing on the H4 header in
  `CriticalPathogenAlert` (`pathogen_alert.py:391`) -- saved by the
  16px size threshold for large-text 3:1 if the H4 is bold, but
  marginal.
- **`WatchedSpeciesAlert` text colour.** Same pattern,
  `pathogen_alert.py:594` uses `#fd7e14` text on `#fff3cd` background;
  contrast ~3.0:1, fails AA for normal text.
- **`text-muted` on the help cards.** The "Important: ..." line at
  `validation_layout.py:480` and the Dashboard pathogen-alert chip
  text at `pathogen_alert.py:179,188,202` use `#6c757d` on either
  `#f8f9fa` or near-white -- contrast ~4.45:1, just under the 4.5:1
  AA floor. Borderline; safer at `#5c636a` or darker.
- **Tiny text below readable threshold.** Watchlist row Kraken2-DB
  taxid sub-label uses `fontSize: "0.65rem"` (~10.4px) with
  `text-muted` and `opacity: "0.8"`
  (`watchlist_layout.py:993`). Three layered reductions stack a ~3:1
  contrast hit -- below WCAG-recommended 12px floor for body text.
- **Missing ARIA roles in five of seven layouts.** Only
  `dashboard_layout.py`, `main_layout.py`, `preparation_layout.py`,
  `header.py`, and `pathogen_alert.py` use `role=` or `aria-`
  attributes. `qc_layout.py`, `classification_layout.py`,
  `validation_layout.py`, `watchlist_layout.py`, `config_layout.py`
  have zero ARIA. AgGrid and Plotly graphs are accessible by
  default, but the surrounding cards/alerts/banners are unannotated
  for screen readers.
- **`role="status"` on the verdict banner uses
  `aria-live="polite"`.** `dashboard_layout.py:93-94`. ACTION
  REQUIRED is set to `aria-live="assertive"` only on the Zone 2
  alert container (line 109). When the verdict transitions from
  ALL CLEAR to ACTION REQUIRED via Zone 1 alone (no Zone 2 cards
  yet, e.g. before validation runs), screen-reader users get a
  polite announcement for what should be an urgent state change.
- **No keyboard focus indicator overrides.** Bootstrap defaults
  apply, but custom-styled buttons with inline `style={...}` (e.g.
  `pathogen_alert.py:447-450` `View Report` button) do not
  reinforce a visible focus ring. CLAUDE.md asks for "Focus
  indicators: visible focus states for keyboard navigation (3:1
  contrast minimum)".

## Microcopy / clarity issues

- **British/American mix.** "Analyse"
  (`modern_components.py:34,20,25`) vs "Analyzed"
  (`dashboard_layout.py:56,123,136,279`). Pick one (project
  precedent in CLAUDE.md uses American "Analyzed" in user-facing
  contexts). User-instruction memory says "use modest scientific
  language in documentation and code" -- both spellings are
  acceptable, but mixing is jarring inside one app.
- **"Match Quality" vs "Match %".** Same metric (mean BLAST percent
  identity) is "Match Quality" on the result card
  (`validation_layout.py:599`) but "Match %" in the stats table
  (`validation_layout.py:196`). The card and the table sit in the
  same accordion family -- pick one term.
- **"Query Coverage" jargon.** `validation_layout.py:198`
  "Query Coverage (%)" with a tooltip explaining "Percentage of the
  reference genome covered by sequences". The header itself uses the
  jargon; a plain-language version like "Genome Covered (%)" or
  "Reference Span (%)" carries the same information. Tooltips do not
  help an operator scanning a column header on a 1280x800 lab
  display.
- **"Total Seqs".** `validation_layout.py:190` abbreviates "Total
  Sequences" to "Total Seqs". The Dashboard sample table uses the
  full "Sequences Analyzed" (`dashboard_layout.py:277`). Pick one.
- **"DNA matches" in pathogen alerts.** `pathogen_alert.py:325,521`
  refer to "DNA matches" for read counts. Operators reading a "1,234
  DNA matches" badge below a pathogen name reasonably ask "matches to
  what?" The CLAUDE.md plain-language column rename used "Sequences
  Analyzed" / "Read Length" / "Match Rate"; "DNA matches" predates
  that vocabulary and should align.
- **"Scan Database" button.** `preparation_layout.py:483` labels the
  taxid-mapping action as "Scan Database". A non-bioinformatician
  reads this as "scan a hard drive" -- the action actually verifies
  watchlist entries against Kraken2's index. "Verify Watchlist
  Against Database" (used as the card title at line 469) is clear
  but the button below it should match the title's verb, e.g.
  "Verify".
- **"Apply Settings" with "Auto-saved" badge.** Configuration tab
  shows both "Apply Settings" as the primary CTA
  (`config_layout.py:267-273`) and a small "Auto-saved" badge in the
  header (`header.py:130-136`). If settings auto-save, what does
  Apply do? The tooltip clarifies ("Apply these settings and
  start/continue the analysis"), but the affordance is contradictory
  without reading hovers.
- **"Confidence" labelling overlap.** The pathogen alert badge says
  "HIGH confidence" (`pathogen_alert.py:336`), the validation card
  says "Confirmed" / "Partial" / "Low Confidence"
  (`validation_layout.py:425-447`), and the Q-score badge says "Q15
  - Good" (`modern_components.py:559`). Three different scales are
  all rendered as similar pill badges -- an operator may read them
  as parallel.

## Top 5 UX fixes (highest value to clinical users)

1. **Consolidate the amber and red foreground tokens to the
   WCAG-compliant pair (`#664d03` on `#fff3cd`, `#721c24` on
   `#f8d7da`).** Replace `#856404` and the `text-warning` /
   `text-danger` Bootstrap utilities anywhere they paint text on
   white or pale-tint backgrounds. Most pressing in
   `validation_layout.py:46-67` (the four big-number summary cards
   on the Validation tab fail AA today) and
   `pathogen_alert.py:514,594` (HIGH RISK and WATCH labels). One
   audit-and-replace pass closes most of the AA failures listed
   above.
2. **Restore the documented "background-is-the-answer" verdict
   banner.** Change
   `dashboard_tab.py:1591` and `dashboard_layout.py:87` from
   `border: 6px solid {color}` to `border-left: 6px solid {color}`
   (and either `border: 1px solid #dee2e6` or no other border).
   This matches CLAUDE.md, removes the visual conflict with the
   Stage Strip, and lets the background colour carry the verdict
   weight as intended.
3. **Add an error verdict to Zone 1.** Today, a missing Kraken2 DB
   or a Nextflow launch failure leaves the verdict at STANDBY -- a
   clinician walks past the dashboard thinking the run is yet to
   start. Add a sixth state, e.g. PIPELINE ERROR with `#f8d7da`
   background and `#dc3545` left border, populated from
   `backend-status.error_msg`. Failing closed (visible error)
   beats failing silent for a clinical-scan UI.
4. **Lock the responsive grid to CLAUDE.md's three breakpoints.**
   Add `xs=12` to all Zone 3 cards in `dashboard_layout.py:140-204`
   so they stack 1x4 below 576px (closest Bootstrap break to the
   spec'd 480px), and update the Zone 1 icon class at
   `dashboard_tab.py:1509` from `d-sm-inline` to `d-md-inline`.
   Apply `xs=12 sm=6` to the validation summary cards at
   `validation_layout.py:49-67` and the QC after-filtering cards at
   `qc_layout.py:62-94`. One project-wide grid pass.
5. **Unify the empty/error state surface.** Move the
   classification, watchlist, config, and preparation tabs onto
   `EmptyStateMessage` for the no-data case
   (`modern_components.py:717`), and add a sibling
   `ErrorStateMessage` component (same shape, red-tier accents) so
   every tab can render a consistent error block when its callback
   raises. Today the Classification tab silently shows an empty
   Plotly graph when no Kraken2 reports exist -- a clinician
   cannot tell whether that means "no organisms found" (good) or
   "no data to load" (broken).
