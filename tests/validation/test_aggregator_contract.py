"""Cross-repo contract test (Layer D).

A golden ``validation_results.json`` shaped exactly like nanometanf's
``AGGREGATE_VALIDATION_RESULTS`` process emits (see
``modules/local/aggregate_validation_results/main.nf``) must be fully consumed
by the GUI's ``ValidationParser.parse_nanometanf_aggregate_json``. A field
rename or shape change in either repo breaks this test, which is the seam where
the "users don't see BLAST validation" class of bug originates.

The golden file is committed alongside this test so it is reviewed when the
upstream schema changes, rather than regenerated silently.
"""

import shutil
from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationStatus,
)

pytestmark = pytest.mark.unit

_GOLDEN = Path(__file__).parent / "fixtures" / "aggregator_golden_validation_results.json"


@pytest.fixture
def golden_results_dir(tmp_path):
    """Lay the golden aggregate JSON into a results/validation/ tree."""
    vdir = tmp_path / "validation"
    vdir.mkdir(parents=True)
    shutil.copy(_GOLDEN, vdir / "validation_results.json")
    return tmp_path


def test_parser_consumes_every_documented_field(golden_results_dir):
    parser = ValidationParser(str(golden_results_dir))
    results = parser.get_validation_results()

    # 1773 'both' -> blast + minimap2 (2), 1280 blast (1), 1639 minimap2 (1) = 4
    assert len(results) == 4

    by_key = {(r.sample_id, r.taxid, r.validation_method): r for r in results}

    # --- BLAST entry with minimap2 folded in (the 'both' shape) ---
    blast = by_key[("barcode01", 1773, "blast")]
    assert blast.species == "Mycobacterium tuberculosis"
    assert blast.total_reads == 3500          # kraken_reads
    assert blast.validated_reads == 3200      # blast_hits
    assert blast.percent_validated == pytest.approx(91.4, abs=0.1)  # hit_rate*100
    assert blast.percent_identity_mean == pytest.approx(97.5)        # avg_identity
    assert blast.status == ValidationStatus.CONFIRMED

    # The minimap2 fold-in fields expand into a separate minimap2 result.
    mm2_fold = by_key[("barcode01", 1773, "minimap2")]
    assert mm2_fold.validated_reads == 3300   # minimap2_mapped
    assert mm2_fold.percent_identity_mean == pytest.approx(98.0)  # minimap2_identity

    # --- BLAST-only entry ---
    blast_only = by_key[("barcode01", 1280, "blast")]
    assert blast_only.validated_reads == 1800
    # Status is recomputed from the data (1800/2800 = 64% hit rate -> partial),
    # not copied from the JSON's validation_status string.
    assert blast_only.status == ValidationStatus.PARTIAL

    # --- minimap2-only entry: ref_name / ref_length must survive ---
    mm2 = by_key[("barcode02", 1639, "minimap2")]
    assert mm2.species == "Listeria monocytogenes"
    assert mm2.validated_reads == 3900        # mapped_reads
    assert mm2.reference_accession == "NC_003210.1"   # ref_name
    assert mm2.reference_length == 2944528            # ref_length
    assert mm2.avg_mapq == pytest.approx(56.0)
    assert mm2.status == ValidationStatus.CONFIRMED


def test_both_methods_present_per_validated_taxid(golden_results_dir):
    """D1: the 'both' taxid surfaces under BOTH methods so neither sub-tab
    silently drops it."""
    results = ValidationParser(str(golden_results_dir)).get_validation_results()
    methods_1773 = {r.validation_method for r in results if r.taxid == 1773}
    assert methods_1773 == {"blast", "minimap2"}
