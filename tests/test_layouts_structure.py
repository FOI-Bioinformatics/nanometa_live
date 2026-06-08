"""
Structure guards for app/layouts/.

Layout edits that introduce a duplicate component id or break construction
silently break the callbacks bound to those ids -- the documented failure mode.
These tests import every top-level layout builder, assert it constructs into a
Dash component, and assert there are no duplicate string ids within it.

This is the cheap regression net for "someone renamed/duplicated an id".
"""

import pytest
from dash.development.base_component import Component

from nanometa_live.app.layouts.classification_layout import create_classification_layout
from nanometa_live.app.layouts.config_layout import create_config_layout
from nanometa_live.app.layouts.dashboard_layout import create_dashboard_layout
from nanometa_live.app.layouts.deployment_layout import create_deployment_layout
from nanometa_live.app.layouts.main_layout import create_main_layout
from nanometa_live.app.layouts.qc_layout import create_qc_layout
from nanometa_live.app.layouts.validation_layout import create_validation_layout
from nanometa_live.app.layouts.watchlist_preparation_layout import (
    create_watchlist_preparation_layout,
)

LAYOUT_BUILDERS = [
    create_classification_layout,
    create_config_layout,
    create_dashboard_layout,
    create_deployment_layout,
    create_qc_layout,
    create_validation_layout,
    create_watchlist_preparation_layout,
]


from dash_test_utils import collect_string_ids as _collect_string_ids


@pytest.mark.parametrize("builder", LAYOUT_BUILDERS, ids=lambda b: b.__name__)
class TestLayoutStructure:
    def test_constructs_to_component(self, builder):
        assert isinstance(builder(), Component)

    def test_no_duplicate_string_ids(self, builder):
        ids = []
        _collect_string_ids(builder(), ids)
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"{builder.__name__} has duplicate ids: {dupes}"


class TestMainLayout:
    def test_main_layout_constructs(self):
        # main_layout aggregates the tab layouts; assert it builds cleanly.
        assert isinstance(create_main_layout(), Component)


def _find_by_id(component, target_id):
    """Depth-first search for a Dash component with id == target_id."""
    if getattr(component, "id", None) == target_id:
        return component
    children = getattr(component, "children", None)
    if isinstance(children, Component):
        children = [children]
    if isinstance(children, (list, tuple)):
        for child in children:
            if isinstance(child, Component):
                found = _find_by_id(child, target_id)
                if found is not None:
                    return found
    return None


class TestCoverageDropdownSize:
    """Operator feedback #4: the coverage species dropdown was too small."""

    def test_dropdown_exposes_more_options(self):
        selector = _find_by_id(create_validation_layout(), "coverage-species-selector")
        assert selector is not None
        # Taller rows + a deeper open menu so ~8-10 options are visible at once.
        assert getattr(selector, "optionHeight", None) == 45
        assert getattr(selector, "maxHeight", None) == 400


class TestGenomeRefreshLoading:
    """Operator feedback #3: ref-genome Refresh gave no visual feedback."""

    def test_genome_lists_wrapped_in_loading(self):
        from dash import dcc
        loading = _find_by_id(create_watchlist_preparation_layout(), "genome-lists-loading")
        assert isinstance(loading, dcc.Loading)
        # The refreshed lists live inside the Loading so the spinner shows.
        assert _find_by_id(loading, "genome-missing-list") is not None
        assert _find_by_id(loading, "genome-downloaded-list") is not None
