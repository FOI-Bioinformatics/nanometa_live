"""What kind of taxonomy a loaded Kraken2 database uses.

Two independent questions were previously conflated across four separate
enums and one config key:

**Q1 -- are this database's taxids NCBI-compatible?** Governs matching: whether
an exact taxid comparison between a watchlist entry and a Kraken2 report row
means anything. A GTDB or in-house database assigns its own integers, so taxid
562 in the report is not necessarily *Escherichia coli*.

**Q2 -- what nomenclature do its names use?** Governs which external service can
resolve a name, whether ``kingdom="Bacteria"`` may be assumed when fetching a
genome, and whether the GTDB polyphyly suffix variants (``Bacillus_A``) are
worth generating.

They are orthogonal. The old single ``DatabaseTaxonomyType`` had a ``MIXED``
member that was produced but never read anywhere -- unreadable precisely
because one axis was trying to answer both questions. ``taxids_are_ncbi=False``
with ``nomenclature=NCBI`` is "NCBI-style names, remapped taxids", which is
what most real mixed databases actually are, and the two-axis model can say it.

Both are properties of the database on disk, detected by inspecting it. Neither
is an operator opinion, so neither belongs in the application config. An
operator override exists for the case where detection is wrong, but it is
stored per database rather than globally -- see ``load_profile_for_db``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class Nomenclature(Enum):
    """The naming convention a database's taxon names follow."""

    NCBI = "ncbi"
    GTDB = "gtdb"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DatabaseProfile:
    """What was detected about a Kraken2 database's taxonomy.

    ``taxids_are_ncbi`` is a plain bool rather than a tri-state on purpose.
    Every consumer of the old enum tested ``== NCBI`` or ``== CUSTOM``, so
    ``UNKNOWN`` and ``CUSTOM`` already behaved identically. ``False`` is also
    the conservative default: a false exact-taxid match names the *wrong
    organism* on a pathogen dashboard, whereas a missed shortcut merely falls
    through to name matching.

    ``nomenclature`` does need UNKNOWN, because its fallback is a genuinely
    distinct third behaviour -- query both name-resolution APIs, and generate
    the GTDB name variants anyway rather than risk missing a detection.

    ``detected_by`` is the evidence, in operator-readable form. It is what
    makes the override honest: an operator correcting the profile should be
    able to see why the detector decided as it did.
    """

    taxids_are_ncbi: bool = False
    nomenclature: Nomenclature = Nomenclature.UNKNOWN
    detected_by: str = ""
    overridden: bool = False

    @property
    def display_label(self) -> str:
        """Short label for the UI, e.g. "GTDB" or "NCBI (remapped taxids)"."""
        if self.nomenclature is Nomenclature.GTDB:
            base = "GTDB"
        elif self.nomenclature is Nomenclature.NCBI:
            base = "NCBI"
        else:
            base = "Custom"
        if self.nomenclature is Nomenclature.NCBI and not self.taxids_are_ncbi:
            return "NCBI names, remapped taxids"
        if self.nomenclature is not Nomenclature.NCBI and self.taxids_are_ncbi:
            return f"{base} names, NCBI taxids"
        return base

    @property
    def generates_gtdb_variants(self) -> bool:
        """Whether GTDB genus-suffix variants are worth generating.

        UNKNOWN is included deliberately: a misdetected GTDB database must
        still match its organisms, and a false positive costs only CPU.
        """
        return self.nomenclature in (Nomenclature.GTDB, Nomenclature.UNKNOWN)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taxids_are_ncbi": self.taxids_are_ncbi,
            "nomenclature": self.nomenclature.value,
            "detected_by": self.detected_by,
            "overridden": self.overridden,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DatabaseProfile":
        """Rebuild from a serialised dict; unusable input yields the default.

        Tolerant by design -- this is read from on-disk caches that an
        operator may have hand-edited, and an unreadable profile should
        degrade to "unknown" rather than take the application down.
        """
        if not isinstance(data, dict):
            return cls()
        raw = str(data.get("nomenclature", "unknown")).lower()
        try:
            nomenclature = Nomenclature(raw)
        except ValueError:
            logger.debug("Unknown nomenclature %r in profile; using unknown", raw)
            nomenclature = Nomenclature.UNKNOWN
        return cls(
            taxids_are_ncbi=bool(data.get("taxids_are_ncbi", False)),
            nomenclature=nomenclature,
            detected_by=str(data.get("detected_by", "")),
            overridden=bool(data.get("overridden", False)),
        )


# --------------------------------------------------------------------------
# Per-database override
# --------------------------------------------------------------------------

_OVERRIDE_SUFFIX = "_profile_override.json"


def override_path(db_hash: str, mappings_dir: Path) -> Path:
    """Where a manual override for one database lives.

    Deliberately a *sibling* of ``{db_hash}_index.json`` rather than a field
    inside it: the index is a derived cache that is deleted and rebuilt
    whenever its format version changes, and an operator correction must
    survive that.
    """
    return Path(mappings_dir) / f"{db_hash}{_OVERRIDE_SUFFIX}"


def load_override(db_hash: str, mappings_dir: Path) -> Optional[DatabaseProfile]:
    """Read a manual override, or None when there is none."""
    path = override_path(db_hash, mappings_dir)
    if not path.exists():
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable profile override %s: %s", path, exc)
        return None
    return replace(DatabaseProfile.from_dict(data), overridden=True)


def save_override(
    db_hash: str, mappings_dir: Path, profile: DatabaseProfile
) -> Path:
    """Persist a manual override for one database."""
    path = override_path(db_hash, mappings_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = replace(profile, overridden=True).to_dict()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    tmp.replace(path)
    return path


def clear_override(db_hash: str, mappings_dir: Path) -> bool:
    """Remove a manual override; True when one was actually removed."""
    path = override_path(db_hash, mappings_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def apply_override(
    detected: DatabaseProfile, db_hash: str, mappings_dir: Path
) -> DatabaseProfile:
    """Layer any operator override over a detected profile.

    The detector's evidence is preserved in ``detected_by`` so the UI can
    still show what was found even when the operator disagreed with it.
    """
    override = load_override(db_hash, mappings_dir)
    if override is None:
        return detected
    return replace(
        override,
        detected_by=(
            f"operator override (detector said: "
            f"{detected.display_label}; {detected.detected_by})"
            if detected.detected_by else "operator override"
        ),
    )


def load_profile_for_db(database_path: str) -> DatabaseProfile:
    """Read a database's profile without deserialising its node list.

    Background callbacks run in a separate OS process where the module-level
    index singleton is empty (see the background-callback isolation note in
    CLAUDE.md). They need the profile to choose a taxonomy API and a genome
    kingdom hint, but not the tens of thousands of nodes beside it, so this
    reads the small ``"profile"`` object out of the index cache and stops.

    Returns the default (unknown) profile when no cache exists yet, which
    resolves to "query both APIs" -- correct, if slower, behaviour.
    """
    from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
    from nanometa_live.core.utils.paths import get_mappings_dir_from_env

    if not database_path:
        return DatabaseProfile()

    db_hash = get_database_hash(database_path)
    if not db_hash:
        return DatabaseProfile()

    mappings_dir = Path(get_mappings_dir_from_env())
    index_path = mappings_dir / f"{db_hash}_index.json"
    detected = DatabaseProfile()
    if index_path.exists():
        try:
            with open(index_path) as fh:
                data = json.load(fh)
            detected = DatabaseProfile.from_dict(data.get("profile"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Could not read profile from %s: %s", index_path, exc)

    return apply_override(detected, db_hash, mappings_dir)


def kingdom_hint_for_database(config) -> "Optional[str]":
    """"Bacteria" when the loaded database is GTDB, else None.

    GTDB is bacteria and archaea by construction, so on such a database the
    per-taxid NCBI kingdom lookup can be skipped -- which matters offline,
    where that lookup returns None and the download then fails outright.

    Read from the detected profile rather than a config key: whether a
    database is GTDB is a property of the database. Any other nomenclature,
    including undetectable, returns None so the normal per-taxid path runs;
    a generic custom database may hold viruses or eukaryotes, and hinting
    "Bacteria" there would misroute their downloads.
    """
    from nanometa_live.core.taxonomy.database_profile import (
        Nomenclature, load_profile_for_db,
    )

    profile = load_profile_for_db(str((config or {}).get("kraken_db", "")))
    return "Bacteria" if profile.nomenclature is Nomenclature.GTDB else None
