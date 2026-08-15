"""A never-hydrated watchlist snapshot means "unknown", not "nothing enabled".

``ReadinessChecker._resolve_active_watchlist`` deliberately distinguishes two
states, and says so in its own docstring:

    Returns ``None`` only when neither source is available -- the checks treat
    that as "could not determine" and use their directory/config fallback,
    which is distinct from an empty list ("watchlist loaded but nothing
    enabled").

That is the distinction this whole project is built around: a missing
measurement is not a negative result. The Store then initialised to ``[]``,
the determined-empty value, so before ``hydrate_watchlist_entries_snapshot``
had ever run, a background readiness check was told authoritatively that zero
pathogens were enabled and reported "No watchlist enabled".

The config fallback written specifically to avoid that false message requires
``None`` and so could never fire. The codebase even explains why it matters:
"Telling an operator to go enable pathogens they have already enabled trains
them to ignore the readiness panel."
"""

from __future__ import annotations

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

pytestmark = pytest.mark.unit


CONFIGURED = {"watchlist": {"enabled": True, "builtin": ["cdc_bioterrorism"]}}


class TestUndeterminedIsNotEmpty:
    def test_none_falls_back_to_config_rather_than_claiming_nothing_enabled(self):
        """The background-worker case: singleton empty, snapshot never set."""
        result = ReadinessChecker()._check_watchlist_active(CONFIGURED, None)

        assert result.passed is True, (
            "an undetermined watchlist was reported as 'nothing enabled'; "
            "this is the false-negative the config fallback exists to prevent"
        )
        assert "not yet loaded" in result.message.lower()

    def test_an_empty_list_still_means_nothing_is_enabled(self):
        """The distinction only has value if [] keeps its meaning.

        An operator who has genuinely disabled every pathogen must still be
        told so -- otherwise the fix would trade one wrong answer for another.
        """
        result = ReadinessChecker()._check_watchlist_active(CONFIGURED, [])

        assert result.passed is False
        assert "no watchlist enabled" in result.message.lower()

    def test_entries_present_are_reported_as_active(self):
        result = ReadinessChecker()._check_watchlist_active(
            CONFIGURED, [{"name": "Bacillus anthracis", "taxid": 1392}]
        )

        assert result.passed is True
        assert "1 pathogen" in result.message


class TestTheStoreDefaultPreservesTheDistinction:
    def test_the_snapshot_store_does_not_default_to_an_empty_list(self):
        """Guards the actual defect, which lived in the Store's default value.

        Every branch above can be correct while the app still ships broken, as
        it did: the logic distinguished None from [], and the Store handed it
        [] before anything had been determined.
        """
        import re
        import pathlib

        source = pathlib.Path(
            __import__("nanometa_live.app.app", fromlist=["app"]).__file__
        ).read_text()

        match = re.search(
            r"dcc\.Store\(\s*id=['\"]watchlist-entries-snapshot['\"]"
            r"(?P<rest>[^)]*)\)",
            source,
        )
        assert match, "the watchlist-entries-snapshot Store was not found"

        rest = match.group("rest")
        assert "data=[]" not in rest.replace(" ", ""), (
            "watchlist-entries-snapshot defaults to [], which the readiness "
            "checker reads as 'determined: nothing enabled' rather than 'not "
            "yet determined', producing a false 'No watchlist enabled'"
        )
