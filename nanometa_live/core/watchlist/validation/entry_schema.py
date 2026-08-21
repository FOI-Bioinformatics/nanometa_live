"""Per-entry schema validation for watchlist YAML files.

Extracted from ``WatchlistLoader`` (which delegates here) so the loader
stays within the file-size gate; the checks themselves are pure functions
over one parsed entry dict.
"""

from typing import List


def validate_pathogen_entry(i: int, p: object) -> List[str]:
    """Schema and type errors for one pathogen entry (1-based index i+1).

    The type checks are finding W3 (2026-08-17 audit): without them the
    errors were "defused" later by from_dict's try/excepts, which
    silently changed the entry's behaviour -- a non-numeric taxid became
    a pseudo-taxid entry that can never match a report, and a
    non-numeric alert_threshold fell back to the default.
    """
    errors: List[str] = []
    if not isinstance(p, dict):
        return [f"Pathogen {i+1}: must be a dictionary"]

    if "name" not in p:
        errors.append(f"Pathogen {i+1}: missing 'name' field")

    if "threat_level" in p:
        valid_levels = ["critical", "high", "moderate", "low"]
        if p["threat_level"] not in valid_levels:
            errors.append(
                f"Pathogen {i+1}: invalid threat_level "
                f"'{p['threat_level']}'"
            )

    if "bsl_level" in p:
        if not isinstance(p["bsl_level"], int) or p["bsl_level"] not in [1, 2, 3, 4]:
            errors.append(f"Pathogen {i+1}: bsl_level must be 1, 2, 3, or 4")

    for taxid_key in ("taxid_ncbi", "db_taxid"):
        value = p.get(taxid_key)
        if value is None:
            continue
        try:
            if int(value) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                f"Pathogen {i+1}: {taxid_key} must be a "
                f"positive integer, got '{value}'"
            )

    if "alert_threshold" in p:
        try:
            if int(p["alert_threshold"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                f"Pathogen {i+1}: alert_threshold must be a "
                f"positive integer, got '{p['alert_threshold']}'"
            )

    if "names_alt" in p:
        names_alt = p["names_alt"]
        if not isinstance(names_alt, list) or not all(
            isinstance(n, str) for n in names_alt
        ):
            errors.append(
                f"Pathogen {i+1}: names_alt must be a list of names"
            )
    return errors


def entries_without_taxid(data: object) -> List[str]:
    """Names of pathogen entries in parsed watchlist data with no taxonomy ID.

    Such an entry is loaded, displayed and counted like any other, but it
    can never match a Kraken2 report (matching keys on ``taxid_ncbi`` /
    ``db_taxid``), so it is a permanently silent watch item -- worth
    telling the operator about at upload time.
    """
    if not isinstance(data, dict):
        return []

    missing = []
    for i, p in enumerate(data.get("pathogens") or []):
        if not isinstance(p, dict):
            continue
        if p.get("taxid_ncbi") is None and p.get("db_taxid") is None:
            missing.append(str(p.get("name") or f"entry {i + 1}"))
    return missing
