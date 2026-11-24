"""The Validation tab's criteria line states the rules that decide a status.

It said "Minimap2 also requires alignment MAPQ >= 10" as if MAPQ decided the
status -- an organism at average MAPQ 3 still read CONFIRMED -- and left out
the two rules that do downgrade a Confirmed: fewer than 10 validated reads
and, for coverage results, genome breadth under 5% (live test 2026-11-24).
"""

import pytest

from nanometa_live.app.tabs.validation_tab_helpers import _format_criteria_text
from nanometa_live.core.parsers.blast_validation_parser import (
    MIN_BREADTH_FOR_CONFIRMED,
    MIN_READS_FOR_CONFIRMED,
)

pytestmark = pytest.mark.unit


def test_states_the_read_and_breadth_rules():
    text = _format_criteria_text({})
    assert f"at least {MIN_READS_FOR_CONFIRMED} validated reads" in text
    assert f"{MIN_BREADTH_FOR_CONFIRMED * 100:.0f}% of the reference genome" in text


def test_mapq_is_described_as_a_counting_filter():
    text = _format_criteria_text({"minimap2_min_mapq": 20})
    assert "requires alignment MAPQ" not in text
    assert "MAPQ >= 20 are counted" in text
