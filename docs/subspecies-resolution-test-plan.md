# Subspecies resolution end-to-end test plan

Status: proposed, 2026-08-20. Companion to
`docs/sample-handling-test-plan.md` and
`docs/quickstart-with-nanorunner.md`.

## Purpose

Nanometa Live claims to resolve organisms below species rank: `SPECIES_RANKS`
covers `S1`-`S3`, the Taxonomy tab offers a Subspecies Focus preset, the
Organisms tab offers an `S1` rank filter, and the exported report gives
subspecies their own table. None of that has been exercised end to end against
a database that actually resolves subspecies.

This exercise answers four questions with simulated reads of known
composition:

1. Does a subspecies-level detection travel intact from Kraken2 report through
   watchlist matching, verdict banner, Organisms tab and exported report?
2. With a fresh data directory, are the *correct* reference genomes downloaded
   for subspecies watchlist entries, and are they stored under the right key?
3. Given a barcode, can an operator determine which subspecies it contains?
4. What does the system report for a barcode containing a mixture of two
   subspecies of the same species?

Question 3 is the one with a genuinely uncertain answer. Kraken2's ability to
place a read at `S1` depends on how many subspecies-discriminating minimizers
survived database minimization, and the four *F. tularensis* subspecies are
roughly 99.9% identical. The exercise is therefore designed to *measure*
discrimination against ground truth, not to assume it.

## Why Francisella tularensis

The in-house `bioshield26.1_8G` flextaxd database resolves four subspecies
under *F. tularensis*, which is the clinically meaningful split named in
CLAUDE.md (Type A versus Type B is a virulence distinction, not a taxonomic
footnote). Verified from `inspect.txt`:

| DB taxid | DB name (GTDB style, no `subsp.`) | Minimizers | NCBI taxid |
|---|---|---|---|
| 4007169 | Francisella tularensis (species, `S`) | 20,329 direct | 263 |
| 4007186 | Francisella tularensis tularensis | 1,228 | 119856 |
| 4007187 | Francisella tularensis holarctica | 1,901 | 119857 |
| 4007188 | Francisella tularensis mediasiatica | 1,588 | 135248 |
| 4007189 | Francisella tularensis novicida | 7,297 | 264 |

The database holds 16,102 `S1` nodes in total; *Brucella melitensis* (8
subspecies) and *Yersinia pestis* (2) are available as a second organism if the
*Francisella* result warrants a replication.

Note the ratio in that table sets expectations: subspecies-specific minimizers
are roughly 6-30% of the species node's direct count. A minority of reads
reaching `S1` is the expected outcome, not a failure. The test criterion is
therefore ordinal (the correct subspecies must rank first, and clearly above
its siblings), not a fixed percentage.

## Reference genomes (accessions verified against NCBI, 2026-08-20)

| Role | Strain | Accession | Assembly | NCBI taxid |
|---|---|---|---|---|
| Type A | subsp. *tularensis* SCHU S4 | `GCF_000008985.1` | Complete | 177416 |
| Type B | subsp. *holarctica* LVS | `GCF_000009245.1` | Complete | 376619 |
| mediasiatica | subsp. *mediasiatica* FSC147 | `GCF_000018925.1` | Complete | 441952 |
| novicida | subsp. *novicida* U112 | `GCF_000014645.1` | Complete | 401614 |
| sister species | *F. philomiragia* (reference) | `GCF_018135955.1` | Complete | 28110 |
| background | *E. coli* K-12 MG1655 | `GCF_000005845.2` | Complete | 511145 |

*F. tularensis* subsp. *mediasiatica* has no complete RefSeq assembly at
subspecies-taxid level; FSC147 is the complete strain-level genome and is what
should be used.

## Ground-truth barcode matrix

Seven barcodes, `sample_handling: by_barcode`. Composition is known per read,
because the builtin and badread generators both carry the source genome stem in
the read ID.

| Barcode | Composition | Purpose | Expected top `S1` |
|---|---|---|---|
| barcode01 | LVS, pure | Type B baseline | *F. t. holarctica* (4007187) |
| barcode02 | SCHU S4, pure | Type A baseline | *F. t. tularensis* (4007186) |
| barcode03 | FSC147, pure | third subspecies | *F. t. mediasiatica* (4007188) |
| barcode04 | U112, pure | most divergent subspecies; positive control for the method | *F. t. novicida* (4007189) |
| barcode05 | LVS 70% + SCHU S4 30% | **mixture of two subspecies** | both present, holarctica > tularensis |
| barcode06 | *F. philomiragia*, pure | specificity: a sister species must not produce a spurious *F. tularensis* subspecies call | none under 4007169 |
| barcode07 | *E. coli* 99.8% + LVS 0.2% | declared negative control carrying trace contamination | trace holarctica, reported not acted on |

barcode04 is the method's positive control: *novicida* has by far the most
discriminating minimizers (7,297), so if subspecies assignment fails even
there, the problem is in the pipeline rather than in taxonomic resolution.

barcode07 exercises two guards at once: `negative_control_samples` reporting
("also in negative control barcode07 (N reads, X% of positives)") and the
shallow-depth clause. It must never suppress the barcode01 detection.

## Environment decisions

- **Read simulation must use badread, not the builtin generator.** The builtin
  backend emits error-free subsequences, which would inflate subspecies
  discrimination well above what a real run achieves. badread 0.4.2 is
  installed in the `nanorunner` conda environment. It is only detected when
  that environment is activated (running the binary by absolute path leaves it
  off `PATH` and `nanorunner list-generators` reports it missing). Activate the
  environment.
- **Do not read the Kraken2 database from `/Volumes/sekvens2`.** That volume is
  exFAT; memory-mapped random access over USB is the case the readiness
  checklist warns about, and macOS writes AppleDouble sidecars there. A local
  APFS copy of `bioshield26.1_8G` already exists at
  `/tmp/nanometa_e2e/bioshield26.1_8G` (7.5 GB) - reuse it.
- **No Nextflow work directory or conda environment on exFAT.** Both need
  symlinks and POSIX permissions.
- **Reuse the existing conda cache.** A fresh data directory would otherwise
  rebuild every pipeline environment (tens of minutes). Export
  `NXF_CONDA_CACHEDIR=/tmp/nanometa_e2e/datadir/work/conda` (4.2 GB, already
  populated) before launching; `_build_nextflow_env` copies `os.environ`, so
  the variable propagates to GUI-spawned runs. The cache must stay at its
  original absolute path - conda environments embed build-time paths and do not
  survive being copied elsewhere.
- **Kraken2 must be 2.1.6.** 2.1.5 segfaults with `--memory-mapping` under
  Rosetta.
- Local root has 19 GB free with `/tmp/nanometa_e2e` occupying 23 GB. See
  Phase 0.

## Phase 0 - prerequisites

1. **Settle the uncommitted working tree.** Five modified files and three new
   test files are outstanding, including `resolve_project_dir()`, which changes
   the project directory default from `os.getcwd()` to
   `~/nanometa-projects/<name>`. That is precisely the code path this exercise
   depends on. Run the two unverified test files, then the full suite and the
   code-size gate:

   ```bash
   /Users/andreassjodin/miniforge3/envs/nanometa/bin/python -m pytest -q -o addopts="" \
       tests/test_project_dir_default.py tests/test_watchlist_file_path_visible.py
   /Users/andreassjodin/miniforge3/envs/nanometa/bin/python -m pytest -q -o addopts=""
   python scripts/check_code_size.py
   ```

   Commit before starting, so the exercise tests committed code. The
   `--project` help text in `app/__main__.py` still reads "default: current
   directory" and is now stale; fix it in the same commit.

2. **Reclaim disk.** `/tmp/nanometa_e2e/results` (3.8 GB) and the four stale
   watch directories (~2 GB) are recoverable. Keep `bioshield26.1_8G` (7.5 GB)
   and `datadir/work/conda` (4.2 GB) - both are reused above. This step deletes
   prior run artifacts and needs an explicit go-ahead.

3. **Confirm the toolchain**: `nextflow -v` (26.04.6 present), kraken2 2.1.6,
   minimap2 and blastn in the `nf-core` environment, `datasets` CLI on `PATH`.

## Phase 1 - acquire the genomes

```bash
conda activate nanorunner
nanorunner download \
  --accession GCF_000009245.1 --accession GCF_000008985.1 \
  --accession GCF_000018925.1 --accession GCF_000014645.1 \
  --accession GCF_018135955.1 --accession GCF_000005845.2
```

Omitting `--target` downloads without generating. Genomes land in
`~/.nanorunner/genomes/ncbi/<accession>.fna.gz`. *E. coli* `GCF_000005845.2` is
already cached there.

Rename or symlink to readable stems before generating - with `--genomes` the
file stem becomes both the read-ID prefix and the output filename, which is what
makes ground truth legible later:

```
holarctica_LVS.fna.gz, tularensis_SCHUS4.fna.gz, mediasiatica_FSC147.fna.gz,
novicida_U112.fna.gz, philomiragia.fna.gz, ecoli_K12.fna.gz
```

Note `--abundances` is only accepted alongside `--genomes`; it is rejected with
`--accession`/`--species`/`--taxid`/`--mock` because the config is validated
before genome resolution. Downloading first and then passing local files is the
working route, not merely a stylistic preference.

## Phase 2 - pilot before committing to the full matrix

Generate one barcode of 1,000 badread reads from LVS, classify it directly with
kraken2 against `bioshield26.1_8G`, and read off:

- badread throughput in Mbp/min, which sets the depth budget for Phase 3;
- the fraction of reads assigned to `S1` versus `S` versus `G`, which
  establishes whether the ordinal success criterion is even reachable.

If essentially no reads reach `S1` for LVS, run the same pilot on U112
(barcode04's genome, 7,297 discriminating minimizers). A negative result on
both would mean the database, not the application, limits subspecies
resolution - a finding worth reporting on its own, and the point at which the
rest of the exercise should be rescoped rather than run.

### Measured, 2026-08-20

1,000 badread reads from LVS at 4,008 bp mean length, 93-97% read identity;
96.9% classified in 5.4 s with `--memory-mapping`.

| Node | Reads | Share of clade |
|---|---|---|
| holarctica (correct) | 576 | 60.7% |
| tularensis | 7 | 0.7% |
| novicida | 7 | 0.7% |
| mediasiatica | 5 | 0.5% |
| stopped at species 4007169 | 354 | 37.3% |
| genus only | 3 | 0.3% |

Discrimination is substantially stronger than the minimizer counts suggested:
61% of clade reads reach `S1`, and the correct subspecies leads its runner-up
by 82x - well above the proposed 5x criterion, which is therefore kept as a
floor rather than raised to match. Misassignment among the three wrong
subspecies is 19 of 595 `S1` reads (3.2%), which sets the expected noise level
for the specificity and mixture checks.

Throughput is about 7.5 Mbp/min per badread process, so a 10,000-read barcode
takes roughly 5 minutes. Running the seven barcodes as separate concurrent
processes keeps the whole dataset inside one such interval.

Also confirmed here: kraken2 2.17.1 reads the flextaxd database without
complaint, so the 2.1.5 memory-mapping segfault is not a concern for this
exercise.

## Phase 3 - build the dataset

Target depth: 10,000 reads per barcode at 4,000 bp mean length (about 40 Mbp,
roughly 21x on the 1.9 Mb *F. tularensis* genome), adjusted by the Phase 2
throughput measurement. `--reads-per-file 1000` gives ten files per barcode,
enough granularity for the later realtime pass.

Barcodes 01-04 and 06, one genome each, in flag order:

```bash
nanorunner generate \
  --target $DATASET \
  --genomes holarctica_LVS.fna.gz \
  --genomes tularensis_SCHUS4.fna.gz \
  --genomes mediasiatica_FSC147.fna.gz \
  --genomes novicida_U112.fna.gz \
  --genomes philomiragia.fna.gz \
  --generator-backend badread \
  --read-count 50000 --reads-per-file 1000 --mean-read-length 4000 \
  --no-wait --no-parallel --seed 42
```

`--read-count` is the total across genomes, so 50,000 gives 10,000 each. With
more than one `--genomes` the structure defaults to multiplex and the barcode
index follows flag order, giving `barcode01/holarctica_LVS_reads_0000.fastq.gz`
and so on. `--no-parallel` is required for byte-reproducibility: the parallel
path spawns per-file RNGs and the output stops being seed-determined.

barcode05, the mixture, is a second invocation targeting the barcode directory
directly, because `--mix-reads` is ignored in multiplex mode:

```bash
nanorunner generate \
  --target $DATASET/barcode05 \
  --genomes holarctica_LVS.fna.gz --genomes tularensis_SCHUS4.fna.gz \
  --abundances 0.7 --abundances 0.3 \
  --mix-reads --force-structure singleplex \
  --generator-backend badread \
  --read-count 10000 --reads-per-file 1000 --mean-read-length 4000 \
  --no-wait --no-parallel --seed 43
```

This writes `barcode05/reads_NNNN.fastq.gz` with each file split 70/30 and the
reads interleaved. Verified empirically at small scale: the composition lands
exactly on the requested split and read IDs retain the genome stem.

barcode07, the negative control, is the same shape with a 0.998/0.002 split of
*E. coli* and LVS - about 20 contaminating reads in 10,000.

Do not re-run a multiplex generate into `$DATASET` afterwards: barcode
numbering restarts at `barcode01` each run and would overwrite.

Finally, record ground truth. Note that badread does **not** put the genome
stem in the read ID - it emits a UUID plus the source contig accession and
coordinates in the description field:

```
@55efcf5c-... NC_007880.1,-strand,809349-814150 length=4781 read_identity=93.750%
```

So ground truth for the mixed barcodes comes from the contig accession
(`NC_007880.1` = LVS, `NC_006570.2` = SCHU S4, `NC_000913.3` = *E. coli*), not
from the filename stem. This is only a concern for barcode05 and barcode07;
the pure barcodes are identified by their directory. Count reads per accession
per barcode and write `ground_truth.json`. This is the file every later
assertion compares against.

## Phase 4 - author the subspecies watchlist

No shipped watchlist contains a subspecies entry, so this exercise needs one:
`subspecies_francisella.yaml`, v2.0 schema, five entries (four subspecies plus
the species node as a control).

Each entry must carry **both** identifiers:

- `db_taxid`: the flextaxd graft id (4007186-4007189). This is what matches the
  Kraken2 report and what the genome is cached under.
- `taxid_ncbi`: the real NCBI subspecies taxid (119856, 119857, 135248, 264).
  This is what the genome is *fetched* by.

The two are separate on purpose (commit `6fbd966`). Omitting `taxid_ncbi` is
not a cosmetic lapse here: the GTDB lookup path builds
`s__Francisella_tularensis_holarctica`, GTDB has no node below species, and
there is no strip-to-species fallback - so an `S1` entry without `taxid_ncbi`
has no route to a genome at all. Setting `alert_threshold` low (10-25 reads) is
appropriate given that only a minority of reads are expected to reach `S1`.

Including the species node alongside its four subspecies is itself a test: they
share NCBI parent 263, which is exactly the collision the uncommitted
`_identity_key()` fix addresses. All five entries must remain distinct in the
Watchlist tab. That is the behavioural confirmation the previous session
deferred.

## Phase 5 - fresh directories and genome download

```bash
export NXF_CONDA_CACHEDIR=/tmp/nanometa_e2e/datadir/work/conda
python -m nanometa_live.app \
  --config $PROJECT/config.yaml \
  --data-dir $FRESH_DATA \
  --project $FRESH_PROJECT \
  --port 8060
```

Genome download is **not** automatic at pipeline start. `parameter_mapping`
only writes `pipeline_input/pathogen_genomes.json` from genomes already cached.
Downloading is a deliberate GUI action: Preparation tab, "Download All".

Checks after the download completes:

1. `$FRESH_DATA/genomes/` contains `4007186.fasta` ... `4007189.fasta` - named
   by **db_taxid**, not by the NCBI taxid.
2. Each FASTA's definition line names the expected subspecies. A file existing
   is not the same as the right organism being in it; a fuzzy GTDB name match
   returning the species representative would produce four identical files.
   Compare sizes and the first header of each.
3. `genome_metadata.json` records the accession actually fetched.
4. **Predicted defect, confirm or refute**: `preparation_tab.py:1805` tallies
   results using the entry's own taxid while `download_genomes_batch` keys its
   results by the cache taxid. A successful subspecies download is expected to
   be counted as a failure in the badge and log. If the badge says four
   failures while four correct FASTAs are on disk, that is the defect.
5. `nanometa-prepare` reaches the same downloads through
   `mobile_lab_preparer.py`, which was never converted to the fetch/cache
   split. Check whether the CLI path fetches by the graft id (4007187) and
   therefore returns the wrong organism or nothing.
6. Confirm nothing was written into the repository checkout - the point of the
   `resolve_project_dir` change.

## Phase 6 - pipeline run

Batch mode first, because it is the shorter loop and the subspecies question
does not depend on realtime behaviour.

```yaml
processing_mode: batch
sample_handling: by_barcode
nanopore_output_directory: $DATASET
kraken_db: /tmp/nanometa_e2e/bioshield26.1_8G
blast_validation: true
min_reads_for_validation: 10
negative_control_samples: ["barcode07"]
```

Watch for the collision modal (the outdir is fresh, so it should not appear)
and confirm the run metadata fingerprint is written.

## Phase 7 - evaluate against ground truth

A small script, not a GUI reading. For each barcode, parse
`kraken2/<barcode>.kraken2.report.txt` and produce:

- reads at each of the four `S1` nodes;
- reads at the species node 4007169 and at genus 4007157;
- the fraction of the barcode's *F. tularensis* clade reads that reached `S1`.

Success criteria, in order of importance:

1. **Correct assignment.** For each of barcode01-04, the expected `S1` node
   carries more reads than any other `S1` node under 4007169. This is the
   claim the exercise exists to test.
2. **Separation.** The expected node exceeds the runner-up by a margin large
   enough to be actionable - propose 5x, to be confirmed or revised against
   the Phase 2 pilot rather than asserted now.
3. **Specificity.** barcode06 (*F. philomiragia*) produces no `S1` node under
   4007169 above the discovery floor.
4. **Depth honesty.** The `S1` fraction is reported alongside every subspecies
   claim. A subspecies call resting on 40 reads out of 10,000 must not be
   presented with the same confidence as the species call resting on 9,000.

Record the measured `S1` fraction whatever it is. If subspecies assignment is
real but thin - say 2-5% of clade reads - that is the honest answer to question
3, and it has a direct operational consequence: `alert_threshold` for an `S1`
watchlist entry cannot be set from species-level intuition.

## Phase 8 - the mixture

barcode05 is where the interesting failure modes are.

- Do both *holarctica* and *tularensis* appear as separate `S1` rows?
- Is their read ratio ordered correctly (holarctica > tularensis)? The absolute
  ratio will not be 70:30 - the two subspecies have different numbers of
  discriminating minimizers, so the observed ratio is biased by the database.
  Quantify that bias by comparing barcode05 against the barcode01 and barcode02
  single-subspecies baselines; the plan is to report the bias, not to correct
  for it.
- Does the verdict banner name both, and does per-sample attribution resolve
  barcode05 for each? `samples_for_detection` must be exercised here rather
  than a direct index into `taxid_to_samples`.
- Does either detection get lost because `alert_threshold` is applied per
  sample? A mixture splits reads between two entries and may leave both below a
  threshold that the combined species-level count clears.
- Does the `ambiguous_with` machinery fire? *F. tularensis* subspecies are
  separate nodes rather than shared ones, so it should not - but the
  *Burkholderia mallei* / *pseudomallei* case in the same database shows what
  it looks like when it does.

## Phase 9 - GUI and report

Only after the numbers are established, since a GUI check against unknown
ground truth proves nothing.

- **Taxonomy tab**: enable the Subspecies Focus preset (`G, S, S1`) and confirm
  the `S1` nodes hang off their species in both Sankey and Sunburst. Both views
  resolve parents through the taxid chain, so this should hold; confirm rather
  than assume.
- **Organisms tab**: set the rank filter to `S1`, confirm each barcode's
  subspecies appears with the right read count and that the count matches
  `cumul_reads` rather than the per-rank column.
- **Dashboard verdict banner**: ACTION REQUIRED naming the subspecies, with
  per-sample attribution listing the right barcodes and the barcode07 negative
  control appended as an observation rather than a suppression.
- **Export Results**: the report must render the separate subspecies table
  (`_extract_organisms` is called once for `S` and once for `S1/S2/S3`), and
  must not list a species beside its own subspecies in the abundance ranking.
- **Validation tab**: check whether BLAST identity or minimap2 breadth
  distinguishes the four genomes at all. The prior expectation is that they do
  not, at roughly 99.9% ANI - every read maps well to every subspecies
  reference. If so, that belongs in the write-up as a stated limit: validation
  confirms *F. tularensis*, and Kraken2 is the only surface making a subspecies
  claim. That is a meaningful caveat for an operator reading a Type A result.

## Phase 10 - realtime pass (optional)

If Phases 6-9 pass, replay the same dataset as timed batches to confirm the
subspecies rows survive cumulative aggregation:

```bash
nanorunner replay --source $DATASET --target $WATCH \
  --interval 15 --operation copy
```

with `processing_mode: realtime` and `realtime_timeout_minutes: 10`. The point
of interest is whether a subspecies row that appears in batch 3 is still there
in batch 10, given the aggregator rewrites per-pair stats each batch.

## Phase 11 - write-up

`docs/audit/subspecies-2026-08-XX.md`, following the existing audit documents:
the measured numbers, the defects found with commits, and an explicit statement
of what was *not* proven. In particular, a result from one flextaxd database
with 1,228-7,297 discriminating minimizers per subspecies does not generalize
to other databases, and should not be written as though it does.

## Risk register

| Risk | Handling |
|---|---|
| Kraken2 assigns too few reads to `S1` for any conclusion | Phase 2 pilot measures this before the full matrix is built; rescope rather than run |
| Subspecies genome download fails silently (GTDB has no subspecies node) | `taxid_ncbi` mandatory in the watchlist; Phase 5 check 2 inspects FASTA contents, not just file existence |
| Download success miscounted as failure (`preparation_tab.py:1805`) | Predicted in advance; Phase 5 check 4 confirms |
| `nanometa-prepare` path still fetches by graft id | Phase 5 check 5 |
| Species and subspecies entries merge on shared NCBI taxid 263 | Phase 4 includes the species node deliberately; depends on the uncommitted `_identity_key()` fix being committed in Phase 0 |
| badread too slow for the target depth | Phase 2 measures throughput and sets the depth budget |
| Error-free reads inflate discrimination | badread rather than the builtin backend; note that even badread understates real error rates for a degraded flowcell |
| Disk exhaustion (19 GB free) | Phase 0 reclaims ~6 GB; the dataset itself is under 2 GB |
| Kraken2 database on exFAT | Use the existing local APFS copy |

## Deliverables

1. `ground_truth.json` and the simulated dataset (about 2 GB, keep on local disk).
2. `subspecies_francisella.yaml` - a subspecies watchlist worth shipping as an
   example if the exercise succeeds.
3. An evaluation script comparing Kraken2 output against ground truth,
   reusable for other databases.
4. `docs/audit/subspecies-2026-08-XX.md` with measured results and defects.
5. Regression tests for any defect confirmed in Phase 5.
