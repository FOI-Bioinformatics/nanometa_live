# Subspecies resolution: measured results and defects

Exercise run 2026-08-20 against the plan in
[`docs/subspecies-resolution-test-plan.md`](../subspecies-resolution-test-plan.md).

## Summary

Subspecies resolution works, and works better than the database's minimizer
counts suggested. On simulated nanopore reads of known composition, Kraken2
placed 50-73% of *F. tularensis* clade reads at `S1` and named the correct
subspecies in all four pure barcodes, leading its nearest wrong sibling by
33-78x. A 70/30 mixture of two subspecies resolved into both components in the
right order. A negative control spiked with 19 contaminating reads gave up 13
of them, correctly below the alert threshold.

The application layer did not fare as well. Four defects were found and fixed,
all in the path between a subspecies watchlist entry and its reference genome.
Before the fixes, one of five watchlist entries obtained a usable genome; after
them, five of five do, each carrying the right organism. Fixed test-first with
31 new regression tests; full suite 3,973 passed, 108 skipped.

Three further findings are recorded but **not** fixed, because each is a
calibration or design decision rather than a defect:

- a sister species raises a subspecies alert at the configured threshold
  (finding 5);
- an absolute read threshold cannot work below species, because the
  cross-assignment noise floor scales with depth and the threshold does not
  (finding 6);
- `confirmed` on the Validation tab does not survive the move below species:
  all four subspecies come back confirmed in a sample containing one of them
  (finding 7). This is the one that most needs a decision.

## What was measured

Seven barcodes of 10,000 badread reads each (~40 Mbp, ~21x on a 1.9 Mb
genome), generated from verified complete RefSeq assemblies and classified
against the in-house `bioshield26.1_8G` flextaxd database.

| Barcode | Contents | Verdict | `S1` reads | of clade | Result |
|---|---|---|---|---|---|
| barcode01 | LVS (Type B) | PASS | 6,036 | 64.1% | holarctica leads by 64x |
| barcode02 | SCHU S4 (Type A) | PASS | 4,748 | 50.1% | tularensis leads by 33x |
| barcode03 | FSC147 | PASS | 5,317 | 56.5% | mediasiatica leads by 39x |
| barcode04 | U112 | PASS | 6,457 | 72.6% | novicida leads by 78x |
| barcode05 | LVS 69% + SCHU S4 29% | PASS | 5,698 | 60.7% | both resolved, observed 75/25 |
| barcode06 | *F. philomiragia* | FALSE POSITIVE | 66 | - | see finding 5 |
| barcode07 | *E. coli* + 19 LVS reads | PASS | 14 | - | 13/19 recovered, below threshold |

Misassignment among the three wrong subspecies runs at about 3% of `S1` reads
(19 of 595 in the pilot), which sets the noise floor for the specificity and
mixture checks.

**The mixture is biased, and the bias is the database's.** barcode05 was built
at 68.6% holarctica / 29.3% tularensis by read count, and resolved as 75%/25%.
The two subspecies carry different numbers of discriminating minimizers (1,901
vs 1,228), so the observed ratio overstates whichever component discriminates
better. The ordering is reliable; the proportions are not a quantitative
estimate of input abundance and should not be reported as one.

**Depth matters more than the headline numbers suggest.** Only about 60% of
clade reads reach `S1` even in a pure sample. A subspecies call therefore rests
on roughly half the evidence the species call does, and an `alert_threshold`
set from species-level intuition will be too high for a subspecies entry.

## Defects found

### 1. The project watchlist tier was searched in the wrong directory

`WatchlistLoader`'s contract names `<project_dir>/watchlists/` as the
highest-priority source. The manager was handing the loader
`results_output_directory` (falling back to `main_dir`), so two notions of
"project" inside one class disagreed: toggle state resolved under
`project_dir` while discovery searched the results directory.

Survivable while the project dir defaulted to the working directory and
results were written beneath it. It stopped being survivable in the same
session, because the project dir now defaults to `~/nanometa-projects/<name>`
while results live at `<project>/results/<slug>` -- so a watchlist placed
where the documentation says it goes was never found. The results directory
remains in the search path, since `import_watchlist(destination="project")`
has been saving operator uploads there.

Fixed in `c1ce198`, 9 tests.

### 2. The download fetched by the database graft id

`download_genomes_batch` assigned `entry["taxid"] = <cache taxid>` and only
then computed `_fetch_taxid` from that same dict. `genome_fetch_taxid` falls
back to `taxid`, so it received the flextaxd graft id and offered it to NCBI --
which its own docstring promises never happens. The line destroyed the field
the next line depended on.

The range check cannot catch this. Pseudo-taxids start at 2,000,000,000, while
a graft id (4,007,187) sits far below and is indistinguishable from a real
NCBI taxid by range alone. Only call order separates them.

This shows up on subspecies specifically. For a species, the Bacteria route
tries a name-based GTDB lookup first and succeeds; GTDB has no rank below
species, so a subspecies name finds nothing there and falls through to the
corrupted call.

### 3. Two download fallbacks ignored the cache taxid

`_download_ncbi_genome_by_taxid` honoured `cache_taxid` on its main path but
not in its two "no reference genome" fallbacks, which wrote the file under the
NCBI taxid. A genome under the wrong key is invisible: `has_genome(db_taxid)`
is False, so it reads as missing, is reported missing, and is re-downloaded on
every attempt.

Exactly three of the five entries landed this way -- those whose NCBI taxon has
no flagged reference genome. The two that do have one cached correctly, which
is why the defect presented as a partial success rather than an outright
failure.

### 4. A species-level entry was given a subspecies genome

An NCBI taxon query matches the whole subtree. Measured directly:

```
datasets summary genome taxon 263 --reference
-> GCF_000833355.1, organism tax_id 1450527,
   Francisella tularensis subsp. novicida D9876
```

So the *F. tularensis* watchlist entry received a *novicida* genome as its
reference -- the most sequence-divergent member of the group. Validation would
then measure a Type A or Type B detection against the wrong organism,
depressing identity and coverage for a true detection.

`--tax-exact-match` is the remedy but cannot be applied unconditionally: for
taxon 263 it yields nothing under `--reference`, because the only reference
genome in that subtree IS the subspecies. Downloads and accession resolution
now try the exact node first and fall back to the subtree, logging the organism
actually obtained rather than accepting it silently.

Findings 2-4 fixed together in `8c63c13`, 22 tests.

Effect, same five entries, before and after:

| Entry | Before | After |
|---|---|---|
| F. tularensis (4007169) | novicida D9876, wrong organism | *F. tularensis* 15NIIEG |
| subsp. tularensis (4007186) | cached as `119856.fasta`, invisible | correct |
| subsp. holarctica (4007187) | cached as `119857.fasta`, invisible | correct |
| subsp. mediasiatica (4007188) | cached as `135248.fasta`, invisible | correct |
| subsp. novicida (4007189) | correct | correct |

### 5. A sister species raises a subspecies alert

*F. philomiragia* (barcode06), which contains no *F. tularensis* at all, put
124 reads into the *F. tularensis* clade, 48 of them at *novicida*. At the
watchlist's `alert_threshold` of 25 that is an alert on a sample with none of
the organism in it.

This is not an application defect -- it is the cross-assignment floor between
congeneric species at 1.4% of clade reads, and *novicida* is both the most
divergent subspecies and the one nearest *philomiragia*, so the direction is
biologically plausible. It is recorded here because it has a direct
operational consequence: a subspecies `alert_threshold` in the low tens will
fire on a related species, and *F. philomiragia* is itself a rare human
pathogen that can plausibly appear in a real sample.

No fix is proposed. The right response is threshold guidance and, for any
subspecies detection, confirmation on the Validation tab.

### 6. An absolute read threshold is the wrong instrument below species

Not a defect either, but the clearest operational consequence of the exercise,
and only visible once the full run reached the product surfaces. The exported
report lists *F. t. holarctica* as DETECTED in five barcodes:

```
barcode01 (5,809 reads)  barcode05 (4,125 reads)
barcode04 (79 reads)  barcode02 (75 reads)  barcode03 (52 reads)
```

The first two are real. The last three are cross-assignment noise from the
other subspecies, and they appear only because 52-79 reads clears the
watchlist's `alert_threshold` of 25.

The noise floor is a *fraction* of clade reads (roughly 1-3%), so it scales
with depth while an absolute threshold does not. At 10,000 reads per barcode
that floor is 40-130 reads; at 100,000 it would be 400-1,300, and every
subspecies would be "detected" in every barcode containing the species. A
subspecies `alert_threshold` therefore has to be set against the expected
depth, or expressed as a share of the parent clade rather than a read count.

The verdict is not wrong -- the reads genuinely carry those assignments -- but
an operator reading "detected in 5 barcodes" will infer more than the data
supports.

### 7. "Confirmed" does not survive the move below species

**Not fixed. It changes the meaning of a safety-critical verdict in two repos
and needs a decision, not an improvised patch.**

Validation ran minimap2 for every (barcode, subspecies) pair, which answers a
question the plan had listed as unprovable. Two things came out of it, and they
point in opposite directions.

**Genome breadth does discriminate; identity does not.** For barcode01, which
contains only LVS:

| Reference | Mapped reads | Genome breadth | Identity | Status |
|---|---|---|---|---|
| holarctica (correct) | 5,651 | **0.981** | 99.84% | confirmed |
| novicida | 88 | 0.165 | 99.60% | confirmed |
| tularensis | 55 | 0.105 | 99.71% | confirmed |
| mediasiatica | 44 | 0.098 | 99.76% | confirmed |

Identity is useless below species -- 99.60-99.84% across all four, which is
what ~99.9% ANI predicts. Breadth separates cleanly, by 6-10x. The information
needed to call the right subspecies is present in the validation output.

**But the verdict does not use it that way.** All four are marked `confirmed`,
so the Validation tab tells the operator that holarctica, tularensis,
mediasiatica *and* novicida are all confirmed present in a sample containing
one of them. This is not a broken floor: the contract is
`MIN_READS_FOR_CONFIRMED = 10` and `MIN_BREADTH_FOR_CONFIRMED = 0.05`, and 44
reads at 9.8% breadth clears both. The floors were calibrated to separate a
real organism from index-hop carryover (0.07% breadth) while keeping amplicons
confirmable. They were never meant to arbitrate between four genomes that are
99.9% identical, and at that job an absolute 5% floor does not work.

The credit side: the false positive from finding 5 **is** caught. In barcode06
(*F. philomiragia*, no *F. tularensis* present) novicida comes back
`uncertain` -- 44 reads, breadth 0.026, identity 98.91% -- and holarctica comes
back `rejected` at zero reads. So the Validation tab is exactly the instrument
that refuses to confirm a cross-assignment from a related species, which is
what the watchlist action text tells the operator to consult. It just cannot
tell holarctica from mediasiatica within a true *F. tularensis* sample.

Note also that validation is confirmatory rather than independent here: the
reads handed to minimap2 for taxid X are the reads Kraken2 assigned to X, so
breadth largely tracks the Kraken2 read count. It answers "do the reads
assigned here really look like this genome" -- worth having -- not "which
subspecies is in this sample" arrived at separately.

A relative rule would fit the evidence: within one species, treat the sibling
with the highest breadth as the call and mark siblings below some fraction of
the leader (the observed gap is 6-10x) as cross-assignment rather than
`confirmed`. That is a change to the shared contract in
`tests/test_validation_threshold_contract.py`, `blast_validation_parser.py` and
the two nanometanf modules, so it is recorded here rather than made.

## The full run

Batch mode, seven barcodes, through the GUI with fresh project and data
directories, `bioshield26.1_8G`, conda profile, nanometanf `dev`.

Pipeline output reproduces the direct classification within chopper's filtering
(barcode01 `S1` 6,003 vs 6,036 reads), so nothing between Kraken2 and the
dashboard distorts the subspecies signal.

Confirmed on the product surfaces:

- **Genome preparation.** All five entries resolved, cached under their
  `db_taxid`, BLAST databases built for each, and
  `pipeline_input/pathogen_genomes.json` handed the pipeline five genomes keyed
  by the taxids the Kraken2 report uses.
- **Taxid mapping.** The Scan Database pass mapped 5 of 5 by
  `operator_db_taxid` with none unmapped or needing review, and detected the
  database profile correctly as `taxids_are_ncbi: true`, `nomenclature: gtdb`
  ("11/11 reference taxa match; 265/5000 sampled names carry a GTDB genus
  suffix") -- the hybrid flextaxd case.
- **Verdict banner.** Mid-run, with only the negative control classified, it
  read BELOW ALERT THRESHOLD naming *F. tularensis* and *F. t. holarctica*
  across 9,819 reads -- the sub-threshold state, correctly not a green screen.
  On completion it read ACTION REQUIRED, naming each subspecies separately with
  per-detection sample attribution and the negative-control clause appended
  ("also in negative control barcode07 (13 reads, 0.13% of positives)").
- **Organisms tab.** Subspecies render as full pathogen cards carrying the
  watchlist's threat level, common name ("Tularemia, Type B"), read count,
  share of sample, per-barcode attribution and action text.
- **Exported report.** Contains the separate "Subspecies and strains" table,
  correctly framed: "Listed separately because these are subdivisions of the
  species above, not additions to it: their reads are already counted in the
  parent species row." The report's banner, counts and negative-control clauses
  agree with the dashboard.

Two things went wrong in the run that were not application defects, recorded so
the next attempt is cheaper:

- The first launch died in `KRAKEN2_DB_PRELOAD` because conda could not build
  a new environment: `conda-forge/osx-arm64/repodata.json` was reachable but
  took 29 seconds, and the solve timed out. Pre-building that one environment
  into the shared cache and restarting with Continue (resume) recovered all 11
  completed tasks.
- `NXF_HOME` is set inside the results directory, so the nanometanf git clone
  (968 files, including its own kraken2 test fixtures) lives under
  `<results>/.nextflow`. Checked and found harmless: report discovery is scoped
  to `<results>/kraken2/` via `_scan_subdirs_for_pattern`, and the freshness
  walk only visits `RESULTS_WATCHED_SUBDIRS`, so neither ingests fixtures nor
  pays to walk the clone.

## Not proven

- Whether BLAST can separate the subspecies. minimap2 was measured (finding 7)
  and its breadth signal does separate them; `validation/blast/` was empty in
  this run, so the BLAST side is untested here.
- Realtime mode. Everything here is batch.
- Generality. These numbers come from one flextaxd database with 1,228-7,297
  discriminating minimizers per subspecies. A database built differently will
  behave differently, and the ordinal criterion, not the percentages, is what
  transfers.
- Error-model realism. badread at 93-97% read identity is more forgiving than a
  degraded flowcell.

## Reproducing

Dataset, ground truth and the evaluation script are under
`/tmp/nanometa_subsp/`. The watchlist used is
`subspecies_francisella.yaml` (5 entries: the species node plus its four
subspecies, each carrying both `db_taxid` and `taxid_ncbi`). Rebuild with
`build_dataset.sh`; evaluate any Kraken2 output directory with
`evaluate_subspecies.py <dir>`.
