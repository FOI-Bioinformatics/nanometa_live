#!/usr/bin/env python3
"""Reproduce Bug A: rescan returns "Not Found" for every watchlist entry.

This probe reaches directly into TaxidMapper.load_database()/generate_mappings()
without spinning up the Dash app, so it can be wired into both row 7 (wipe
~/.nanometa) and row 8 (corrupt cache JSON) of the eval test matrix.

Exit codes
----------
0  rescan produced at least one non-UNMAPPED status (PASS)
1  every status came back UNMAPPED, or the corrupt-cache shortcut survived
   the rebuild (FAIL -- this is the active Bug A signature)

Notes on the corrupt-index injection (--corrupt)
------------------------------------------------
We hand-craft an index JSON with `nodes=[]` at the cache path the loader
will look for (db-hash derived). The plan's hypothesis is that the
loader's `if not self._index` guard at taxid_mapping.py:814 does NOT catch
this case (the index object is truthy even when `by_taxid` is empty), so
every match strategy falls through to UNMAPPED with no warning. This
probe asserts the failure mode end-to-end.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    TaxidMapper,
    get_database_hash,
)

# A representative trio of taxa we expect any pluspfp Kraken2 DB to know about.
PROBE_ENTRIES = [
    {"name": "Escherichia coli", "taxid": 562},
    {"name": "Bacillus subtilis", "taxid": 1423},
    {"name": "Staphylococcus aureus", "taxid": 1280},
]


def cache_dir() -> Path:
    return Path.home() / ".nanometa" / "mappings"


def write_corrupt_index(db_path: str) -> Path:
    """Drop a JSON cache with nodes=[] at the path TaxidMapper looks for."""
    db_hash = get_database_hash(db_path)
    cache_dir().mkdir(parents=True, exist_ok=True)
    cache = cache_dir() / f"{db_hash}_index.json"
    payload = {
        "version": "1.0",
        "database_path": db_path,
        "database_type": "ncbi",
        "total_nodes": 0,
        "species_count": 0,
        "built_at": None,
        "inspect_file_path": None,
        "nodes": [],
    }
    cache.write_text(json.dumps(payload))
    return cache


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kraken-db", required=True, help="Path to Kraken2 DB directory")
    ap.add_argument(
        "--corrupt",
        action="store_true",
        help="Pre-write an empty cache JSON to simulate Bug A's corrupt-cache path",
    )
    args = ap.parse_args()

    db = args.kraken_db
    if not Path(db).is_dir():
        print(f"FAIL: kraken db not found at {db}", file=sys.stderr)
        return 1

    if args.corrupt:
        c = write_corrupt_index(db)
        print(f"[probe] wrote corrupt cache: {c}")

    mapper = TaxidMapper(cache_dir=str(cache_dir()))
    print(f"[probe] load_database({db})")
    if not mapper.load_database(db):
        print("FAIL: load_database returned False")
        return 1

    n_nodes = len(mapper._index.by_taxid) if mapper._index else 0
    print(f"[probe] index has {n_nodes} nodes after load")

    if n_nodes == 0:
        # Active Bug A: load succeeded but the index is empty.
        # The plan's expected fix forces a rebuild here -- we report this
        # as a fail so the runner script captures the regression.
        print("FAIL: index loaded with 0 nodes -- Bug A signature")
        return 1

    print(f"[probe] generate_mappings for {len(PROBE_ENTRIES)} probe entries")
    coll = mapper.generate_mappings(PROBE_ENTRIES, preserve_manual=False)

    coll.update_statistics()
    n_total = coll.total_entries
    n_unmapped = coll.unmapped
    n_mapped = n_total - n_unmapped
    print(f"[probe] mapped={n_mapped} unmapped={n_unmapped} total={n_total}")
    for m in coll.mappings.values():
        matched = m.db_taxid if m.db_taxid else "-"
        print(
            f"  ncbi={m.ncbi_taxid:<10d} confidence={m.confidence.value:<10s} matched={matched}"
        )

    if n_unmapped == n_total:
        print("FAIL: every probe entry came back UNMAPPED -- Bug A active")
        return 1

    print("PASS: at least one probe entry mapped successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
