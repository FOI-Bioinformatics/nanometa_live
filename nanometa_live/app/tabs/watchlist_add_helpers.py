"""Input checks for the Watchlist tab's Add Custom Species form.

Pure: no manager access, so the callback passes the current entries in.
The form accepted a taxid of -5 and an alert threshold of 0, and reported
"Added" for a species already on the list (live test 2026-11-24).
"""

from typing import Any, Mapping, Optional


def _positive_int(value) -> Optional[int]:
    """The value as a positive integer, or None when it is not one."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != int(number) or number < 1:
        return None
    return int(number)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def custom_species_problem(
    name: str,
    taxid: Any,
    db_taxid: Any,
    threshold: Any,
    entries: Mapping[Any, Any],
) -> Optional[str]:
    """What is wrong with a custom-species submission, or None.

    Taxids and the threshold are optional, but a value given must be a
    positive integer. A duplicate is an entry with the same (NCBI taxid,
    database taxid) pair -- the watchlist's identity key, under which
    *E. coli* and *E. coli_F* are distinct -- or, without a taxid, the same
    name.
    """
    if not _blank(taxid) and _positive_int(taxid) is None:
        return "Taxonomy ID must be a positive whole number."
    if not _blank(db_taxid) and _positive_int(db_taxid) is None:
        return "Database taxid must be a positive whole number."
    if not _blank(threshold) and _positive_int(threshold) is None:
        return "Alert threshold must be a whole number of reads, 1 or more."

    ncbi = None if _blank(taxid) else _positive_int(taxid)
    dbt = None if _blank(db_taxid) else _positive_int(db_taxid)
    wanted = (name or "").strip().lower()
    for entry in entries.values():
        same_pair = ncbi is not None and entry.taxid == ncbi and (entry.db_taxid or None) == dbt
        same_name = ncbi is None and (entry.name or "").strip().lower() == wanted
        if same_pair or same_name:
            return f"{entry.name} is already on the watchlist."
    return None
