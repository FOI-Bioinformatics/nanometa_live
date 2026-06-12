"""Regression tests for ``update_verdict_banner`` (Phase 5a / B2).

The previous implementation referenced an ``available_samples`` name in
the per-sample-attribution branch without declaring it as a callback
input. The reference lived inside a try/except logging at DEBUG, so the
``NameError`` was swallowed silently: the banner rendered without the
"Triggered by" subhead and the operator never saw which barcode caused
the alert.

These tests pin both pieces of the fix:

1. The registered callback wires ``available-samples`` into its State
   list -- if the wiring is dropped, the parameter is back to being
   undefined.
2. Calling the registered function with a populated kraken_df and a
   matching watchlist entry produces a banner that includes the
   triggering sample name (i.e. the attribution branch ran without
   raising ``NameError``).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest
from dash import Dash

from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks


# -- Helpers --------------------------------------------------------------


def _state_ids(spec) -> list[str]:
    return [
        s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None)
        for s in (spec.get("state", []) or [])
    ]


def _find_callback_by_output(app: Dash, output_id: str):
    """Return the callback spec whose output list includes ``output_id``."""
    for cb_id, spec in app.callback_map.items():
        if output_id in cb_id:
            return cb_id, spec
    return None, None


# -- Wiring regression ---------------------------------------------------


class TestVerdictBannerCallbackWiring:
    def test_available_samples_is_a_state_input(self):
        """The verdict-banner callback must read ``available-samples``;
        otherwise the per-sample-attribution branch raises NameError on
        every render and the subhead silently disappears.
        """
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_dashboard_callbacks(app)

        cb_id, spec = _find_callback_by_output(app, "dashboard-verdict-banner")
        assert spec is not None, "Verdict-banner callback was not registered"
        assert "available-samples" in _state_ids(spec), (
            "Verdict-banner callback must include `available-samples` in its "
            "State list -- otherwise the per-sample attribution branch "
            "raises NameError under DEBUG-suppressed logging."
        )


# -- Behavioural regression ---------------------------------------------


class TestVerdictBannerAttributionRuns:
    """Drive the attribution branch end-to-end. If ``available_samples``
    is undefined the inner ``except Exception`` swallows the NameError,
    ``triggering_samples`` stays empty, and the rendered banner does not
    contain the per-sample subhead. Asserting on the rendered output is
    enough to pin the fix.
    """

    def _kraken_df_with_critical(self) -> pd.DataFrame:
        # Minimal shape consumed by the verdict-banner code path:
        # rank == "S" and reads >= 5 rows are turned into "organisms",
        # then watchlist matching identifies dangerous taxa.
        return pd.DataFrame([
            {
                "perc": 99.0, "cumul_reads": 1000, "reads": 1000,
                "rank": "S", "taxid": 12345, "name": "Bacillus anthracis",
                "parent_taxid": 1,
            },
            {
                "perc": 1.0, "cumul_reads": 10, "reads": 10,
                "rank": "S", "taxid": 99999, "name": "Generic species",
                "parent_taxid": 1,
            },
        ])

    def test_attribution_branch_completes_without_nameerror(self, tmp_path):
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_dashboard_callbacks(app)
        _, spec = _find_callback_by_output(app, "dashboard-verdict-banner")
        # Access the unwrapped function: Dash decorates the registered
        # callback with an add_context wrapper, but the original function
        # is preserved via __wrapped__.
        callback_fn = getattr(spec["callback"], "__wrapped__", spec["callback"])

        # Ensure the State count matches the wired signature.
        states = spec.get("state", []) or []
        assert "available-samples" in _state_ids(spec)

        # Build the inputs in declared order.
        results_dir = tmp_path / "results"
        (results_dir / "kraken2").mkdir(parents=True)
        config = {
            "results_output_directory": str(results_dir),
            "main_dir": str(results_dir),
        }
        status = {"running": True, "completed": False, "start_time": None}
        overall_status = {"status": "ok"}
        validation_data = {"results": []}
        available_samples = ["barcode01", "barcode02"]

        critical_organisms = [{
            "taxid": 12345,
            "name": "Bacillus anthracis",
            "threat_level": "critical",
            "kraken_taxid": 12345,
        }]

        with patch(
            "nanometa_live.app.tabs.dashboard_tab.load_kraken_data",
            return_value=self._kraken_df_with_critical(),
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._species_df_to_organisms",
            return_value=critical_organisms,
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._get_active_watchlist_entries",
            return_value=[{"taxid_ncbi": 12345, "name": "Bacillus anthracis"}],
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._check_pathogens_with_mapping",
            return_value=critical_organisms,
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab._load_per_sample_organisms",
            return_value={12345: [
                {"sample": "barcode01", "reads": 1000, "abundance": 90.0,
                 "is_negative_control": False},
            ]},
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab.interval_tick_is_redundant",
            return_value=False,
        ):
            # Args follow the declared order: fingerprint, watchlist_state,
            # n_intervals, config, status, overall_status, validation_data,
            # available_samples
            outputs = callback_fn(
                "fp1", None, 0,
                config, status, overall_status, validation_data,
                available_samples,
            )

        assert outputs is not None
        rendered = json.dumps(outputs, default=str)
        # ACTION REQUIRED branch must have rendered.
        assert "ACTION REQUIRED" in rendered
        # Per-sample attribution branch must have completed (no NameError).
        # If `available_samples` was undefined, the outer except swallowed it
        # and "Triggered by" never made it into the banner.
        assert "Triggered by" in rendered
        assert "barcode01" in rendered
        # The banner must also NAME the triggering pathogen(s) -- the count
        # alone ("N of M above threshold") left the operator asking "which?".
        assert "Above threshold" in rendered
        assert "Bacillus anthracis" in rendered


class TestPathogenNaming:
    """`_make_banner_content` names the pathogens above threshold so the
    operator does not have to leave the dashboard to learn which organisms
    triggered ACTION REQUIRED."""

    def _render(self, triggering_pathogens):
        from nanometa_live.app.tabs.dashboard_helpers import _make_banner_content
        content = _make_banner_content(
            "exclamation-octagon-fill", "#dc3545",
            "ACTION REQUIRED", "3 of 35 watched pathogens above alert threshold",
            "ACTIVE", "00:05:00",
            triggering_pathogens=triggering_pathogens,
        )
        return json.dumps(content, default=str)

    def test_names_each_pathogen(self):
        rendered = self._render(["Bacillus anthracis", "Yersinia pestis"])
        assert "Above threshold" in rendered
        assert "Bacillus anthracis" in rendered
        assert "Yersinia pestis" in rendered

    def test_overflow_beyond_five_summarized(self):
        names = [f"Pathogen {i}" for i in range(8)]
        rendered = self._render(names)
        # First five named inline, the remaining three summarized.
        assert "Pathogen 0" in rendered
        assert "Pathogen 4" in rendered
        assert "(+3 more)" in rendered
        assert "Pathogen 7" not in rendered

    def test_no_block_when_empty(self):
        assert "Above threshold" not in self._render(None)
        assert "Above threshold" not in self._render([])
