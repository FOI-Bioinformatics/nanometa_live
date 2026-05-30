"""
Smoke tests for the layout builders in app/components/.

Several component builders had no coverage. These tests assert each constructs
without error, returns a Dash component, carries no duplicate string IDs (the
failure mode that silently breaks callbacks), and -- for the coverage plots --
produces Plotly figures from a CoverageData input. Builders are exercised with
their real (default) arguments; this is structural, not pixel-level.
"""

import numpy as np
import plotly.graph_objects as go
import pytest
from dash.development.base_component import Component

from nanometa_live.app.components.config_form import create_config_form
from nanometa_live.app.components.coverage_plots import (
    create_coverage_depth_figure,
    create_coverage_stats_summary,
    create_cumulative_coverage_figure,
    create_depth_histogram_figure,
)
from nanometa_live.app.components.header import create_header
from nanometa_live.app.components.taxid_mapping_ui import (
    create_mapping_controls,
    create_mapping_status_dashboard,
    create_mapping_table_section,
)
from nanometa_live.app.components.waiting_banner import waiting_for_first_batch_banner
from nanometa_live.core.parsers.paf_coverage_parser import CoverageData


from dash_test_utils import collect_string_ids as _collect_string_ids, assert_no_duplicate_ids as _assert_no_duplicate_ids


@pytest.fixture
def coverage():
    depth = np.array([0, 1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=np.uint32)
    return CoverageData(ref_name="ref1", ref_length=len(depth), depth_array=depth)


class TestSimpleBuilders:
    def test_header_includes_title(self):
        header = create_header("My Analysis Run")
        assert isinstance(header, Component)
        ids = []
        _collect_string_ids(header, ids)  # constructs and walks cleanly

    def test_config_form_constructs_without_duplicate_ids(self):
        form = create_config_form()
        assert isinstance(form, Component)
        _assert_no_duplicate_ids(form)

    def test_waiting_banner_constructs(self):
        banner = waiting_for_first_batch_banner()
        assert isinstance(banner, Component)


class TestTaxidMappingUi:
    @pytest.mark.parametrize(
        "builder",
        [create_mapping_status_dashboard, create_mapping_controls, create_mapping_table_section],
    )
    def test_builders_construct_with_unique_ids(self, builder):
        card = builder()
        assert isinstance(card, Component)
        _assert_no_duplicate_ids(card)


class TestCoveragePlots:
    def test_depth_figure(self, coverage):
        assert isinstance(create_coverage_depth_figure(coverage), go.Figure)

    def test_cumulative_figure(self, coverage):
        assert isinstance(create_cumulative_coverage_figure(coverage), go.Figure)

    def test_histogram_figure(self, coverage):
        assert isinstance(create_depth_histogram_figure(coverage), go.Figure)

    def test_stats_summary_is_component(self, coverage):
        assert isinstance(create_coverage_stats_summary(coverage), Component)
