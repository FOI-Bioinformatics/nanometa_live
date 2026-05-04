# Archive

Historical documents from the development of Nanometa Live. These files are
preserved for reference but are not actively maintained. The current state
of the codebase is the source of truth; if an archive document and the code
disagree, trust the code.

## Layout

```
archive/
|-- README.md            (this file)
|-- audits/              Dated audit reports
|-- plans/               Design plans and implementation specs
|-- migration/           Snakemake -> Nextflow migration notes
`-- *.md                 Legacy implementation summaries
```

## Audits (`audits/`)

Audit reports from development cycles. Filenames follow
`YYYY-MM-DD-<scope>.md`. The auditing was structured around named cycles
and synthesis docs:

- `2026-04-28-*` -- production readiness, throughput at 12--24 barcodes,
  initial python-pro audit of nanometa_live
- `2026-04-29-*` -- container URL verification, orphan-file simplification,
  short-amplicon support, three-part readiness rollup, UX/UI
- `2026-04-30-*` -- configuration tab review
- `2026-05-01-*` -- update-frequency / event-driven analysis
- `2026-05-02-*` -- frontend review, nanorunner compatibility, synthesis

## Plans (`plans/`)

Design specifications and implementation plans. Filenames follow
`YYYY-MM-DD-<scope>.md` (some pairs have a `<scope>` and a `<scope>-design`
companion).

- `2026-01-30/31-validation-*` -- validation system design and tab redesign
- `2026-03-02-ux-improvements-design.md`
- `2026-03-06-offline-deployment-design.md`
- `2026-03-07-e2e-testing-fixes.md`
- `2026-03-15-ux-evaluation*` -- pre-clinical-redesign UX work
- `2026-03-25-taxonomy-mapping-fixes*`
- `2026-04-28-throughput-fixes.md` -- throughput remediation waves

## Migration (`migration/`)

Snakemake -> Nextflow migration design notes:

- `nextflow_manager_design.md` -- `NextflowManager` design
- `output_parsing_strategy.md` -- parser implementation
- `parameter_mapping.md` -- config to Nextflow parameter mapping

## Top-level legacy docs

| Document | Description |
|----------|-------------|
| IMPLEMENTATION_SUMMARY.md | v2.0 migration summary |
| MODERNIZATION_COMPLETE.md | Modernisation completion notes |
| TAB_STRATEGY_SUMMARY.md | Tab redesign strategy |
| TAB_IMPLEMENTATION_COMPLETE.md | Tab implementation notes |
| TAB_MODERNIZATION_STRATEGY.md | Tab UX improvements |
| APP_STARTUP_FIXES.md | Startup issue resolutions |
| CONFIG_TAB_ANALYSIS.md | Configuration tab analysis |
| FRONTEND_TESTING_COMPLETE.md | Test infrastructure setup |
| TEST_COVERAGE_SUMMARY.md | Test coverage analysis |
| SNAKEMAKE_REMOVAL_SUMMARY.md | Snakemake removal notes |
| MANUAL_TESTING_GUIDE.md | Pre-redesign manual UI testing guide (2025-10-07) |
| ux-evaluation-report.md | UX evaluation that drove the 2026-04 clinical redesign |
| ux-findings-dashboard.md | Dashboard tab UX findings (2026-03-15) |
| ux-findings-field.md | Field-deployment UX findings (2026-03-15) |
| ux-findings-results-organisms.md | Organisms tab UX findings (2026-03-15) |
| ux-findings-results-quality.md | QC tab UX findings (2026-03-15) |
| ux-findings-setup.md | Setup/Config tab UX findings (2026-03-15) |
