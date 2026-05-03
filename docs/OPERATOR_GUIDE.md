# Nanometa Live Operator Guide

For laboratory personnel running analyses from nanopore sequencing data.

## What this tool does

Nanometa Live analyses DNA from your samples and reports:

1. Which organisms are present (bacteria, viruses, etc.)
2. Data quality (whether results are reliable)
3. Whether target pathogens on the active watchlist were detected
4. Recommended next steps for each alert

## Status colors

The dashboard uses three colors throughout:

- Green: quality is acceptable, no issues detected.
- Amber: review recommended; quality is fair but not ideal.
- Red: action required; a critical condition was detected.

## Dashboard overview

When you open Nanometa Live, the Dashboard tab is the default view. It has four zones, top to bottom.

### Zone 1 - Verdict banner

A single large banner across the top of the page. The background color summarises the run state:

```
ALL CLEAR                          0 of 42 monitored pathogens found
   No action required              Sample: barcode01 | ACTIVE  02:14:06
                                   Last updated 14:23:45
```

```
ACTION REQUIRED                    2 of 42 monitored pathogens found
   Act immediately                 Sample: barcode01 | ACTIVE  02:14:06
                                   Last updated 14:23:45
```

Verdict states:

| State | Color | What it means |
|-------|-------|---------------|
| ALL CLEAR | Green | No watched pathogens detected. Run is progressing or complete. |
| ACTION REQUIRED | Red | A critical or high-risk pathogen on your watchlist was detected. Follow your safety protocol. |
| MONITORING | Amber | Only moderate-risk watched species detected. Review. |
| SCREENING IN PROGRESS | Blue | Run is active; first results pending. |
| STANDBY | Grey | No run is active. |

If validation (BLAST / minimap2) has not yet run on a detected pathogen, the ACTION REQUIRED banner appends "- pending confirmatory validation" to the sub-line.

### Zone 2 - Pathogen alert cards (only when alerts exist)

When a pathogen is detected, one or more cards appear beneath Zone 1:

```
CRITICAL - Bacillus anthracis (Anthrax)
   4,521 matches | 3.62% of sample | HIGH confidence | BLAST Verified
   DETECTED IN: [barcode03] [barcode11]
   Contact your safety officer immediately.
```

`DETECTED IN:` tells you which samples each pathogen was found in. Colored chips list the samples.
- Normal sample chips use the alert severity color.
- Negative-control samples appear as flat gray chips with `(NC)` after the name.
- If a pathogen appears in many samples, the first three are shown inline and the rest indicated as `+X more`.

### Zone 3 - Supporting metrics (four cards)
```
┌──────────────────┬──────────────┬──────────────────┬──────────┐
│    10,000        │  Good        │  12 species      │  ACTIVE  │
│ Sequences        │  Q17 Quality │  detected        │ 02:14:06 │
│ Analyzed         │              │                  │          │
└──────────────────┴──────────────┴──────────────────┴──────────┘
```

1. **Sequences Analyzed**: total reads processed so far
2. **Sample Quality**: plain-language level (Excellent / Good / Fair / Poor) with the Q-score as a subtitle
3. **Species Detected**: count of distinct organisms found
4. **Run Time**: elapsed time + run state badge

### Zone 4 - Sample details (collapsed accordion)

Click to expand a per-sample table with plain-language columns:
- Sequences Analyzed: reads processed for that sample.
- Sample Quality: Q-score with color coding.
- Read Length: typical read length.
- Match Rate: how many reads were classified.

---

## Quick reference

1. Check the verdict banner color first.
2. If alerts are present, read the top alert card: it states what was detected, why it matters, and what to do.
3. Follow the listed action or click the button in the alert.

Example alert text:

```
CRITICAL: Low quality detected in 3 samples: barcode01 (45%), barcode03 (38%)

-> Check sequencing conditions (temperature, flow cell health, sample quality)

Technical details: Pass rate below 50%
```

---

## Common situations

### Situation 1: Analysis complete, green verdict
Meaning: everything processed, data quality acceptable.

What to do:
1. Click "Generate Report" (in alerts or top right).
2. Select PDF or Excel format.
3. Save to your designated location.
4. Review results in the taxonomy tab if needed.
5. Archive or share the report per local protocol.

---

### Situation 2: Amber verdict with "fair quality" warning
Meaning: data is usable but not optimal. Results are likely valid with some uncertainty.

What to do:
1. Click "View QC Report".
2. Check which samples are affected.
3. Review the "Reasons for Removal" section in the QC tab.
4. If pass rate is 60-70%: proceed with caution and note in the report.
5. If pass rate is below 60%: consider re-running affected samples.

---

### Situation 3: Red verdict with "species of interest detected"
Meaning: a target organism on the watchlist was identified.

What to do (immediate):
1. Click "Review Detections".
2. Navigate to the organisms tab.
3. Verify the organism identification (check read counts).
4. Click "Generate Report" for detailed species info.
5. Follow your organisation's reporting protocol.
6. Contact appropriate authorities per local guidelines.

Priority: immediate.

---

### Situation 4: Low yield or insufficient reads
Meaning: not enough genetic material was sequenced.

What to do:
1. Check whether the sequencing run is still active.
2. If active, let it continue and check back in 30 minutes.
3. If complete, verify sample loading was correct.
4. Check the summary tab for total reads.
5. Consider re-running critical samples.

---

### Situation 5: High error count or red system alert
Meaning: technical problem with the analysis.

What to do:
1. Take a screenshot of the error message.
2. Note what you were doing when the error occurred.
3. Click "Help" -> "Report Issue".
4. Contact your bioinformatics support team.
5. Provide screenshot and description.

Priority: urgent if it is blocking your work.

---

## Tab guide

### Dashboard tab (default)
- Purpose: summary verdict.
- When to use: always check first.
- Key info: Zone 1 verdict banner, Zone 2 pathogen cards with sample attribution, Zone 3 metrics, Zone 4 per-sample details.
- Action buttons: View Report, Confirm (on pathogen cards).

### Configuration tab
- Purpose: set up new analyses.
- When to use: before starting a new run.
- Key settings: database selection, processing mode.
- Note: usually pre-configured, but verify before critical runs.

### Organisms tab
- Purpose: detected organisms and classification results.
- When to use: after analysis completes.
- Key info: organism cards with abundance bars and confidence badges.
- Export: download species lists.

### Quality control tab
- Purpose: data quality metrics across pipeline stages.
- When to use: when quality alerts appear, or to verify data is trustworthy.
- Key info:
  - Stage Strip at top: `Raw -> Quality-filtered -> Classified` with counts and a classification-rate delta.
  - Read Quality card: Q20/Q30/average quality with color-coded thresholds.
  - Read Length card: N50 and average length.
  - Sample Breakdown table: per-sample filtered reads, classification rate, average Q score.
- Pipeline note: when running Chopper (the default), the "Raw" slot shows "Not available" because Chopper does not produce a pre-filter read count.

### Taxonomy tab
- Purpose: visual organism relationships.
- When to use: investigating complex samples.
- Key views: Sankey diagram (flow), Sunburst (hierarchy).
- Tip: switch between views with the radio buttons.

### Validation tab
- Purpose: verify organism identifications.
- When to use: when a detection needs confirmation.
- Key views: BLAST identity scores, minimap2 coverage plots.
- Tip: use "Validate" buttons on organism cards to trigger on-demand validation.

### Watchlist tab
- Purpose: manage which pathogens to monitor.
- When to use: setting up monitoring for specific organisms.
- Key features: 9 built-in watchlists (clinical_pathogens, cdc_bioterrorism, who_priority, foodborne, respiratory, who_drinking_water, nosocomial_eskape, wastewater_surveillance, zoonotic_one_health) and custom uploads.
- Tip: quick-start buttons activate common watchlists with one click.

### Preparation tab
- Purpose: download reference genomes and prepare BLAST databases.
- When to use: before running validation on new organisms.
- Key info: genome download status, database readiness.

---

## Tips for effective use

### General
1. Check the Dashboard tab first.
2. Follow alerts in order; they are priority-sorted.
3. Hover for help: most elements have a tooltip.
4. Red rows need immediate attention.
5. Screenshot important findings for records and reports.

### Quality
1. Data quality score above 75: proceed with confidence.
2. Data quality score 60-75: usable for most purposes.
3. Data quality score below 60: review carefully, consider re-running critical samples.
4. Pass rate above 70% is normal; below 60% indicates issues.

### Organism detection
1. High read counts (above 1000 reads): high-confidence identification.
2. Medium read counts (100-1000): likely present; verify if critical.
3. Low read counts (below 100): possible contamination or background.
4. Always cross-check target species in the taxonomy tab.

### When to contact support
- Red system errors that persist.
- Data quality consistently below 50% for known good samples.
- Unexpected organism detections in negative controls.
- Questions about specific organism identifications.
- Help interpreting complex results.

---

## Tuning for high-throughput runs (12-24 barcodes)

The pipeline ships defaults that suit a typical lab workstation
running fewer than 12 simultaneous barcodes. Multiplexed runs at 12,
24, or more barcodes benefit from a few configuration knobs that
trade memory for parallelism and avoid pipeline stalls.

### Pick a host class

| Host class | Cores | RAM | Storage |
|---|---|---|---|
| Field laptop | 4-8 | 16-32 GB | NVMe SSD |
| Lab workstation | 16 | 64 GB | NVMe SSD |
| Beefy workstation | 32 | 128 GB | RAID SSD |
| Server / cluster node | 64+ | 256 GB+ | NVMe / shared FS |

### Recommended config knobs

Add to your `config.yaml` (Nanometa Live forwards these as Nextflow
params). Defaults shown apply when the param is omitted.

| Param | Field laptop | Workstation 16c/64GB | Workstation 32c/128GB | Server 64c+ |
|---|---|---|---|---|
| `kraken2_memory_mapping` | `true` | `true` | `true` | `true` |
| `kraken2_memory_gb` | `12` | `12-32` (DB-dependent) | `32-90` (DB-dependent) | `32-90` |
| `max_classification_forks` | `2` | `4-8` | `8-16` | `16-32` |
| `max_concurrent_batches` | `2` | `4` | `4-8` | `4-8` |
| `update_interval_seconds` | `30` | `30` | `15` | `15` |
| `pipeline_cores` | `4` | `8` | `16` | `32` |

### `kraken2_memory_gb` rule of thumb

Set `kraken2_memory_gb` to **on-disk database size + 4 GB**:

| Database | On disk | `kraken2_memory_gb` |
|---|---|---|
| MiniKraken2 | 8 GB | `12` (default) |
| GTDB Bac120 | ~25 GB | `30` |
| Kraken2 PlusPF | ~70 GB | `74` |
| Kraken2 PlusPFP | ~80 GB | `84` |

With memory-mapping enabled (default), all parallel Kraken2 forks
share the OS page cache rather than each loading their own copy --
so this is per-process headroom, not per-instance RAM.

### `max_classification_forks` and `max_concurrent_batches`

These two together set the total in-flight Kraken2 work:

```
total_in_flight = N_samples × max_concurrent_batches
                  capped by max_classification_forks
```

For 24 barcodes with `max_concurrent_batches = 4` and
`max_classification_forks = 8` on a 16-core / 64 GB host:
- total in-flight = min(24 × 4, 8) = 8 concurrent Kraken2 jobs
- with mmap'd DB shared across 8 forks, ~84 GB total RAM
  request fits in 64 GB if Linux releases unused page cache

If your host OOMs or the dashboard shows long stalls between
Kraken2 batches, lower `max_classification_forks` first; raise it
only when pipeline progress is clearly bottlenecked on Kraken2.

### When to adjust `update_interval_seconds`

The dashboard refreshes every `update_interval_seconds` seconds
(default 30). On 24-barcode runs the loader sees fresh batch reports
on most ticks, which is fine. Lower to 15 only when you have a fast
host and want sub-30-second pathogen alerts; raise to 60 if the
dashboard feels sluggish (often a sign you should also tune the
knobs above).

### Verifying your tuning

After updating `config.yaml` and restarting Nanometa Live:

1. Open the Dashboard tab. Verdict banner should reach a non-STANDBY
   state within one `update_interval_seconds` cycle once data starts
   landing.
2. Check the Quality Control tab's per-sample table. The visible row
   count should match the actual barcode count without paginating
   (this is the W3-A pagination bump from cycle 18).
3. The Pathogen Alert "+N more" pill should be clickable -- the
   popover lists every triggering sample (W1-B from cycle 18).
4. Open the Nextflow trace report at
   `<results>/pipeline_info/execution_trace_*.txt`. Sustained Kraken2
   tasks should stay within the host's CPU and memory limits.

---

## Training scenarios (practice with mock data)

### Scenario 1: normal run
Goal: get familiar with the interface using good-quality data.

Setup:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_normal \
    normal \
    3
```

Expected: green verdict, around 80% quality, 5-8 organisms, no critical alerts.

Practice: navigate all tabs, hover tooltips, generate a report.

---

### Scenario 2: quality issues
Goal: recognise and respond to quality problems.

Setup:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_quality \
    quality_issues \
    5
```

Expected: amber or red verdict, below 65% quality, quality alerts.

Practice: identify affected samples, read the QC report, follow action guidance.

---

### Scenario 3: pathogen detection
Goal: respond to a watchlist pathogen detection.

Setup:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_pathogen \
    pathogen \
    3
```

Expected: red alert for the species of interest, high-priority action.

Practice: rapid verification, report generation, following local protocol.

---

## Support and resources

### Quick help
- In-app help: click the "?" icon next to any element.
- Tab help: click the "Help" button in each tab.
- Alert guidance: read the "->" recommendation in each alert.

### Contact information
- Bioinformatics support: [Contact details here]
- Emergency pathogen hotline: [Emergency contact here]
- Technical issues: [IT support here]

### Additional resources
- Full documentation: [Link to detailed docs]
- Video tutorials: [Link to training videos]
- FAQ: [Link to common questions]

---

## Operator proficiency checklist

Basic
- [ ] Understand the verdict colors (green/amber/red).
- [ ] Locate and read the alerts panel.
- [ ] Check the data quality score.
- [ ] Navigate between tabs.
- [ ] Hover over elements to see tooltips.

Intermediate
- [ ] Generate a PDF report.
- [ ] Interpret QC statistics.
- [ ] Identify samples needing attention.
- [ ] Follow action guidance for an alert.
- [ ] Export an organism list from the taxonomy tab.

Advanced
- [ ] Configure species of interest.
- [ ] Interpret Sankey and Sunburst diagrams.
- [ ] Compare results across multiple samples.
- [ ] Troubleshoot quality issues.
- [ ] Rehearse the local pathogen-response protocol.

---

## Network access

By default the dashboard listens only on the local machine
(`127.0.0.1`). Open it in a browser running on the same
machine at `http://localhost:8050`. Other workstations on the
network cannot reach it; this is intentional. The dashboard
has no login.

Two ways to view results from a different workstation:

1. **SSH tunnel** (recommended). On your laptop:
   ```bash
   ssh -N -L 8050:localhost:8050 user@analysis-machine
   ```
   Then open `http://localhost:8050` on your laptop while the
   tunnel is up.

2. **Bind to all interfaces** (only on a trusted network). On
   the analysis machine, restart with:
   ```bash
   python -m nanometa_live.app --host 0.0.0.0 --port 8050
   ```
   The dashboard is now reachable at
   `http://<machine-ip>:8050` from anywhere on the network.
   Only do this on a network you trust; the dashboard has no
   authentication and exposes pathogen results.

If you are unsure which option is appropriate, ask your IT
team.

---

*Questions? Contact your bioinformatics support team.*
