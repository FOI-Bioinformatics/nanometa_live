"""The dashboard metric tiles must not depend on the sample-selector component.

Observed live on the 2026-08-19 multi-pathogen realtime run: "Sequences
Analyzed" and "Species Detected" sat at **0** for the whole run while the
verdict banner showed 14 watched pathogens above threshold, the sample table
listed 3 samples, and ``dashboard-overall-status-cache`` in the browser
already held ``total_reads=3985, organisms_detected=85``. Invoking the
callback directly against the running server returned "3,985" / "85", and the
callback was registered with the right inputs -- yet the browser never
dispatched it once in 157 callback POSTs.

Cause: ``sample-selector`` carries ``data-dash-is-loading="true"`` almost
continuously. Its options are rebuilt from ``sample-freshness``, which
advances on every polling tick (the per-sample age pills), and the callback
returns ``no_update`` for ``.value``. Dash defers any callback whose Input is
a property of a component with a pending output, so a callback keyed on
``sample-selector.value`` is starved for as long as the freshness map keeps
churning -- i.e. for the entire realtime run.

Every other tab already reads the ``selected-sample`` Store instead of the
component. The metrics callback was the only dashboard consumer reading the
component directly, and the only one that froze.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.callback

from dash import Dash

from tests.dash_test_utils import get_callback_fn


@pytest.fixture()
def app():
    import nanometa_live.app.tabs.dashboard_tab as dt

    application = Dash(__name__)
    dt.register_dashboard_callbacks(application)
    return application


def _spec(app):
    for key, spec in app.callback_map.items():
        if "dashboard-sequences-count" in key:
            return spec
    raise AssertionError("metrics callback not registered")


class TestTriggerSource:
    def test_does_not_depend_on_the_selector_component(self, app):
        inputs = [i["id"] for i in _spec(app)["inputs"]]
        assert "sample-selector" not in inputs, (
            "the metric tiles are keyed on a component whose output is "
            "pending on every poll, so Dash starves them: both tiles read 0 "
            "for an entire realtime run (2026-08-19)"
        )

    def test_reads_the_selected_sample_store(self, app):
        inputs = [i["id"] for i in _spec(app)["inputs"]]
        assert "selected-sample" in inputs, (
            "the tiles must follow the same sample Store every other tab "
            "uses, so a sample switch still rescopes them"
        )

    def test_keeps_its_data_and_interval_triggers(self, app):
        inputs = [i["id"] for i in _spec(app)["inputs"]]
        assert "dashboard-overall-status-cache" in inputs
        assert "update-interval" in inputs, (
            "the interval backstop repairs a dropped store-update response"
        )


class TestRendersFromTheCache:
    def _call(self, app, selected, cache):
        fn = get_callback_fn(app, "dashboard-sequences-count")
        return fn(cache, selected, 3, {"results_output_directory": "/nope"},
                  ["All Samples", "barcode01"], {})

    CACHE = {
        "status": "success",
        "total_reads": 3985,
        "organisms_detected": 85,
        "_main_dir": "/nope",
        "_available_samples": ["All Samples", "barcode01"],
        "_samples_data": [],
    }

    def test_all_samples_uses_the_aggregate_numbers(self, app):
        seq, org, cache = self._call(app, "All Samples", self.CACHE)
        assert seq == "3,985"
        assert org == "85"
        assert cache == {"reads": 3985, "organisms": 85}

    def test_empty_selection_is_treated_as_all_samples(self, app):
        seq, _org, _c = self._call(app, None, self.CACHE)
        assert seq == "3,985"

    def test_no_cache_yields_zeroes(self, app):
        seq, org, _c = self._call(app, "All Samples", None)
        assert (seq, org) == ("0", "0")


class TestNoOtherDashboardCallbackKeysOnTheComponent:
    SOURCE = (
        Path(__file__).resolve().parents[1]
        / "nanometa_live" / "app" / "tabs" / "dashboard_tab.py"
    )

    def test_dashboard_tab_does_not_input_the_selector(self):
        src = self.SOURCE.read_text()
        assert 'Input("sample-selector"' not in src, (
            "a dashboard callback keys on the sample-selector component "
            "again; use the selected-sample Store"
        )
