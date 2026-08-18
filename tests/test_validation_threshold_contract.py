"""The two repos must agree on what "confirmed" means.

nanometanf writes a ``validation_status`` into validation_results.json and
validation_summary.tsv; nanometa_live derives its own via
``ValidationResult.determine_status``. Both are shipped to the operator --
the raw pipeline files are copied into the exported bundle
(``report_generator._RAW_SUBDIRS``) -- so when the two definitions drift the
artefact contradicts the dashboard.

They did drift. The pipeline confirmed on hit rate and identity alone, so on
the 2026-08-18 Bioshield run a single index-hopped read covering 0.07% of a
genome was written out as a *confirmed* detection of a Tier 1 select agent
while the dashboard said PARTIAL. Nothing checked, which is why nobody
noticed.

This test is the check. It pins the floors on this side and, when a
nanometanf checkout is reachable, asserts the pipeline declares the same
numbers. Mirrors the NANOMETANF_PATH pattern in test_container_inventory.py.
"""

import os
import re
from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    MIN_BREADTH_FOR_CONFIRMED,
    MIN_READS_FOR_CONFIRMED,
    ValidationResult,
    ValidationStatus,
)

pytestmark = pytest.mark.unit

#: The agreed contract. Changing either side means changing both, and this
#: constant, deliberately: the edit should be impossible to make by accident.
CONTRACT_MIN_READS = 10
CONTRACT_MIN_BREADTH = 0.05

_NANOMETANF_PATH = Path(
    os.environ.get("NANOMETANF_PATH", str(Path.home() / "Code" / "nanometanf"))
)
_CONFIG = _NANOMETANF_PATH / "nextflow.config"


def _pipeline_param(name):
    """Read a param default out of nanometanf's nextflow.config."""
    text = _CONFIG.read_text()
    match = re.search(rf"^\s*{name}\s*=\s*([0-9.]+)", text, re.MULTILINE)
    assert match, f"{name} not declared in {_CONFIG}"
    return float(match.group(1))


class TestThisSideHoldsTheContract:
    def test_read_floor(self):
        assert MIN_READS_FOR_CONFIRMED == CONTRACT_MIN_READS

    def test_breadth_floor(self):
        assert MIN_BREADTH_FOR_CONFIRMED == CONTRACT_MIN_BREADTH


@pytest.mark.skipif(
    not _CONFIG.is_file(),
    reason="nanometanf checkout not present (set NANOMETANF_PATH to enable)",
)
class TestPipelineDeclaresTheSameFloors:
    def test_min_reads_matches(self):
        assert _pipeline_param("validation_min_reads") == CONTRACT_MIN_READS, (
            "nanometanf and nanometa_live disagree on the read floor for "
            "'confirmed'; the exported bundle would contradict the dashboard")

    def test_min_breadth_matches(self):
        assert _pipeline_param("validation_min_breadth") == CONTRACT_MIN_BREADTH, (
            "nanometanf and nanometa_live disagree on the breadth floor for "
            "'confirmed'")

    def test_modules_actually_apply_the_floors(self):
        """Declaring a param is not applying it."""
        blast = (_NANOMETANF_PATH / "modules" / "local" / "blastn_validation"
                 / "main.nf").read_text()
        mm2 = (_NANOMETANF_PATH / "modules" / "local" / "minimap2_validation"
               / "main.nf").read_text()
        assert "hits >= min_reads" in blast, (
            "blastn_validation declares no read floor in its status rule")
        assert "hits >= min_reads" in mm2, (
            "minimap2_validation declares no read floor in its status rule")
        assert "genome_breadth >= min_breadth" in mm2, (
            "minimap2_validation ignores genome breadth in its status rule")
        assert "concentrated" in mm2, (
            "the amplicon exemption is missing: a PCR product covers a sliver "
            "of the genome by design and must remain confirmable")


class TestVerdictsAgreeOnTheRealBioshieldRows:
    """The five (sample, taxid) pairs that exposed the drift.

    Measured on the 2026-08-18 run. The pipeline said "confirmed" for all
    five; only the first two should be.
    """

    CASES = [
        # reads, identity, breadth, expect_confirmed
        (28308, 99.81, 0.9814, True),    # barcode11 holarctica -- real
        (5294, 99.89, 0.7172, True),     # barcode11 species    -- real
        (5, 99.92, 0.0123, False),       # barcode16 holarctica -- carryover
        (1, 99.89, 0.0007, False),       # barcode16 species    -- carryover
        (1, 99.94, 0.0015, False),       # barcode14 holarctica -- carryover
    ]

    @pytest.mark.parametrize("reads,identity,breadth,expect_confirmed", CASES)
    def test_gui_verdict(self, reads, identity, breadth, expect_confirmed):
        r = ValidationResult(
            sample_id="s", taxid=1, total_reads=reads, validated_reads=reads,
            percent_validated=100.0, percent_identity_mean=identity,
            validation_method="minimap2", genome_breadth=breadth,
            coverage_concentrated=False,
        )
        r.status = r.determine_status()
        assert (r.status == ValidationStatus.CONFIRMED) is expect_confirmed

    def test_amplicon_survives_the_breadth_floor(self):
        # 0.08% breadth but concentrated: a PCR product, not carryover.
        r = ValidationResult(
            sample_id="s", taxid=1, total_reads=40, validated_reads=40,
            percent_validated=100.0, percent_identity_mean=99.5,
            validation_method="minimap2", genome_breadth=0.0008,
            coverage_concentrated=True,
        )
        r.status = r.determine_status()
        assert r.status == ValidationStatus.CONFIRMED
