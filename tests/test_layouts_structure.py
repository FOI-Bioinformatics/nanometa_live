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
from nanometa_live.app.layouts.main_layout import create_main_layout
from nanometa_live.app.layouts.preparation_layout import create_preparation_layout
from nanometa_live.app.layouts.qc_layout import create_qc_layout
from nanometa_live.app.layouts.validation_layout import create_validation_layout
from nanometa_live.app.layouts.watchlist_layout import create_watchlist_layout

LAYOUT_BUILDERS = [
    create_classification_layout,
    create_config_layout,
    create_dashboard_layout,
    create_preparation_layout,
    create_qc_layout,
    create_validation_layout,
    create_watchlist_layout,
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
