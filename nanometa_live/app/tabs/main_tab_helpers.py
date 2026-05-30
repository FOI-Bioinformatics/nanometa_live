"""
Pure helpers for the Main (Organisms) results tab.

Extracted from main_tab.py so the registration function there stays focused on
Dash callback declarations. These functions hold the watchlist/detection logic
that takes plain data (a kraken DataFrame, a watchlist list) and returns plain
data -- no Dash ``app`` capture -- so they are unit-testable in isolation.

main_tab.py re-exports these names for backward compatibility.
"""

import pandas as pd
from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager


def species_in_watchlist(taxid: int, watchlist: list) -> bool:
    """Check if a species is in the watchlist by taxid."""
    if not watchlist:
        return False
    return any(s.get("taxid") == taxid for s in watchlist)


def add_species_to_watchlist(species: dict, watchlist: list) -> list:
    """Add a species to the watchlist."""
    if not watchlist:
        watchlist = []
    # Avoid duplicates by taxid
    if species.get("taxid") and species_in_watchlist(species["taxid"], watchlist):
        return watchlist
    return watchlist + [species]


def remove_species_from_watchlist(taxid: int, watchlist: list) -> list:
    """Remove a species from the watchlist by taxid."""
    if not watchlist:
        return []
    return [s for s in watchlist if s.get("taxid") != taxid]


def filter_detected_species(kraken_df, watchlist: list) -> list:
    """
    Filter detected species from kraken data that are in the watchlist.

    Uses proper taxid mapping to handle GTDB and custom Kraken2 databases
    where taxids differ from NCBI taxids.

    Returns only SPECIES-level entries that are DETECTED (have reads > 0).
    Filters out higher taxonomic ranks (class, order, family, etc.) to avoid
    false positives from parent taxa.
    """
    if kraken_df is None or kraken_df.empty or not watchlist:
        return []

    # Get WatchlistManager and active entries
    manager = get_watchlist_manager()
    active_entries = manager.get_active_entries()

    # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mapping_collection = get_mapping_collection()

    # Build reverse mapping: Kraken2 db_taxid -> NCBI taxid
    # This is critical for GTDB databases where taxids are different
    db_to_ncbi = {}
    if mapping_collection:
        for ncbi_taxid, mapping in mapping_collection.mappings.items():
            if mapping.db_taxid:
                db_to_ncbi[mapping.db_taxid] = ncbi_taxid

    # Collect NCBI taxids from active watchlist entries
    ncbi_taxids = {e.taxid for e in active_entries.values() if e.taxid}
    active_names = {e.name.lower().strip() for e in active_entries.values()}

    # Also include legacy watchlist taxids/names
    legacy_taxids = {s.get("taxid") for s in watchlist if s.get("taxid")}
    legacy_names = {s.get("name", "").lower().strip() for s in watchlist if s.get("name")}

    all_ncbi_taxids = ncbi_taxids | legacy_taxids
    all_names = active_names | legacy_names

    # Prepare kraken data for matching
    kraken_df = kraken_df.copy()
    kraken_df['taxid_int'] = kraken_df['taxid'].fillna(0).astype(int)
    kraken_df['name_lower'] = kraken_df['name'].fillna('').str.lower().str.strip()
    kraken_df['rank_clean'] = kraken_df['rank'].fillna('').str.strip()

    # Filter to species-level only (S = species, S1/S2 = subspecies)
    # Exclude higher ranks like C (class), O (order), F (family), G (genus)
    species_ranks = {'S', 'S1', 'S2'}
    species_mask = kraken_df['rank_clean'].isin(species_ranks)
    species_df = kraken_df[species_mask]

    if species_df.empty:
        return []

    # Map Kraken2 taxids to NCBI taxids for comparison
    # This handles GTDB databases where db_taxid != ncbi_taxid
    species_df = species_df.copy()
    species_df['mapped_ncbi_taxid'] = species_df['taxid_int'].map(
        lambda x: db_to_ncbi.get(x, x)  # Use mapped taxid if available, else original
    )

    # Match by:
    # 1. Mapped NCBI taxid (handles GTDB -> NCBI mapping)
    # 2. Direct Kraken2 taxid (for NCBI databases where taxid matches)
    # 3. Name matching (fallback, less reliable)
    mask = (
        species_df['mapped_ncbi_taxid'].isin(all_ncbi_taxids) |
        species_df['taxid_int'].isin(all_ncbi_taxids) |
        species_df['name_lower'].isin(all_names)
    )
    matched_df = species_df[mask]

    # Detection means "actually saw reads classify here". Use cumul_reads
    # so the badge count survives the F1-audit degenerate case (every
    # read parked at root rank collapses the per-rank ``reads`` column
    # to zero). Filter out zero-read placeholder rows so the badge
    # number agrees with the cards' Detected/Not-Detected split.
    cumul_col = 'cumul_reads' if 'cumul_reads' in matched_df.columns else 'reads'
    matched_df = matched_df[matched_df[cumul_col].fillna(0).astype(int) > 0]

    if matched_df.empty:
        return []

    # Convert to list of dicts, preserving the original Kraken2 taxid
    result_df = pd.DataFrame({
        'taxid': matched_df['taxid_int'],  # Original Kraken2 taxid for display
        'ncbi_taxid': matched_df['mapped_ncbi_taxid'],  # Mapped NCBI taxid
        'name': matched_df['name'].fillna('Unknown'),
        'reads': matched_df[cumul_col].fillna(0).astype(int),
        'abundance': matched_df['%'].fillna(0.0).astype(float),
        'rank': matched_df['rank_clean']
    })
    return result_df.to_dict('records')


def get_all_watchlist_with_detection(kraken_df, watchlist: list) -> list:
    """
    Get ALL watchlist entries with their detection status from Kraken2 data.

    Unlike filter_detected_species, this returns ALL watchlist entries
    regardless of detection status. Undetected entries have reads=0.

    This provides complete visibility into what's being monitored.
    """
    # Get WatchlistManager and active entries
    manager = get_watchlist_manager()
    active_entries = manager.get_active_entries()

    if not active_entries and not watchlist:
        return []

    # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mapping_collection = get_mapping_collection()

    # Build mapping: NCBI taxid -> Kraken2 db_taxid
    ncbi_to_db = {}
    if mapping_collection:
        for ncbi_taxid, mapping in mapping_collection.mappings.items():
            if mapping.db_taxid:
                ncbi_to_db[ncbi_taxid] = mapping.db_taxid

    # Also build reverse mapping for lookups
    db_to_ncbi = {v: k for k, v in ncbi_to_db.items()}

    # Prepare kraken data for matching (if available)
    # Two lookups: taxid-keyed and name-keyed. The name-keyed path
    # exists so a watchlist entry that does not match by taxid (because
    # the kraken DB renamed / reclassified the species) can still be
    # found via species name -- matching the matching strategy used by
    # filter_detected_species. Without this the badge count and the
    # Detected/Not-Detected card split disagree, and "5 detected"
    # entries silently collapse into the Not Detected section.
    kraken_lookup = {}
    name_lookup = {}
    if kraken_df is not None and not kraken_df.empty:
        kraken_df = kraken_df.copy()
        kraken_df['taxid_int'] = kraken_df['taxid'].fillna(0).astype(int)
        # cumul_reads is the F1-audit canonical "actually detected"
        # signal; ``reads`` collapses to zero when every read is parked
        # at root rank (the degenerate single-batch case caught by the
        # 2026-05-09 F1 fix). Use cumul_reads so the count survives.
        cumul_col = 'cumul_reads' if 'cumul_reads' in kraken_df.columns else 'reads'

        # Build lookup vectorized (avoid iterrows for performance with large dataframes)
        valid_mask = kraken_df['taxid_int'] > 0
        for taxid, reads, abundance, name in zip(
            kraken_df.loc[valid_mask, 'taxid_int'],
            kraken_df.loc[valid_mask, cumul_col].fillna(0).astype(int),
            kraken_df.loc[valid_mask, '%'].fillna(0.0).astype(float),
            kraken_df.loc[valid_mask, 'name'].fillna(''),
        ):
            entry = {'reads': int(reads), 'abundance': float(abundance), 'name': name}
            kraken_lookup[int(taxid)] = entry
            # Also store by mapped NCBI taxid if different
            ncbi_taxid = db_to_ncbi.get(int(taxid), int(taxid))
            if ncbi_taxid != int(taxid):
                kraken_lookup[ncbi_taxid] = entry
            # Index by species name too. Lowercase + strip mirrors the
            # case-insensitive comparison filter_detected_species does.
            name_key = str(name).strip().lower()
            if name_key:
                name_lookup[name_key] = entry

    # Build result list from ALL active watchlist entries
    result = []
    seen_taxids = set()

    for entry_id, entry in active_entries.items():
        if entry.taxid in seen_taxids:
            continue
        seen_taxids.add(entry.taxid)

        # Try to find detection in Kraken2 data
        # 1. Check by NCBI taxid directly
        # 2. Check by mapped Kraken2 db_taxid
        # 3. Check by species name (fallback; matches the matching
        #    strategy used by filter_detected_species so the badge
        #    count and the cards-render path agree).
        detection = None
        db_taxid = ncbi_to_db.get(entry.taxid, entry.taxid)

        if entry.taxid in kraken_lookup:
            detection = kraken_lookup[entry.taxid]
        elif db_taxid in kraken_lookup:
            detection = kraken_lookup[db_taxid]
        else:
            name_key = (entry.name or '').strip().lower()
            if name_key and name_key in name_lookup:
                detection = name_lookup[name_key]

        result.append({
            'taxid': db_taxid,  # Use Kraken2 db_taxid for display
            'ncbi_taxid': entry.taxid,
            'name': entry.name,
            'reads': detection['reads'] if detection else 0,
            'abundance': detection['abundance'] if detection else 0.0,
            'detected': detection is not None and detection['reads'] > 0,
            'category': entry.category,
            'threat_level': entry.threat_level.value if entry.threat_level else 'unknown'
        })

    # Also include legacy watchlist entries not in WatchlistManager.
    # When the GUI runs update_main_results in the background-callback
    # worker process (audit item #3), the WatchlistManager singleton is
    # empty and this loop is the ONLY path that hydrates entries from
    # the dcc.Store-passed watchlist arg. The name fallback below
    # mirrors filter_detected_species so badge and cards agree.
    for s in watchlist:
        taxid = s.get("taxid")
        if taxid and taxid not in seen_taxids:
            seen_taxids.add(taxid)
            db_taxid = ncbi_to_db.get(taxid, taxid)
            detection = (
                kraken_lookup.get(taxid)
                or kraken_lookup.get(db_taxid)
                or name_lookup.get((s.get("name") or '').strip().lower())
            )

            result.append({
                'taxid': db_taxid,
                'ncbi_taxid': taxid,
                'name': s.get("name", "Unknown"),
                'reads': detection['reads'] if detection else 0,
                'abundance': detection['abundance'] if detection else 0.0,
                'detected': detection is not None and detection['reads'] > 0,
                'category': 'custom',
                'threat_level': 'unknown'
            })

    # Sort by: detected first (desc), then by reads (desc), then by name
    result.sort(key=lambda x: (-int(x['detected']), -x['reads'], x['name'].lower()))

    return result


def create_species_alert_banner(detected_species: list) -> html.Div:
    """Create an alert banner for detected watched species."""
    if not detected_species:
        return None

    species_names = [s["name"] for s in detected_species[:5]]
    count = len(detected_species)

    # "Detected" here means any reads on a watchlist species at species
    # rank, regardless of per-pathogen alert_threshold. The Dashboard
    # verdict banner counts only entries above threshold, so the two
    # numbers can legitimately differ -- the footnote spells that out.
    head = (
        f"{count} watched species with reads"
        if count != 1
        else "1 watched species with reads"
    )
    if count <= 5:
        body = ", ".join(species_names)
    else:
        body = f"{', '.join(species_names)} (+{count - 5} more)"

    return dbc.Alert([
        html.I(className="bi bi-exclamation-triangle-fill me-2"),
        html.Strong(f"{head}: "),
        body,
        html.Br(),
        html.Small(
            "Lists every watchlist hit at species rank. The Dashboard "
            "banner counts only pathogens above their alert threshold.",
            className="text-muted",
        ),
    ], color="warning", className="mb-3")
