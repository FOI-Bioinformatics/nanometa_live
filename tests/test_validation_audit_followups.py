"""Three Validation-tab audit follow-ups (2026-08-18).

1. ``validation_method="both"`` produced a SECOND coverage entry for a pair
   that already had one. ``collect_minimap2_results`` deduped on the literal
   string ``"minimap2"`` while the rest of the parser dedups on the method
   CLASS, so a "both" result (written by on-demand validation, and by an
   aggregate entry that carries no per-entry method) never suppressed the
   on-disk stats file. The Coverage tab then rendered two cards for one
   organism, with conflicting numbers and the same pattern-matching DOM id.

2. The Coverage empty state could not tell "minimap2 never ran" from
   "minimap2 ran and found nothing": it classified by substring instead of
   the diagnostic code the BLAST side uses. Same doctrine -- a missing
   measurement must not render as a negative result.

3. A verdict of CONFIRMED rested on percentages alone, so three reads
   mapping at 99% identity confirmed an organism. Percentages are unstable
   at low n; a handful of reads is not a confirmation. (Genome breadth
   cannot carry this: ``avg_coverage`` from both pipeline modules is
   per-READ query coverage -- span/qlen for minimap2, qcovs for BLAST --
   not the fraction of the genome covered.)
"""

import json

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationResult,
    ValidationStatus,
)

pytestmark = pytest.mark.unit


class TestBothMethodDoesNotDuplicateCoverage:
    def _tree(self, tmp_path, method):
        mm2 = tmp_path / "validation" / "minimap2"
        mm2.mkdir(parents=True)
        (mm2 / "bc01_taxid263.minimap2_stats.json").write_text(json.dumps({
            "sample_id": "bc01", "taxid": 263, "total_reads": 100,
            "mapped_reads": 95, "hit_rate": 0.95, "avg_identity": 99.0,
            "avg_coverage": 0.9, "avg_mapq": 55,
        }))
        # An on-demand result claiming method="both" for the same pair.
        od = tmp_path / "on_demand_validation"
        od.mkdir(parents=True)
        (od / "bc01_263_validation.json").write_text(json.dumps({
            "sample_id": "bc01", "taxid": 263, "validation_method": method,
            "total_reads": 100, "validated_reads": 90,
            "percent_validated": 90.0, "percent_identity_mean": 98.0,
        }))
        return tmp_path

    def test_both_does_not_yield_two_coverage_entries(self, tmp_path):
        results = ValidationParser(
            str(self._tree(tmp_path, "both"))).get_validation_results()
        coverage = [r for r in results
                    if r.validation_method in ("minimap2", "both")]
        keys = [(r.sample_id, r.taxid) for r in coverage]
        assert len(keys) == len(set(keys)), (
            f"one organism produced {len(keys)} coverage entries: {keys} -- "
            "duplicate cards share a DOM id and show conflicting numbers")

    def test_blast_only_result_still_lets_minimap2_through(self, tmp_path):
        # The invariant that must not regress: BLAST and minimap2 are
        # different methods for the same pair and must both surface.
        results = ValidationParser(
            str(self._tree(tmp_path, "blast"))).get_validation_results()
        methods = {r.validation_method for r in results}
        assert "minimap2" in methods and "blast" in methods


class TestCoverageEmptyStateDiagnoses:
    def _empty_cb(self):
        from dash import Dash
        from tests.dash_test_utils import get_callback_fn
        from nanometa_live.app.tabs.validation_tab import (
            register_validation_callbacks,
        )
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_validation_callbacks(app)
        return get_callback_fn(app, "coverage-empty-message")

    def test_method_blast_only_says_minimap2_not_run(self):
        store = {"results": [], "status": {"code": "waiting",
                                           "message": "Waiting for results."}}
        _style, msg, _sec = self._empty_cb()(
            store, {"validation_method": "blast"})
        text = str(msg)
        assert "not run" in text.lower() or "not selected" in text.lower(), (
            "with validation_method=blast the coverage tab must say minimap2 "
            "was never run, not imply it ran and found nothing")

    def test_disabled_is_named(self):
        store = {"results": [], "status": {"code": "disabled",
                                           "message": "Validation is disabled."}}
        _style, msg, _sec = self._empty_cb()(store, {"validation_method": "both"})
        assert "Disabled" in str(msg)

    def test_missing_dbs_is_named(self):
        store = {"results": [], "status": {
            "code": "missing_dbs", "message": "Reference databases missing."}}
        _style, msg, _sec = self._empty_cb()(store, {"validation_method": "both"})
        assert "Databases" in str(msg) or "Reference" in str(msg), (
            "the coverage tab discarded the diagnosis the BLAST tab shows")


class TestConfirmationNeedsReadSupport:
    def _result(self, validated, total, identity=99.0, method="minimap2"):
        r = ValidationResult(
            sample_id="bc01", taxid=263, species="Ft",
            total_reads=total, validated_reads=validated,
            percent_validated=(validated / total * 100) if total else 0.0,
            percent_identity_mean=identity, validation_method=method,
        )
        r.status = r.determine_status()
        return r

    def test_three_reads_is_not_a_confirmation(self):
        r = self._result(3, 3)
        assert r.status != ValidationStatus.CONFIRMED, (
            "100% of 3 reads is not a confirmation -- percentages are "
            "unstable at low n")

    def test_ample_reads_still_confirm(self):
        assert self._result(950, 1000).status == ValidationStatus.CONFIRMED

    def test_at_the_floor_confirms(self):
        from nanometa_live.core.parsers.blast_validation_parser import (
            MIN_READS_FOR_CONFIRMED,
        )
        n = MIN_READS_FOR_CONFIRMED
        assert self._result(n, n).status == ValidationStatus.CONFIRMED

    def test_downgrade_is_not_a_negative_result(self):
        # It must land on a state that still shows evidence, never NO_DATA.
        r = self._result(3, 3)
        assert r.status in (ValidationStatus.PARTIAL,
                            ValidationStatus.LOW_CONFIDENCE,
                            ValidationStatus.UNCERTAIN)

    def test_blast_method_uses_the_same_floor(self):
        assert self._result(4, 4, method="blast").status != ValidationStatus.CONFIRMED
