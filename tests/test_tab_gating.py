"""Tab-aware rendering: hidden-tab display work skips; detection never does.

During a live run the results fingerprint advances every tick, so the
Sankey/Sunburst figure, four QC figures, the per-sample QC table and both
QC cards were rebuilt and re-shipped for tabs the operator was not looking
at (round-2 audit, 2026-08-22). Each now takes ``tabs.active_tab`` and
returns no_update while its tab is hidden; switching to the tab fires the
Input and renders the LATEST fingerprint.

The safety carve-out is the other half: the detection chain (overall
status cache, verdict banner, dashboard alerts, pathogen alert panel,
readiness, fingerprint computation) must NEVER be gated on the visible
tab. The introspection test pins that permanently.
"""

from unittest.mock import MagicMock, patch

import pytest
from dash.exceptions import PreventUpdate

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


@pytest.fixture
def qc_app():
    from nanometa_live.app.tabs.qc_tab import register_qc_callbacks
    return make_callback_app(register_qc_callbacks)


@pytest.fixture
def classification_app():
    from nanometa_live.app.tabs.classification_tab import (
        register_classification_callbacks,
    )
    return make_callback_app(register_classification_callbacks)


class TestHiddenTabSkips:
    def _assert_gated(self, module, fn, args_before_tab, args_after_tab,
                      wrong_tab="dashboard-tab"):
        loads = {"n": 0}

        def counting(*a, **kw):
            loads["n"] += 1
            raise AssertionError("loader touched while the tab is hidden")

        with patch.object(module, "load_kraken_data", counting, create=True), \
             patch.object(module, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "update-interval"
            with pytest.raises(PreventUpdate):
                fn(*args_before_tab, wrong_tab, *args_after_tab)
        assert loads["n"] == 0

    def test_qc_plots_skip_when_hidden(self, qc_app):
        from nanometa_live.app.tabs import qc_tab
        fn = get_callback_fn(qc_app, "cumul-reads-graph")
        self._assert_gated(qc_tab, fn,
                           ({"fp": "1"}, "All Samples", 1), ({}, {}))

    def test_per_sample_table_skips_when_hidden(self, qc_app):
        from nanometa_live.app.tabs import qc_tab
        fn = get_callback_fn(qc_app, "per-sample-table")
        self._assert_gated(qc_tab, fn,
                           ({"fp": "1"}, "All Samples", 1), ({}, {}))

    def test_base_quality_card_skips_when_hidden(self, qc_app):
        from nanometa_live.app.tabs import qc_tab
        fn = get_callback_fn(qc_app, "base-quality-card-container")
        self._assert_gated(qc_tab, fn,
                           ({"fp": "1"}, "All Samples", 1), ({}, {}))

    def test_read_statistics_card_skips_when_hidden(self, qc_app):
        from nanometa_live.app.tabs import qc_tab
        fn = get_callback_fn(qc_app, "read-statistics-card-container")
        self._assert_gated(qc_tab, fn,
                           ({"fp": "1"}, "All Samples", 1), ({}, {}))

    def test_classification_plot_skips_when_hidden(self, classification_app):
        from nanometa_live.app.tabs import classification_tab
        fn = get_callback_fn(classification_app, "classification-plot")
        self._assert_gated(
            classification_tab, fn,
            ({"fp": "1"}, 0, "sankey", "All Samples", "D,K,P", None,
             "default", 10, 600, None, 1),
            (None, None, {}, {}))

    def test_tab_activation_renders(self, qc_app):
        """Switching TO the tab is a real trigger: the gate lets it through
        and the body runs against the latest fingerprint."""
        from nanometa_live.app.tabs import qc_tab
        fn = get_callback_fn(qc_app, "cumul-reads-graph")
        with patch.object(qc_tab, "ctx") as mock_ctx, \
             patch.object(qc_tab, "resolve_outdir_for_fingerprint",
                          return_value=None):
            mock_ctx.triggered_id = "tabs"
            result = fn({"fp": "1"}, "All Samples", 1, "qc-tab", {}, {})
        assert result is not None  # empty figures, not PreventUpdate


class TestDetectionChainIsNeverTabGated:
    """Permanent guard: nobody may quietly gate the alarm surfaces."""

    NEVER_GATED = {
        "compute_overall_status_cache",
        "update_verdict_banner",
        "update_dashboard_alerts",
        "update_pathogen_alert_panel",
        "compute_results_fingerprint",
        "update_readiness_state",
    }

    def test_no_detection_callback_takes_active_tab(self):
        import ast
        import pathlib
        app_root = (pathlib.Path(__file__).resolve().parent.parent
                    / "nanometa_live" / "app")
        offenders = []
        for path in sorted(app_root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                if fn.name not in self.NEVER_GATED:
                    continue
                for dec in fn.decorator_list:
                    for node in ast.walk(dec):
                        if (isinstance(node, ast.Constant)
                                and node.value == "active_tab"):
                            offenders.append(f"{path.name}:{fn.name}")
        assert not offenders, (
            f"detection-chain callbacks gated on the visible tab: "
            f"{offenders}. A verdict must never claim a result it did not "
            f"earn -- and it must never be deferred because the operator "
            f"was looking elsewhere."
        )