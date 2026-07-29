"""Readiness must not tell an operator to do what they have already done.

``_check_watchlist_active`` takes the active entries when they can be read and
falls back to the config when they cannot -- which happens whenever the
WatchlistManager singleton is empty, notably in a DiskcacheManager background
worker, the documented reason the entries snapshot Store exists at all.

The fallback read ``config["watchlist"]["enabled_watchlists"]``. The app never
writes that key: WatchlistManager._load_config_locked reads "enabled",
"builtin", "custom", "custom_files" and "overrides". So the branch was dead and
every undeterminable case reported

    No watchlist enabled - enable pathogens in the Watchlist & Preparation tab

for an operator whose watchlist was configured and loaded.

The direction is safe -- it under-claims screening rather than over-claiming it,
unlike the ALL CLEAR defects found elsewhere in this campaign -- but a readiness
panel that raises false alarms is one operators learn to skip, which costs the
true alarms too.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

pytestmark = pytest.mark.unit


def _check(config, active_entries):
    rc = ReadinessChecker.__new__(ReadinessChecker)
    return ReadinessChecker._check_watchlist_active(rc, config, active_entries)


class TestFallbackWhenStateCannotBeRead:
    """active_entries is None: the singleton was unreadable or empty."""

    @pytest.mark.parametrize("wl,expected,why", [
        ({"enabled": True, "builtin": ["cdc_bioterrorism"], "custom": []},
         True, "a configured builtin watchlist"),
        ({"enabled": True, "builtin": [], "custom": [{"name": "X", "taxid": 1}]},
         True, "a configured custom entry"),
        ({"enabled": True, "builtin": [], "custom": [], "custom_files": ["x.yaml"]},
         True, "a configured custom file"),
    ])
    def test_a_configured_watchlist_is_recognised(self, wl, expected, why):
        r = _check({"watchlist": wl}, None)
        assert r.passed is expected, (
            f"readiness reported {r.message!r} despite {why}; the operator is "
            f"told to enable pathogens they have already enabled"
        )
        assert "not yet loaded" in r.message.lower(), (
            f"the message should say the watchlist is configured but unread, "
            f"not assert a state: {r.message!r}"
        )

    def test_an_explicitly_disabled_watchlist_is_not_claimed_active(self):
        """enabled=False must win over the presence of names."""
        r = _check({"watchlist": {"enabled": False, "builtin": ["cdc_bioterrorism"]}}, None)
        assert r.passed is False

    def test_no_watchlist_at_all_still_reports_none(self):
        r = _check({"watchlist": {"enabled": True, "builtin": [], "custom": []}}, None)
        assert r.passed is False
        assert "No watchlist enabled" in r.message

    def test_missing_watchlist_config_reports_none(self):
        r = _check({}, None)
        assert r.passed is False


class TestKnownStateWins:
    """When the entries ARE readable they decide, config is not consulted."""

    def test_active_entries_are_authoritative(self):
        r = _check({"watchlist": {"enabled": False}},
                   [{"name": "Francisella tularensis", "taxid": 263}])
        assert r.passed is True
        assert "1 pathogen" in r.message

    def test_empty_active_entries_mean_none_enabled(self):
        """An empty list is a determined answer, not an unknown one."""
        r = _check({"watchlist": {"enabled": True, "builtin": ["cdc_bioterrorism"]}}, [])
        assert r.passed is False, (
            "an empty entry list means screening is genuinely off; the config "
            "fallback must not override a known answer"
        )
