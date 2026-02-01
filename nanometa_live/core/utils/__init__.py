"""
Utility functions for Nanometa Live.

This package contains various utility functions used throughout the application
for file operations, data processing, and analysis.
"""

from nanometa_live.core.utils.file_utils import *
from nanometa_live.core.utils.data_utils import *
from nanometa_live.core.utils.blast_utils import *
from nanometa_live.core.utils.kraken_utils import *
from nanometa_live.core.utils.diversity_metrics import (
    # Alpha diversity functions
    AlphaDiversity,
    calculate_shannon_index,
    calculate_simpson_index,
    calculate_chao1,
    calculate_pielou_evenness,
    calculate_alpha_diversity,
    # Beta diversity functions
    calculate_bray_curtis,
    calculate_jaccard,
    build_abundance_matrix,
    calculate_beta_diversity_matrix,
    get_diversity_summary,
)
from nanometa_live.core.utils.offline_cache import (
    OfflineTaxonomyCache,
    CacheEntry,
    get_cache,
    cached_api_call,
    DEFAULT_CACHE_DIR,
    DEFAULT_TTL,
)
from nanometa_live.core.utils.auto_detect import (
    detect_sample_handling,
    detect_kraken_taxonomy,
    estimate_update_interval,
    auto_detect_config,
    get_barcode_list,
    detect_file_format,
)
from nanometa_live.core.utils.read_extractor import (
    ReadExtractor,
    ExtractionResult,
)
