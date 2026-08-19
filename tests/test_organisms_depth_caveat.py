"""The Organisms panel must qualify a negative it has not earned.

The Dashboard banner gates on read depth: below ``low_read_floor`` it reports
INSUFFICIENT READS rather than ALL CLEAR, because an absence measured over
almost no reads is not evidence of absence. The Organisms tab's watched-species
panel split purely on ``detected`` and inherited none of that, so a run of one
read rendered:

    Watched Organisms 0/35
    Not Detected (35)

identically to a properly-powered negative. An operator who opens Organisms
without first reading the Dashboard banner -- or who screenshots or exports
just this panel -- sees an unqualified all-clear.

The caveat is deliberately additive: the not-detected list still renders, and
nothing is hidden. What changes is that the panel stops presenting an
undetermined result as a negative one.
"""

from __future__ import annotations

import pytest

from nanometa_live.app.tabs.dashboard_helpers import DEFAULT_LOW_READ_FLOOR
from nanometa_live.app.tabs.main_tab_helpers import not_detected_caveat

pytestmark = pytest.mark.unit


class TestShallowDepthIsQualified:
    @pytest.mark.parametrize("depth", [0, 1, DEFAULT_LOW_READ_FLOOR - 1])
    def test_a_caveat_is_returned_below_the_floor(self, depth):
        caveat = not_detected_caveat(total_reads=depth, n_not_detected=35)

        assert caveat, (
            f"{depth} reads produced no caveat; the panel presents an "
            f"unqualified negative it has not earned"
        )

    def test_the_caveat_states_the_actual_depth(self):
        """A vague warning is easy to dismiss; a number is not."""
        caveat = not_detected_caveat(total_reads=1, n_not_detected=35)

        assert "1" in caveat
        assert "read" in caveat.lower()

    def test_it_does_not_claim_the_organisms_are_absent(self):
        """The wording is the whole point of this fix."""
        caveat = not_detected_caveat(total_reads=1, n_not_detected=35)

        lowered = caveat.lower()
        assert "not detected" not in lowered, (
            "the caveat repeats the claim it exists to qualify"
        )


class TestAdequateDepthIsUnchanged:
    @pytest.mark.parametrize(
        "depth", [DEFAULT_LOW_READ_FLOOR, DEFAULT_LOW_READ_FLOOR + 1, 100_000]
    )
    def test_no_caveat_at_or_above_the_floor(self, depth):
        assert not_detected_caveat(total_reads=depth, n_not_detected=35) is None

    def test_unknown_depth_produces_no_caveat(self):
        """None means "not determined" and must not be read as zero.

        Treating unknown as zero would put a false shallow-depth warning on
        every caller that cannot compute a total.
        """
        assert not_detected_caveat(total_reads=None, n_not_detected=35) is None

    def test_nothing_to_qualify_produces_no_caveat(self):
        """With no not-detected entries there is no negative being claimed."""
        assert not_detected_caveat(total_reads=1, n_not_detected=0) is None

    def test_the_floor_is_configurable_and_matches_the_dashboard(self):
        """Both surfaces anchor to min_reads_for_validation."""
        assert not_detected_caveat(
            total_reads=80, n_not_detected=5, low_read_floor=100
        )
        assert not_detected_caveat(
            total_reads=80, n_not_detected=5, low_read_floor=50
        ) is None
