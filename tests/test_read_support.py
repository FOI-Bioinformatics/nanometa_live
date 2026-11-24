"""One read-support rule, named for what it measures.

At the Barcelona exercise (2026-11-24 feedback) "High confidence" meant
>= 100 reads on the Dashboard alert cards and >= 1000 on the Organisms cards,
showed no threshold, and sat beside "pending confirmatory validation", where
it read as if confirmation had been done. It counts classified reads only.
"""

from pathlib import Path

import pytest

from nanometa_live.app.components.organism_components import OrganismCard
from nanometa_live.app.components.pathogen_alert import (
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
)
from nanometa_live.app.tabs import dashboard_helpers
from nanometa_live.core.utils.read_support import (
    READ_SUPPORT_LABELS,
    READ_SUPPORT_TOOLTIP,
    read_support_label,
    read_support_level,
)
from test_pathogen_alert_rendering import _text, _walk

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("reads,level", [
    (0, "none"), (None, "none"), ("x", "none"),
    (1, "low"), (19, "low"),
    (20, "moderate"), (99, "moderate"),
    (100, "high"), (5000, "high"),
])
def test_read_support_boundaries(reads, level):
    assert read_support_level(reads) == level


@pytest.mark.parametrize("word,label", [
    ("HIGH", "High read support"), ("High", "High read support"),
    ("high", "High read support"), ("MODERATE", "Moderate read support"),
    ("medium", "Moderate read support"), ("LOW", "Low read support"),
    ("N/A", "No reads"), ("none", "No reads"),
])
def test_read_support_label_accepts_every_word_in_use(word, label):
    assert read_support_label(word) == label


def test_report_and_modal_words_are_unchanged():
    """The report and the modal compare on these words."""
    assert dashboard_helpers.compute_detection_confidence(150) == "High"
    assert dashboard_helpers.compute_detection_confidence(50) == "Moderate"
    assert dashboard_helpers.compute_detection_confidence(5) == "Low"
    assert dashboard_helpers.compute_detection_confidence(0) == "N/A"


def test_organism_card_and_alert_card_agree_at_150_reads():
    level = read_support_level(150)
    organism = _text(OrganismCard(name="X", abundance=1.0, read_count=150,
                                  confidence=level, taxid=1))
    alert = _text(CriticalPathogenAlert(
        "X", read_count=150,
        confidence=dashboard_helpers._card_confidence(150)))
    assert "High read support" in organism
    assert "High read support" in alert


def test_organisms_tab_uses_the_shared_thresholds():
    """500 reads was Medium on the Organisms tab (High >= 1000) and HIGH on
    the Dashboard (>= 100); the tab now asks read_support_level."""
    src = (Path(dashboard_helpers.__file__).parent / "main_tab.py").read_text()
    assert "high_confidence_reads" not in src
    assert "medium_confidence_reads" not in src
    assert "read_support_level(" in src
    assert read_support_level(500) == "high"


def test_no_card_says_confidence():
    for card in (
        OrganismCard(name="X", abundance=1.0, read_count=150,
                     confidence="high", taxid=1),
        CriticalPathogenAlert("X", read_count=150, confidence="HIGH"),
        HighRiskPathogenAlert("X", read_count=150, confidence="HIGH"),
    ):
        assert "confidence" not in _text(card).lower()


def test_cards_explain_the_rule_on_hover():
    for card in (
        OrganismCard(name="X", abundance=1.0, read_count=150,
                     confidence="high", taxid=1),
        CriticalPathogenAlert("X", read_count=150, confidence="HIGH"),
        HighRiskPathogenAlert("X", read_count=150, confidence="HIGH"),
    ):
        titles = [getattr(n, "title", None) for n in _walk(card)]
        assert READ_SUPPORT_TOOLTIP in titles


def test_labels_cover_every_level():
    assert set(READ_SUPPORT_LABELS) == {"high", "moderate", "low", "none"}
