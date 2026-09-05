# 0007. One database profile with two independent axes

**Status:** accepted (2026-07)

## Context

Four disagreeing axes (`kraken_taxonomy`, `DatabaseTaxonomyType`,
`TaxonomyType`, the watchlist's `taxonomy_mode`) tried to answer two
different questions with one value, and a MIXED value was never read.
Field databases are flextaxd hybrids: an NCBI backbone with GTDB-named
clades grafted in at high taxids.

## Decision

`core/taxonomy/database_profile.py` carries `taxids_are_ncbi` (may a raw
taxid comparison be trusted; defaults to False because a wrong trust names
the wrong organism) and `nomenclature` (ncbi, gtdb or unknown; unknown
narrows nothing). Both are detected from the database itself, never from
its directory name. `ExactTaxidStrategy` carries no name verification,
because renamed taxa (SARS-CoV-2, Candida auris) are matched only by taxid.
GTDB genus-suffix variants are generated lazily and gated on the profile.

## Consequences

The profile rides the index file (cache version 2.0) and is copied onto the
mappings file, because workers load the mappings standalone. Coverage
analysis (`core/taxonomy/coverage.py`) reports which watchlist entries a
minimized database can see at all; an ALL CLEAR for an absent entry is no
result.

## Evidence

`tests/test_database_profile.py`.
