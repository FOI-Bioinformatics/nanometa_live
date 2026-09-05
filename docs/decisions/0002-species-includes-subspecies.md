# 0002. Species includes subspecies

**Status:** accepted (2026-08-20)

## Context

Three rules disagreed on what "species" meant: `== "S"` in the verdict and
attribution paths, `{"S","S1","S2"}` in the Organisms tab, and a
`normalize_ranks` table that was never called. A subspecies watchlist entry
(F. tularensis holarctica, Type B, at rank S1) could be watched on the
Organisms tab and never reach the verdict banner. The distinction is
clinical: Type A tularensis is markedly more virulent than Type B.

## Decision

`core/taxonomy/ranks.py` owns `SPECIES_RANKS = {S, S1, S2, S3}` and is the
single definition. Per-taxon consumers treat each row as an independent
taxid. Rankings that list "most abundant" stay species-only, because a
species beside its own subspecies reads as double counting. On the pipeline
side, read extraction for validation selects the clade
(`KreportTree.cladeOf`), not the exact node.

## Consequences

Kraken2's `cumul_reads` already contains a node's descendants; never sum
across ranks. Subspecies get their own table in the report. The Taxonomy
tab offers S1 as a level, off by default, because adding it splits a
species' flow rather than adding to it.

## Evidence

`tests/test_taxid_coordination.py`, `tests/test_report_generator.py`,
`tests/test_sunburst_tax_levels.py`.
