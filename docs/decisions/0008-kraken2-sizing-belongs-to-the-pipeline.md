# 0008. Kraken2 sizing belongs to nanometanf, not the generated config

**Status:** accepted (2026-08-18)

## Context

The generated `-c` config outranks every pipeline config layer. A retired
`withName: 'KRAKEN2_KRAKEN2'` block pinned `cpus = 1` and `memory = 8.GB`,
so every GUI-launched classification ran single-threaded regardless of
nanometanf's own scaling.

## Decision

`create_nextflow_config` emits no Kraken2 process block. The GUI passes
`--kraken2_memory_gb` sized from the measured `hash.k2d` and
`kraken2_memory_mapping` resolved by an explicit-value-wins resolver. CPU
is `--max_cpus`; `pipeline_cores`, `validation_cores` and `blast_cores`
were removed because nothing read them or they pinned process names the
pipeline does not have.

## Consequences

`create_default_config` writes no default for a key whose resolver treats
"explicit value wins", or the resolver becomes dead code. The readiness
checklist warns when the database sits on a removable or network volume.

## Evidence

`tests/test_readiness_offline_checks.py`, `tests/test_deployment_gui_fixes.py`.
