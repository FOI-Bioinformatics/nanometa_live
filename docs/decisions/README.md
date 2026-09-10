# Decision records

Each record states one decision the code depends on, why it was taken, what
it costs, and the test that pins it. They are distilled from `CLAUDE.md`
and the audit reports under `docs/audit/`; where the two disagree, the
record is wrong and should be corrected from the code.

Format: `NNNN-short-title.md`, starting with `# NNNN. Title`, a
`**Status:**` line (accepted, superseded by NNNN), then `## Context`,
`## Decision`, `## Consequences`, `## Evidence`. Evidence names at least one
file under `tests/`. `tests/test_decision_records.py` enforces the format.

| Record | Decision |
|--------|----------|
| [0001](0001-verdict-earns-its-result.md) | A verdict never claims a result it did not earn |
| [0002](0002-species-includes-subspecies.md) | Species includes subspecies |
| [0003](0003-one-alert-per-watchlist-entry.md) | One alert per watchlist entry, keyed by (NCBI taxid, db_taxid) |
| [0004](0004-background-callbacks-share-state-via-stores.md) | Background callbacks share state through Stores and take no per-tick Input |
| [0005](0005-per-sample-cache-scope.md) | A per-sample cache entry is fingerprinted against that sample's own files |
| [0006](0006-run-outdir-is-derived.md) | The run output directory is derived, not configured |
| [0007](0007-one-database-profile-two-axes.md) | One database profile with two independent axes |
| [0008](0008-kraken2-sizing-belongs-to-the-pipeline.md) | Kraken2 sizing belongs to nanometanf, not the generated config |
| [0009](0009-import-never-reports-success-over-a-problem.md) | A bundle import never reports success over a problem it found |
| [0010](0010-a-control-must-do-something.md) | A control must do something |
