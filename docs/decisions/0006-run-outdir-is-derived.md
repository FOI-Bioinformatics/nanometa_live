# 0006. The run output directory is derived, not configured

**Status:** accepted (2026-08-18)

## Context

A hand-written config that set only `results_output_directory` was
silently redirected to a derived folder, and the collision modal's
Continue and Archive buttons launched into a fresh hidden directory while
the modal promised the one it showed.

## Decision

`resolve_run_outdir` (`app/utils/outdir_resolution.py`) decides where a
run writes: a non-empty `results_dir_override` verbatim, otherwise
`<project>/results/<slug(analysis_name)>`. `results_output_directory` is
the computed value written back at Start so the viewer follows it. Every
launch path, including the collision handler, resolves through the same
function. A mid-run Apply pins both keys for the running run.

## Consequences

An explicit custom folder goes in `results_dir_override`. Every successful
start writes `.nanometa.run.json` with an input fingerprint, so pointing a
different input at a populated folder is detected next time.

## Evidence

`tests/test_outdir_resolution.py`, `tests/test_outdir_resolution_sweep.py`,
`tests/test_input_layout_mismatch.py`.
