"""A render skipped by the debounce must not be recorded as rendered.

``update_pathogen_alert_panel`` stamped the render memo (``mark_rendered``)
BEFORE its 2 s ``should_skip_update`` debounce. A direct trigger arriving
within 2 s of the previous render -- a second watchlist toggle, or a toggle
followed by a fingerprint change -- was then dropped by the debounce but
recorded as rendered, and every interval backstop tick for the next
``RENDER_MEMO_TTL_SECONDS`` (120 s) judged its refresh redundant. The panel
is on the detection chain, so it stayed on the previous state for up to two
minutes.
"""

from unittest.mock import patch

import pandas as pd
import pytest
from dash.exceptions import PreventUpdate

from nanometa_live.app.utils import debounce
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
    debounce._debounce_timestamps.clear()
    debounce._render_fp.clear()
    app = make_callback_app(register_dashboard_callbacks)
    yield get_callback_fn(
        app, "dashboard-pathogen-alert-container",
        input_contains="results-fingerprint")
    debounce._debounce_timestamps.clear()
    debounce._render_fp.clear()


def _call(panel_fn, trigger, fp):
    from nanometa_live.app.tabs import dashboard_tab as dt

    with patch.object(dt, "load_kraken_data", return_value=KRAKEN_DF), \
         patch.object(dt, "_check_pathogens_both", return_value=([], [])), \
         patch.object(dt, "_get_active_watchlist_entries", return_value=[]), \
         patch.object(dt, "_create_pathogen_alert_panel",
                      return_value=("rendered", {"display": "block"})), \
         patch.object(dt, "os") as mock_os, \
         patch.object(dt, "ctx") as mock_ctx:
        mock_os.path.isdir.return_value = True
        mock_ctx.triggered_id = trigger
        mock_ctx.triggered = [{"prop_id": f"{trigger}.data"}]
        return panel_fn({"fp": fp}, None, 1, CONFIG, {}, ["barcode01"])


def test_debounced_direct_trigger_is_retried_by_the_next_interval_tick(panel_fn):
    # Render once for fp "1".
    _call(panel_fn, "results-fingerprint", "1")
    # The fingerprint moves to "2" within the debounce window: dropped.
    with pytest.raises(PreventUpdate):
        _call(panel_fn, "results-fingerprint", "2")
    # The next backstop tick carries fp "2". It must render, because "2"
    # was never put on screen.
    debounce._debounce_timestamps.clear()  # the 2 s window has passed
    assert _call(panel_fn, "update-interval", "2") is not None
