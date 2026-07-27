"""Signals used to work out what taxonomy a Kraken2 database uses.

Split out of ``database_indexer`` so that module stays about *building* an
index and this one about *reading* it. The two detection methods on
``DatabaseIndexBuilder`` remain there, since they operate on a built index;
these are the constants and the file-level probes they lean on.
"""

from __future__ import annotations

import gzip
import logging
import re
from pathlib import Path
from typing import Dict, Tuple

from nanometa_live.core.taxonomy.database_profile import Nomenclature

logger = logging.getLogger(__name__)


_NCBI_REFERENCE_TAXA: Dict[int, str] = {
    562: "Escherichia coli",
    632: "Yersinia pestis",
    1392: "Bacillus anthracis",
    287: "Pseudomonas aeruginosa",
    1280: "Staphylococcus aureus",
    1773: "Mycobacterium tuberculosis",
    1717: "Corynebacterium diphtheriae",
    263: "Francisella tularensis",
    623: "Shigella flexneri",
    727: "Haemophilus influenzae",
    1313: "Streptococcus pneumoniae",
    485: "Neisseria gonorrhoeae",
    1351: "Enterococcus faecalis",
    1352: "Enterococcus faecium",
    1396: "Bacillus cereus",
    1423: "Bacillus subtilis",
    28901: "Salmonella enterica",
    470: "Acinetobacter baumannii",
    817: "Bacteroides fragilis",
    # Archaea
    2234: "Archaeoglobus fulgidus",
    # Fungi
    4932: "Saccharomyces cerevisiae",
    5476: "Candida albicans",
    746128: "Aspergillus fumigatus",
    # Protozoa
    5833: "Plasmodium falciparum",
    5691: "Trypanosoma brucei",
    # Viruses
    2697049: "Severe acute respiratory syndrome coronavirus 2",
    10298: "Human alphaherpesvirus 1",
    11676: "Human immunodeficiency virus 1",
    # Plants and animals (host / background taxa in most panels)
    9606: "Homo sapiens",
    10090: "Mus musculus",
    3702: "Arabidopsis thaliana",
    4565: "Triticum aestivum",
}

# GTDB writes a rank prefix on every name; none of these occur in NCBI names,
# so a single occurrence is conclusive.
_GTDB_RANK_PREFIXES: Tuple[str, ...] = (
    "d__", "p__", "c__", "o__", "f__", "g__", "s__",
)

# GTDB appends an alphabetic suffix to a genus it has split for polyphyly,
# e.g. "Bacillus_A anthracis". Also conclusive on its own.
_GTDB_GENUS_SUFFIX_RE = re.compile(r"^[A-Z][a-z]+_[A-Z]$")

# Species nodes sampled when inferring the naming convention. Large enough to
# find the rare suffixed genera, small enough to stay cheap on a PlusPFP-sized
# database.
_NOMENCLATURE_SAMPLE_SIZE = 5000

# Fraction of sampled names that must be binomial before a database is called
# NCBI-style, when no GTDB marker was found at all.
_BINOMIAL_MAJORITY = 0.5

# GTDB accession prefixes needed in the first 200 seqid2taxid lines
# before that file is taken as evidence. A handful could be an NCBI
# database that happens to include GTDB-sourced sequences.
_SEQID_GTDB_MIN_LINES = 50


def _names_agree(actual: str, expected: str) -> bool:
    """Whether a database's name for a taxid is the organism NCBI has there.

    Tolerant of the ways databases legitimately differ -- extra strain or
    serovar suffixes, underscores instead of spaces -- but not of a bare
    substring test, which is far too loose now that the probe set spans
    kingdoms. Viral names in particular share generic leading words: matching
    on "human" alone would call *Human immunodeficiency virus 1* and *Human
    alphaherpesvirus 1* the same organism, turning the check into a coin flip
    in exactly the cases it exists to catch.
    """
    actual_l = " ".join(str(actual).lower().replace("_", " ").split())
    expected_l = " ".join(str(expected).lower().split())
    if not actual_l or not expected_l:
        return False
    # Strain/serovar suffixes and shortened forms: one name contains the other.
    if expected_l in actual_l or actual_l in expected_l:
        return True
    # Otherwise require the first two tokens to agree -- genus plus epithet
    # for an organism, and enough of a viral designation to be distinctive.
    actual_tokens = actual_l.split()
    expected_tokens = expected_l.split()
    if len(actual_tokens) < 2 or len(expected_tokens) < 2:
        return False
    return actual_tokens[:2] == expected_tokens[:2]


def _open_maybe_gz(path: Path):
    """Open a path as text, transparently handling a .gz suffix."""
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _nomenclature_hints_from_files(db_path: Path) -> Tuple[Nomenclature, str]:
    """Infer nomenclature from a database's sidecar files.

    A last resort, consulted only when the taxon names themselves were
    inconclusive. These two files carry evidence the inspect dump does not:

    * ``library/library_report.tsv`` records the source lineages, which keep
      their GTDB rank prefixes even when the taxon names in the index have
      been flattened.
    * ``seqid2taxid.map`` keys GTDB assemblies by their GenBank/RefSeq
      accessions, which GTDB prefixes with ``GB_``/``RS_``.

    Deliberately excluded, though the previous implementation used them: the
    directory-name hint (``"gtdb" in db_name`` fires on ``/data/gtdb_and_ncbi/``)
    and a default of GTDB when nothing matched. Both are guesses, and guessing
    is what this detection replaced -- an honest UNKNOWN makes the caller
    query both APIs and generate variants anyway, which is safe.

    Returns ``(nomenclature, evidence)``.
    """
    library_report = db_path / "library" / "library_report.tsv"
    if library_report.exists():
        try:
            with open(library_report, "r", errors="replace") as fh:
                content = fh.read(2000)
            if "d__" in content or "s__" in content:
                return Nomenclature.GTDB, "GTDB lineage prefixes in library report"
            if "cellular organisms" in content:
                return Nomenclature.NCBI, "NCBI lineage markers in library report"
        except OSError as exc:
            logger.debug("Could not read %s: %s", library_report, exc)

    for seqid_map in (
        db_path / "seqid2taxid.map",
        db_path / "seqid2taxid.map.gz",
    ):
        if not seqid_map.exists():
            continue
        try:
            with _open_maybe_gz(seqid_map) as fh:
                lines = [fh.readline() for _ in range(200)]
        except (OSError, EOFError) as exc:
            logger.debug("Could not read %s: %s", seqid_map, exc)
            break
        gtdb_lines = sum(1 for line in lines if "GB_" in line or "RS_" in line)
        if gtdb_lines > _SEQID_GTDB_MIN_LINES:
            return (
                Nomenclature.GTDB,
                f"{gtdb_lines} GTDB accession prefixes in seqid2taxid.map",
            )
        break

    return Nomenclature.UNKNOWN, "no nomenclature markers in database files"
