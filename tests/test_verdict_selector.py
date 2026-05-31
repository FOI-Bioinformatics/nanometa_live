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
