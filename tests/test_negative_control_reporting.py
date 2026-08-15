"""A watched organism found in a negative control must be stated, not implied.

A negative control carrying the organism the run is positive for is
diagnostic about the whole run: it is the signature of barcode crosstalk or
carryover, and it bears on how the positive counts should be read. Until now
the software knew which samples were controls and did nothing with it beyond
appending "(NC)" to a chip.

Measured on a real Bioshield run: barcode11 carried 34,096 Francisella
tularensis reads and barcode16, the negative control, carried 6 -- 0.0176% of
the positive, inside the usual index-hopping range, and the only organism in
that control above the discovery floor.

What is reported is the observation, never the cause. "6 reads, 0.02% of the
positive samples" is measured; "contamination" is a conclusion the tool is not
in a position to draw, and a genuinely contaminated control looks the same
from here.

A control is never allowed to suppress or downgrade a detection -- that would
mean discarding a positive on an inference.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.utils.attribution import build_pathogen_attribution

pytestmark = pytest.mark.unit

DETECTION = [{"name": "Francisella tularensis", "taxid": 263, "threshold": 5}]


def _rows(*specs):
    """(sample, reads, is_nc) -> attribution rows."""
    return {263: [
        {"sample": s, "reads": r, "abundance": 0.0, "is_negative_control": nc}
        for s, r, nc in specs
    ]}


class TestTheControlIsReported:
    def test_a_control_carrying_the_organism_is_named(self):
        attr = build_pathogen_attribution(
            DETECTION,
            _rows(("barcode11", 34096, False), ("barcode16", 6, True)),
        )[0]

        assert attr.negative_control_samples == ["barcode16"], (
            "the run's negative control carried the detected organism and the "
            "attribution did not say so"
        )

    def test_the_control_reads_are_carried(self):
        attr = build_pathogen_attribution(
            DETECTION,
            _rows(("barcode11", 34096, False), ("barcode16", 6, True)),
        )[0]

        assert attr.negative_control_reads == 6

    def test_the_ratio_to_the_positives_is_computed(self):
        """0.0176% -- the number that makes crosstalk assessable."""
        attr = build_pathogen_attribution(
            DETECTION,
            _rows(("barcode11", 34096, False), ("barcode16", 6, True)),
        )[0]

        assert attr.negative_control_fraction == pytest.approx(
            6 / 34096 * 100, rel=1e-3
        )

    def test_no_control_means_nothing_to_report(self):
        attr = build_pathogen_attribution(
            DETECTION, _rows(("barcode11", 34096, False)),
        )[0]

        assert attr.negative_control_samples == []
        assert attr.negative_control_reads == 0
        assert attr.negative_control_fraction is None

    def test_a_clean_control_is_not_named(self):
        """Only controls that actually carry the organism are reported."""
        attr = build_pathogen_attribution(
            DETECTION, _rows(("barcode11", 34096, False)),
        )[0]

        assert not attr.negative_control_samples


class TestTheDetectionIsNeverWeakened:
    def test_the_positive_sample_still_triggers(self):
        attr = build_pathogen_attribution(
            DETECTION,
            _rows(("barcode11", 34096, False), ("barcode16", 6, True)),
        )[0]

        assert "barcode11" in attr.samples, (
            "a detection was withheld because a control also carried the "
            "organism; a contaminated control does not make a positive go away"
        )

    def test_a_control_alone_still_resolves_the_detection(self):
        """Only the control carries it -- still reported, still attributed."""
        attr = build_pathogen_attribution(
            DETECTION, _rows(("barcode16", 6, True)),
        )[0]

        assert attr.resolved
        assert attr.negative_control_samples == ["barcode16"]

    def test_a_control_below_threshold_is_still_flagged_as_a_control(self):
        """NC status is independent of the alert threshold."""
        attr = build_pathogen_attribution(
            [{"name": "F. tularensis", "taxid": 263, "threshold": 1000}],
            _rows(("barcode11", 34096, False), ("barcode16", 6, True)),
        )[0]

        assert attr.negative_control_samples == ["barcode16"]
        assert "barcode16" in attr.below_threshold_samples


class TestTheBannerStatesIt:
    """The operator must see it without opening another tab."""

    @staticmethod
    def _text(*specs, threshold=5):
        from nanometa_live.core.utils.attribution import format_attribution_text
        attrs = build_pathogen_attribution(
            [{"name": "Francisella tularensis", "taxid": 263,
              "threshold": threshold}],
            _rows(*specs),
        )
        return format_attribution_text(attrs) or ""

    def test_the_control_is_named_in_the_banner_line(self):
        text = self._text(("barcode11", 34096, False), ("barcode16", 6, True))

        assert "barcode16" in text, (
            f"the negative control carrying the organism is not mentioned: "
            f"{text!r}"
        )

    def test_the_reads_and_fraction_are_shown(self):
        """The two numbers that let an operator judge crosstalk."""
        text = self._text(("barcode11", 34096, False), ("barcode16", 6, True))

        assert "6 reads" in text
        assert "0.02%" in text, f"fraction of the positives missing: {text!r}"

    def test_the_positive_sample_is_still_named_first(self):
        text = self._text(("barcode11", 34096, False), ("barcode16", 6, True))

        assert text.index("barcode11") < text.index("barcode16")
        assert "Triggered by" in text

    def test_no_control_leaves_the_line_unchanged(self):
        text = self._text(("barcode11", 34096, False))

        assert "negative control" not in text.lower()
        assert "barcode11" in text

    def test_it_states_the_observation_not_a_diagnosis(self):
        """Wording discipline: measured facts only.

        A control carrying the organism looks identical whether it is
        crosstalk or a genuinely contaminated control, so the banner must not
        assert either.
        """
        text = self._text(("barcode11", 34096, False), ("barcode16", 6, True))

        lowered = text.lower()
        for claim in ("contaminat", "carryover", "index hop", "false positive"):
            assert claim not in lowered, (
                f"the banner asserts a cause it cannot know ({claim!r}): {text!r}"
            )
