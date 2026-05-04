"""Tests for the validation tab's card-list pagination and the
grouped coverage species selector.

Closes P1-T06 and P1-T07 from
docs/audit-2026-04-28-throughput-ux.md.
"""

from dash import html
import dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.validation_tab import (
    _CARD_LIST_INITIAL_LIMIT,
    _build_coverage_selector_options,
    _build_paginated_card_list,
)


# ---------------------------------------------------------------- pagination


class TestPaginatedCardList:
    """The paginated wrapper must cap initial DOM at 30 cards but
    surface a "Show all" button so the operator can request the full set."""

    def _make_cards(self, n: int):
        return [html.Div(f"card-{i}") for i in range(n)]

    def test_short_list_renders_in_full(self):
        cards = self._make_cards(5)
        result = _build_paginated_card_list(cards, show_all=False,
                                            show_all_button_id="b")
        # 5 cards + no footer
        assert len(result.children) == 5

    def test_long_list_renders_first_page_plus_footer(self):
        cards = self._make_cards(120)
        result = _build_paginated_card_list(cards, show_all=False,
                                            show_all_button_id="blast-show-all-btn")
        # 30 cards + 1 footer Div
        assert len(result.children) == _CARD_LIST_INITIAL_LIMIT + 1
        footer = result.children[-1]
        # Footer text mentions both visible and total counts
        rendered = str(footer.to_plotly_json())
        assert f"Showing {_CARD_LIST_INITIAL_LIMIT} of 120" in rendered
        assert "Show all 120" in rendered

    def test_show_all_renders_every_card(self):
        cards = self._make_cards(120)
        result = _build_paginated_card_list(cards, show_all=True,
                                            show_all_button_id="b")
        # 120 cards + 1 footer noting "Showing all"
        assert len(result.children) == 121

    def test_empty_list_returns_empty_div(self):
        result = _build_paginated_card_list([], show_all=False,
                                            show_all_button_id="b")
        assert result.children == []


# ---------------------------------------------------------------- grouping


class TestCoverageSelectorGrouping:
    """populate_coverage_selector groups options by sample with disabled
    header rows so 24-barcode runs do not present 120 flat entries."""

    def _build_data(self, samples_x_species):
        results = []
        for sample_id, species_list in samples_x_species.items():
            for taxid, name in species_list:
                results.append({
                    "sample_id": sample_id,
                    "taxid": taxid,
                    "species": name,
                    "validation_method": "minimap2",
                })
        return {"results": results}

    def test_options_grouped_by_sample(self):
        data = self._build_data({
            "barcode01": [(562, "Escherichia coli"), (28901, "Salmonella enterica")],
            "barcode02": [(562, "Escherichia coli"), (1280, "Staphylococcus aureus")],
        })
        options, value = _build_coverage_selector_options(data, current_value=None)

        # Two header rows + four species options
        headers = [o for o in options if o.get("disabled")]
        species_opts = [o for o in options if not o.get("disabled")]
        assert len(headers) == 2
        assert len(species_opts) == 4

        # Headers carry the sample id in label and a __header__ value
        assert any("barcode01" in o["label"] for o in headers)
        assert any("barcode02" in o["label"] for o in headers)
        assert all(o["value"].startswith("__header__:") for o in headers)

        # First option must be a header so groups are visually separated
        assert options[0]["value"].startswith("__header__:")

        # Default value must be a non-disabled option
        assert value is not None
        assert not value.startswith("__header__:")

    def test_existing_value_preserved_across_refresh(self):
        data = self._build_data({
            "barcode01": [(562, "Escherichia coli")],
            "barcode02": [(562, "Escherichia coli")],
        })
        options, value = _build_coverage_selector_options(
            data, current_value="barcode01_562"
        )
        assert value == "barcode01_562"

    def test_stale_value_falls_back_to_first(self):
        data = self._build_data({
            "barcode01": [(562, "Escherichia coli")],
        })
        options, value = _build_coverage_selector_options(
            data, current_value="barcodeXX_999",
        )
        assert value == "barcode01_562"

    def test_empty_data_returns_empty(self):
        options, value = _build_coverage_selector_options({"results": []}, None)
        assert options == []
        assert value is None
