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

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
    DatabaseTaxonomyType,
)
from nanometa_live.core.watchlist.validation.name_normalizer import (
    get_name_normalizer,
)

logger = logging.getLogger(__name__)


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
            index.database_type = self._detect_taxonomy_type(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = datetime.utcnow()

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
            index.database_type = self._detect_taxonomy_type(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = datetime.utcnow()

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
            index.database_type = self._detect_taxonomy_type(index)
            index.total_nodes = len(index.by_taxid)
            index.species_count = len([n for n in index.by_taxid.values() if n.rank == "S"])
            index.built_at = datetime.utcnow()

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

    def _detect_taxonomy_type(
        self,
        index: DatabaseTaxonomyIndex
    ) -> DatabaseTaxonomyType:
        """
        Detect whether database uses NCBI or custom taxonomy.

        A database is classified as NCBI only when ALL checked reference taxa
        match their expected NCBI organisms. If any mismatch is found, the
        database uses custom/arbitrary taxids (e.g., GTDB-based databases).

        Detection approach:
        1. Check if well-known NCBI taxids map to expected organisms
        2. Fall back to naming pattern analysis if no reference taxa found
        """
        # Check if well-known NCBI taxids map to expected organisms
        # This is the most reliable check - custom databases reuse these taxids
        ncbi_reference_taxa = {
            562: "Escherichia coli",
            632: "Yersinia pestis",
            1392: "Bacillus anthracis",
            287: "Pseudomonas aeruginosa",
            1280: "Staphylococcus aureus",
        }

        matches = 0
        checked = 0

        for ncbi_taxid, expected_name in ncbi_reference_taxa.items():
            if ncbi_taxid in index.by_taxid:
                checked += 1
                actual_name = index.by_taxid[ncbi_taxid].name.lower()
                expected_lower = expected_name.lower()
                # Check if the genus matches at least
                expected_genus = expected_lower.split()[0]
                if expected_genus in actual_name or expected_lower in actual_name:
                    matches += 1

        # NCBI only if ALL checked taxa match
        if checked > 0 and matches == checked:
            logger.info(
                f"Detected NCBI database: {matches}/{checked} reference taxa match"
            )
            return DatabaseTaxonomyType.NCBI
        elif checked > 0:
            # Any mismatch means custom taxids
            logger.info(
                f"Detected custom database: {matches}/{checked} reference taxa match "
                f"(custom/arbitrary taxids detected)"
            )
            return DatabaseTaxonomyType.CUSTOM

        # Fall back to naming pattern analysis if no reference taxa found
        custom_indicators = 0
        ncbi_indicators = 0

        sample_size = min(200, len(index.by_taxid))
        sample_nodes = list(index.by_taxid.values())[:sample_size]

        for node in sample_nodes:
            name = node.name

            # Check for GTDB-style prefix patterns (indicates custom taxonomy)
            if any(name.startswith(p) for p in ["d__", "p__", "c__", "o__", "f__", "g__", "s__"]):
                custom_indicators += 3
            elif "_" in name and " " not in name:
                custom_indicators += 1

            # Check for NCBI patterns (binomial nomenclature with spaces)
            if " " in name and not any(name.startswith(p) for p in ["d__", "p__", "c__", "o__", "f__", "g__", "s__"]):
                ncbi_indicators += 1

        total = custom_indicators + ncbi_indicators
        if total == 0:
            return DatabaseTaxonomyType.UNKNOWN

        custom_ratio = custom_indicators / total

        if custom_ratio > 0.6:
            return DatabaseTaxonomyType.CUSTOM
        elif custom_ratio < 0.3:
            return DatabaseTaxonomyType.NCBI
        else:
            return DatabaseTaxonomyType.MIXED

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
