# Audit campaign, August 2026

Multi-agent defect hunt across nanometa_live and nanometanf, followed by a
real-data pass and an air-gapped deployment run. Nineteen defects fixed, each
with a regression test observed failing before its fix.

This record exists for the reasons the earlier audit records do: so the next
session does not re-find what was rejected, and does not re-derive what was
settled.

## The one failure mode

Most of what was found is a single fault in different costumes: **the system
rendering "we did not measure" identically to "we measured and it is fine"**.

- The exported report showed a green NO WATCHED ORGANISMS DETECTED over a
  one-read run with 35 organisms loaded.
- The Organisms panel showed an unqualified "Not Detected (35)" on the same
  data, while the Dashboard correctly said INSUFFICIENT READS.
- An ACTION REQUIRED alarm raised on 6 reads out of 11 was worded identically
  to one raised on 34,096 out of 34,141.
- The readiness snapshot Store defaulted to `[]`, which the checker reads as
  "determined: nothing enabled", so a background worker reported "No watchlist
  enabled" before hydration had ever run.
- nanometanf's `failed_samples` came back `null` ("not determined") in exactly
  the case it exists for, a batch where every sample failed QC.
- A QC card showed the all-samples total under a single sample's name,
  crediting a barcode that produced nothing with 101 MB of another's bases.

Two of these were **already solved elsewhere in the codebase** and simply never
propagated: `INSUFFICIENT_READS` existed on the dashboard and not in the report
or the Organisms panel; the `None`-vs-`[]` distinction was documented in
`_resolve_active_watchlist`'s own docstring and then defeated by a Store
default. The lesson is that a guard on one surface is not a guard on the tool.

## Controls that did nothing

Four settings were saved, reloaded, and ignored. They were treated on their
merits rather than uniformly:

| Setting | Outcome | Why |
|---|---|---|
| `danger_lower_limit` ("Alert Threshold") | removed | No consumer, while its tooltip promised "Lower values are more sensitive". Per-entry `alert_threshold` superseded it. |
| `remove_temp_files` ("Clean temp files") | removed | No consumer. Wiring it to Nextflow `cleanup` would delete work dirs for every existing install and break `-resume`. |
| `default_reads_per_level` | wired | Had an obvious consumer already on screen (Taxonomy min-reads control). |
| `gui_port` | wired | `--port` now defaults to None so config can win; it was clobbered by argparse's 8050 every launch. |

Also retired: `min_perc_identity`, a back-compat shim whose comment claimed
"New configs only carry the latter" while `create_default_config` wrote it into
every config. It was not a fallback; it was the only path, and it made the
identity slider decorative. The dangerous direction was downward — lowering the
threshold to catch a divergent strain left BLAST filtering at 90 in silence.

## What real data found that synthetic data could not

`/Volumes/sekvens2/kraken_db` and `/Volumes/Untitled/Bioshield` provided real
databases and real ONT reads with known truth, including a negative control.
Within minutes:

- The **negative control** (`barcode16`, 11 total reads, 6 of them
  *F. tularensis*) was screened as a clinical sample and produced ACTION
  REQUIRED, because under `by_barcode` input the sample name carries no marker
  and `negative_control_samples` was undiscoverable.
- Per-sample attribution counted the **per-rank `reads` column**, not
  `cumul_reads`: 29,721 against the Organisms tab's 34,096 for the same
  detection, and 4-against-6 for the control, which put it below the discovery
  floor so its contamination appeared nowhere.

No fixture in the suite produces an 11-read sample with a critical hit. Both
defects were unreachable without real data, which is the strongest argument in
this record for keeping a real corpus available.

It also confirmed CLAUDE.md's flextaxd model empirically: *Homo sapiens* keeps
NCBI 9606 while *F. tularensis* is 4007169 in the grafted block, and detection
matched watchlist taxid 263 to 4007169 **by name**, populating `detected_taxid`
correctly.

## Rejected, so it is not re-found

- **25-vs-14 container images.** Not a defect. The export deliberately unions
  singularity URLs with docker fallbacks; ~30% of nf-core modules ship only a
  `community.wave.seqera.io` tag.
- **Re-enabling the realtime nf-tests in CI.** Would reintroduce a known job
  hang. `docs/upstream-issues/26-watchpath-cleanup-hang.md` records that the
  watchPath fix is resolved on macOS/arm64 and **not** on the GitHub runner;
  a local pass does not contradict that.
- **`fastq_input_dir`'s unreachable branch.** Dead, but part of the
  mutually-exclusive input-source set that `_validate_single_input_source`
  guards and tests exercise. Removing it is churn against defensive code.

## Tests that could not fail

Three guards were found asserting something other than what their own docstring
claimed:

- `test_the_dashboard_is_not_reporting_an_unscreened_state` asserted
  `len(page_text) > 0` — a character count that passes whether the banner reads
  ACTION REQUIRED or NOT SCREENED. Its docstring named that exact failure mode.
  Worse, its fixture booted with `--config X --main_dir Y`, and the entry point
  discarded `--config` in that combination, so the whole real-server module had
  been walking the unscreened path.
- `failure_paths.nf.test` asserted only `workflow.success` while its own note
  claimed the manifest records the failure. The claim was unchecked and, on
  that input, false.
- `failed_samples.nf.test`'s "not supplied" case passed `[]`, which is the
  value the workflow sends when it HAS determined the answer — the test
  encoded the ambiguity that caused the bug.

When writing a guard, state the precondition that lets it fail.

## Air-gapped rig

See the "What the air-gapped rig proved" section of CLAUDE.md for the verified
list and, more importantly, the explicit list of what it did **not** prove.
The headline: Nextflow reused the bundled image by its `_singularity_cache_name`
filename with **zero pull attempts** on a machine with no route to anything.

## Residual risk

Unchanged and not closable on this hardware: real x86_64 execution (the rig is
arm64), setuid apptainer, a field kernel and distro, a pipeline run to
completion at scale, and conda-profile bundles with pre-warmed environments.
None of these should be reported as passed.
