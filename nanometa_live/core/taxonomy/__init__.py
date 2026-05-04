"""
Taxonomy module for Nanometa Live.

Provides:
- API clients for NCBI and GTDB taxonomy lookups with local caching
- Taxonomy ID mapping between NCBI and Kraken2 database taxids
"""

from nanometa_live.core.taxonomy.taxonomy_api import (
    TaxonomyAPIClient,
    NCBIClient,
    GTDBClient,
    NCBIResult,
    GTDBResult,
    TaxonomyCache,
    get_ncbi_client,
    get_gtdb_client,
)

from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    DatabaseTaxonomyType,
    AlternativeMatch,
    TaxidMapping,
    DatabaseTaxonomyNode,
    DatabaseTaxonomyIndex,
    TaxidMappingCollection,
    TaxidMapper,
    get_database_hash,
    get_mapping_cache_path,
    get_mapping_collection,
    set_mapping_collection,
    get_database_index,
    set_database_index,
    get_taxid_mapper,
)

from nanometa_live.core.taxonomy.database_indexer import (
    DatabaseIndexBuilder,
    get_index_builder,
    build_database_index,
)

__all__ = [
    # API clients
    "TaxonomyAPIClient",
    "NCBIClient",
    "GTDBClient",
    "NCBIResult",
    "GTDBResult",
    "TaxonomyCache",
    "get_ncbi_client",
    "get_gtdb_client",
    # Taxid mapping
    "MappingConfidence",
    "DatabaseTaxonomyType",
    "AlternativeMatch",
    "TaxidMapping",
    "DatabaseTaxonomyNode",
    "DatabaseTaxonomyIndex",
    "TaxidMappingCollection",
    "TaxidMapper",
    "get_database_hash",
    "get_mapping_cache_path",
    "get_mapping_collection",
    "set_mapping_collection",
    "get_database_index",
    "set_database_index",
    "get_taxid_mapper",
    # Database indexer
    "DatabaseIndexBuilder",
    "get_index_builder",
    "build_database_index",
]
