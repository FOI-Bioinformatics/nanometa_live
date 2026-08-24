"""Every module-level cache must be covered by both reset paths.

The round-3 audit found five caches that survived `clear_all_loader_caches`
(run boundaries) and `instrument.reset_caches` (perf cold cells): the
taxonomy map, the PAF breadth cache, the validation-parser singletons, the
organisms memo and the pathogen memos. The failure mode recurs whenever a
new cache is added, so this test greps the loader stack for module-level
cache-shaped assignments and fails on any name not in the covered
inventory -- the structural fix the plan called a cache registry, done as
a fence instead of a refactor.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import nanometa_live

PKG = Path(nanometa_live.__file__).parent

# Modules whose module-level dict/OrderedDict/set assignments are treated
# as caches. Extend when a new module joins the per-poll loader stack.
WATCHED_MODULES = [
    "core/utils/loader_utils.py",
    "core/utils/classification_loaders.py",
    "core/utils/qc_loaders.py",
    "core/utils/seqkit_batch_cache.py",
    "core/utils/report_accumulation.py",
    "core/utils/sample_detector.py",
    "core/utils/read_length_probe.py",
    "core/utils/staleness.py",
    "core/parsers/paf_coverage_parser.py",
    "core/parsers/blast_validation_parser.py",
    "app/utils/organisms_memo.py",
    "app/tabs/kraken2_helpers.py",
    "app/tabs/validation_tab_helpers.py",
]

# Names covered by clear_all_loader_caches and/or instrument.reset_caches,
# or deliberately exempt (with the reason).
COVERED_OR_EXEMPT = {
    # cleared by clear_data_cache / clear_all_loader_caches
    "_kraken_cache", "_fastp_cache", "_file_mtimes", "_parse_locks",
    "_sample_cache", "_file_mapping_cache",
    # classification_loaders: cleared by clear_report_frame_cache
    "_report_frame_cache", "_last_good_frame", "_latest_batch_memo",
    "_frame_sizes", "_last_good_sizes",
    # round-3 modules with their own registered clear functions
    "_cache",            # seqkit_batch_cache
    "_sample_accum",     # report_accumulation
    "_serving_since", "_last_warned",   # staleness
    "_breadth_cache",    # paf_coverage_parser (harness reset)
    "_length_cache",     # read_length_probe (capped + superseded in place)
    "_parser_singletons",  # blast_validation_parser (reset_validation_parsers)
    "_memo",             # organisms_memo (harness reset + epoch eviction)
    "_TAXONOMY_CACHE",   # kraken2_helpers (harness reset + single-DB evict)
    "_batch_ids_memo",   # validation_tab_helpers (dir-mtime keyed, bounded)
    # exempt: not caches
    "_saturation_warned",   # once-per-path warning dedup, tiny, harmless
    "_debounce_timestamps",  # qc: none
}

_ASSIGN_RE = re.compile(
    r"^(_[A-Za-z0-9_]+)\s*(?::[^=]+)?=\s*"
    r"(?:\{\}|OrderedDict\(\)|dict\(\)|set\(\))\s*$",
    re.MULTILINE,
)


class TestCacheInventory:
    def test_every_module_level_cache_is_covered(self):
        uncovered = []
        for rel in WATCHED_MODULES:
            src = (PKG / rel).read_text()
            for m in _ASSIGN_RE.finditer(src):
                name = m.group(1)
                if name not in COVERED_OR_EXEMPT:
                    uncovered.append(f"{rel}::{name}")
        assert not uncovered, (
            "Module-level cache(s) not in the covered inventory: "
            f"{uncovered}. Wire each into clear_all_loader_caches (run "
            "boundaries) and scripts/perf/instrument.reset_caches (cold "
            "cells), then add it to COVERED_OR_EXEMPT with a comment."
        )

    def test_run_boundary_reset_actually_empties_the_big_ones(self, tmp_path):
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.core.utils import classification_loaders as cl
        from nanometa_live.core.utils import seqkit_batch_cache as sbc
        from nanometa_live.core.utils import report_accumulation as ra

        loader_utils._kraken_cache["k"] = (0.0, None)
        cl._report_frame_cache[("p", 1, 1)] = None
        cl._frame_sizes[("p", 1, 1)] = 1
        sbc._cache[("p", 1, 1)] = None
        ra._sample_accum[("d", "s")] = ((), {}, [])
        loader_utils.clear_all_loader_caches()
        assert not loader_utils._kraken_cache
        assert not cl._report_frame_cache and not cl._frame_sizes
        assert not sbc._cache
        assert not ra._sample_accum
