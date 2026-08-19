"""A watchlist hit below its alert threshold is shown, and never behind green.

Measured on the MP02 dilution run (barcode03, 19,391 reads): *F. tularensis*
subsp. *holarctica* at 8 reads and *Bacillus anthracis* at 7 reads cleared the
discovery floor of 5 but not the alert threshold of 10. The Dashboard showed
neither -- no alert card, and a verdict that would read ALL CLEAR if nothing
else were present -- while the Organisms tab and the exported HTML report
both marked them DETECTED in red. One sample, three surfaces, three
different answers.

The rule adopted (operator decision, 2026-08-19): **show sub-threshold hits
everywhere, but never behind a green ALL CLEAR.** A detection the operator
configured a threshold for is still evidence; the threshold governs whether
it is an *alarm*, not whether it is *visible*. Green is reserved for a screen
that found nothing at all.

Two consequences pinned here:

- ``check_organisms_with_mapping`` can return the sub-threshold matches, so
  the Dashboard can render them instead of dropping them on the floor.
- ``select_verdict`` gains a ``subthreshold`` input: with no above-threshold
  hit but at least one below it, the verdict is amber MONITORING, never
  ALL_CLEAR. An above-threshold hit still wins outright, and a genuinely
  clean screen is still green.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.tabs.dashboard_helpers import select_verdict


def _verdict(dangerous=(), subthreshold=(), **kw):
    params = dict(
        has_config=True,
        pipeline_running=False,
        overall_status_starting=False,
        main_dir_available=True,
        kraken_has_data=True,
        dangerous=list(dangerous),
        subthreshold=list(subthreshold),
        n_watched=35,
        validation_has_results=False,
        total_reads=19_391,
    )
    params.update(kw)
    return select_verdict(**params)


HOLARCTICA = {
    "name": "Francisella tularensis subsp. holarctica", "taxid": 119857,
    "reads": 8, "threat_level": "critical", "threshold": 10,
}
ANTHRACIS = {
    "name": "Bacillus anthracis", "taxid": 1392, "reads": 7,
    "threat_level": "critical", "threshold": 10,
}
ABOVE = {
    "name": "Yersinia pestis", "taxid": 632, "reads": 493,
    "threat_level": "critical", "threshold": 10,
}


class TestNeverGreenOverEvidence:
    def test_a_subthreshold_hit_is_not_all_clear(self):
        v = _verdict(subthreshold=[HOLARCTICA])
        assert v.state != "ALL_CLEAR", (
            "8 reads of a Tier-1 select agent rendered as a green ALL CLEAR; "
            "the threshold decides whether it alarms, not whether it exists"
        )

    def test_it_is_the_amber_monitoring_state(self):
        assert _verdict(subthreshold=[HOLARCTICA]).state == "MONITORING"

    def test_the_subtitle_says_how_many_and_why_they_are_quiet(self):
        sub = _verdict(subthreshold=[HOLARCTICA, ANTHRACIS]).subtitle.lower()
        assert "2" in sub
        assert "threshold" in sub, (
            f"the operator is not told these sit below their alert "
            f"threshold: {sub!r}"
        )

    def test_the_organisms_are_named(self):
        v = _verdict(subthreshold=[HOLARCTICA])
        blob = f"{v.title} {v.subtitle}"
        assert "Francisella" in blob, (
            "a verdict that will not name the organism sends the operator "
            "hunting across tabs"
        )


class TestNothingElseChanges:
    def test_an_above_threshold_hit_still_wins(self):
        v = _verdict(dangerous=[ABOVE], subthreshold=[HOLARCTICA])
        assert v.state == "ACTION_REQUIRED"

    def test_a_genuinely_clean_screen_is_still_green(self):
        assert _verdict().state == "ALL_CLEAR"

    def test_shallow_depth_still_outranks_a_clean_screen(self):
        assert _verdict(total_reads=3, low_read_floor=10).state == "INSUFFICIENT_READS"

    def test_no_watchlist_is_still_not_screened(self):
        assert _verdict(n_watched=0).state == "NOT_SCREENED"

    def test_subthreshold_defaults_to_empty(self):
        # Callers that do not supply the new input keep the old behaviour.
        assert select_verdict(
            has_config=True, pipeline_running=False,
            overall_status_starting=False, main_dir_available=True,
            kraken_has_data=True, dangerous=[], n_watched=5,
            validation_has_results=False, total_reads=1000,
        ).state == "ALL_CLEAR"


class TestWatchlistReturnsSubThresholdMatches:
    """The matcher must be able to hand back what it filtered out."""

    def _manager_with_entry(self, threshold=10):
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager, WatchlistEntry,
        )
        from nanometa_live.core.config.pathogen_loader import ThreatLevel

        m = WatchlistManager()
        e = WatchlistEntry(taxid=1392, name="Bacillus anthracis",
                           threat_level=ThreatLevel.CRITICAL)
        e.alert_threshold = threshold
        e.enabled = True
        m._entries = {1392: e}
        m._name_index = {"bacillus anthracis": 1392}
        m._enabled_watchlists = set()
        return m

    ORGANISMS = [{"taxid": 1392, "name": "Bacillus anthracis", "reads": 7,
                  "abundance": 0.04}]

    def test_above_threshold_only_by_default(self):
        m = self._manager_with_entry()
        alerts = m.check_organisms_with_mapping(self.ORGANISMS)
        assert alerts == [], "7 reads is below the threshold of 10"

    def test_below_threshold_matches_are_available_on_request(self):
        m = self._manager_with_entry()
        below = m.check_organisms_with_mapping(
            self.ORGANISMS, below_threshold=True)
        assert len(below) == 1
        assert below[0]["reads"] == 7
        assert below[0]["threshold"] == 10
        assert below[0]["name"] == "Bacillus anthracis"

    def test_an_above_threshold_hit_is_not_returned_as_below(self):
        m = self._manager_with_entry(threshold=5)
        assert m.check_organisms_with_mapping(
            self.ORGANISMS, below_threshold=True) == []
