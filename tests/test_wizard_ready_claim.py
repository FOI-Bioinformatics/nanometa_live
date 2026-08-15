"""The deployment wizard must not call a system ready when it is not.

`run_all_wizard_steps` marked a step "done" whenever `_execute_wizard_step`
returned without raising, then announced

    All 8 steps completed. System is ready for offline deployment.

But several steps report a problem by RETURNING a warning alert rather than
raising. Step 0 does exactly that when no watchlist is enabled -- the single
most important thing to configure before a field deployment, since without it
nothing is screened for. So the wizard could tell an operator the system was
ready while its own step 0 said "No watchlist entries enabled".

Found 2026-07-29, the same "reassuring conclusion that was not earned" shape as
the ALL CLEAR and exported-report defects.

The outcome was already encoded in the returned alert's colour; the loop simply
discarded the return value. It now reads it: success counts as done, and
warning/danger/info count as needing attention, with the step's own message
carried into the summary so the operator sees what to fix.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.app.tabs.preparation_helpers import (
    _alert_text,
    _execute_wizard_step,
)

pytestmark = pytest.mark.unit


class TestStepZeroReportsItsOwnFailure:
    """The step that decides whether anything will be screened for."""

    def _step_zero(self, entries):
        mgr = MagicMock()
        mgr.get_active_entries.return_value = entries
        with patch(
            "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
            return_value=mgr,
        ):
            return _execute_wizard_step(0, {"kraken_db": "/tmp/db"})

    def test_no_watchlist_is_not_a_success(self):
        alert = self._step_zero({})
        assert alert.color == "warning", (
            "a deployment with nothing to screen for must not report success; "
            "the wizard counts colour, so this is what stops it claiming ready"
        )

    def test_no_watchlist_says_what_to_do(self):
        assert "Enable pathogens" in _alert_text(self._step_zero({}))

    def test_an_active_watchlist_is_a_success(self):
        alert = self._step_zero({263: MagicMock(), 1392: MagicMock()})
        assert alert.color == "success"
        assert "2 watchlist entries active" in _alert_text(alert)

    def test_an_unreadable_watchlist_is_not_a_success(self):
        """"Could not load" is not "nothing to load"."""
        with patch(
            "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
            side_effect=RuntimeError("boom"),
        ):
            alert = _execute_wizard_step(0, {"kraken_db": "/tmp/db"})
        assert alert.color in ("info", "warning", "danger"), (
            "a step that could not determine its answer must not count as "
            "succeeded; that is how an unverified system gets called ready"
        )


class TestAlertTextHelper:
    """The summary carries each step's own words, so it must extract them."""

    def test_extracts_nested_text(self):
        import dash_bootstrap_components as dbc
        from dash import html

        alert = dbc.Alert([html.I(className="bi"), "Something is wrong"],
                          color="warning")
        assert "Something is wrong" in _alert_text(alert)

    def test_handles_a_bare_string(self):
        assert _alert_text("plain") == "plain"

    def test_handles_an_empty_component(self):
        from dash import html

        assert _alert_text(html.Div()) == ""


class TestTheWizardLoopReadsTheOutcome:
    """The defect was in the loop, so the loop is what must be pinned.

    `run_all_wizard_steps` is a background callback, but its body is an
    ordinary function once unwrapped: it takes `set_progress` as its first
    argument and returns the wizard state. Driving it directly with a stub
    `_execute_wizard_step` is enough to assert what it concludes, and it is
    the only place that asserts the loop reads the colour at all -- the tests
    above would still pass with the loop discarding the return value again.
    """

    def _run(self, outcomes):
        """Run the wizard with `outcomes[i]` returned by step i."""
        import dash
        import dash_bootstrap_components as dbc
        from nanometa_live.app.tabs import preparation_tab

        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        preparation_tab.register_preparation_callbacks(app)
        from tests.dash_test_utils import get_callback_fn

        fn = get_callback_fn(
            app, "wizard-step-state", input_contains="wizard-run-all-btn"
        )

        seen = []
        with patch.object(
            preparation_tab, "_execute_wizard_step",
            side_effect=lambda idx, *a, **k: outcomes[idx],
        ):
            state = fn(lambda v: seen.append(v), 1, None, {"kraken_db": "/tmp/db"},
                       "/tmp/out", "b.tar.gz", False, "docker")
        # The last set_progress value is the final summary alert.
        return state, seen[-1][0]

    def _summary_text(self, alert):
        from nanometa_live.app.tabs.preparation_helpers import _alert_text

        return _alert_text(alert)

    def test_all_successful_steps_do_report_ready(self):
        """Control: the good news must still be deliverable."""
        import dash_bootstrap_components as dbc

        ok = [dbc.Alert("fine", color="success") for _ in range(8)]
        state, alert = self._run(ok)
        assert alert.color == "success"
        assert "ready for offline deployment" in self._summary_text(alert)
        assert set(state["steps"].values()) == {"done"}

    def test_a_warning_step_blocks_the_ready_claim(self):
        """The defect. Step 0 warns; the wizard must not call it ready."""
        import dash_bootstrap_components as dbc

        outcomes = [dbc.Alert("fine", color="success") for _ in range(8)]
        outcomes[0] = dbc.Alert(
            "No watchlist entries enabled.", color="warning"
        )
        state, alert = self._run(outcomes)

        # Substring care: the failure text is "NOT ready for offline
        # deployment", which contains the success phrase. Assert on the
        # success sentence, which only the all_ok branch emits.
        assert "All 8 steps completed" not in self._summary_text(alert), (
            "a wizard step reported a problem and the wizard still announced "
            "the system ready; this is the defect the colour check prevents"
        )
        assert "Not ready for offline deployment" in self._summary_text(alert)
        assert alert.color == "warning"
        assert state["steps"]["0"] == "warning"
        assert state["steps"]["1"] == "done"

    def test_the_summary_carries_the_step_s_own_words(self):
        """An operator needs to know WHAT to fix, not just that something is."""
        import dash_bootstrap_components as dbc

        outcomes = [dbc.Alert("fine", color="success") for _ in range(8)]
        outcomes[3] = dbc.Alert("No genomes downloaded.", color="warning")
        _, alert = self._run(outcomes)
        text = self._summary_text(alert)
        assert "No genomes downloaded." in text
        assert "Step 4" in text, "the step must be named so it can be found"

    def test_a_raising_step_is_still_a_failure(self):
        """The pre-existing exception path must be untouched by the fix."""
        import dash_bootstrap_components as dbc

        outcomes = [dbc.Alert("fine", color="success") for _ in range(8)]

        class Boom(dbc.Alert):
            pass

        from nanometa_live.app.tabs import preparation_tab

        def side_effect(idx, *a, **k):
            if idx == 5:
                raise RuntimeError("disk full")
            return outcomes[idx]

        import dash
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        preparation_tab.register_preparation_callbacks(app)
        from tests.dash_test_utils import get_callback_fn

        fn = get_callback_fn(
            app, "wizard-step-state", input_contains="wizard-run-all-btn"
        )
        seen = []
        with patch.object(
            preparation_tab, "_execute_wizard_step", side_effect=side_effect
        ):
            state = fn(lambda v: seen.append(v), 1, None, {}, "/tmp", "b", False,
                       "docker")
        assert state["steps"]["5"] == "failed"
        assert "disk full" in self._summary_text(seen[-1][0])
