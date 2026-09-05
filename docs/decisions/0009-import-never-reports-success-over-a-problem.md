# 0009. A bundle import never reports success over a problem it found

**Status:** accepted (2026-08-14, extended 2026-08-27)

## Context

On an air-gapped rig a wrong `--db` path imported in silence, a failure
writing the rebased config left `success` True with `${KRAKEN_DB}` still in
it, and blocker messages opened with "Import aborted" during a dry run
that aborted nothing.

## Decision

`_verify_extracted_bundle` holds every pre-copy check and is shared by
`import_bundle` and the non-mutating `verify_bundle`, so the dry run
matches the import. A supplied database that is not usable sets
`kraken_db_invalid`; a config write failure sets `success = False`.
Messages state the condition, not the consequence. Singularity images are
named by Nextflow's own cache convention (`_singularity_cache_name`) and
`NXF_SINGULARITY_CACHEDIR` is injected at launch; conda caches are
relocated by rewriting the recorded build prefix and re-signing patched
Mach-O binaries.

## Consequences

Add a new check to `_verify_extracted_bundle`, never to the import path
alone. Build and field machine must share OS and CPU architecture for
conda mode; cross-platform means docker or singularity.

## Evidence

`tests/test_bundle_manager.py`, `tests/test_conda_cache_relocation.py`,
`tests/test_nextflow_manager.py`.
