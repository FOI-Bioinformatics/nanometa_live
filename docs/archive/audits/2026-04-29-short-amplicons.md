# Short-Amplicon Audit -- 2026-04-29

## Summary

The nanometa_live + nanometanf stack is **blocked out-of-the-box for
short amplicons** (read length 200-1500 bp). The single most consequential
default is ``chopper_minlength = 1000`` at
``nanometanf/nextflow.config:137``, which discards every read shorter
than 1 kb. V3-V4 (~460 bp), shorter ITS amplicons, and most plate-
friendly custom amplicon designs lose all reads at the QC stage.
16S full-length (~1.5 kb) clears the bar but the long tail of legitimately
shorter reads still gets dropped.

Once the length filter is relaxed, the rest of the stack runs but
several operator-facing metrics misinterpret short-read data: the QC
tab's Q30 bands, classification-rate bands, and the dashboard's Sample
Quality categorization are all calibrated for ONT whole-genome reads
where Q-scores trend higher and classification rates are near-saturating.
On amplicons the same data shows amber/red on otherwise-fine runs.

**Risk score for short-amplicon support:**
- Out-of-the-box: **3/10** (run-breaking due to chopper default)
- With recommended config preset (Phase 1 below): **7/10** (workable;
  metrics still long-read-tuned)
- After GUI Advanced Settings ship (Phase 2 plan, separate cycle):
  **8/10** (operator can switch without editing YAML)
- After Q30 / classification-band amplicon-aware reinterpretation
  (deferred): **9/10**

## P0 -- run-blockers with default config

### [P0-A01] chopper_minlength = 1000 discards every amplicon < 1 kb

**File:** ``nanometanf/nextflow.config:137``

**Issue:** The default ``chopper_minlength = 1000`` is hardcoded for
ONT whole-genome reads. Any amplicon protocol producing reads shorter
than 1 kb (V3-V4 ~460 bp, ITS 250-700 bp depending on region, custom
designs typically <1 kb) loses 100% of reads at the QC stage. The
pipeline does not surface a warning -- chopper just emits an empty
output and downstream Kraken2 receives zero reads.

**Impact:** Run-blocking. Operator sees zero classified reads, no
clear root-cause indicator in the dashboard.

**Fix:** Set ``chopper_minlength: 100`` or ``0`` in operator's
``config.yaml``. The plumbing at ``conf/modules.config:113`` is
``params.chopper_minlength ? "--minlength ${params.chopper_minlength}" : ''``
so a falsy value (``0`` or ``null``) skips the flag entirely.
**Operator escape hatch exists**, but is undocumented.

### [P0-A02] filtlong_min_length = 1000 has the same problem

**File:** ``nanometanf/nextflow.config:147``

**Issue:** When ``qc_tool: filtlong`` is selected, the same 1 kb
floor applies. Same plumbing pattern at ``conf/modules.config:139``.

**Mitigation:** A ``low_length`` filtlong profile already exists at
``conf/qc_profiles.config:66`` with ``filtlong_min_length = 500`` --
half-coverage of the use case. There is no equivalent chopper profile
shipped, and ``500`` still cuts off V3-V4.

**Fix:** Operator overrides ``filtlong_min_length`` in their
``config.yaml``. Phase 2 GUI work below makes this a one-click
adjustment.

## P1 -- degradations (data flows but metrics mislead)

### [P1-A01] Q30 thresholds tuned for long reads

**File:** ``nanometa_live/app/components/organism_components.py:1177-1182``

**Issue:** The Q30 status helper categorizes ``>=45%`` as green,
``25-44%`` as amber, ``<25%`` as red. Short ONT reads carry
proportionally more end-of-read low-quality bases (the Q-score
"ramp-up" and ramp-down regions are a larger fraction of a 460 bp
read than a 30 kb read). Legitimate V3-V4 amplicons typically show
Q30% in the 30-50% band.

**Impact:** Operators see amber Q30 on otherwise-fine amplicon runs,
trigger unnecessary "review" workflows or re-runs.

**Fix recommendation:** Defer to a follow-up cycle. Either (a)
bake an "amplicon mode" flag into the operator's config that
selects relaxed bands (green >=25%, amber 10-24%, red <10%), or
(b) annotate the metric with a "(long-read tuned)" qualifier when
the operator has not declared amplicon mode.

### [P1-A02] Classification-rate bands tuned for long reads

**File:** ``nanometa_live/app/tabs/qc_tab.py:120, 123, 127``

**Issue:** The QC stage strip's classification-rate delta uses
``>=80%`` green, ``50-79%`` amber, ``<50%`` red. Short amplicons
classify at lower rates because (i) Kraken2's k=35 default uses
fewer informative k-mers per short read, and (ii) the database
coverage of amplicon regions varies widely.

**Impact:** A 100% bacterial 16S amplicon run with 60% Kraken2
classification rate (typical) shows amber, suggesting "review" --
but the data is correct.

**Fix recommendation:** Same as P1-A01: amplicon-mode bands or
annotation. Deferred.

### [P1-A03] Sample Quality categorization at the dashboard

**File:** ``nanometa_live/app/tabs/dashboard_tab.py:1940-1950``

**Issue:** The dashboard's "Sample Quality" card buckets samples by
unclassified-read percentage: ``<30%`` Good, ``<50%`` Fair, else
Poor; ``0%`` is Excellent. Amplicon runs typically have 20-50%
unclassified depending on database coverage and primer bias.

**Impact:** Dashboard verdict reads "Fair" or "Poor" on amplicon
runs that are operationally fine.

**Fix recommendation:** Deferred (same family as P1-A01/P1-A02).

### [P1-A04] minimap2 preset map-ont for sub-500 bp reads

**File:** ``nanometanf/nextflow.config:97`` (default ``map-ont``);
``nanometanf/modules/local/minimap2_validation/main.nf:27`` (preset
plumbing parameterised, not hardcoded -- so operator can override).

**Issue:** The ``map-ont`` preset is tuned for long ONT reads with a
seed length and bandwidth that suit kilobase-plus reads. For short
(sub-500 bp) reads the ``sr`` preset gives more sensitive alignments.

**Impact:** Validation under-reports hits on V3-V4-class amplicons.

**Fix:** Set ``minimap2_preset: "sr"`` in operator config when
amplicons are <500 bp. Above 500 bp, ``map-ont`` is fine.

### [P1-A05] validation_identity_threshold = 90% may under-confirm

**File:** ``nanometanf/nextflow.config:101-102``;
``nanometanf/modules/local/minimap2_validation/main.nf:30``.

**Issue:** ``validation_identity_threshold = 90.0`` (percent identity
required for a read to count as confirming validation) is a high bar
for short ONT reads. Q-score noise on a 460 bp read translates to
~1-3% identity loss vs the same noise on a 30 kb read. Many
legitimate amplicon hits fall in the 85-90% identity band.

**Impact:** Validation systematically under-confirms amplicon
detections. The dashboard shows ACTION REQUIRED with "pending
confirmatory validation" suffix indefinitely.

**Fix:** Operator sets ``validation_identity_threshold: 80.0`` or
``75.0`` for amplicon runs.

## P2 -- polish (lower priority)

### [P2-A01] Read-length histograms dominated by amplicon size

**File:** ``nanometa_live/app/tabs/qc_tab.py`` (read-length plot
construction).

**Issue:** The QC tab's read-length histogram is configured for the
broad distribution of long ONT reads (logarithmic-ish x-axis, bins
sized for 1-50 kb range). On amplicons the entire distribution
collapses to a narrow peak around the amplicon size; the histogram
is uninformative.

**Fix recommendation:** When all reads cluster within a narrow band,
auto-switch the x-axis to linear with bins sized for the cluster.
Deferred.

### [P2-A02] N50 reporting unhelpful for amplicons

**Issue:** The QC card reports N50, which on an amplicon run roughly
equals the amplicon length. This is correct but adds no diagnostic
value -- the operator already knows the amplicon size. A more useful
metric for amplicons would be "% reads within +/- 10% of expected
amplicon size".

**Fix recommendation:** Add an "amplicon mode" QC card variant.
Deferred.

### [P2-A03] Coverage plots assume WGS shape

**File:** ``nanometa_live/app/components/coverage_plots.py``.

**Issue:** The minimap2 coverage plots assume a long reference
(>10 kb) and show breadth across the full genome. For amplicon
validation the reference should be the amplicon target (~500 bp);
showing breadth across a full genome misses the point that an
amplicon either covers its target region or it does not.

**Fix recommendation:** Add a "reference type" detection that
switches the visualization when the reference is amplicon-sized.
Deferred.

## Recommended config preset for short-amplicon runs

Operators can paste the following into their ``config.yaml`` to
enable amplicon mode end-to-end. Phase 2 of the implementation plan
will surface these as GUI controls so editing YAML is no longer
required.

```yaml
# Read filtering -- relax for amplicon-scale reads
chopper_minlength: 100        # set to 0 to disable length filtering entirely
chopper_quality: 7            # ONT short-read Q-scores trend lower than long-read
filtlong_min_length: 100      # only used when qc_tool: filtlong

# minimap2 validation -- short-read preset and looser identity
minimap2_preset: "sr"         # short-read preset; switch back to map-ont at >=500 bp
minimap2_min_mapq: 5          # lower bar for short alignments
validation_identity_threshold: 80.0  # accept short-read Q-score noise

# Kraken2 -- defaults are fine; tighten only if false positives observed
kraken2_confidence: 0.0
kraken2_minimum_hit_groups: 0

# Classification visualisation -- smaller filter floor for amplicon depth
default_reads_per_level: 5
```

For per-protocol fine-tuning the operator should benchmark the
``minimap2_preset`` and ``validation_identity_threshold`` against a
known-positive control. The defaults above are conservative starting
points.

## Pipeline run modes that need re-evaluation

Real-time mode at amplicon scale needs separate operator awareness.
Amplicon plates often produce a few hundred to a few thousand reads
per barcode total -- not per minute. The watchPath + batch_timeout
machinery (``nanometanf/subworkflows/local/realtime_monitoring/main.nf:202-242``)
emits batches when either ``max_batch_size`` (50) or
``batch_timeout`` (60 s) is reached. For amplicon runs this means most
batches will be timeout-flushed rather than size-flushed, with
batch sizes substantially below ``max_batch_size``. The pipeline
handles this correctly but operators should expect more frequent,
smaller batches.

Recommendation: lower ``max_batch_size`` to 10-20 and
``batch_timeout`` to 30 s for amplicon runs to reduce per-barcode
result latency.

## Recommended profile addition (deferred)

A ``conf/qc_profiles.config`` ``short_amplicon`` profile would
collapse the YAML preset into a single ``-profile short_amplicon``
flag. The existing ``low_length`` filtlong profile at
``conf/qc_profiles.config:66`` is the prior art. Deferred because
the GUI Advanced Settings work in Phase 2 of the plan exposes the
same overrides through individual fields, which gives operators
more granular control than a named profile.

## Related GUI work (Phase 2 of the implementation plan)

Per the user's request, the eight overrides in the recommended preset
above will be surfaced as inputs in the existing Configuration tab
"Advanced Settings" accordion (``nanometa_live/app/components/config_form.py:244-799``).
The plan at ``/Users/andreassjodin/.claude/plans/how-could-we-make-cheerful-shell.md``
covers the implementation. The GUI work does not require any
nanometanf changes -- ``parameter_mapping.py`` routing and a new
sub-card in ``config_form.py`` are sufficient.

## Verification (operator-driven empirical run)

1. Override ``chopper_minlength: 100`` in a test ``config.yaml``.
2. Run nanometanf against a V3-V4 amplicon FASTQ (~460 bp reads).
3. Confirm chopper output retains a comparable read count to input
   (only Q-filtered reads should be dropped).
4. Run nanometa_live against the produced output; observe whether
   Q30 metric reads "Poor" / "Fair" simply because amplicons have
   lower per-base Q than long reads. If so, P1-A01 is confirmed.
5. Set ``validation_identity_threshold: 80.0`` and re-run validation
   on a known-positive control. Compare confirmed-read counts vs
   the default 90% threshold.
6. Run with ``minimap2_preset: "sr"`` and compare validated-read
   counts against ``map-ont`` for the same input.
