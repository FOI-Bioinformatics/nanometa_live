# 0003. One alert per watchlist entry, keyed by (NCBI taxid, db_taxid)

**Status:** accepted (2026-09-02)

## Context

The Bioshield list carries E. coli, E. coli_E and E. coli_F as three entries
with distinct database nodes and one NCBI taxid (562). Deduplicating alerts
on the NCBI taxid alone collapsed them: E. coli_F at 11 reads (threshold 10)
vanished behind E. coli at 22, and which variant survived flipped with the
frame's row order.

## Decision

`_dedupe_alerts_by_entry` keeps the dominant node per entry, keyed on the
same pair `_identity_key` stores entries under. Every alert carries
`db_taxid`. Where several watchlist keys resolve to one database node
(B. mallei within B. pseudomallei under GTDB), the first is the match and
the rest become `ambiguous_with`, rendered as "X or Y".

## Consequences

Matching is index-based (O(rows + entries)) and only alert-relevant tiers
are indexed. Entries without any taxid get a synthetic key in the reserved
pseudo-taxid band (`core/taxonomy/pseudo_taxid.py`) and can never match a
report; the upload path surfaces them.

## Evidence

`tests/test_taxid_coordination.py`,
`tests/test_watchlist_matching_equivalence.py`,
`tests/test_pathogen_check_memo.py`.
