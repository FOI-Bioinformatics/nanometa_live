"""Resolving a watchlist entry to the report rows it owns.

The exported report screens the watchlist itself (``ReportGenerator.
_screen_watchlist``) rather than reusing the dashboard's alert list, because
it runs over frames the dashboard never loaded (one per sample) and in a
background worker whose singletons start empty. What it must NOT do is screen
by a different rule than the dashboard: a report that disagrees with the
screen the operator watched is worse than no report.

It did. ``_match_entry_rows`` compared ``db_taxid or taxid`` against the
frame's taxid column and fell back to an exact lowercase name compare -- no
taxid mapping, no name normalisation. On a GTDB or flextaxd database that
resolves nothing: *Bacillus anthracis* (NCBI 1392) against the row
``Bacillus_A anthracis`` (4005020) matched zero rows, every entry read
``detected=False``, and ``report.html`` rendered the green "NO WATCHED
ORGANISMS DETECTED" over a run the dashboard alarmed on (audit 2026-11-06,
finding 2). The docstring claimed "the same precedence the dashboard uses",
which it was not.

Both halves are repaired here, with the dashboard's own machinery:

- the taxid half consults the mapping collection, which is what turns NCBI
  1392 into database node 4005020;
- the name half goes through ``TaxonomyMatcher``, the same index-based
  matcher ``check_organisms_with_mapping_split`` uses, at the same 0.7 floor.

The mapping collection is resolved singleton-first and then from the
``{db_hash}_mappings.json`` file, because a DiskcacheManager worker holds no
singleton -- the same reason ``_screen_watchlist`` hydrates its own
``WatchlistManager``. That file is kept rather than rebuilt precisely so a
standalone load works (see "One database profile, two axes" in CLAUDE.md).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)

#: Name-match floor, identical to the alert floor in
#: ``WatchlistManager.check_organisms_with_mapping_split``. Below it a match is
#: not alert-relevant, so it must not put reads on a report row either.
NAME_MATCH_FLOOR = 0.7


def resolve_mapping_collection(config: Optional[Dict[str, Any]]) -> Optional[Any]:
    """The live taxid mapping collection, or the one cached for this database.

    Returns None when neither exists, in which case screening falls back to
    the raw taxid plus normalised names -- still better than the exact-string
    compare it replaces, and the honest answer for a database nobody has
    scanned.
    """
    try:
        from nanometa_live.core.taxonomy.taxid_mapping import (
            get_mapping_cache_path,
            get_mapping_collection,
            TaxidMappingCollection,
        )
    except ImportError:  # pragma: no cover - import guard
        return None

    collection = get_mapping_collection()
    if collection is not None and collection.mappings:
        return collection

    kraken_db = (config or {}).get("kraken_db") or ""
    if not kraken_db:
        return None
    try:
        path = get_mapping_cache_path(kraken_db)
        if not path.exists():
            return None
        loaded = TaxidMappingCollection.load(str(path))
    except (OSError, ValueError) as exc:
        logger.warning("Could not load taxid mappings for the report: %s", exc)
        return None
    if loaded is not None and loaded.mappings:
        logger.info(
            "Report screen loaded %d taxid mappings from %s",
            len(loaded.mappings), path,
        )
        return loaded
    return None


class EntryRowResolver:
    """Which rows of a Kraken2 frame belong to each watchlist entry.

    Built once per screen: the name index is O(entries) to build and each
    distinct report name is resolved once, so a 129-entry watchlist over a
    3000-row frame costs O(rows + entries) rather than the product.
    """

    def __init__(
        self,
        entries: Iterable[Any],
        frames: Iterable[pd.DataFrame],
        mapping_collection: Optional[Any] = None,
    ) -> None:
        self._entries: List[Any] = [e for e in entries if e is not None]
        self._ids: Dict[int, Set[int]] = {}
        self._names: Dict[int, Set[str]] = {}
        # Generate the entries' speculative GTDB genus-suffix forms for name
        # matching when the loaded database is GTDB or undetectable, so an
        # NCBI watchlist name reaches a grafted GTDB report name
        # (``Bacillus anthracis`` -> ``Bacillus_A anthracis``) with no taxid
        # mapping, exactly as the live dashboard pass does. No profile (no
        # mapping collection): generate, matching the unknown-nomenclature
        # default rather than silently missing a GTDB report.
        profile = getattr(mapping_collection, "profile", None)
        self._gtdb = bool(
            getattr(profile, "generates_gtdb_variants", True)
            if profile is not None else True
        )
        self._build_ids(mapping_collection)
        self._build_names(frames)

    # -- taxid side ------------------------------------------------------
    def _build_ids(self, mapping_collection: Optional[Any]) -> None:
        by_key: Dict[int, int] = {}
        if mapping_collection is not None:
            for key, mapping in getattr(
                mapping_collection, "mappings", {}
            ).items():
                db_taxid = getattr(mapping, "db_taxid", None)
                if db_taxid:
                    by_key[int(key)] = int(db_taxid)

        for entry in self._entries:
            ids: Set[int] = set()
            declared = getattr(entry, "db_taxid", None)
            entry_taxid = getattr(entry, "taxid", None)
            for value in (declared, entry_taxid):
                if value:
                    ids.add(int(value))
            # The mapping for this entry's own key: a fork entry is keyed by
            # its db_taxid in the collection, the primary entry by its NCBI
            # taxid (TaxidMapping.entry_key).
            for key in (declared, entry_taxid):
                if key and int(key) in by_key:
                    ids.add(by_key[int(key)])
                    break
            self._ids[id(entry)] = ids

    # -- name side -------------------------------------------------------
    def _build_names(self, frames: Iterable[pd.DataFrame]) -> None:
        names: Set[str] = set()
        for df in frames:
            if df is None or getattr(df, "empty", True):
                continue
            if "name" not in df.columns:
                continue
            for raw in df["name"].astype(str).tolist():
                stripped = raw.strip()
                if stripped:
                    names.add(stripped)
        if not names or not self._entries:
            return

        from nanometa_live.core.watchlist.taxonomy_matcher import (
            get_taxonomy_matcher,
        )
        matcher = get_taxonomy_matcher()
        index = matcher.build_entry_index(
            self._entries, generates_gtdb_variants=self._gtdb)
        for name in names:
            entry, score = matcher.match_row_indexed(name, index)
            if entry is not None and score >= NAME_MATCH_FLOOR:
                self._names.setdefault(id(entry), set()).add(name.lower())

    # -- queries ---------------------------------------------------------
    def ids_for(self, entry: Any) -> Set[int]:
        return self._ids.get(id(entry), set())

    def names_for(self, entry: Any) -> Set[str]:
        return self._names.get(id(entry), set())

    def rows_for(self, df: pd.DataFrame, entry: Any) -> pd.DataFrame:
        """The rows of *df* this entry owns, taxid match first.

        Taxid before name, as both dashboard match paths do: an id hit is a
        statement about a database node, a name hit is an inference about a
        string. When only names match and several rows answer, the row with
        the largest clade count is kept rather than the sum -- a species row
        and its subspecies rows can both carry the entry's name, and the
        species row's cumulative count already CONTAINS the others, so
        summing them would double count (the rule
        ``_dedupe_alerts_by_entry`` applies to alerts).
        """
        if df is None or df.empty:
            return df

        ids = self.ids_for(entry)
        if ids:
            matched = df[df["taxid"].isin(ids)]
            if not matched.empty:
                return matched

        names = self.names_for(entry)
        if not names or "name" not in df.columns:
            return df.iloc[0:0]
        lowered = df["name"].astype(str).str.strip().str.lower()
        matched = df[lowered.isin(names)]
        if len(matched) > 1:
            read_col = (
                "cumul_reads" if "cumul_reads" in matched.columns else "reads"
            )
            dominant = matched[read_col].astype(float).idxmax()
            matched = matched.loc[[dominant]]
        return matched


def split_negative_controls(
    per_sample: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Partition one entry's per-sample rows around its negative controls.

    A control that carries a detection is reported, never acted on: it is
    kept out of the triggering-sample list but a control-only hit still
    reads as detected, so a contaminated control can never make a real
    aggregate positive disappear. Mirrors the dashboard's
    ``build_pathogen_attribution`` (CLAUDE.md, "Negative controls").
    """
    triggering = [s for s in per_sample if not s.get("is_negative_control")]
    controls = [s for s in per_sample if s.get("is_negative_control")]
    control_reads = sum(s["reads"] for s in controls)
    positive_reads = sum(s["reads"] for s in triggering)
    return {
        "triggering_samples": triggering,
        "negative_control_rows": controls,
        "negative_control_fraction": (
            (control_reads / positive_reads * 100)
            if (controls and positive_reads) else None
        ),
        "control_only": bool(controls and not triggering),
    }
