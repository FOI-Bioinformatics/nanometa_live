"""Unit tests for the classification_confidence verdict."""

import pytest

from nanometa_live.core.parsers.blast_confidence import classification_confidence

pytestmark = pytest.mark.unit


def test_high_confidence_whole_genome():
    c = classification_confidence(
        mean_identity=98.0, coverage_breadth=0.7, subject_agreement=0.95,
        n_reads=500, is_concentrated=False,
    )
    assert c["level"] == "high"
    assert c["score"] >= 0.8


def test_low_confidence_ambiguous_subjects():
    c = classification_confidence(
        mean_identity=85.0, coverage_breadth=0.6, subject_agreement=0.3,
        n_reads=200, is_concentrated=False,
    )
    assert c["level"] == "low"


def test_amplicon_low_breadth_not_penalised():
    # An amplicon: tiny genome-wide breadth but strong identity + agreement.
    amp = classification_confidence(
        mean_identity=98.0, coverage_breadth=0.02, subject_agreement=0.95,
        n_reads=400, is_concentrated=True,
    )
    wgs = classification_confidence(
        mean_identity=98.0, coverage_breadth=0.02, subject_agreement=0.95,
        n_reads=400, is_concentrated=False,
    )
    # With breadth excluded, the amplicon scores higher than the same numbers
    # treated as whole-genome (where 2% breadth drags it down).
    assert amp["score"] > wgs["score"]
    assert amp["level"] == "high"
    assert any("amplicon" in r.lower() or "concentrated" in r.lower()
               for r in amp["reasons"])


def test_thin_read_support_capped_to_moderate():
    c = classification_confidence(
        mean_identity=99.0, coverage_breadth=0.8, subject_agreement=1.0,
        n_reads=5, is_concentrated=False,
    )
    # Strong numbers but only 5 reads -> cannot be "high".
    assert c["level"] != "high"


def test_zero_reads_is_low():
    c = classification_confidence(0, 0, 0, 0)
    assert c["level"] == "low"
    assert c["score"] == 0.0


def test_reasons_are_populated():
    c = classification_confidence(96.0, 0.5, 0.9, 100)
    assert isinstance(c["reasons"], list) and c["reasons"]
