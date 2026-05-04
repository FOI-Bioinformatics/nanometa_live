# Nanometa Live End-to-End Validation Design

**Date:** 2026-01-30
**Status:** Approved
**Goal:** Confirm Nanometa Live works for real-time multiplexed nanopore analysis with actionable GUI output.

## Validation Strategy

Three layers, each building on the previous:

1. **Smoke Test** — App starts, loads data, all tabs render without errors.
2. **Acceptance Testing** — Synthetic 4-barcode dataset with known organisms verifies classification, alerts, validation, and QC.
3. **Interactive Walkthrough** — Manual GUI walkthrough exercising clinical, environmental, and research decision workflows.

## Synthetic Data Design

4 barcodes, each with a distinct scenario:

| Barcode | Scenario | Seeded Organisms | Purpose |
|---------|----------|-----------------|---------|
| barcode01 | Clinical positive | *M. tuberculosis*, *S. aureus* + background | Critical pathogen alerts |
| barcode02 | Foodborne contamination | *L. monocytogenes*, *S. enterica* + background | Foodborne watchlist alerts |
| barcode03 | Environmental/water | *L. pneumophila* + low *E. coli* + diverse taxa | WHO water watchlist, abundance |
| barcode04 | Negative control | Background flora only | No false alerts, baseline QC |

Data generated as Kraken2 report files, FASTP JSON, and one synthetic PAF file. Cumulative reports at 3 time points simulate real-time updates.

Output structure:
```
synthetic_testdata/
├── kraken2/
│   ├── barcode01.cumulative.kraken2.report.txt
│   ├── barcode02.cumulative.kraken2.report.txt
│   ├── barcode03.cumulative.kraken2.report.txt
│   └── barcode04.cumulative.kraken2.report.txt
├── fastp/
│   ├── barcode01.fastp.json
│   ├── barcode02.fastp.json
│   ├── barcode03.fastp.json
│   └── barcode04.fastp.json
└── validation/
    └── minimap2/
        └── barcode01_taxid1773.paf
```

## Smoke Test Specification

Automated script checks:

1. App launches and serves on port 8050
2. All 8 tabs render without HTTP 500 errors
3. Sample detector finds all barcodes
4. Data loaders return non-empty data for Kraken2 and FASTP
5. Core stores populate (app-config, available-samples, backend-status)
6. No uncaught JavaScript exceptions

Pass criteria: all checks green.

## Acceptance Test Scenarios

### Clinical decisions
1. barcode01 organism list shows *M. tuberculosis* and *S. aureus*
2. Critical alert banner appears for barcode01
3. Validate button triggers validation, result card shows identity and read count
4. Coverage plots render (depth, cumulative, histogram)

### Environmental monitoring
5. barcode03 triggers WHO water watchlist alert for *L. pneumophila*
6. Low-level *E. coli* appears but does not trigger alert
7. barcode04 (negative control) fires no alerts, QC shows normal metrics

### Research/composition
8. Classification tab shows taxonomic breakdown matching seeded organisms
9. Sample selector switches data correctly per barcode
10. Dashboard shows overview across all samples

### Real-time simulation
11. Cumulative report time point 1 shows partial data
12. Later time points show increasing counts, new species appear
13. Alert fires when pathogen count crosses threshold mid-run

### Validation flow
14. On-demand validation UI accessible from organism card
15. Coverage plots render from synthetic PAF data

## Interactive Walkthrough Checklist

Manual steps with pass/fail recording:

1. Dashboard loads, status indicators visible, 4 barcodes detected
2. Sample selector switches between all barcodes
3. Organisms tab shows pathogen cards with read counts and threat levels
4. Alert banners: critical for barcode01, none for barcode04
5. Classification tab taxonomy matches expected organisms
6. QC tab shows FASTP metrics per barcode
7. Watchlist manager loads built-in watchlists, toggle works
8. Validation tab shows results, View Coverage renders 3 plots
9. Config tab displays current configuration
10. Rapid barcode switching shows no stale data

## Deliverables

```
tests/validation/
├── generate_synthetic_data.py
├── smoke_test.py
├── acceptance_test.py
└── synthetic_testdata/          (gitignored)
docs/
├── plans/2026-01-30-validation-design.md
└── validation-walkthrough-checklist.md
```

## Out of Scope

- Nextflow pipeline execution (visualization layer only)
- Browser automation (Selenium/Playwright)
- Performance or load testing
- App code modifications (unless bugs found)
