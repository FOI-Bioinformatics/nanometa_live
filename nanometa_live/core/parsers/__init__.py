"""
Parsers for nanometanf and workflow outputs.

The legacy ``NanometanfOutputParser`` and ``RealtimeMonitor`` were
removed on 2026-04-30. They had no production callers and used a
divergent column-name contract (``percent``, ``reads_clade``,
``reads_taxon``) compared to the active loaders in
``nanometa_live.core.utils.classification_loaders`` (``%``,
``cumul_reads``, ``reads``). Tests that previously instantiated the
parser have been ported to ``load_kraken_data``.
"""

from .blast_validation_parser import (
    BlastValidationParser,
    ValidationResult,
    ValidationStatus,
    generate_mock_validation_data,
)
from .paf_coverage_parser import (
    CoverageData,
    parse_paf_coverage,
)

__all__ = [
    'BlastValidationParser',
    'ValidationResult',
    'ValidationStatus',
    'generate_mock_validation_data',
    'CoverageData',
    'parse_paf_coverage',
]
