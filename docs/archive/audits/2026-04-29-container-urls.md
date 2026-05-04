# Module Container URL Audit -- 2026-04-29

Inventory of every nanometanf module's tri-source artifact:
the bioconda spec from ``environment.yml``, the Singularity
URL from ``main.nf`` (depot.galaxyproject.org), and the
Docker reference. Each Singularity URL is HEAD-checked;
the conda version is cross-checked against the container tag.

Closes W6-A from
``docs/plan-2026-04-28-throughput-fixes.md``.

## Summary

- Total modules audited: **40**
- OK (conda + container in version sync): **25**
- Runtime-base container (intentional, not a mismatch): **15**
- Version mismatch (conda vs container): **0**
- Singularity URL unreachable: **0**
- No container directive: **0**

## Methodology

- ``container "${ ... }"`` ternary is parsed with a
  regex that picks the first depot.galaxyproject.org URL
  and the first biocontainers / quay.io / community.wave
  Docker reference encountered.
- ``environment.yml`` is parsed with PyYAML; the first
  ``bioconda::`` (or unprefixed) dependency wins.
- Singularity URLs are HEAD-checked with an 8 s timeout.
  HEAD checks performed at run time on the build machine.
- Version match compares the version segment before the
  ``--<hash>`` build suffix (e.g. ``0.12.0`` of
  ``chopper:0.12.0--hdcf5f25_0``) against the conda spec's
  trailing ``=<version>``.

## Results

| Module | Scope | Conda spec | Singularity tag | Sing reachable | Verdict |
|---|---|---|---|---|---|
| aggregate_validation_results | local | python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| blastn_validation | local | blast=2.16.0 | (none) | no (skipped) | **OK** |
| canonical_assembly_writer | local | conda-forge::python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| canonical_classification_writer | local | conda-forge::python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| canonical_qc_writer | local | conda-forge::python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| canonical_validation_writer | local | conda-forge::python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| extract_reads_by_taxid | local | seqtk=1.4 | 1.4 | yes (HTTP 200) | **OK** |
| fastp_streaming | local | fastp=1.0.1 | (none) | no (skipped) | **OK** |
| generate_realtime_report | local | conda-forge::python=3.11 | (none) | no (skipped) | **runtime-base** |
| generate_snapshot_stats | local | conda-forge::python=3.11 | (none) | no (skipped) | **runtime-base** |
| kraken2_db_preload | local | conda-forge::coreutils=9.5 | 22.04 | yes (HTTP 200) | **runtime-base** |
| kraken2_final_aggregator | local | python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| kraken2_incremental_classifier | local | kraken2=2.1.5 | (none) | no (skipped) | **OK** |
| kraken2_optimized | local | kraken2=2.1.5 | (none) | no (skipped) | **OK** |
| kraken2_output_merger | local | python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| kraken2_report_generator | local | krakentools=1.2 | 1.2 | yes (HTTP 200) | **OK** |
| manifest_writer | local | conda-forge::python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| minimap2_validation | local | minimap2=2.28 | 2.28 | yes (HTTP 200) | **OK** |
| multiqc_nanopore_stats | local | python=3.11 | 1.21 | yes (HTTP 200) | **runtime-base** |
| nanoplot_compare | local | nanoplot=1.46.1 | 1.46.1 | yes (HTTP 200) | **OK** |
| realtime_progress_tracker | local | python=3.11 | 3.11 | yes (HTTP 200) | **runtime-base** |
| seqkit_merge_stats | local | python>=3.9 | 3.12 | yes (HTTP 200) | **runtime-base** |
| update_cumulative_stats | local | conda-forge::python=3.11 | (none) | no (skipped) | **runtime-base** |
| blast/blastn | nf-core | blast=2.17.0 | (none) | no (skipped) | **OK** |
| blast/makeblastdb | nf-core | blast=2.17.0 | (none) | no (skipped) | **OK** |
| chopper | nf-core | chopper=0.12.0b | (none) | no (skipped) | **OK** |
| fastp | nf-core | fastp=1.1.0 | (none) | no (skipped) | **OK** |
| fastqc | nf-core | fastqc=0.12.1 | 0.12.1 | yes (HTTP 200) | **OK** |
| filtlong | nf-core | filtlong=0.2.1 | 0.2.1 | yes (HTTP 200) | **OK** |
| flye | nf-core | flye=2.9.5 | (none) | no (skipped) | **OK** |
| kraken2/kraken2 | nf-core | kraken2=2.1.6 | (none) | no (skipped) | **OK** |
| miniasm | nf-core | miniasm=0.3_r179 | 0.3_r179 | yes (HTTP 200) | **OK** |
| minimap2/align | nf-core | minimap2=2.29 | (none) | no (skipped) | **OK** |
| multiqc | nf-core | multiqc=1.34 | (none) | no (skipped) | **OK** |
| nanoplot | nf-core | nanoplot=1.46.1 | 1.46.1 | yes (HTTP 200) | **OK** |
| porechop/porechop | nf-core | porechop=0.2.4 | (none) | no (skipped) | **OK** |
| seqkit/stats | nf-core | seqkit=2.9.0 | 2.9.0 | yes (HTTP 200) | **OK** |
| taxpasta/merge | nf-core | taxpasta=0.7.0 | 0.7.0 | yes (HTTP 200) | **OK** |
| taxpasta/standardise | nf-core | taxpasta=0.7.0 | 0.7.0 | yes (HTTP 200) | **OK** |
| untar | nf-core | conda-forge::coreutils=9.5 | (none) | no (skipped) | **OK** |

## Notes for follow-on work

- Local modules without container directives are expected:
  they run plain shell or Python and pick up tools from
  the host or a parent process scope.
- Any ``mismatch`` rows mean the conda ``environment.yml``
  and the container tag drifted. Fix in-repo by re-pulling
  the module via ``nf-core modules update <name>``.
- Any ``unreachable`` rows mean the depot.galaxyproject.org
  URL no longer resolves. Either upstream rebuilt the image
  under a different tag, or the depot dropped the artifact;
  file an upstream nf-core/modules issue for those rows.
- This table is the input artifact for any future
  Apptainer pre-pull deployment path (Wave 7 candidate).
