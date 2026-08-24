"""
Unit tests for the pure clinical verdict-banner state machine,
``dashboard_helpers.select_verdict`` (extracted from update_verdict_banner).

This is the safety-critical decision that tells an operator whether action is
required. The callback now only gathers inputs (file I/O) and renders; every
branch of the decision lives here and is exercised in isolation. The tests
assert the exact precedence the original callback encoded:

    no-config -> starting -> data-driven (action/monitoring/all-clear)
    -> running-no-data -> standby

plus the threat-level classification and the subtitle text.
"""

import pytest

from nanometa_live.app.tabs.dashboard_helpers import (
    VerdictDescriptor,
    _action_required_subtitle,
    _classify_dangerous,
    select_verdict,
)

pytestmark = pytest.mark.unit


# Sensible defaults; each test overrides only what it exercises.
BASE = dict(
    has_config=True,
    pipeline_running=False,
    overall_status_starting=False,
    main_dir_available=True,
    kraken_has_data=True,
    dangerous=[],
    n_watched=5,
    validation_has_results=True,
)


def verdict(**overrides):
    return select_verdict(**{**BASE, **overrides})


class TestNoConfig:
    def test_no_config_running_is_screening(self):
        d = verdict(has_config=False, pipeline_running=True)
        assert d.state == "SCREENING"
        assert d.icon_extra_class == "spin"

    def test_no_config_idle_is_standby(self):
        d = verdict(has_config=False, pipeline_running=False)
        assert d.state == "STANDBY"

    def test_no_config_ignores_data(self):
        # Even with dangerous hits present, no config short-circuits first.
        d = verdict(has_config=False, pipeline_running=False,
                    dangerous=[{"threat_level": "critical"}])
        assert d.state == "STANDBY"


class TestStartingPrecedence:
    def test_starting_beats_data(self):
        # "starting" must win even when Kraken data with a critical hit exists.
        d = verdict(overall_status_starting=True,
                    dangerous=[{"threat_level": "critical"}])
        assert d.state == "SCREENING"

    def test_starting_beats_standby(self):
        d = verdict(overall_status_starting=True, main_dir_available=False,
                    kraken_has_data=False)
        assert d.state == "SCREENING"


class TestActionRequired:
    @pytest.mark.parametrize("level", ["critical", "high", "high_risk"])
    def test_any_escalated_hit_triggers_action(self, level):
        d = verdict(dangerous=[{"threat_level": level}])
        assert d.state == "ACTION_REQUIRED"
        assert d.title == "ACTION REQUIRED"
        assert d.needs_attribution is True
        assert d.show_icon_mobile is True
        assert d.bg_color == "#f8d7da"

    def test_subtitle_counts_and_validation_note(self):
        d = verdict(dangerous=[{"threat_level": "critical"},
                               {"threat_level": "high"}],
                    n_watched=9, validation_has_results=False)
        assert "2 of 9 watched pathogens above alert threshold" in d.subtitle
        assert "pending confirmatory validation" in d.subtitle

    def test_subtitle_omits_note_when_validated(self):
        d = verdict(dangerous=[{"threat_level": "critical"}],
                    validation_has_results=True)
        assert "pending confirmatory validation" not in d.subtitle


class TestMonitoring:
    def test_non_escalated_hit_is_monitoring(self):
        # A watchlist hit that is neither critical nor high-risk.
        d = verdict(dangerous=[{"threat_level": "moderate"}])
        assert d.state == "MONITORING"
        assert d.title == "MONITORING"
        assert d.needs_attribution is False
        assert d.bg_color == "#fff3cd"

    def test_missing_threat_level_is_monitoring(self):
        # An entry with no threat_level key is a hit but not escalated.
        d = verdict(dangerous=[{"taxid": 1280}])
        assert d.state == "MONITORING"


class TestAllClear:
    def test_no_hits_is_all_clear(self):
        d = verdict(dangerous=[], n_watched=7)
        assert d.state == "ALL_CLEAR"
        assert d.title == "ALL CLEAR"
        assert "0 of 7 watched pathogens" in d.subtitle
        assert d.bg_color == "#d4edda"


class TestNoData:
    def test_dir_present_no_data_running_is_screening(self):
        d = verdict(kraken_has_data=False, pipeline_running=True)
        assert d.state == "SCREENING"

    def test_dir_present_no_data_idle_is_standby(self):
        d = verdict(kraken_has_data=False, pipeline_running=False)
        assert d.state == "STANDBY"

    def test_no_dir_running_is_standby(self):
        # No results directory: STANDBY even while running, matching the
        # original (the SCREENING-on-empty branch was gated on a valid dir).
        d = verdict(main_dir_available=False, kraken_has_data=False,
                    pipeline_running=True)
        assert d.state == "STANDBY"

    def test_no_dir_idle_is_standby(self):
        d = verdict(main_dir_available=False, kraken_has_data=False,
                    pipeline_running=False)
        assert d.state == "STANDBY"


class TestClassifyDangerous:
    def test_buckets(self):
        dangerous = [
            {"threat_level": "critical"},
            {"threat_level": "high"},
            {"threat_level": "high_risk"},
            {"threat_level": "moderate"},
            {"taxid": 1},  # no level
        ]
        critical, high_risk = _classify_dangerous(dangerous)
        assert len(critical) == 1
        assert len(high_risk) == 2  # high + high_risk
        # moderate / no-level are in neither escalated bucket.

    def test_empty(self):
        assert _classify_dangerous([]) == ([], [])


class TestActionSubtitleHelper:
    def test_validated(self):
        assert _action_required_subtitle(3, 10, True) == (
            "3 of 10 watched pathogens above alert threshold"
        )

    def test_unvalidated_appends_note(self):
        out = _action_required_subtitle(1, 4, False)
        assert out.endswith("pending confirmatory validation")


class TestDescriptorShape:
    def test_returns_descriptor_instances(self):
        # Every branch returns a VerdictDescriptor with the full field set.
        for kw in (
            dict(has_config=False),
            dict(overall_status_starting=True),
            dict(dangerous=[{"threat_level": "critical"}]),
            dict(dangerous=[{"threat_level": "moderate"}]),
            dict(dangerous=[]),
            dict(kraken_has_data=False, pipeline_running=True),
            dict(main_dir_available=False, kraken_has_data=False),
        ):
            d = verdict(**kw)
            assert isinstance(d, VerdictDescriptor)
            assert d.icon and d.icon_color and d.title and d.bg_color
            assert d.border_color


class TestNothingWatched:
    """The case where no watchlist is active at all.

    Found on 2026-07-28 by opening the dashboard against a real results tree
    with ``--main_dir`` and no configured watchlist. The banner rendered a
    green shield and the word ALL CLEAR while the Organisms tab, one click
    away, listed Francisella tularensis -- an HHS Tier 1 select agent -- as
    the most abundant organism at 54.2% of all reads (34,103 of them).

    ``select_verdict`` has no branch for ``n_watched == 0``: an empty
    ``dangerous`` list falls through to ALL CLEAR regardless of whether it is
    empty because 116 organisms were screened and none exceeded threshold, or
    because nothing was screened at all. Those are opposite situations and the
    banner cannot currently tell them apart. The subtitle does read "0 of 0",
    but it is the fine print under a green all-clear headline.

    Every existing test in this file passed n_watched as 5, 7 or 9, which is
    why the case was never noticed.

    Fixed 2026-07-28: select_verdict now returns a distinct NOT_SCREENED state
    (amber, "No watchlist active") before the ALL CLEAR return.
    """

    def test_zero_watched_is_not_reported_as_all_clear(self):
        d = verdict(dangerous=[], n_watched=0)
        assert d.state != "ALL_CLEAR", (
            "with no watchlist loaded the dashboard announces ALL CLEAR, which "
            "asserts a negative screening result that was never performed"
        )

    def test_a_populated_watchlist_with_no_hits_is_still_all_clear(self):
        """The genuine all-clear must keep working -- this is the contrast."""
        d = verdict(dangerous=[], n_watched=116)
        assert d.state == "ALL_CLEAR"
        assert "116" in d.subtitle


class TestAllClearRequiresEnoughReadsToMeanIt:
    """ALL CLEAR must mean something was screened, not that a report existed.

    select_verdict took no read-depth input, and ``kraken_has_data`` is set
    from ``not kraken_df.empty`` (dashboard_tab.py) -- the report having ROWS,
    not reads. So a sample whose QC produced nothing rendered

        ALL CLEAR - 0 of 116 watched pathogens above alert threshold

    identically to a sample with 34,000 reads and no hits. That was the end of
    the chain in tests/test_manifest_failed_sample.py: an unreadable FASTQ,
    absorbed by error isolation, reported as success, listed in the manifest,
    offered in the selector -- and declared clear.

    Fixed 2026-07-29 by passing the depth in and adding INSUFFICIENT READS.

    The floor is DEFAULT_LOW_READ_FLOOR (50), anchored to the existing
    ``min_reads_for_validation`` default: if a detection needs 50 reads to be
    worth confirming, an absence measured over fewer is not worth reporting as
    clear. The message additionally names the operator's own highest alert
    threshold when the sample is shallower than it, because that case is
    decidable rather than a judgement -- even if every read were one organism,
    it could not reach that threshold.
    """

    def test_zero_reads_is_not_an_all_clear(self):
        d = verdict(dangerous=[], n_watched=116, total_reads=0)
        assert d.state == "INSUFFICIENT_READS"
        assert "No reads were analysed" in d.subtitle

    def test_a_shallow_sample_is_not_an_all_clear(self):
        d = verdict(dangerous=[], n_watched=116, total_reads=3)
        assert d.state == "INSUFFICIENT_READS"

    def test_the_message_states_the_actual_depth(self):
        """"Too few" is only actionable if the operator can see how few."""
        d = verdict(dangerous=[], n_watched=116, total_reads=3)
        assert "3 reads" in d.subtitle, (
            f"the operator cannot judge the result without the number: "
            f"{d.subtitle!r}"
        )

    def test_it_names_the_threshold_that_could_not_be_reached(self):
        d = verdict(dangerous=[], n_watched=116, total_reads=3,
                    highest_alert_threshold=25)
        assert "25" in d.subtitle and "cannot reach" in d.subtitle, (
            f"when the depth is below the highest alert threshold that is a "
            f"decidable fact and worth stating: {d.subtitle!r}"
        )

    def test_it_is_not_styled_as_a_clear_result(self):
        """Wording alone is not enough; a green banner reads as reassurance."""
        d = verdict(dangerous=[], n_watched=116, total_reads=3)
        assert d.bg_color != "#d4edda", "styled the same green as ALL CLEAR"

    def test_a_deep_sample_still_reads_as_clear(self):
        d = verdict(dangerous=[], n_watched=116, total_reads=34141)
        assert d.state == "ALL_CLEAR"
        assert "34,141 reads" in d.subtitle, (
            "the genuine all-clear should state the depth it is based on, so "
            "it cannot be confused with a shallow one"
        )

    def test_unknown_depth_keeps_the_previous_behaviour(self):
        """None means "not determined", which must not be read as zero."""
        d = verdict(dangerous=[], n_watched=116, total_reads=None)
        assert d.state == "ALL_CLEAR"

    def test_a_detection_still_wins_over_shallow_depth(self):
        """A hit is a hit; low depth must not downgrade a real detection."""
        d = verdict(dangerous=[{"threat_level": "critical"}], n_watched=116,
                    total_reads=3)
        assert d.state == "ACTION_REQUIRED"


class TestTheDepthGateIsAggregateScoped:
    """What the INSUFFICIENT READS fix does and does not cover.

    The verdict banner is computed over ALL samples: dashboard_tab.py loads
    ``load_kraken_data(main_dir, "All Samples")`` and its callback does not
    take ``selected-sample`` as an input. The metric tiles ARE per-sample.

    So the depth gate fires when the WHOLE RUN is empty or shallow. It does
    not fire when one sample among several fails -- the more likely field
    case, one bad barcode out of 24. There the operator selecting the failed
    sample sees a banner reading ALL CLEAR (accurate for the run) above tiles
    reading 0 sequences analysed (accurate for the sample).

    That is deliberately NOT "fixed" by making the banner per-sample. The
    banner is a safety verdict over everything analysed: scoping it to the
    selection would hide a detection sitting in a sample the operator is not
    currently looking at, which is a worse failure than the confusion it would
    resolve.

    These tests pin the scope so the gate is not later mistaken for per-sample
    coverage.
    """

    def test_the_gate_fires_on_an_empty_run(self):
        d = verdict(dangerous=[], n_watched=116, total_reads=0)
        assert d.state == "INSUFFICIENT_READS"

    def test_the_gate_does_not_fire_when_the_aggregate_is_deep(self):
        """One failed sample among many leaves the aggregate healthy.

        The banner stays ALL CLEAR, which is correct for the run. The
        operator learns about the failed sample from the per-sample tiles,
        not from here.
        """
        d = verdict(dangerous=[], n_watched=116, total_reads=34141)
        assert d.state == "ALL_CLEAR", (
            "the aggregate verdict should not be downgraded because one "
            "constituent sample was empty; that would suppress the run-level "
            "result the banner exists to give"
        )

    def test_a_detection_anywhere_still_reaches_the_banner(self):
        """The reason the banner stays aggregate-scoped."""
        d = verdict(dangerous=[{"threat_level": "critical"}], n_watched=116,
                    total_reads=34141)
        assert d.state == "ACTION_REQUIRED"


class TestPipelineError:
    """A dead pipeline must never render as a clean result.

    Round-3 finding: a pipeline killed at 40% of its samples left
    main_dir_available=True, kraken_has_data=True, dangerous=[] -- a green
    ALL CLEAR over a run that processed less than half its data. The
    header pill went red; the banner operators are trained on stayed
    green. pipeline_error is derived from backend-status
    (pipeline_status == "error"), which a user-initiated stop clears, so
    a deliberate Stop can never trip this state.
    """

    def test_error_beats_all_clear(self):
        d = verdict(pipeline_error=True)
        assert d.state == "PIPELINE_ERROR"

    def test_error_banner_is_not_green(self):
        d = verdict(pipeline_error=True)
        assert d.bg_color != "#d4edda", "error must not reassure"

    def test_error_subtitle_says_results_are_partial(self):
        d = verdict(pipeline_error=True)
        assert "before the failure" in d.subtitle

    def test_error_detail_is_carried(self):
        d = verdict(pipeline_error=True,
                    pipeline_error_detail="Nextflow exited with code 137")
        assert "137" in d.subtitle

    def test_detection_still_wins_over_error(self):
        # Never suppress a hit: ACTION REQUIRED outranks the error state,
        # with the failure noted so the operator knows coverage is partial.
        d = verdict(pipeline_error=True,
                    dangerous=[{"threat_level": "critical"}])
        assert d.state == "ACTION_REQUIRED"
        assert "pipeline error" in d.subtitle.lower()

    def test_subthreshold_still_shows_over_error(self):
        d = verdict(pipeline_error=True,
                    subthreshold=[{"name": "X", "threat_level": "high"}])
        assert d.state == "MONITORING"
        assert "pipeline error" in d.subtitle.lower()

    def test_error_beats_not_screened(self):
        d = verdict(pipeline_error=True, n_watched=0)
        assert d.state == "PIPELINE_ERROR"

    def test_error_beats_insufficient_reads(self):
        d = verdict(pipeline_error=True, total_reads=1)
        assert d.state == "PIPELINE_ERROR"

    def test_error_with_no_data_is_not_standby(self):
        # Crash before any output: the old flow fell to STANDBY, reading
        # as "never started".
        d = verdict(pipeline_error=True, main_dir_available=False,
                    kraken_has_data=False)
        assert d.state == "PIPELINE_ERROR"

    def test_no_error_leaves_every_state_unchanged(self):
        assert verdict(pipeline_error=False).state == "ALL_CLEAR"
        assert verdict().state == "ALL_CLEAR"


class TestResultsDirLost:
    """A results directory that vanishes mid-run is not STANDBY.

    Round-3 finding: unplugging the results volume degraded the dashboard
    to grey STANDBY with zeroed tiles -- indistinguishable from "no run
    ever happened". results_dir_lost is set by the callback when the dir
    was previously fingerprinted non-empty and is now absent.
    """

    def test_lost_dir_is_not_standby(self):
        d = verdict(results_dir_lost=True, main_dir_available=False,
                    kraken_has_data=False)
        assert d.state == "RESULTS_UNAVAILABLE"

    def test_lost_dir_while_running_is_still_lost(self):
        d = verdict(results_dir_lost=True, main_dir_available=False,
                    kraken_has_data=False, pipeline_running=True)
        assert d.state == "RESULTS_UNAVAILABLE"

    def test_lost_dir_is_not_green_or_grey(self):
        d = verdict(results_dir_lost=True, main_dir_available=False,
                    kraken_has_data=False)
        assert d.bg_color not in ("#d4edda", "#f8f9fa")

    def test_available_dir_ignores_the_flag(self):
        # The flag only matters when the dir is actually gone; a caller
        # that raced (flag stale, dir back) must not hide live data.
        d = verdict(results_dir_lost=True)
        assert d.state == "ALL_CLEAR"

    def test_absent_flag_keeps_standby(self):
        d = verdict(main_dir_available=False, kraken_has_data=False)
        assert d.state == "STANDBY"


class TestStaleSamplesClause:
    """When samples are serving last-good fallback data, the verdict
    subtitle says so instead of presenting frozen numbers as live."""

    def test_stale_count_appends_clause(self):
        d = verdict(stale_samples=3)
        assert d.state == "ALL_CLEAR"
        assert "3 sample" in d.subtitle and "stale" in d.subtitle

    def test_zero_stale_appends_nothing(self):
        d = verdict(stale_samples=0)
        assert "stale" not in d.subtitle

    def test_detection_subtitle_carries_stale_clause_too(self):
        d = verdict(dangerous=[{"threat_level": "critical"}],
                    stale_samples=2)
        assert d.state == "ACTION_REQUIRED"
        assert "stale" in d.subtitle
