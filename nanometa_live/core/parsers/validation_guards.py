"""Safety guards for read validation.

Two pure, dependency-light checks that protect against the failure modes amplicon
(e.g. full-length 16S rRNA) validation exposes:

1. ``check_reference_organism`` -- the validation reference for a taxid is the
   genome registered for that taxid in ``pathogen_genomes.json``. If the wrong
   genome was registered (its FASTA header names a different genus than the
   watchlist species), an identity-only CONFIRMED would attribute a hit to the
   wrong organism. This flags a genus-level mismatch.

2. ``conserved_region_caveat`` -- 16S rRNA is >97% conserved across species, so
   amplicon reads can clear the identity threshold against a near relative's
   reference. When the supporting coverage is concentrated on a short locus
   (``CoverageData.is_concentrated``), the confirmation rests on a region that
   does not discriminate close species; surface that caveat to the operator.

Both return ``None`` when there is nothing to warn about, so callers can do
``if (msg := guard(...)): ...``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Accession-like leading token in a FASTA header (e.g. "NZ_CP009607.1"); the
# organism description follows it.
_GENERIC_FIRST_TOKENS = {"the", "a", "an"}


def _genus_of(name: Optional[str]) -> str:
    """Return the lowercased genus (first alphabetic token) of an organism name."""
    if not name:
        return ""
    for token in str(name).strip().split():
        t = "".join(ch for ch in token if ch.isalpha())
        if t and t.lower() not in _GENERIC_FIRST_TOKENS:
            return t.lower()
    return ""


def reference_organism_from_fasta(genome_path) -> Optional[str]:
    """Read the organism description from a FASTA header.

    Returns the text after the first (accession) token of the first ``>`` line,
    or ``None`` if the file is unreadable/empty. Handles plain and ``.gz`` FASTA.
    """
    p = Path(genome_path)
    try:
        if p.suffix == ".gz":
            import gzip
            with gzip.open(p, "rt") as fh:
                header = fh.readline()
        else:
            with open(p, "r") as fh:
                header = fh.readline()
    except (OSError, UnicodeDecodeError) as e:
        logger.debug("Could not read FASTA header from %s: %s", p, e)
        return None
    header = header.strip()
    if not header.startswith(">"):
        return None
    parts = header[1:].split(None, 1)
    return parts[1].strip() if len(parts) == 2 else None


def check_reference_organism(genome_path, expected_name: Optional[str]) -> Optional[str]:
    """Flag a genus mismatch between a reference genome and the expected species.

    Returns a human-readable warning when both the genome header organism and the
    ``expected_name`` are known and their genus differs; otherwise ``None`` (a
    missing/uninformative side is treated as "cannot tell", not a mismatch).
    """
    ref_org = reference_organism_from_fasta(genome_path)
    ref_genus = _genus_of(ref_org)
    exp_genus = _genus_of(expected_name)
    if not ref_genus or not exp_genus:
        return None
    if ref_genus != exp_genus:
        return (
            f"Reference genome organism '{ref_org}' does not match the expected "
            f"species '{expected_name}' (genus '{ref_genus}' vs '{exp_genus}'). "
            "Validation results for this target may be attributed to the wrong "
            "organism -- check the registered reference genome."
        )
    return None


def _status_value(status) -> str:
    """Normalise a status (enum or str) to its lowercase string value."""
    val = getattr(status, "value", status)
    return str(val).lower() if val is not None else ""


def conserved_region_caveat(coverage, status=None) -> Optional[str]:
    """Return a specificity caveat when confirmation rests on a short locus.

    Fires when the supporting coverage is concentrated on a short region
    (``coverage.is_concentrated``) -- the amplicon / 16S case where high identity
    is not species-discriminating. ``status`` is optional; when given, the caveat
    is suppressed for clearly negative states (no_data/failed) where there is
    nothing to over-claim.
    """
    if coverage is None or not getattr(coverage, "is_concentrated", False):
        return None
    if status is not None and _status_value(status) in {"no_data", "failed"}:
        return None
    # Total covered bases (sums multi-copy rRNA loci); NOT covered_span, which for
    # a multi-copy 16S spans the megabases between operons and would mislead.
    covered = getattr(coverage, "covered_bp", 0)
    return (
        f"Confirmation rests on a short conserved region (~{covered:,} bp of "
        "coverage, e.g. a 16S locus). Such regions are highly similar across "
        "related species, so this result may not distinguish the target from "
        "close relatives -- treat the species-level call with corresponding caution."
    )
