"""Confirmatory validation, asserted against real BLAST and minimap2 output.

Classification says an organism is *probably* present; validation is what
turns that into a callable result by aligning the assigned reads back to a
reference genome. It is the product's confirmatory claim, and its failure mode
is the worst one available here: a **false negative on a select agent**, where
the pipeline runs green, the dashboard renders, and the confirmation silently
never happened.

Validation has 21 unit-test files, all against synthetic fixtures. Until this
module it had never been run against real ONT reads at all -- every round-1 run
set ``run_validation: false``.

Sample map, from the Bioshield truth set:

===========  ===========================================================
barcode11    Francisella tularensis LVS, near-pure. Taxid 263 must
             CONFIRM here.
barcode14    ZymoBIOMICS D6300, which contains no select agent. Taxid
             263 must NOT confirm.
barcode16    Negative control. Carries 6 reads of taxid 263 from
             lab-side index hopping (round 1 proved it is not barcode
             leakage); those must not survive confirmation.
===========  ===========================================================

Run with::

    NANOMETA_REALDATA_DIR=/path/to/results/R8 pytest tests/realdata/test_validation.py -v
"""

from __future__ import annotations

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationStatus,
)

pytestmark = pytest.mark.integration

TULARENSIS = 263

#: Statuses that mean "this organism is confirmed present".
CONFIRMING = {ValidationStatus.CONFIRMED, ValidationStatus.PARTIAL}


@pytest.fixture(scope="module")
def validation_results(results_dir):
    """Every validation result in the tree, or skip if none were produced."""
    if not (results_dir / "validation").is_dir():
        pytest.skip(
            f"no validation/ directory under {results_dir}; the run was made "
            f"with run_validation disabled"
        )
    results = ValidationParser(str(results_dir)).get_validation_results()
    if not results:
        pytest.skip("validation/ exists but the parser returned no results")
    return results


def _for(results, sample=None, taxid=None, method=None):
    out = results
    if sample is not None:
        out = [r for r in out if r.sample_id == sample]
    if taxid is not None:
        out = [r for r in out if int(r.taxid) == taxid]
    if method is not None:
        out = [r for r in out if method in (r.validation_method or "").lower()]
    return out


class TestTheConfirmatoryClaim:
    """barcode11 is a near-pure LVS culture. Confirmation must succeed."""

    def test_the_select_agent_is_validated_in_the_positive_control(
        self, validation_results
    ):
        hits = _for(validation_results, sample="barcode11", taxid=TULARENSIS)
        assert hits, (
            "no validation result of any kind for F. tularensis in the LVS "
            "positive control. Classification found 34,096 reads of it; if "
            "validation produced nothing, the confirmatory step silently did "
            "not run for the one organism it most needed to."
        )

    def test_the_positive_control_actually_confirms(self, validation_results):
        hits = _for(validation_results, sample="barcode11", taxid=TULARENSIS)
        statuses = {r.status for r in hits}
        assert statuses & CONFIRMING, (
            f"F. tularensis did not confirm in a near-pure LVS culture; "
            f"statuses were {[s.value if hasattr(s, 'value') else s for s in statuses]}. "
            f"That is a false negative on a Tier 1 select agent."
        )

    def test_validated_reads_are_a_real_fraction_of_the_assigned_reads(
        self, validation_results
    ):
        """Guards against a confirmation built on almost no evidence."""
        hits = _for(validation_results, sample="barcode11", taxid=TULARENSIS)
        confirming = [r for r in hits if r.status in CONFIRMING]
        if not confirming:
            pytest.skip("nothing confirmed; covered by the test above")
        best = max(confirming, key=lambda r: r.validated_reads or 0)
        assert (best.validated_reads or 0) > 0, (
            "a confirming result validated zero reads"
        )


class TestNoFalsePositives:
    """The other half. A detector that confirms everything confirms nothing."""

    def test_the_mock_community_does_not_confirm_the_select_agent(
        self, validation_results
    ):
        """D6300 contains no F. tularensis."""
        confirming = [
            r for r in _for(validation_results, sample="barcode14", taxid=TULARENSIS)
            if r.status in CONFIRMING
        ]
        assert not confirming, (
            f"F. tularensis was CONFIRMED in a mock community known not to "
            f"contain it: {[(r.validation_method, r.validated_reads) for r in confirming]}"
        )

    def test_the_negative_control_does_not_confirm_the_select_agent(
        self, validation_results
    ):
        """The most important negative in the set.

        The negative control carries 6 index-hopped reads of taxid 263, which
        is above the watchlist alert threshold of 5. Confirmation is the step
        that should stop those 6 reads from being reported as a finding. If it
        confirms them, the threshold question raised in round 1 becomes far
        more urgent.
        """
        confirming = [
            r for r in _for(validation_results, sample="barcode16", taxid=TULARENSIS)
            if r.status in CONFIRMING
        ]
        assert not confirming, (
            f"the negative control CONFIRMED F. tularensis from index-hopped "
            f"reads: {[(r.validation_method, r.validated_reads, r.total_reads) for r in confirming]}"
        )


class TestBothMethodsSurface:
    """BLAST and minimap2 are distinct methods for the same (sample, taxid).

    CLAUDE.md records a shipped bug where the aggregate JSON short-circuited
    the on-disk scan: a minimap2-only aggregate hid the BLAST results entirely,
    so the Coverage sub-tab populated while the BLAST sub-tab stayed empty. The
    regression test for it uses a synthetic fixture; this asserts the same
    property against a real tree, where the aggregator actually ran.
    """

    def test_both_method_classes_are_present_somewhere(self, validation_results):
        methods = {
            "minimap2" if "minimap2" in (r.validation_method or "").lower()
            else "blast"
            for r in validation_results
        }
        assert methods == {"blast", "minimap2"}, (
            f"the run requested validation_method 'both' but only {methods} "
            f"reached the parser; one method's results are being hidden"
        )

    def test_the_positive_control_carries_both_methods(self, validation_results):
        hits = _for(validation_results, sample="barcode11", taxid=TULARENSIS)
        methods = {
            "minimap2" if "minimap2" in (r.validation_method or "").lower()
            else "blast"
            for r in hits
        }
        assert methods == {"blast", "minimap2"}, (
            f"only {methods} present for the select agent in the positive "
            f"control; the operator would see one sub-tab populated and the "
            f"other empty, which is the exact reported symptom"
        )


class TestResultInvariants:
    """Properties that must hold of every result, whatever the biology."""

    def test_validated_never_exceeds_total(self, validation_results):
        """More confirmed reads than assigned reads is arithmetically wrong.

        This is the shape of the BLAST HSP double-counting bug: counting raw
        alignments rather than distinct query reads pushes the ratio above 1.
        """
        bad = [
            r for r in validation_results
            if (r.total_reads or 0) > 0
            and (r.validated_reads or 0) > (r.total_reads or 0)
        ]
        assert not bad, (
            "results where validated_reads exceeds total_reads: "
            + str([(r.sample_id, r.taxid, r.validated_reads, r.total_reads)
                   for r in bad[:5]])
        )

    def test_percent_validated_is_a_percentage(self, validation_results):
        bad = [r for r in validation_results
               if r.percent_validated is not None
               and not (0 <= r.percent_validated <= 100)]
        assert not bad, (
            "percent_validated outside [0, 100]: "
            + str([(r.sample_id, r.taxid, r.percent_validated) for r in bad[:5]])
        )

    def test_identity_values_are_percentages(self, validation_results):
        bad = [
            r for r in validation_results
            if r.percent_identity_mean is not None
            and not (0 <= r.percent_identity_mean <= 100)
        ]
        assert not bad, (
            "percent_identity_mean outside [0, 100]: "
            + str([(r.sample_id, r.taxid, r.percent_identity_mean) for r in bad[:5]])
        )

    def test_every_result_names_its_sample_and_method(self, validation_results):
        """A result the GUI cannot attribute is a result it cannot display."""
        bad = [r for r in validation_results
               if not r.sample_id or not r.validation_method]
        assert not bad, (
            f"{len(bad)} results are missing a sample id or method"
        )
