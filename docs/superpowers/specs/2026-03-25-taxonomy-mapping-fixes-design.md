# Taxonomy Mapping Fixes - Design Spec

**Date:** 2026-03-25
**Status:** Approved
**Scope:** Fix 5 taxonomy-related issues identified by team audit

## Problem

The taxid mapping system has gaps that cause organisms to go undetected when watchlist entries use newer NCBI/ICTV taxonomy while the Kraken2 database uses older taxonomy. Additionally, strategy priority ordering causes genus-level matches to preempt correct species-level matches, and direct taxid matching on GTDB databases can produce false positives.

## Fixes

### Fix 1: Thread `names_alt` into taxid mapping

**Files:**
- `nanometa_live/core/watchlist/validation/match_strategies.py`
- `nanometa_live/core/taxonomy/taxid_mapping.py`
- `nanometa_live/app/tabs/preparation_tab.py`

**Change:**
1. Add `alt_names: Optional[List[str]] = None` parameter to `CompositeMatchStrategy.match()`
2. After all strategies fail with the primary name, iterate `alt_names` and retry `ExactNameStrategy` and `VariantMatchStrategy` for each
3. Add `MatchType.ALT_NAME` enum value (score ~0.9)
4. In `TaxidMapper.generate_mappings()` (line 828-847), read `entry.get("names_alt", [])` and pass to `match()`
5. In `preparation_tab.py` (line 722-724), include `"names_alt": e.get("names_alt", [])` in the entry dict

**Rationale:** The data is already available in `WatchlistEntry.names_alt`. It just needs to be threaded through the call chain. Retrying only ExactName and Variant (not Fuzzy/Parent) keeps the semantics clean: alt names are trusted synonyms, not guesses.

### Fix 2: Fix strategy priority ordering

**File:** `nanometa_live/core/watchlist/validation/match_strategies.py`

**Change:**
- `ParentTaxonStrategy.priority`: 5 → 50
- `SubstringMatchStrategy.priority`: 6 → 45
- Update module docstring (lines 8-14) to reflect actual order

**Resulting order:**
1. ExactTaxid (1)
2. ExactName (2)
3. Variant (3)
4. Reclassification (35)
5. Fuzzy (40)
6. Substring (45)
7. ParentTaxon (50)

**Rationale:** ParentTaxon returns genus-level matches (score 0.5) that preempt Reclassification (score 0.85+) and Fuzzy (score 0.85+). Species-level matches from these strategies are always preferable to genus-level fallbacks.

### Fix 3: Guard `check_organisms()` against DB type

**File:** `nanometa_live/core/watchlist/watchlist_manager.py`

**Change:** At line 723, before the direct taxid match:
```python
# Only try direct taxid match for NCBI databases
db_is_ncbi = True  # default assumption
try:
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mc = get_mapping_collection()
    if mc and mc.database_type:
        from nanometa_live.core.taxonomy.taxid_mapping import DatabaseTaxonomyType
        db_is_ncbi = mc.database_type == DatabaseTaxonomyType.NCBI
except Exception:
    pass

if db_is_ncbi and taxid and taxid in active_entries:
    entry = active_entries[taxid]
    best_score = 1.0
```

Apply the same guard to `check_organisms_with_mapping()` (line ~1478).

**Rationale:** On GTDB databases, Kraken2 report taxids are custom/arbitrary. Direct comparison against NCBI watchlist taxids produces false positives from random collisions.

### Fix 4: Fix `mobile_lab_preparer.py` AttributeError

**File:** `nanometa_live/core/workflow/mobile_lab_preparer.py`

**Change:** Replace line 346-348:
```python
# Old (broken):
return [
    {"taxid": e.taxid, "name": e.name, "kraken_taxid": e.kraken_taxid}
    for e in entries
]

# New:
from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
mc = get_mapping_collection()
result = []
for e in entries:
    kraken_taxid = None
    if mc and e.taxid:
        kraken_taxid = mc.get_db_taxid(e.taxid)
    result.append({
        "taxid": e.taxid,
        "name": e.name,
        "kraken_taxid": kraken_taxid or e.taxid,
        "names_alt": e.names_alt,
    })
return result
```

**Rationale:** `WatchlistEntry` has no `kraken_taxid` field. The mapping collection is the correct source for DB-specific taxids.

### Fix 5: Fix `names.dmp` path fallback

**File:** `nanometa_live/core/taxonomy/database_indexer.py`

**Change:** After line 96, add fallback check for root-level `names.dmp`:
```python
names_dmp = db_path / "taxonomy" / "names.dmp"
if not names_dmp.exists():
    names_dmp = db_path / "names.dmp"  # Some DBs have it at root

if names_dmp.exists():
    ...
```

Apply same pattern for `nodes.dmp`.

**Rationale:** Real PlusPFP databases have `names.dmp` at the database root, not in a `taxonomy/` subdirectory.

## Testing

- Verify existing tests still pass (`pytest tests/ -v`)
- Strategy priority fix can be verified by checking sorted order in `CompositeMatchStrategy.__init__`
- The `names_alt` threading can be tested by creating a mock DB index without "Orthoebolavirus zairense" but with "Zaire ebolavirus", and verifying the mapping succeeds via alt name

## Out of Scope

- Expanding `KNOWN_RECLASSIFICATIONS` dictionary (separate task)
- Unifying dual name normalizers (separate task)
- Adding test coverage for taxid mapping (separate task)
- Removing dead code in `data_utils.py` (separate task)
