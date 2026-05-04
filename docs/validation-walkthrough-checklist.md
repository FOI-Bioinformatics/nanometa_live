# Nanometa Live Validation Walkthrough Checklist

**Date:** ___________
**Tester:** ___________
**App version:** ___________
**Data source:** synthetic_testdata (4 barcodes)

## Setup

1. Generate synthetic data:
   ```
   python -c "
   from tests.validation.generate_synthetic_data import generate_all_synthetic_data
   generate_all_synthetic_data('/tmp/nanometa_validation_data')
   "
   ```
2. Launch app:
   ```
   nanometa-live --main_dir /tmp/nanometa_validation_data --port 8050
   ```
3. Open browser to http://localhost:8050

## Walkthrough

| # | Step | Expected | Pass | Notes |
|---|------|----------|------|-------|
| 1 | Dashboard tab loads | Status indicators visible, 4 barcodes listed | [ ] | |
| 2 | Select barcode01 | Data updates to show clinical organisms | [ ] | |
| 3 | Organisms tab - barcode01 | Cards for M. tuberculosis and S. aureus visible | [ ] | |
| 4 | Alert banner - barcode01 | Critical/high alert for clinical pathogens | [ ] | |
| 5 | Select barcode02 | Data updates to foodborne organisms | [ ] | |
| 6 | Organisms tab - barcode02 | Cards for L. monocytogenes and S. enterica | [ ] | |
| 7 | Select barcode03 | Data updates to water/environmental organisms | [ ] | |
| 8 | Organisms tab - barcode03 | L. pneumophila card visible, low E. coli | [ ] | |
| 9 | Select barcode04 | Only background flora shown | [ ] | |
| 10 | Alert banner - barcode04 | No alert banners | [ ] | |
| 11 | Classification tab | Taxonomy breakdown visible, taxa match scenario | [ ] | |
| 12 | QC tab | FASTP metrics per barcode: reads, quality, length | [ ] | |
| 13 | Watchlist tab | Built-in watchlists load, toggle entries on/off | [ ] | |
| 14 | Validation tab | Results section renders | [ ] | |
| 15 | View Coverage - barcode01 | 3 plots render (depth, cumulative, histogram) | [ ] | |
| 16 | Config tab | Current config displays correctly | [ ] | |
| 17 | Rapid barcode switching | Switch 01-02-03-04 quickly, no stale data | [ ] | |

## Summary

**Passed:** ___ / 17
**Failed:** ___
**Observations:**

___________________________________________
