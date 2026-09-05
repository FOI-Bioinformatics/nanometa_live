# Known untested surface

Written 2026-07-29, at the close of a three-round pre-release bug hunt.
Last updated 2026-08-14, after the August campaign.

This document exists because the absence of a statement reads as coverage. The
test suite is large (3426 tests) and the campaigns that produced this document
found thirty-eight real defects between them, which makes it easy to assume the
remaining surface is sound. Some of it is simply unexamined, and a biothreat tool should say
which.

Each entry states what is not known, why it is not known, and what it would
take to find out.

---

## Verified in this campaign

Stated first so the gaps below are read in proportion.

- **Confirmatory validation, end to end on real reads.** *Francisella
  tularensis* LVS confirmed at 98.27% BLAST hit rate / 97.34% identity and
  98.59% minimap2 / 99.82% identity, close to the previously recorded baseline.
  Three defects had to be fixed before this worked at all.
- **Classification against three independent databases.** The same barcode gave
  34,096 / 34,133 / 34,125 reads for taxid 263 under k2_pluspfp, minikraken2 and
  the Bioshield flextaxd build.
- **Batch and realtime agree exactly** on every sample of a three-barcode run.
- **Sample grouping does not change the biology.** per_file and single_sample
  over identical input: 12 taxa and 3,160 classified reads both ways, nothing
  lost or invented, 0.00% drift.
- **The negative control carries no software-side contamination.** 6 reads of
  taxid 263 appear whether it is run alone or multiplexed with a high-titre
  sample, which places them in the FASTQ rather than in our demultiplexing.
- **The dashboard serves without callback errors.** All nine tabs, 208
  `/_dash-update-component` requests, all 200/204.

---

## Closed by the August 2026 campaign

Full record in [`audit/campaign-2026-08.md`](audit/campaign-2026-08.md).

- **Air-gapped operation, on a real rig.** Ubuntu + apptainer 1.5.3, verified
  air-gapped before any result was trusted. Nextflow reused the bundled image
  by its `_singularity_cache_name` filename with **zero pull attempts**; the
  GUI served with no external URLs and its icon fonts resolved. The section
  below is narrowed accordingly, not deleted -- amd64 execution, setuid
  apptainer and a real field kernel remain untested.
- **Bundle export/import honesty.** A wrong `--db` path, an unwritable config,
  and blocker wording that claimed an abort that did not happen.
- **The exported report's read-depth gate**, and the same distinction carried
  to the Organisms panel and to the wording of an alarm.
- **Per-sample attribution**, which counted the per-rank `reads` column while
  every other surface used `cumul_reads` -- a 13% discrepancy on a real
  detection, and a negative control pushed below the discovery floor.
- **Negative controls end to end**: recognised, reported alongside a detection
  with reads and share of the positives, and declarable from the GUI.
- **Four settings that did nothing** -- two removed, two wired.

Worth recording because it is the campaign's clearest lesson: the last two
entries were only reachable with a **real database and real reads**. No fixture
in the suite produces an 11-read sample carrying a critical pathogen, and both
defects surfaced within minutes of the real corpus being available.

---

## Closed since this document was written

- **Singularity image-cache naming**, confirmed against real Apptainer in CI.
- **CI itself**, which had never run; now green on every job.
- **Ten "reassuring conclusion" defects** found by asking of each surface
  whether it can state something it has not earned: the exported report's
  all-clear with nothing screened, ALL CLEAR over too few reads, a sample that
  produced no data offered like a healthy one, a readiness check reading a
  config key that does not exist, untracked fixtures, and two test bugs that
  only manifested under CI's profile.

  Four more in the preparation tab, which is what an operator uses to ready a
  field deployment, so each one ships:

  - The offline-prep wizard announced "All 8 steps completed. System is ready
    for offline deployment" while its own step 0 said no watchlist was
    enabled. Several steps report a problem by returning a warning alert
    rather than raising, and the loop discarded the return value.
  - Genome download reported "All genomes already downloaded" with a green
    Complete badge when the inventory it reads had never been computed. The
    store started as `{}`, which was indistinguishable from "nothing missing".
  - BLAST database build reported "All BLAST databases already built" when
    there were no genomes at all -- vacuously true, and identical on screen to
    a prepared system.
  - Genome download's Complete badge counted download failures only, so every
    download landing while every BLAST build failed still read Complete.

  The last three share a consequence: a genome without a BLAST database cannot
  be validated against, so the first evidence is a validation that cannot run,
  on a field machine, long after the green badge.

## Not verified

### Air-gapped operation

Offline mode is asserted at the socket layer: outbound connections are made to
raise and the paths that would reach out are driven
(`tests/test_offline_no_network.py`). That proves the code does not *attempt* a
connection in-process.

**Closed 2026-08-14.** It has now been run on a genuinely disconnected
machine: a `--privileged` Ubuntu container with `--network none`, verified to
have loopback only, no DNS and no outbound TCP before any result was trusted.
A bundle was exported, verified, imported and served. Nextflow resolved the
bundled image from `NXF_SINGULARITY_CACHEDIR` and attempted **no pull** (zero
matches for pull/download and zero network errors in `.nextflow.log`); the GUI
returned HTTP 200 with no external URLs and both icon fonts resolving.

What that run did **not** establish, and what remains open here: the images are
amd64 and the rig is arm64, so nothing was executed -- the run failed exactly
at "the image's architecture (amd64) could not run on the host's (arm64)",
which confirms the documented cross-platform restriction rather than testing
around it. Real x86_64 execution, setuid-mode apptainer, and a field kernel and
distro are still unknown.

**amd64 execution of a bundled image, verified 2026-09-05 in CI.** The
bundle-deploy workflow exports a singularity bundle on an amd64 runner,
imports it on a second and runs the bundled image with `NXF_OFFLINE=true`;
the Nextflow log shows the local-library hit and no pull, and the process
reports x86_64. Limits: one stand-in module and one image, not the full
nanometanf set, and the runner is not air-gapped. The sibling conda-mode
`import` job in the same workflow run (33947378546) failed on stale
build-machine paths (`nanometa_home`, `data_dir`, `genome_cache_dir`) in its
rebased config, so the record above should not be over-read as covering that
path too -- see the pre-existing defect noted in the Task 2 report.

### Conda environment relocation across machines

**The known blocker.** Conda environments embed absolute build-machine paths.
The cross-machine bundle CI job (`.github/workflows/bundle-deploy.yml`)
deliberately passes `--no-pre-warm`, so it proves the bundle transfers and
imports, and proves nothing about pre-warmed environments. Its first
recorded run was 2026-09-05 (it had been gated on pull requests touching
files that no pull request changed), and that run failed its own
assertion: the imported config still named the build machine's `data_dir`,
`genome_cache_dir` and `nanometa_home`. The import now rebases those keys
onto the field installation's root; the job is green from the fix commit
onward.

An operator who exports with pre-warmed environments and imports on a field
machine at a different path is in untested territory. A CI variant that
pre-warms on one runner and imports on a second was designed and postponed.

### Architecture portability

Both bundle-deploy runners are the same OS and architecture. Conda environments
carry per-architecture binaries, so arm64-to-x86 and macOS-to-Linux transfer are
unproven. The documented restriction (build and field machine must match) has
not been tested in either direction.

### Singularity

A CI job now renders the profile, stub-runs under it, and checks that Nextflow
caches a pulled image under the filename the offline bundle predicts
(`BundleManager._singularity_cache_name`). That check is the important one: if
upstream changes the convention, our unit test still passes while a field
machine silently re-pulls every image.

**Verified 2026-07-29.** The job ran and passed on GitHub Actions with real
Apptainer: the profile renders, the pipeline runs under it in stub mode, and
Nextflow cached a pulled image under exactly the filename
`_singularity_cache_name` predicts. The offline bundle's image naming is
therefore confirmed against the real `SingularityCache` convention rather than
only against our own reimplementation.

Still unverified: a real (non-stub) pipeline run under Singularity, and
Singularity on an actually air-gapped machine.

### Docker profile, locally

The Docker daemon was down for the whole campaign. Everything local ran under
`-profile conda`. CI runs `-profile test,docker`, so the Docker path has CI
coverage, but no run in this campaign exercised it.

### Realtime mode in CI

The realtime nf-tests are excluded from CI because `watchPath` leaks a
`FileAlterationMonitor` thread on the GitHub ubuntu runner. Realtime was
verified twice on macOS/arm64 (2026-05-10, and again 2026-07-29 with a real 8 GB
database, exiting cleanly in 235 s), and a full realtime pipeline run agreed
exactly with batch mode. On Linux, realtime behaviour is verified nowhere.

### Validation beyond a single sample

The successful validation run (R10) covered one sample and one taxid: barcode11,
taxid 263. Multi-sample validation, the negative control through validation, and
the realtime cumulative/per-batch validation drill-down were not exercised on
real data. The unit tests for those paths pass, but unit tests passed throughout
the period when validation produced nothing at all.

### The preparation tab, beyond its verdicts -- partially closed

872 statements at 35% coverage, the largest untested user-facing surface. Round
3 audited every place it states an outcome and fixed the four defects listed
above; those paths are now covered and mutation-checked.

What remains untested is the work itself rather than the reporting: a bundle
export and import driven from the UI, a genome download that actually reaches
NCBI, a BLAST database built from a real genome. The unit tests stub the
genome manager, so they prove the tab reports its results honestly, not that
the results are right.

### GUI behaviour beyond rendering

The live-server test opens all nine tabs and asserts no callback fails. It does
not drive multi-step flows: the preparation wizard, bundle export/import from
the UI, watchlist upload/download round-trip, the output-collision modal, or the
Resume/Discard session banner. Export Results is covered by unit tests against
its generator, not by clicking the button.

### Pipeline failure paths -- partially closed

Round 3 added `tests/failure_paths.nf.test`, which asserts the pipeline refuses
a nonexistent database naming the path, an incomplete database naming the
missing `.k2d` file, and no database at all while pointing at both
`--kraken2_db` and `--skip_kraken2`.

Closed 2026-07-29. An unreadable FASTQ is still absorbed by
`conf/error_isolation.config` and the run still reports success -- correct for a
24-barcode run, where one bad barcode must not abort the other 23 -- but the
drop is now recorded rather than silent. `_manifest.json` carries
`failed_samples`, derived from the difference between the samples attempted and
those that emitted QC output, and the GUI marks them in the sample selector.
`null` there means "not determined" and stays distinct from `[]` meaning "none
failed".

---

## Two cautions from the campaign itself

**A passing stub suite is not evidence that a feature works.**
`validation_assembly_stub_matrix.nf.test` ran the full pipeline with
`run_validation = true` and passed throughout the period when validation
silently produced an empty result file. It asserted that the run succeeded and
that a versions file was written. Both were true. Nothing asserted that
validation produced a result.

**CI had not run at all.** The nf-test workflow fired on pushes to `master` and
on pull requests; development happens on `dev`, so no job had run for weeks.
Three of the defects found in this campaign are exactly what that suite would
catch.

**A guard must state the precondition that lets it fail.** The August campaign
found three tests asserting something other than what their own docstrings
claimed: a browser check asserting `len(page_text) > 0` (a character count that
passes whether the banner reads ACTION REQUIRED or NOT SCREENED, and whose
docstring named that exact failure mode); a pipeline test asserting only
`workflow.success` while its note claimed the manifest records the failure; and
a module test whose "not supplied" case passed `[]`, the value the workflow
sends when it HAS determined the answer. Each was written in good faith. None
could fail.

**Synthetic fixtures cannot reach some defects.** Two August defects -- an
alarm carrying no depth on a 6-of-11-read negative control, and attribution
counting the wrong read column -- were invisible to a 3400-test suite and
surfaced within minutes of a real database and real reads being available. A
real corpus is not a luxury for this tool.

Fixed 2026-07-29 by adding `dev` to the push branches. The first run failed 20
of 155 tests, almost all because thirteen test fixtures had never been
committed -- a blanket `test_*` in .gitignore excluded them, so every affected
test passed locally and failed on a fresh clone. The third run was fully green:
155 tests on both Nextflow 26.04.0 and latest-everything, plus Singularity and
all three platform profiles.

`tests/lib/fixtures_are_tracked.py` now runs before the suite and fails if any
fixture a test references is untracked. It also refuses to pass when it finds
nothing to check, because its first version did exactly that -- an
absolute-path skip matched the runner's checkout directory and it reported
"0 fixture paths" while exiting 0.
