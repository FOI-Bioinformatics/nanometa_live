"""Tests for the validation tab's aggregate read counts.

The Validation Summary card and the per-result card now show both the
percentage and the absolute number of reads validated, per the
2026-05-01 operator request "I want to see both % and absolute number
of reads that are confirmed/validated".

These tests pin:
  * ``_compute_summary`` aggregates ``validated_reads`` and
    ``total_reads`` across the result list.
  * ``create_validation_status_card`` accepts the new kwargs and
    renders the aggregate row with the absolute counts AND the
    derived percentage.
  * ``create_validation_result_card`` renders the per-species
    "X of Y reads" plus "(Z%)" treatment.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# _compute_summary aggregates read totals
# ---------------------------------------------------------------------------


class TestComputeSummaryAggregatesReads:
    def _result(self, status, validated, total):
        return {
            "status": status,
            "validated_reads": validated,
            "total_reads": total,
            "species": "X",
        }

    def test_returns_per_status_counts_unchanged(self):
        from nanometa_live.app.tabs.validation_tab import _compute_summary
        results = [
            self._result("confirmed", 90, 100),
            self._result("partial", 60, 100),
            self._result("low", 10, 100),
            self._result("no_data", 0, 0),
        ]
        c = _compute_summary(results)
        assert c["confirmed"] == 1
        assert c["partial"] == 1
        assert c["low_confidence"] == 1
        assert c["no_data"] == 1

    def test_aggregates_validated_reads_across_results(self):
        from nanometa_live.app.tabs.validation_tab import _compute_summary
        results = [
            self._result("confirmed", 90, 100),
            self._result("partial", 60, 100),
            self._result("low", 10, 50),
        ]
        c = _compute_summary(results)
        assert c["reads_validated"] == 90 + 60 + 10
        assert c["reads_total"] == 100 + 100 + 50

    def test_no_data_results_contribute_zero(self):
        from nanometa_live.app.tabs.validation_tab import _compute_summary
        results = [
            self._result("confirmed", 90, 100),
            self._result("no_data", 0, 0),
        ]
        c = _compute_summary(results)
        assert c["reads_validated"] == 90
        assert c["reads_total"] == 100

    def test_missing_or_string_read_counts_handled_gracefully(self):
        from nanometa_live.app.tabs.validation_tab import _compute_summary
        results = [
            {"status": "confirmed", "validated_reads": 90, "total_reads": 100, "species": "A"},
            {"status": "confirmed", "species": "B"},  # no read counts
            {"status": "confirmed", "validated_reads": "bad", "total_reads": "data", "species": "C"},
        ]
        c = _compute_summary(results)
        # Only the first result contributes; the others are skipped silently.
        assert c["reads_validated"] == 90
        assert c["reads_total"] == 100
        # Status counts still reflect all three
        assert c["confirmed"] == 3

    def test_empty_results(self):
        from nanometa_live.app.tabs.validation_tab import _compute_summary
        c = _compute_summary([])
        assert c["confirmed"] == 0
        assert c["reads_validated"] == 0
        assert c["reads_total"] == 0


# ---------------------------------------------------------------------------
# create_validation_status_card renders the aggregate row
# ---------------------------------------------------------------------------


def _walk(component):
    """Yield every Dash component in the tree (BFS)."""
    if component is None:
        return
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        yield from _walk(c)


def _flatten_text(component):
    """Concatenate all string content found in the tree."""
    parts = []
    for node in _walk(component):
        if isinstance(node, str):
            parts.append(node)
            continue
        text = getattr(node, "children", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts)


class TestStatusCardRendersReadAggregate:
    def test_card_shows_absolute_counts_and_percentage(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_status_card,
        )
        card = create_validation_status_card(
            confirmed=3, partial=1, low_confidence=0, no_data=0, total=4,
            reads_validated=180, reads_total=240,
        )
        text = _flatten_text(card)
        assert "180" in text
        assert "240" in text
        # 180/240 = 75.0%
        assert "75.0%" in text
        # The "of" connector appears
        assert "of" in text

    def test_zero_reads_total_shows_no_data_message(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_status_card,
        )
        card = create_validation_status_card(
            confirmed=0, partial=0, low_confidence=0, no_data=2, total=2,
            reads_validated=0, reads_total=0,
        )
        text = _flatten_text(card)
        assert "no validation data" in text

    def test_default_kwargs_back_compat(self):
        # Older callers that didn't pass reads_validated / reads_total
        # should still get a renderable card.
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_status_card,
        )
        card = create_validation_status_card(
            confirmed=1, partial=0, low_confidence=0, no_data=0, total=1,
        )
        text = _flatten_text(card)
        # Falls into the "no validation data" branch when reads_total is 0
        assert "no validation data" in text


# ---------------------------------------------------------------------------
# create_validation_result_card shows per-species absolute + %
# ---------------------------------------------------------------------------


class TestResultCardShowsAbsoluteAndPercentage:
    def test_card_renders_x_of_y_format(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_result_card,
        )
        card = create_validation_result_card(
            species="Bacillus anthracis",
            taxid=1392,
            status="confirmed",
            percent_validated=90.0,
            percent_identity=96.5,
            total_reads=100,
            validated_reads=90,
            sample_id="barcode01",
            validation_method="blast",
        )
        text = _flatten_text(card)
        # Headline: absolute count
        assert "90 of 100" in text
        # Subheading: percentage
        assert "(90.0%)" in text
        # Identity also present
        assert "96.5%" in text

    def test_minimap2_card_shows_mapping_confidence_with_scale(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_result_card,
        )
        card = create_validation_result_card(
            species="Escherichia coli",
            taxid=562,
            status="confirmed",
            percent_validated=80.0,
            percent_identity=95.0,
            total_reads=200,
            validated_reads=160,
            sample_id="barcode02",
            validation_method="minimap2",
            avg_mapq=42.0,
        )
        text = _flatten_text(card)
        assert "160 of 200" in text
        assert "(80.0%)" in text
        # Mapping Confidence with /60 scale
        assert "42 / 60" in text
        assert "30+ reliable" in text

    def test_blast_card_shows_read_alignment_pct(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_result_card,
        )
        card = create_validation_result_card(
            species="Listeria monocytogenes",
            taxid=1639,
            status="partial",
            percent_validated=55.0,
            percent_identity=92.0,
            total_reads=80,
            validated_reads=44,
            coverage=0.65,  # 65% read alignment
            sample_id="barcode03",
            validation_method="blast",
        )
        text = _flatten_text(card)
        assert "44 of 80" in text
        assert "(55.0%)" in text
        # Read Alignment % is rendered as 65.0%
        assert "65.0%" in text

    def test_card_handles_zero_reads(self):
        from nanometa_live.app.layouts.validation_layout import (
            create_validation_result_card,
        )
        card = create_validation_result_card(
            species="Salmonella",
            taxid=28901,
            status="no_data",
            percent_validated=0.0,
            percent_identity=0.0,
            total_reads=0,
            validated_reads=0,
            sample_id="barcode04",
        )
        text = _flatten_text(card)
        # No raise; renders 0 of 0 explicitly so the operator can see the
        # gap rather than a silent omission.
        assert "0 of 0" in text
        assert "(0.0%)" in text
