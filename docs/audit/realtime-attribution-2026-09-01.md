# Real-time per-sample attribution audit, 2026-09-01

**Report:** operators could not see which sample or barcode carried a detected
watchlist organism. Batch mode was fine; real-time was not.

**Verdict:** confirmed, with three independent causes rather than one. All three
are fixed, each pinned by a regression test, and each verified on a live
nanorunner-fed real-time run. A fourth candidate was ruled out with evidence.

## How the run was driven

The Bioshield demo kit, real-time configuration, five samples (barcode05 to
barcode08 plus the MinKNOW unclassified bin), incremental Kraken2, the
129-entry `bioshield_agents` watchlist, alert threshold 10 per entry.

```
~/nanometa-demo/scripts/run_demo3.sh     # app on port 8063, then Start Analysis
~/nanometa-demo/scripts/feed_demo3.sh    # nanorunner replay, 56 files over ~11 min
```

The results tree was snapshotted every 20 seconds throughout, and each snapshot
replayed offline through the attribution chain with the new probe,
`scripts/audit_realtime_attribution.py`. The completed batch run in
`~/nanometa-demo/runs/demo1_results` was the control.

## What the chain looks like

| Hop | What it does |
|---|---|
| 1 | Kraken2 report files per sample, and the tier the loader selects |
| 2 | `load_kraken_data(dir, "All Samples")`, the aggregate the verdict reads |
| 3 | `_load_per_sample_organisms`, the taxid to samples dict |
| 4 | `samples_for_detection` / `build_pathogen_attribution` |
| 5 | Banner subhead, alert card chips, popover, modal, exported report |

Hops 1 and 2 were healthy at every snapshot, from the first one onward. Report
tiers resolved correctly through the whole progression: batch reports early,
then the progressive cumulative report as each sample's first flush landed. No
sample was ever lost to a tier mismatch. The failures were all at hops 3 to 5.

## Cause A: a sub-threshold sample was counted, not named

`build_pathogen_attribution` lists a sample as triggering only when that
sample's own read count reaches the watchlist entry's `alert_threshold`. The
verdict, though, is decided on the aggregate. A batch run's barcodes are
complete when the verdict first appears, so the hot barcode clears its own
threshold and is named. A real-time run's aggregate leads every individual
barcode for most of the run, and for a low-abundance organism for all of it. The
phrase then collapsed to "aggregate across 5 samples", which is true and names
nobody.

Measured on the live per-sample data, sweeping the entry threshold:

| Threshold | Batch run, *F. tularensis* | Real-time run, same organism |
|---|---|---|
| 10 | barcode06, barcode07, barcode05, +2 | barcode06, barcode05, barcode08, +2 |
| 100 | barcode06, barcode07, barcode05, +2 | barcode06, barcode05, barcode08, +2 |
| 500 | barcode06, barcode07, barcode05 | aggregate across 5 samples |
| 2000 | aggregate across 5 samples | aggregate across 5 samples |

At 500 the batch run names three barcodes and the real-time run names none, on
the same organism, with the per-sample counts (395, 342, 265, 238, 163) sitting
on disk throughout. That is the reported symptom exactly.

**Fix.** The below-threshold branch of `_attribution_phrase` names the top three
samples and keeps the aggregate qualifier: "Francisella tularensis (barcode06,
barcode05, barcode08, +2 more; aggregate across 5 samples)". The threshold
distinction is preserved. A sub-threshold sample is not promoted to a triggering
sample, and the qualifier still says none was individually positive. Negative
controls stay excluded from the names and reported separately.

## Cause B: a detection spread below the discovery floor named nobody at all

This was the most serious finding.

`PER_SAMPLE_DISCOVERY_FLOOR` is 5. It is right for the general attribution
build, which runs across every taxon in every sample and would otherwise carry
thousands of one-read rows. It is wrong for a taxon the aggregate has already
called above its alert threshold, because the aggregate reaches that threshold
by summing exactly the small per-sample counts the floor discards.

*Bacillus anthracis* on the live run:

| Sample | Reads |
|---|---|
| barcode07 | 4 |
| barcode05 | 3 |
| barcode08 | 3 |
| Aggregate | 10 |

Ten reads met the entry's alert threshold and raised ACTION REQUIRED for a
select agent. Every per-sample row was under the floor, so the detection
resolved no samples, and the banner rendered "Sample attribution unavailable"
for the one organism on the panel where the barcode matters most. Four of
thirteen detections on that run were unattributable for this reason:
*B. anthracis*, *F. tularensis* subsp. *tularensis*, *Salmonella diarizonae*,
and *Aspergillus flavus*.

The banner's blanket wording made it worse. Nine detections had resolved
perfectly well on the same render, so the note was wrong about scope as well as
about cause: attribution had not failed, the data was on disk and was filtered
out on purpose.

The exported report proves the data was reachable the whole time. Its
`_attribute_entry_to_samples` applies no discovery floor, and on the same
results directory it already produced `barcode07 (4), barcode05 (3),
barcode08 (3)` for anthrax. The archived artifact was right while the live
screen said attribution was unavailable.

**Fix.** `resolve_below_floor_samples` looks again for exactly the taxids that
resolved nothing, without the floor. It runs only when something failed to
resolve, reads frames the loader cache already holds, and never mutates the
shared per-tick memo. The floor is unchanged on the hot path. After the fix,
none of the thirteen detections is unattributable.

**One trap worth keeping.** The first version of this fix paired the built
attributions against the detection list by position to find what had failed.
`build_pathogen_attribution` deduplicates by label and re-sorts by read count,
so position does not survive it. The second look then searched for the wrong
organism's taxids and left anthrax unattributed exactly as before. Ask the
question per detection with the same predicate the builder uses.
`tests/test_realtime_attribution.py::TestTheSecondLookAsksAboutTheRightOrganism`
pins it.

## Cause C: a moderate-tier hit showed a count instead of a name

A watched-tier hit spanning more than one sample rendered as a bare count pill,
"DETECTED IN: 3 samples", with the names only in a click-to-open popover. On the
live run the moderate cards read "3 samples" and "4 samples" while the critical
cards directly above them named their barcodes.

The suppression had a real reason: the eager version serialised one row per
sample per card, tens of thousands of components at 96 barcodes by 129 entries
(round-2 scale audit). Naming the single highest-count sample costs one chip per
card, roughly a ninety-sixth of what that suppression was avoiding, and the
component budget fence still passes.

**Fix.** The card names its top sample and summarises the rest as "+N more", the
same form the other tiers use. The popover still carries the full list. Verified
live: "DETECTED IN: barcode06 (8 reads), +2 more".

## Cause D: an unread sample was indistinguishable from a clean one

`_load_per_sample_organisms` swallowed three different outcomes into one silent
`continue`: no report on disk yet, a report mid-rewrite when the poll landed,
and a sample that genuinely carries nothing. The first two mean "not measured"
and the third is a negative result.

Observed at 21:14:46, one minute into the run: barcode06 was in the sample list
with no readable report while the banner read "Triggered by: F. tularensis
(barcode05)", implying barcode06 had been screened and was clean. Real-time
lists a sample as soon as its output directory appears, which is before its
first report lands, and rewrites each sample's cumulative report on every batch
thereafter, so both windows recur throughout a run.

**Fix.** `unmeasured_samples` separates the two and the banner names the gap.
It reports a partial gap only. When no sample at all is readable the verdict's
own no-data states already say so, and repeating it would fire the note on every
poll of a run that has not started writing yet.

## Ruled out

**Report tier mismatch between the aggregate and the per-sample loads.** The
probe recorded the tier each sample resolved to at every snapshot. The two
paths agreed at every point of the run, including the transition from batch
reports to the progressive cumulative report, which the barcodes reached at
staggered times. No detection was ever lost this way.

## Cross-surface consistency

The below-floor fix initially landed on the verdict banner alone, which produced
a worse state than the bug: the banner named barcode07, barcode05 and barcode08
for anthrax while the anthrax card directly beneath it showed no attribution row
at all. `augment_attribution_for_unresolved` is now the single entry point,
shared by the verdict banner, the pathogen alert panel and the modal's
per-sample breakdown.

## What was verified live, and what was not

Verified on the running real-time app against real data:

- Verdict banner names barcodes, and no longer claims attribution is unavailable.
- Alert cards name barcodes for every tier, anthrax included, with counts
  matching the reports on disk.
- Moderate cards name their top sample plus an overflow pill.
- The pathogen modal's "Detected in" line lists all five samples with counts.
- Batch mode, re-checked after the changes, names the same barcodes as before
  and additionally gains the four previously unattributable detections.

Verified by test only, not observed on the live rig: the unread-sample note
rendering on the banner. The condition is transient and was not reproducible on
demand during the session; the loader-side behaviour and the banner wiring are
each covered by tests.

Not exercised at all: sample handling modes other than `by_barcode`, and scales
beyond five samples. The causes are not specific to either, but that is
reasoning, not measurement.

## Test and tooling changes

- `scripts/audit_realtime_attribution.py`, a hop-by-hop probe retained as a
  support tool. Point it at a results directory with the run's config.
- `tests/fixtures/realtime_attribution/`, a real real-time snapshot captured
  from this run. Every pre-existing attribution test writes a flat
  `<sample>.kraken2.report.txt`; none exercised the progressive cumulative
  report, the per-batch reports, or the incremental-layout markers.
- `tests/test_realtime_attribution.py`, 18 tests covering the layout and all
  three fixes.

Suite after the changes: 4394 passed, 126 skipped, coverage 76% against the
74% floor.

## Note on the machine, not the code

The suite failed 13 bundle tests mid-audit with `OSError: [Errno 28] No space
left on device`, not from any code change. The volume was at 92% with 1.5 GiB
free. Clearing this session's own snapshots and the accumulated
`pytest-of-andreassjodin` temp trees recovered enough to finish. The Nextflow
work directory under `~/.nanometa/work` is 5.3 GB and holds 825 task
directories predating today, so it was left untouched.
