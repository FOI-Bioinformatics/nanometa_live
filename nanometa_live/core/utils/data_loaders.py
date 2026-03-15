"""
Sample-aware data loading utilities for Nanometa Live v2.0.

This module re-exports all loader functions from category-specific modules
for backward compatibility. New code may import directly from the sub-modules:
- nanometa_live.core.utils.classification_loaders
- nanometa_live.core.utils.qc_loaders
- nanometa_live.core.utils.validation_loaders
- nanometa_live.core.utils.loader_utils
"""

# Shared cache utilities
from nanometa_live.core.utils.loader_utils import (  # noqa: F401
    CACHE_TTL_SECONDS,
    CACHE_MAX_ENTRIES,
    CACHE_CLEANUP_INTERVAL_SECONDS,
    FILE_STABILITY_CHECK_INTERVAL_MS,
    FILE_STABILITY_MIN_SIZE_BYTES,
    _is_file_stable,
    _get_cache_key,
    _is_cache_valid,
    _cleanup_stale_cache_entries,
    clear_data_cache,
    check_data_freshness,
    _get_dir_latest_mtime,
    _get_path_fingerprint,
    _check_mtime_cache,
    _store_mtime_cache,
    _cache_lock,
    _kraken_cache,
    _fastp_cache,
)

# Classification loaders
from nanometa_live.core.utils.classification_loaders import (  # noqa: F401
    KRAKEN2_EXPECTED_COLUMNS,
    KRAKEN2_EXPECTED_COLUMN_COUNT,
    _parse_kraken2_report,
    _deduplicate_batch_files,
    load_kraken_data,
)

# QC loaders
from nanometa_live.core.utils.qc_loaders import (  # noqa: F401
    _empty_fastp_stats,
    _empty_nanoplot_stats,
    _parse_nanostats_file,
    _load_seqkit_as_nanoplot_stats,
    load_fastp_data,
    load_batch_stats,
    load_nanoplot_stats,
    load_seqkit_stats,
    get_sample_statistics_summary,
    get_qc_stats,
)

# Validation loaders
from nanometa_live.core.utils.validation_loaders import (  # noqa: F401
    load_validation_data,
    load_blast_validation_data,
)

# Canonical format loaders
from nanometa_live.core.utils.canonical_loaders import (  # noqa: F401
    load_manifest,
    load_canonical_classification,
    load_canonical_qc_stats,
    load_canonical_validation,
    load_canonical_assembly,
)
