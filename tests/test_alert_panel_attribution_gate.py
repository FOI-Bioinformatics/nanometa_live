"""The alert panel builds per-sample attribution only when something is hit.

Before this gate, `update_pathogen_alert_panel` ran
`_load_per_sample_organisms` unconditionally on every render — S kraken
loads plus S organism-dict builds per tick even on an all-clear run
(round-2 audit, 2026-08-22). The memoized pathogen check answers "any
hits?" for free, so attribution runs only on detection.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


KRAKEN_DF = pd.DataFrame({
    "%": [80.0], "cumul_reads": [800], "reads": [800],
    "rank": ["S"], "taxid": [666], "name": ["Testus organismus"],
})

CONFIG = {"visualization_only": True, "results_output_directory": "/x"}


@pytest.fixture
def panel_fn():
    from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
    app = make_callback_app(register_dashboard_callbacks)
    return get_callback_fn(
        app, "dashboard-pathogen-alert-container",
        input_contains="results-fingerprint")


def _run(panel_fn, dangerous, subthreshold, attribution_counter):
    from nanometa_live.app.tabs import dashboard_tab as dt

    def counting(*a, **kw):
        attribution_counter["n"] += 1
        return {}

    with patch.object(dt, "load_kraken_data", return_value=KRAKEN_DF), \
         patch.object(dt, "_check_pathogens_both",
                      return_value=(dangerous, subthreshold)), \
         patch.object(dt, "get_per_sample_organisms_cached", counting), \
         patch.object(dt, "_get_active_watchlist_entries", return_value=[]), \
         patch.object(dt, "_create_pathogen_alert_panel",
                      return_value=(None, {"display": "none"})), \
         patch.object(dt, "interval_tick_is_redundant", return_value=False), \
         patch.object(dt, "should_skip_update", return_value=False), \
         patch.object(dt, "os") as mock_os:
        mock_os.path.isdir.return_value = True
        with patch.object(dt, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "results-fingerprint"
            panel_fn({"fp": "1"}, None, 1, CONFIG, {}, ["barcode01"])


def test_no_hits_skips_attribution(panel_fn):
    calls = {"n": 0}
    _run(panel_fn, [], [], calls)
    assert calls["n"] == 0, (
        "an all-clear tick must not pay S kraken loads for attribution"
    )


def test_hits_build_attribution(panel_fn):
    calls = {"n": 0}
    _run(panel_fn, [{"taxid": 666, "name": "Testus organismus",
                     "reads": 800}], [], calls)
    assert calls["n"] == 1


def test_subthreshold_hits_also_build_attribution(panel_fn):
    calls = {"n": 0}
    _run(panel_fn, [], [{"taxid": 666, "name": "Testus organismus",
                         "reads": 3}], calls)
    assert calls["n"] == 1
