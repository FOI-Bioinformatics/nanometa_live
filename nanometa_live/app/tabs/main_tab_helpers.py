"""
Pure helpers for the Main (Organisms) results tab.

Extracted from main_tab.py so the registration function there stays focused on
Dash callback declarations. These functions hold the watchlist/detection logic
that takes plain data (a kraken DataFrame, a watchlist list) and returns plain
data -- no Dash ``app`` capture -- so they are unit-testable in isolation.

main_tab.py re-exports these names for backward compatibility.
"""

import logging

import pandas as pd
from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.dashboard_helpers import DEFAULT_LOW_READ_FLOOR
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    get_watchlist_manager,
)


def render_validation_results_card(result):
    """Build the on-demand-validation results Card from a ValidationResult.

    Pure (no I/O) so the background validation callback can build its final
    display from data and this stays unit-testable. ``result`` is a
    ValidationResult (or any object exposing validation_rate, validated_reads,
    avg_identity, extracted_reads, total_classified_reads).
    """
    rate = result.validation_rate
    badge_label = (
        "BLAST Verified" if rate >= 80
        else "Partial Match" if rate >= 50
        else "Low Match"
    )
    badge_color = (
        "success" if rate >= 80
        else "warning" if rate >= 50
        else "danger"
    )
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-check-circle-fill text-success me-2"),
            html.Strong("Validation Results"),
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4(f"{rate:.1f}%", className="text-success mb-0"),
                    html.Small("Validation Rate", className="text-muted"),
                ], className="text-center"),
                dbc.Col([
                    html.H4(f"{result.validated_reads:,}", className="text-primary mb-0"),
                    html.Small("Validated Reads", className="text-muted"),
                ], className="text-center"),
                dbc.Col([
                    html.H4(f"{result.avg_identity:.1f}%", className="text-info mb-0"),
                    html.Small("Avg Identity", className="text-muted"),
                ], className="text-center"),
            ], className="mb-3"),
            html.Div([
                dbc.Badge(badge_label, color=badge_color, className="me-2"),
                html.Small(
                    f"{result.extracted_reads:,} reads extracted from "
                    f"{result.total_classified_reads:,} classified",
                    className="text-muted",
                ),
            ]),
        ]),
    ])


def validation_store_entry(result, taxid, name):
    """Plain-dict summary of a validation result for the results Store."""
    return {
        "taxid": taxid,
        "name": name,
        "validation_rate": result.validation_rate,
        "validated_reads": result.validated_reads,
        "extracted_reads": result.extracted_reads,
        "avg_identity": result.avg_identity,
        "success": True,
    }


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
    if kraken_df is None or kraken_df.empty:
        return []

    # Get WatchlistManager and active entries
    manager = get_watchlist_manager()
    active_entries = manager.get_active_entries()

    # Guard on BOTH sources, matching get_all_watchlist_with_detection. The
    # two are required to agree -- this function drives the alert banner and
    # that one drives the cards -- and guarding on the legacy `watchlist`
    # argument alone made them disagree: with an empty store but a populated
    # manager, the cards showed detections while the banner stayed silent.
    if not active_entries and not watchlist:
        return []

    # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mapping_collection = get_mapping_collection()

    # Reverse mapping: Kraken2 db_taxid -> watchlist key. Critical for GTDB
    # and flextaxd databases, where the report's taxid is not the NCBI one.
    # Shared with the detection path so the two cannot drift; the helper
    # returns every entry that resolves to a node, of which this only needs
    # one -- membership in all_ncbi_taxids is what the mask tests.
    db_to_ncbi = {
        node: keys[0]
        for node, keys in WatchlistManager._build_db_taxid_index(
            active_entries, mapping_collection
        ).items()
    }

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

    # NCBI taxid -> Kraken2 db_taxid. Keyed by the watchlist entry, so
    # several entries sharing one database node each keep their own row --
    # that is why this direction is built rather than inverting the shared
    # index, which is many-to-one.
    ncbi_to_db = {}
    if mapping_collection:
        for ncbi_taxid, mapping in mapping_collection.mappings.items():
            if mapping.db_taxid:
                ncbi_to_db[ncbi_taxid] = mapping.db_taxid
    for key, entry in active_entries.items():
        db_taxid = getattr(entry, "db_taxid", None)
        if db_taxid:
            ncbi_to_db[key] = int(db_taxid)

    # And the reverse, for the kraken_lookup alias below. Many-to-one, so
    # the shared index supplies the primary claimant for each node.
    db_to_ncbi = {
        node: keys[0]
        for node, keys in WatchlistManager._build_db_taxid_index(
            active_entries, mapping_collection
        ).items()
    }

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
            'threat_level': entry.threat_level.value if entry.threat_level else 'unknown',
            'organism_type': entry.organism_type,
            'annotation': entry.annotation or ''
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
                'threat_level': 'unknown',
                'organism_type': s.get('organism_type'),
                'annotation': s.get('annotation', '')
            })

    # Sort by: detected first (desc), then by reads (desc), then by name
    result.sort(key=lambda x: (-int(x['detected']), -x['reads'], x['name'].lower()))

    return result


def build_organism_export(table_data: list, export_format: str, filename: str = "") -> dict:
    """Build the dcc.Download payload for an organism-table export.

    Pure given the table rows + format. Returns a dict with ``content`` /
    ``filename`` (+ ``type`` or ``base64``). ``xlsx`` falls back to CSV when
    openpyxl is unavailable; an unknown format also falls back to CSV.
    """
    if not filename:
        filename = "organism_results"

    df = pd.DataFrame(table_data)

    if export_format == "csv":
        return {
            "content": df.to_csv(index=False),
            "filename": f"{filename}.csv",
            "type": "text/csv",
        }
    elif export_format == "xlsx":
        # For Excel, try to use openpyxl, fall back to CSV if not available
        try:
            import io
            import openpyxl  # noqa: F401  (availability check)
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            import base64
            return {
                "content": base64.b64encode(buffer.getvalue()).decode(),
                "filename": f"{filename}.xlsx",
                "base64": True,
            }
        except ImportError:
            logging.warning("openpyxl not installed, falling back to CSV export")
            return {
                "content": df.to_csv(index=False),
                "filename": f"{filename}.csv",
                "type": "text/csv",
            }
    elif export_format == "txt":
        # Generate a formatted text report
        from datetime import datetime

        report_lines = [
            "=" * 60,
            "           ORGANISM ANALYSIS REPORT",
            "=" * 60,
            "",
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Total Organisms: {len(df)}",
            f"  Total DNA Sequences: {df['reads'].sum():,}",
            "",
            "-" * 60,
            "  TOP ORGANISMS BY ABUNDANCE",
            "-" * 60,
            "",
        ]

        # Table header
        report_lines.append(f"  {'Rank':<6} {'Organism Name':<35} {'Reads':>10} {'%':>8}")
        report_lines.append("  " + "-" * 56)

        # Vectorized report line building
        rank_map = {'S': 'Sp.', 'G': 'Gen.', 'F': 'Fam.', 'O': 'Ord.', 'C': 'Cls.', 'P': 'Phy.', 'D': 'Dom.'}
        ranks = df['rank'].map(lambda r: rank_map.get(r, r)).tolist()
        names = df['name'].apply(lambda n: n[:33] + '..' if len(n) > 35 else n).tolist()
        reads_vals = df['reads'].tolist()
        abundances = df['abundance'].tolist()

        for rank_display, name, reads_val, abundance in zip(ranks, names, reads_vals, abundances):
            report_lines.append(
                f"  {rank_display:<6} {name:<35} {reads_val:>10,} {abundance:>7.1f}%"
            )

        report_lines.extend([
            "",
            "-" * 60,
            "",
            "  NOTES:",
            "  - Sp. = Species, Gen. = Genus, Fam. = Family",
            "  - Reads = Number of DNA sequences classified",
            "  - % = Percentage of total classified sequences",
            "",
            "=" * 60,
            "                    END OF REPORT",
            "=" * 60,
        ])

        report_content = "\n".join(report_lines)

        return {
            "content": report_content,
            "filename": f"{filename}_report.txt",
            "type": "text/plain",
        }
    else:
        # Fallback to CSV
        return {
            "content": df.to_csv(index=False),
            "filename": f"{filename}.csv",
            "type": "text/csv",
        }


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


def not_detected_caveat(
    total_reads,
    n_not_detected: int,
    low_read_floor: int = DEFAULT_LOW_READ_FLOOR,
):
    """Why this panel's "Not Detected" list is not yet a negative result.

    Returns the caveat text, or None when the negative has been earned.

    The Dashboard banner already gates on depth (select_verdict ->
    INSUFFICIENT_READS): below the floor, an absence measured over almost no
    reads is not evidence of absence. The Organisms panel split purely on
    ``detected`` and inherited none of that, so a one-read run rendered
    "Not Detected (35)" identically to a properly-powered negative -- and this
    panel is read, screenshotted and exported on its own, without the banner.

    ``total_reads=None`` means the depth could not be determined and is
    deliberately not treated as zero; that would put a false shallow-depth
    warning on every caller that cannot compute a total.
    """
    if not n_not_detected:
        return None
    if total_reads is None or total_reads >= low_read_floor:
        return None
    return (
        f"Only {total_reads:,} read{'s' if total_reads != 1 else ''} analysed "
        f"- too few to rule these organisms out. Screening is inconclusive "
        f"at this depth, not negative."
    )
