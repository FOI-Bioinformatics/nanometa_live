"""
Database Indexer for Nanometa Live.

This module builds a taxonomy index from Kraken2 database files,
supporting multiple data sources:

1. inspect.txt - Pre-generated kraken2-inspect output
2. taxonomy/names.dmp - NCBI-style taxonomy file
3. kraken2-inspect command - Run dynamically

The index enables efficient lookups by taxid or name for the
taxonomy ID mapping system.
"""

import gzip
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from nanometa_live.core.taxonomy.database_profile import (
    DatabaseProfile,
    Nomenclature,
)
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
)
from nanometa_live.core.watchlist.validation.name_normalizer import (
    get_name_normalizer,
)

logger = logging.getLogger(__name__)

# Well-known NCBI taxids used to test whether a database's integers mean what
# NCBI says they mean. A database that assigns its own taxids reuses these
# numbers for unrelated organisms, which is what makes the probe work.
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


def _utcnow():
    """Naive UTC timestamp, replacing the deprecated stdlib utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


class DatabaseIndexBuilder:
    """
    Build taxonomy index from Kraken2 database sources.

    This class handles parsing various taxonomy file formats and
    building an efficient index for name and taxid lookups.

    Usage:
        builder = DatabaseIndexBuilder()
        index = builder.build_index("/path/to/kraken2/db")
    """

    def __init__(self):
        """Initialize the index builder."""
        self._normalizer = get_name_normalizer()

    def build_index(
        self,
        database_path: str,
        inspect_file: Optional[str] = None
    ) -> Optional[DatabaseTaxonomyIndex]:
        """
        Build taxonomy index from database.

        Tries sources in priority order:
        1. Provided inspect_file
        2. inspect.txt in database directory
        3. taxonomy/names.dmp in database directory
        4. Run kraken2-inspect command

        Args:
            database_path: Path to Kraken2 database directory
            inspect_file: Optional path to inspect output file

        Returns:
            DatabaseTaxonomyIndex or None if building failed
        """
        db_path = Path(database_path)

        if not db_path.exists():
            logger.error(f"Database path does not exist: {database_path}")
            return None

        # Try sources in priority order
        if inspect_file:
            inspect_path = Path(inspect_file)
            if inspect_path.exists():
                logger.info(f"Building index from provided inspect file: {inspect_file}")
                return self.build_from_inspect(str(inspect_path), database_path)

        # Check for existing inspect.txt or inspect.txt.gz
        inspect_txt = db_path / "inspect.txt"
        inspect_txt_gz = db_path / "inspect.txt.gz"

        if inspect_txt.exists():
            logger.info(f"Building index from existing inspect.txt")
            return self.build_from_inspect(str(inspect_txt), database_path)
        elif inspect_txt_gz.exists():
            logger.info(f"Building index from existing inspect.txt.gz")
            return self.build_from_inspect_gz(str(inspect_txt_gz), database_path)

        # Check for names.dmp (taxonomy/ subdir first, then root)
        names_dmp = db_path / "taxonomy" / "names.dmp"
        if not names_dmp.exists():
            names_dmp = db_path / "names.dmp"

        if names_dmp.exists():
            logger.info(f"Building index from {names_dmp}")
            # Check for nodes.dmp in same location as names.dmp
            nodes_dmp = names_dmp.parent / "nodes.dmp"
            if not nodes_dmp.exists():
                # Also check the other location
                alt_nodes = db_path / "taxonomy" / "nodes.dmp" if names_dmp.parent == db_path else db_path / "nodes.dmp"
                if alt_nodes.exists():
                    nodes_dmp = alt_nodes
            return self.build_from_names_dmp(
                str(names_dmp),
                str(nodes_dmp) if nodes_dmp.exists() else None,
                database_path
            )

        # Try running kraken2-inspect
        logger.info(f"Attempting to run kraken2-inspect")
        return self.build_from_kraken2_inspect(database_path)

    def build_from_inspect(
        self,
        filepath: str,
        database_path: str
    ) -> Optional[DatabaseTaxonomyIndex]:
        """
        Build index from kraken2-inspect output format.

        Format: percent\tcumul_reads\treads\trank\ttaxid\tname

        Args:
            filepath: Path to inspect output file
            database_path: Path to database for metadata

        Returns:
            DatabaseTaxonomyIndex or None
        """
        try:
            index = DatabaseTaxonomyIndex(
                database_path=database_path,
                inspect_file_path=filepath
            )

            with open(filepath, 'r') as f:
                for line in f:
                    line = line.rstrip('\n\r')
                    if not line:
                        continue

                    parts = line.split('\t')
                    if len(parts) < 6:
                        continue

                    try:
                        percent = float(parts[0].strip())
                        clade_reads = int(parts[1].strip())
                        direct_reads = int(parts[2].strip())
                        rank = parts[3].strip()
                        taxid = int(parts[4].strip())
                        # Name may have leading spaces for indentation
                        name = parts[5].strip()
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Skipping malformed line: {e}")
                        continue

                    # Create node
                    node = self._create_node(
                        taxid=taxid,
                        name=name,
                        rank=rank,
                        clade_reads=clade_reads,
                        direct_reads=direct_reads,
                        abundance_percent=percent
                    )

                    # Add to index
                    self._add_node_to_index(index, node)

            # Detect database type
            index.profile = self._detect_profile(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = _utcnow()

            # Build prefix index for fast searches
            index.build_prefix_index()

            logger.info(
                f"Built index: {index.total_nodes} nodes, "
                f"{index.species_count} species, type={index.database_type.value}"
            )

            return index

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as e:
            logger.exception(f"Failed to build index from inspect file: {e}")
            return None

    def build_from_inspect_gz(
        self,
        filepath: str,
        database_path: str
    ) -> Optional[DatabaseTaxonomyIndex]:
        """
        Build index from gzipped kraken2-inspect output format.

        Args:
            filepath: Path to gzipped inspect output file
            database_path: Path to database for metadata

        Returns:
            DatabaseTaxonomyIndex or None
        """
        import gzip

        try:
            index = DatabaseTaxonomyIndex(
                database_path=database_path,
                inspect_file_path=filepath
            )

            with gzip.open(filepath, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip('\n\r')
                    if not line:
                        continue

                    parts = line.split('\t')
                    if len(parts) < 6:
                        continue

                    try:
                        percent = float(parts[0].strip())
                        clade_reads = int(parts[1].strip())
                        direct_reads = int(parts[2].strip())
                        rank = parts[3].strip()
                        taxid = int(parts[4].strip())
                        # Name may have leading spaces for indentation
                        name = parts[5].strip()
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Skipping malformed line: {e}")
                        continue

                    # Create node
                    node = self._create_node(
                        taxid=taxid,
                        name=name,
                        rank=rank,
                        clade_reads=clade_reads,
                        direct_reads=direct_reads,
                        abundance_percent=percent
                    )

                    # Add to index
                    self._add_node_to_index(index, node)

            # Detect database type
            index.profile = self._detect_profile(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = _utcnow()

            # Build prefix index for fast searches
            index.build_prefix_index()

            logger.info(
                f"Built index from gzip: {index.total_nodes} nodes, "
                f"{index.species_count} species, type={index.database_type.value}"
            )

            return index

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, EOFError) as e:
            logger.exception(f"Failed to build index from gzipped inspect file: {e}")
            return None

    def build_from_names_dmp(
        self,
        names_path: str,
        nodes_path: Optional[str],
        database_path: str
    ) -> Optional[DatabaseTaxonomyIndex]:
        """
        Build index from NCBI-style names.dmp and nodes.dmp files.

        Args:
            names_path: Path to names.dmp file
            nodes_path: Optional path to nodes.dmp file for ranks
            database_path: Path to database for metadata

        Returns:
            DatabaseTaxonomyIndex or None
        """
        try:
            index = DatabaseTaxonomyIndex(database_path=database_path)

            # Load ranks from nodes.dmp if available
            ranks: Dict[int, str] = {}
            parents: Dict[int, int] = {}

            if nodes_path and Path(nodes_path).exists():
                with open(nodes_path, 'r') as f:
                    for line in f:
                        parts = line.strip().split('\t|\t')
                        if len(parts) >= 3:
                            try:
                                taxid = int(parts[0].strip())
                                parent_taxid = int(parts[1].strip())
                                rank = parts[2].strip()
                                # Convert rank to single letter
                                rank_code = self._rank_to_code(rank)
                                ranks[taxid] = rank_code
                                parents[taxid] = parent_taxid
                            except ValueError:
                                continue

            # Load names from names.dmp
            with open(names_path, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t|\t')
                    if len(parts) >= 4:
                        try:
                            taxid = int(parts[0].strip())
                            name = parts[1].strip()
                            name_class = parts[3].strip().rstrip('\t|')

                            # Only use scientific names
                            if name_class != "scientific name":
                                continue

                            rank = ranks.get(taxid, "U")
                            parent = parents.get(taxid)

                            node = self._create_node(
                                taxid=taxid,
                                name=name,
                                rank=rank,
                                parent_taxid=parent
                            )

                            self._add_node_to_index(index, node)

                        except ValueError:
                            continue

            # Detect database type
            index.profile = self._detect_profile(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = _utcnow()

            # Build prefix index for fast searches
            index.build_prefix_index()

            logger.info(
                f"Built index from names.dmp: {index.total_nodes} nodes, "
                f"{index.species_count} species"
            )

            return index

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as e:
            logger.exception(f"Failed to build index from names.dmp: {e}")
            return None

    def build_from_kraken2_inspect(
        self,
        database_path: str
    ) -> Optional[DatabaseTaxonomyIndex]:
        """
        Build index by running kraken2-inspect command.

        Args:
            database_path: Path to Kraken2 database

        Returns:
            DatabaseTaxonomyIndex or None
        """
        try:
            # Run kraken2-inspect
            result = subprocess.run(
                ["kraken2-inspect", "--db", database_path],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                logger.error(f"kraken2-inspect failed: {result.stderr}")
                return None

            # Write output to temporary file and parse
            db_path = Path(database_path)
            inspect_path = db_path / "inspect.txt"

            with open(inspect_path, 'w') as f:
                f.write(result.stdout)

            logger.info(f"Generated inspect.txt at {inspect_path}")

            return self.build_from_inspect(str(inspect_path), database_path)

        except subprocess.TimeoutExpired:
            logger.error("kraken2-inspect timed out")
            return None
        except FileNotFoundError:
            logger.error("kraken2-inspect command not found")
            return None
        except (subprocess.CalledProcessError, PermissionError, OSError) as e:
            logger.exception(f"Failed to run kraken2-inspect: {e}")
            return None

    def _create_node(
        self,
        taxid: int,
        name: str,
        rank: str,
        parent_taxid: Optional[int] = None,
        clade_reads: int = 0,
        direct_reads: int = 0,
        abundance_percent: float = 0.0
    ) -> DatabaseTaxonomyNode:
        """Create a taxonomy node with normalized names."""
        normalized = self._normalizer.normalize(name)

        return DatabaseTaxonomyNode(
            taxid=taxid,
            name=name,
            rank=rank,
            parent_taxid=parent_taxid,
            name_normalized=normalized.canonical,
            name_gtdb_style=name.lower().replace(" ", "_"),
            clade_reads=clade_reads,
            direct_reads=direct_reads,
            abundance_percent=abundance_percent
        )

    def _add_node_to_index(
        self,
        index: DatabaseTaxonomyIndex,
        node: DatabaseTaxonomyNode
    ) -> None:
        """Add a node to the index."""
        # Primary index by taxid
        index.by_taxid[node.taxid] = node

        # Index by normalized name
        if node.name_normalized:
            if node.name_normalized not in index.by_name:
                index.by_name[node.name_normalized] = []
            if node.taxid not in index.by_name[node.name_normalized]:
                index.by_name[node.name_normalized].append(node.taxid)

        # Index by GTDB-style name
        if node.name_gtdb_style:
            if node.name_gtdb_style not in index.by_name_gtdb:
                index.by_name_gtdb[node.name_gtdb_style] = []
            if node.taxid not in index.by_name_gtdb[node.name_gtdb_style]:
                index.by_name_gtdb[node.name_gtdb_style].append(node.taxid)

    def _detect_profile(
        self,
        index: DatabaseTaxonomyIndex,
    ) -> DatabaseProfile:
        """Answer both taxonomy questions about this database.

        The two axes are independent and are detected independently: a
        database can use NCBI-style binomial names while having remapped its
        taxids, which is what most "mixed" databases actually are.

        Taxon names decide the nomenclature whenever they can. Only when they
        cannot does this fall back to the sidecar files, which carry signals
        the inspect dump does not contain.
        """
        taxids_are_ncbi, taxid_evidence = self._detect_taxids_are_ncbi(index)
        nomenclature, name_evidence = self._detect_nomenclature(index)

        if nomenclature is Nomenclature.UNKNOWN and index.database_path:
            hinted, hint_evidence = _nomenclature_hints_from_files(
                Path(index.database_path)
            )
            if hinted is not Nomenclature.UNKNOWN:
                nomenclature = hinted
                name_evidence = hint_evidence

        return DatabaseProfile(
            taxids_are_ncbi=taxids_are_ncbi,
            nomenclature=nomenclature,
            detected_by=f"{taxid_evidence}; {name_evidence}",
        )

    def _detect_taxids_are_ncbi(
        self,
        index: DatabaseTaxonomyIndex,
    ) -> Tuple[bool, str]:
        """Q1: do this database's taxids mean what NCBI says they mean?

        Probing well-known taxids is the reliable test, because a database
        that assigns its own integers reuses these numbers for unrelated
        organisms. The rule is deliberately strict -- ALL probed taxa must
        match -- and the default when none are present is False, because a
        false exact-taxid match names the wrong organism on a pathogen
        dashboard while a missed one merely falls through to name matching.

        Returns ``(taxids_are_ncbi, evidence)``.
        """
        matches = 0
        checked = 0

        for ncbi_taxid, expected_name in _NCBI_REFERENCE_TAXA.items():
            if ncbi_taxid not in index.by_taxid:
                continue
            checked += 1
            actual_name = index.by_taxid[ncbi_taxid].name.lower()
            expected_lower = expected_name.lower()
            expected_genus = expected_lower.split()[0]
            if expected_genus in actual_name or expected_lower in actual_name:
                matches += 1

        if checked == 0:
            return False, "no reference taxa present"
        evidence = f"{matches}/{checked} reference taxa match"
        if matches == checked:
            logger.info("Detected NCBI-compatible taxids: %s", evidence)
            return True, evidence
        logger.info("Detected remapped taxids: %s", evidence)
        return False, evidence

    def _detect_nomenclature(
        self,
        index: DatabaseTaxonomyIndex,
    ) -> Tuple[Nomenclature, str]:
        """Q2: which naming convention do this database's names follow?

        GTDB is recognised by two unambiguous markers, either of which is
        conclusive on its own because neither occurs in NCBI names: the
        ``d__``..``s__`` rank prefixes, and the alphabetic polyphyly suffix on
        a genus (``Bacillus_A``). A single occurrence is enough -- requiring a
        majority would miss databases that carry only a handful.

        Sampling is over species nodes rather than an insertion-order head of
        ``by_taxid``: the suffixed genera are rare in absolute terms and a
        head sample systematically missed them.

        Returns ``(nomenclature, evidence)``.
        """
        nodes = index.get_species() or list(index.by_taxid.values())
        if not nodes:
            return Nomenclature.UNKNOWN, "database has no taxa"

        sample = nodes[:_NOMENCLATURE_SAMPLE_SIZE]
        prefixed = 0
        suffixed = 0
        binomial = 0

        for node in sample:
            name = node.name.strip()
            if not name:
                continue
            if name.startswith(_GTDB_RANK_PREFIXES):
                prefixed += 1
                continue
            genus = name.split(" ", 1)[0].split("_", 1)[0]
            if _GTDB_GENUS_SUFFIX_RE.match(name.split(" ", 1)[0]):
                suffixed += 1
                continue
            if " " in name and genus[:1].isupper():
                binomial += 1

        if prefixed:
            return (
                Nomenclature.GTDB,
                f"{prefixed}/{len(sample)} sampled names carry GTDB rank prefixes",
            )
        if suffixed:
            return (
                Nomenclature.GTDB,
                f"{suffixed}/{len(sample)} sampled names carry a GTDB genus suffix",
            )
        if binomial and binomial / len(sample) >= _BINOMIAL_MAJORITY:
            return (
                Nomenclature.NCBI,
                f"{binomial}/{len(sample)} sampled names are binomial",
            )
        return (
            Nomenclature.UNKNOWN,
            f"no clear convention in {len(sample)} sampled names",
        )

    def _rank_to_code(self, rank: str) -> str:
        """Convert full rank name to single letter code."""
        rank_map = {
            "domain": "D",
            "superkingdom": "D",
            "kingdom": "K",
            "phylum": "P",
            "class": "C",
            "order": "O",
            "family": "F",
            "genus": "G",
            "species": "S",
            "subspecies": "S1",
            "strain": "S2",
            "no rank": "U",
            "root": "R",
            "unclassified": "U"
        }
        return rank_map.get(rank.lower(), "U")


# Singleton instance
_builder: Optional[DatabaseIndexBuilder] = None


def get_index_builder() -> DatabaseIndexBuilder:
    """Get the global DatabaseIndexBuilder instance."""
    global _builder
    if _builder is None:
        _builder = DatabaseIndexBuilder()
    return _builder


def build_database_index(
    database_path: str,
    inspect_file: Optional[str] = None
) -> Optional[DatabaseTaxonomyIndex]:
    """
    Convenience function to build a database index.

    Args:
        database_path: Path to Kraken2 database
        inspect_file: Optional path to inspect output

    Returns:
        DatabaseTaxonomyIndex or None
    """
    builder = get_index_builder()
    return builder.build_index(database_path, inspect_file)
