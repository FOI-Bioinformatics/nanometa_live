"""``default_reads_per_level`` must actually set the display floor.

The Taxonomy tab has a working min-reads control, and the config has a
documented key -- "Minimum reads to display at each level" -- that nothing
read. The layout hardcoded 10 and ``scale_min_reads_default`` hardcoded 10
again, so an operator who set the key in config.yaml saw no effect.

Unlike the Alert Threshold, which was removed because nothing could sensibly
consume it, this one has an obvious consumer already on screen. Wiring it
makes the documented behaviour true and lets an operator carry a preferred
floor between runs.

The aggregate-scaling heuristic is preserved: on an All-Samples view of 12+
barcodes the floor still rises to ``max(floor, 5N)``, because a 1-read
per-sample detection becomes N reads in the aggregate and would otherwise
survive as taxonomic noise.
"""

from __future__ import annotations

import dash
import pytest

from nanometa_live.app.tabs import classification_tab
from tests.dash_test_utils import get_callback_fn

pytestmark = pytest.mark.callback


@pytest.fixture
def scale_fn():
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    classification_tab.register_classification_callbacks(app)
    return get_callback_fn(
        app, "classification-filter-input", input_contains="available-samples"
    )


SMALL = ["All Samples", "barcode01", "barcode02"]
BIG = ["All Samples"] + [f"barcode{i:02d}" for i in range(1, 25)]


class TestTheConfiguredFloorIsUsed:
    @pytest.mark.parametrize("configured", [5, 25, 100])
    def test_the_starting_value_comes_from_config(self, scale_fn, configured):
        value, _placeholder, _signal = scale_fn(
            SMALL, "All Samples", None,
            {"default_reads_per_level": configured},
        )

        assert value == configured, (
            f"default_reads_per_level={configured} was ignored; the control "
            f"started at {value}"
        )

    def test_absent_config_keeps_the_historical_default(self, scale_fn):
        value, _, _signal = scale_fn(SMALL, "All Samples", None, {})

        assert value == 10

    def test_no_config_at_all_does_not_break(self, scale_fn):
        value, _, _signal = scale_fn(SMALL, "All Samples", None, None)

        assert value == 10


class TestOperatorInputStillWins:
    def test_a_typed_value_is_not_overwritten(self, scale_fn):
        """The heuristic only ever replaced an untouched default."""
        value, _, _signal = scale_fn(
            BIG, "All Samples", 37, {"default_reads_per_level": 25},
        )

        assert value == 37, "an operator's typed floor was overwritten"


class TestAggregateScalingSurvives:
    def test_the_floor_still_rises_on_a_large_aggregate(self, scale_fn):
        """24 barcodes: a 1-read per-sample hit becomes 24 in aggregate."""
        value, placeholder, _signal = scale_fn(
            BIG, "All Samples", None, {"default_reads_per_level": 10},
        )

        assert value == 120, f"expected max(10, 5*24)=120, got {value}"
        assert "24 samples" in placeholder

    def test_a_higher_configured_floor_is_not_lowered_by_the_heuristic(
        self, scale_fn
    ):
        """max(configured, 5N) -- the operator's floor is a floor."""
        value, _, _signal = scale_fn(
            BIG, "All Samples", None, {"default_reads_per_level": 500},
        )

        assert value == 500, (
            f"the heuristic lowered the operator's configured floor to {value}"
        )

    def test_a_single_sample_view_uses_the_configured_floor(self, scale_fn):
        value, _, _signal = scale_fn(
            BIG, "barcode03", None, {"default_reads_per_level": 25},
        )

        assert value == 25
