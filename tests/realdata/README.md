# Real-data assertions

These tests run against output from an actual nanometanf run over ONT reads
whose contents are known independently of this software. Everything else in
`tests/` uses synthetic fixtures, which can only show that the code does what
it was written to do -- not that it produces the right biological answer.

They are skipped unless pointed at a results tree, so the normal developer loop
and CI are unaffected.

## Running them

```bash
NANOMETA_REALDATA_DIR=/path/to/results/R1 pytest tests/realdata -v

# With a second run for the cross-run comparisons:
NANOMETA_REALDATA_DIR=/path/to/results/R1 \
NANOMETA_REALDATA_COMPARE_DIR=/path/to/results/R7 \
  pytest tests/realdata -v
```

`NANOMETA_REALDATA_COMPARE_DIR` should hold a run in which the negative control
was processed **alone**.

## The truth set

Source reads: `/Volumes/Untitled/Bioshield/rawdata/` (external drive).

| Barcode | Sample | Expected |
|---|---|---|
| `barcode11` | *Francisella tularensis* LVS | Near-pure culture; taxid 263 dominant. Tier 1 select agent. |
| `barcode14` | ZymoBIOMICS D6300 | 8 bacteria + 2 yeasts at known nominal abundance. |
| `barcode16` | Negative control | No template. Measures the noise floor. |

D6300 membership is listed in `test_truth_set.py`. Note that *Acinetobacter
baumannii* is **not** a member -- *Limosilactobacillus fermentum* (taxid 1613)
is -- and that Salmonella must be matched at the species taxid 28901, not the
genus 590.

## What is deliberately not asserted

**Relative abundance in D6300.** The gram-positive members (*B. subtilis*,
*S. aureus*, *L. monocytogenes*) resist lysis and are systematically
under-recovered, so observed proportions depart from the nominal 12% for
reasons upstream of this software. Presence is asserted; ranking is not.

**Exact read counts.** `baseline.json` records what run R1 measured on
2026-07-28. Those are observations from one run against one database, not
certified truth. Use them to detect drift in the next release; do not assert
equality against them.

## Why the cross-run comparison exists

A select agent appearing in a negative control has two explanations that a
single run cannot distinguish: contamination already present in the FASTQ
(lab-side index hopping), or this software leaking reads between barcodes. Only
the second is a bug here, and it would be a release blocker.

Running the negative control both multiplexed and alone separates them. On
2026-07-28 both runs reported exactly 6 reads of taxid 263, which places the
reads in the input file and clears the pipeline.

## Baseline measured 2026-07-28 (run R1)

Database `k2_pluspfp_08_GB_20251015`, batch mode, `by_barcode`, chopper
defaults (`minlength 1000`, `quality 10`).

| Sample | Classified | taxid 263 | Top species |
|---|---:|---:|---|
| `barcode11` | 34,120 | 34,096 | *F. tularensis* (99.93%) |
| `barcode14` | 20,676 | 1 | *L. fermentum* (4,229) |
| `barcode16` | 11 | 6 | *F. tularensis* (6) |

The negative control yields only 11 classified reads because it is 119,235 raw
reads of mean length 69 bp -- adapter and noise, as expected with no template
-- and `chopper_minlength = 1000` correctly discards them.

## Known open finding

`test_select_agent_reads_stay_below_the_alert_threshold` is marked `xfail`. The
negative control carries 6 reads of taxid 263 against an `alert_threshold` of 5
in `cdc_bioterrorism.yaml`, so a blank sample raises a CRITICAL alert. The
software is behaving correctly; the open question is whether an absolute
read-count threshold is the right rule, given it cannot distinguish 6 of 11
reads in a near-empty sample from 6 reads in a deep one. Remove the `xfail`
when the threshold policy is settled.
