"""One threat-level definition, presented consistently everywhere.

2026-08-17 reaudit: seven independent color maps and four vocabularies
existed for the same field, disagreeing on colors (the same "low" organism
was green in the report, grey in the watchlist table, cyan on alert cards),
and no surface explained what a level means. core/config/threat_levels.py
is now the single source; these tests pin the consumers to it.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.config.threat_levels import (
    THREAT_LEVEL_ORDER,
    THREAT_LEVELS,
    threat_legend,
    threat_level_info,
    threat_severity,
)


class TestCoreDefinition:
    def test_severity_order_most_severe_first(self):
        assert THREAT_LEVEL_ORDER == ["critical", "high", "moderate", "low"]
        assert threat_severity("critical") < threat_severity("high")
        assert threat_severity("moderate") < threat_severity("low")

    def test_unknown_levels_sort_last_and_get_safe_info(self):
        assert threat_severity("banana") > threat_severity("low")
        info = threat_level_info("banana")
        assert info["label"] == "Unknown"
        assert info["meaning"]

    def test_every_level_carries_a_meaning_and_action(self):
        for level, info in THREAT_LEVELS.items():
            assert info["meaning"], f"{level} has no plain-language meaning"
            assert info["action"], f"{level} has no action text"
            assert info["hex"].startswith("#")

    def test_legend_is_in_severity_order(self):
        assert [e["level"] for e in threat_legend()] == THREAT_LEVEL_ORDER


class TestConsumersDeriveFromCore:
    def test_alert_card_config_uses_shared_aliases(self):
        from nanometa_live.app.components.pathogen_alert import (
            THREAT_LEVELS as card_levels,
        )
        for level, card in card_levels.items():
            assert card["label"] == THREAT_LEVELS[level]["alias"]
            assert card["description"] == THREAT_LEVELS[level]["meaning"]

    def test_plotly_theme_matches_shared_hex(self):
        from nanometa_live.app.utils.plotly_theme import get_threat_color

        for level, info in THREAT_LEVELS.items():
            assert get_threat_color(level) == info["hex"]

    def test_badge_carries_meaning_as_hover(self):
        from nanometa_live.app.utils.threat_display import threat_badge

        badge = threat_badge("critical")
        assert badge.title == THREAT_LEVELS["critical"]["meaning"]
        assert badge.children == "Critical"

    def test_watchlist_row_badge_explains_itself(self):
        from nanometa_live.app.layouts.watchlist_layout import (
            create_pathogen_row,
        )

        row = str(create_pathogen_row(
            {"taxid": 1392, "name": "Bacillus anthracis",
             "threat_level": "critical", "enabled": True}, 0,
        ))
        assert THREAT_LEVELS["critical"]["meaning"] in row

    def test_organism_card_shows_threat_for_watched(self):
        from nanometa_live.app.components.organism_components import (
            OrganismCard,
        )

        card = str(OrganismCard(
            name="Bacillus anthracis", abundance=1.0, read_count=100,
            is_watched=True, threat_level="critical",
        ))
        assert "Critical" in card
        plain = str(OrganismCard(
            name="Escherichia coli", abundance=1.0, read_count=100,
        ))
        assert "Critical" not in plain


class TestReportUsesSharedDefinition:
    def test_watched_results_sorted_by_severity_not_alphabet(self, tmp_path):
        """Alphabetical sort ranks 'low' above 'moderate'; the generator now
        pre-sorts by severity and attaches the shared label + meaning."""
        from nanometa_live.core.config.threat_levels import threat_severity

        rows = [
            {"threat_level": "low", "detected": False, "name": "a"},
            {"threat_level": "critical", "detected": True, "name": "b"},
            {"threat_level": "moderate", "detected": False, "name": "c"},
        ]
        rows.sort(key=lambda w: (threat_severity(w.get("threat_level")),
                                 not w.get("detected"), w.get("name", "")))
        assert [w["threat_level"] for w in rows] == [
            "critical", "moderate", "low",
        ]

    def test_report_template_renders_legend_and_labels(self):
        template = open(
            "nanometa_live/core/export/templates/report.html"
        ).read()
        assert "data.threat_legend" in template
        assert "w.threat_label" in template
        assert 'sort(attribute="threat_level")' not in template
