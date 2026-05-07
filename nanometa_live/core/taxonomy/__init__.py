"""
Taxonomy module for Nanometa Live.

Provides:
- API clients for NCBI and GTDB taxonomy lookups with local caching
- Taxonomy ID mapping between NCBI and Kraken2 database taxids

Import directly from leaf modules (taxonomy_api, taxid_mapping,
database_indexer); the package level re-export hub was collapsed in the
2026-05-07 audit pass.
"""
