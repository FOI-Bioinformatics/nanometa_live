"""A negative control named the obvious way must be recognised.

``is_negative_control`` deliberately refuses to match "negative" as a bare
substring, because that flags ``negative_strand_test`` -- a real sample, not a
control. The rule it settled on was "negative needs a control word beside it,
or to stand alone".

That excluded the most natural name an operator actually uses. On a real
Bioshield run the control was ``negative_barcode16.fastq.gz``; the token set
is {negative, barcode16}, with no control word and more than one token, so it
came back False. The sample was then treated as a clinical one -- and it
carried 6 Francisella tularensis reads out of 11 total, enough to clear that
entry's alert_threshold of 5.

What separates the two cases is what sits beside "negative": a sample
identifier (``barcode16``, ``03``, ``sample 3``) or a biological term
(``strand``). Only the first is a control.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.utils.attribution import is_negative_control

pytestmark = pytest.mark.unit


class TestNamesThatAreControls:
    @pytest.mark.parametrize("name", [
        "negative_barcode16",   # the real-world case that prompted this
        "negative_barcode01",
        "neg_barcode03",
        "negative_bc12",
        "negative_01",
        "neg_1",
        "negative_sample_3",
        "NEGATIVE_BARCODE16",   # case must not matter
        "negative-barcode16",   # nor separator
    ])
    def test_negative_beside_a_sample_identifier(self, name):
        assert is_negative_control(name, {}), (
            f"{name!r} is an operator's negative control and was treated as a "
            f"clinical sample"
        )

    @pytest.mark.parametrize("name", [
        "NTC", "ntc", "nc", "blank", "neg_ctrl", "negative_control",
        "negcontrol", "no_template_control", "negative",
    ])
    def test_the_existing_forms_still_match(self, name):
        assert is_negative_control(name, {})


class TestNamesThatAreNot:
    @pytest.mark.parametrize("name", [
        "negative_strand_test",   # the false positive the rule exists to avoid
        "negative_strand",
        "neg_strand_rna",
        "gram_negative_isolate",
        "barcode16",
        "patient_04",
        "",
    ])
    def test_not_flagged(self, name):
        assert not is_negative_control(name, {}), (
            f"{name!r} was flagged as a negative control; a real sample "
            f"excluded from screening is a missed detection"
        )

    def test_a_biological_term_is_not_a_sample_identifier(self):
        """The distinction the whole rule rests on.

        'strand' is a word about the molecule; 'barcode16' names a sample.
        Only the second makes 'negative' mean 'control'.
        """
        assert is_negative_control("negative_barcode16", {})
        assert not is_negative_control("negative_strand_test", {})


class TestTheExplicitListStillWins:
    def test_a_declared_sample_is_a_control_whatever_it_is_called(self):
        cfg = {"negative_control_samples": ["barcode16"]}

        assert is_negative_control("barcode16", cfg)

    def test_declaring_others_does_not_disable_the_patterns(self):
        cfg = {"negative_control_samples": ["barcode99"]}

        assert is_negative_control("negative_barcode16", cfg)
