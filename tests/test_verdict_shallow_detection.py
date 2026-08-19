"""An alarm raised on almost no reads must say so.

The verdict logic already refuses to call a NEGATIVE result over shallow depth
(INSUFFICIENT READS), and ALL CLEAR states the depth it rests on -- its
docstring says why: "so a negative over 34,000 reads cannot be confused at a
glance with one over 60".

The detection path had no equivalent. A real Bioshield negative control
carried 6 Francisella tularensis reads out of 11 total; F. tularensis is
CRITICAL with alert_threshold 5, so the verdict was ACTION REQUIRED, worded
identically to the same run's genuine 34,096-read detection in barcode11.

A detection still outranks depth -- suppressing an alarm because the run was
shallow is the one thing this tool must never do. What changes is that the
banner now carries the depth, so an operator can tell a 34,096-read finding
from a 6-of-11-read one without leaving the page.
"""

from __future__ import annotations

import pytest

from nanometa_live.app.tabs.dashboard_helpers import (
    DEFAULT_LOW_READ_FLOOR, select_verdict,
)

pytestmark = pytest.mark.unit

CRITICAL_HIT = [{
    "name": "Francisella tularensis", "taxid": 263, "reads": 6,
    "threat_level": "critical", "alert_threshold": 5,
}]


def _verdict(total_reads, dangerous=CRITICAL_HIT, **kw):
    return select_verdict(
        has_config=True, pipeline_running=False, overall_status_starting=False,
        main_dir_available=True, kraken_has_data=True,
        dangerous=dangerous, n_watched=35, validation_has_results=False,
        total_reads=total_reads, **kw
    )


class TestTheAlarmStillFires:
    @pytest.mark.parametrize("depth", [1, 11, 49, 100, 34141])
    def test_a_detection_is_never_suppressed_by_depth(self, depth):
        """The non-negotiable half."""
        assert _verdict(depth).state == "ACTION_REQUIRED"

    def test_unknown_depth_still_raises_the_alarm(self):
        assert _verdict(None).state == "ACTION_REQUIRED"


class TestTheAlarmCarriesItsDepth:
    def test_a_shallow_detection_says_how_shallow(self):
        """The real case: 6 of 11 reads on a negative control.

        Pass the floor explicitly: 11 reads was shallow against the old
        default of 50, and the point of the test is the wording, not which
        number the product currently ships.
        """
        sub = _verdict(11, low_read_floor=50).subtitle

        assert "11" in sub, (
            f"an alarm raised on 11 total reads does not say so: {sub!r}"
        )

    def test_a_well_powered_detection_is_not_cluttered(self):
        """34,096 reads needs no caveat; adding one would dilute the signal."""
        sub = _verdict(34141).subtitle

        assert "34,141" not in sub
        assert "only" not in sub.lower()

    @pytest.mark.parametrize("depth", [1, DEFAULT_LOW_READ_FLOOR - 1])
    def test_every_depth_below_the_floor_is_qualified(self, depth):
        assert "only" in _verdict(depth).subtitle.lower()

    @pytest.mark.parametrize("depth", [DEFAULT_LOW_READ_FLOOR, 1000])
    def test_at_or_above_the_floor_no_qualifier(self, depth):
        assert "only" not in _verdict(depth).subtitle.lower()

    def test_unknown_depth_adds_no_claim(self):
        """None means undetermined; it must not read as shallow."""
        assert "only" not in (_verdict(None).subtitle or "").lower()

    def test_the_threshold_count_survives(self):
        """The existing wording must not be lost to the new clause."""
        sub = _verdict(11, low_read_floor=50).subtitle

        assert "1 of 35" in sub
        assert "alert threshold" in sub

    def test_pending_validation_is_still_reported(self):
        assert "pending confirmatory validation" in _verdict(11).subtitle


class TestMonitoringToo:
    def test_a_moderate_detection_on_shallow_depth_is_qualified(self):
        """MONITORING is a detection as well, and rests on the same reads."""
        moderate = [{
            "name": "Some organism", "taxid": 1, "reads": 6,
            "threat_level": "moderate", "alert_threshold": 5,
        }]
        v = _verdict(11, dangerous=moderate, low_read_floor=50)

        assert v.state == "MONITORING"
        assert "11" in v.subtitle, (
            f"MONITORING on 11 reads does not state the depth: {v.subtitle!r}"
        )
