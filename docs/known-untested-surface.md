# Known untested surface

Written 2026-07-29, at the close of a two-round pre-release bug hunt.

This document exists because the absence of a statement reads as coverage. The
test suite is large (3154 tests) and the campaign that produced this document
found nine real defects, which makes it easy to assume the remaining surface is
sound. Some of it is simply unexamined, and a biothreat tool should say which.

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

## Closed since this document was written

- **Singularity image-cache naming**, confirmed against real Apptainer in CI.
- **CI itself**, which had never run; now green on every job.
- **Six "reassuring conclusion" defects** found by asking of each surface
  whether it can state something it has not earned: the exported report's
  all-clear with nothing screened, ALL CLEAR over too few reads, a sample that
  produced no data offered like a healthy one, a readiness check reading a
  config key that does not exist, untracked fixtures, and two test bugs that
  only manifested under CI's profile.

## Not verified

### Air-gapped operation

Offline mode is asserted at the socket layer: outbound connections are made to
raise and the paths that would reach out are driven
(`tests/test_offline_no_network.py`). That proves the code does not *attempt* a
connection in-process.

It has never been run on a genuinely disconnected machine. Subprocess network
access is covered only by asserting no subprocess is spawned, which is weaker
than observing one fail. A truly air-gapped smoke test remains the only way to
know.

### Conda environment relocation across machines

**The known blocker.** Conda environments embed absolute build-machine paths.
The cross-machine bundle CI job (`.github/workflows/bundle-deploy.yml`)
deliberately passes `--no-pre-warm`, so it proves the bundle transfers and
imports, and proves nothing about pre-warmed environments.

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

### GUI behaviour beyond rendering

The live-server test opens all nine tabs and asserts no callback fails. It does
not drive multi-step flows: the preparation wizard, bundle export/import from
the UI, watchlist upload/download round-trip, the output-collision modal, or the
Resume/Discard session banner. Export Results is covered by unit tests against
its generator, not by clicking the button.

### Pipeline failure paths

Nothing asserts that the pipeline fails *cleanly* on a missing database, an
unreadable FASTQ, or a corrupt input. The one case covered is an empty input
directory, which succeeds without scheduling work. Failure-injection tests exist
on the Python side (process killed, truncated report, database unmounted) but
not on the Nextflow side.

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
