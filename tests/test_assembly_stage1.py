"""Stage 1 of the assembly audit: nothing is claimed that is not true.

The audit (docs/audit/assembly-2026-09-03.md) found the feature could run,
succeed and publish a number that was not a result, and that a failed assembly
reached no surface at all. These pin the GUI half of the repair.
"""

from pathlib import Path

import pytest

from nanometa_live.app.tabs.reports_helpers import (
    LOW_COVERAGE_ASSEMBLY,
    build_assembly_panel,
)


def _text(component) -> str:
    return str(component)


def _stats(coverage=40.0, n=3):
    return {
        "sample": "barcode05",
        "summary": {"total_contigs": n, "total_length": 570013,
                    "largest_contig": 38949, "n50": 12368, "l50": 15,
                    "circular_contigs": 3, "gc_content": 0.369},
        "contigs": [{"name": f"contig_{i}", "length": 1000 + i,
                     "coverage": coverage, "is_circular": False,
                     "gc_content": 0.37} for i in range(n)],
    }


class TestPanelNeverRendersNothing:
    """Off, failed, awaiting and produced must be distinguishable.

    The panel returned "" for an empty list, with a docstring reading
    "assembly not run, render nothing", so a run with assembly off and a run
    whose assemblies all failed looked identical: blank (audit A4).
    """

    def test_disabled_says_so(self):
        out = build_assembly_panel([], enabled=False)
        assert out != ""
        assert "not enabled" in _text(out).lower()

    def test_failed_names_the_tasks(self):
        out = build_assembly_panel([], enabled=True,
                                   failed_samples=["barcode05", "barcode06"])
        text = _text(out)
        assert "failed" in text.lower()
        assert "barcode05" in text and "barcode06" in text

    def test_enabled_but_no_results_yet(self):
        out = build_assembly_panel([], enabled=True)
        assert out != "" and "no results yet" in _text(out).lower()

    def test_unknown_state_still_renders(self):
        out = build_assembly_panel([])
        assert out != "" and "not produced" in _text(out).lower()

    @pytest.mark.parametrize("kwargs", [
        {"enabled": False}, {"enabled": True},
        {"enabled": True, "failed_samples": ["b1"]}, {},
    ])
    def test_no_state_is_empty(self, kwargs):
        assert build_assembly_panel([], **kwargs) != ""

    def test_the_four_states_are_distinguishable(self):
        seen = {
            _text(build_assembly_panel([], enabled=False)),
            _text(build_assembly_panel([], enabled=True)),
            _text(build_assembly_panel([], enabled=True, failed_samples=["b1"])),
            _text(build_assembly_panel([])),
        }
        assert len(seen) == 4


class TestDepthIsShown:
    """Coverage is the number that says whether the others mean anything.

    Flye states it in its own log and the canonical writer keeps it per
    contig, but the summary block carries only contigs/length/N50/circular/GC
    and the KPI row renders exactly the summary. Measured on a real run: 63
    contigs at an N50 of 12,368, built at a median coverage of 4.
    """

    def test_median_depth_appears_as_a_kpi(self):
        out = _text(build_assembly_panel([_stats(coverage=40.0)], enabled=True))
        assert "Median depth" in out
        assert "40x" in out

    def test_low_coverage_is_called_fragments(self):
        out = _text(build_assembly_panel([_stats(coverage=4.0)], enabled=True))
        assert "fragments rather than a genome" in out
        assert "4x" in out

    def test_adequate_coverage_gets_no_warning(self):
        out = _text(build_assembly_panel([_stats(coverage=40.0)], enabled=True))
        assert "fragments rather than a genome" not in out

    def test_missing_coverage_does_not_claim_zero(self):
        stats = _stats()
        for c in stats["contigs"]:
            c.pop("coverage")
        out = _text(build_assembly_panel([stats], enabled=True))
        assert "fragments rather than a genome" not in out
        assert "0x" not in out.replace("10x", "")

    def test_threshold_is_below_the_usable_floor(self):
        assert 0 < LOW_COVERAGE_ASSEMBLY < 30


class TestRealtimeAssemblyRuns:
    """Assembly is no longer dropped in real time.

    It used to run on every arriving file and publish each result over the
    last, so the launch switched it off (round-5 C8, assembly audit A3). The
    pipeline now accumulates a sample's reads and re-assembles on a cadence,
    so the operator's switch is honoured.
    """

    def _params(self, tmp_path, **over):
        from nanometa_live.core.config.parameter_mapping import (
            create_nextflow_params, pop_launch_warnings,
        )
        pop_launch_warnings()
        inbox = tmp_path / "in"; inbox.mkdir(exist_ok=True)
        (inbox / "s.fastq.gz").write_bytes(b"@r\nACGT\n+\n!!!!\n")
        res = tmp_path / "out"; res.mkdir(exist_ok=True)
        cfg = {"nanopore_output_directory": str(inbox),
               "results_output_directory": str(res),
               "kraken_db": str(tmp_path / "db"),
               "processing_mode": "realtime", "sample_handling": "by_barcode",
               "analysis_name": "t", "blast_validation": False,
               "enable_assembly": True}
        cfg.update(over)
        params = create_nextflow_params(cfg)
        return params, pop_launch_warnings()

    def test_the_switch_is_honoured(self, tmp_path):
        params, _warnings = self._params(tmp_path)
        assert params.get("enable_assembly") is True

    def test_the_cadence_reaches_the_launch(self, tmp_path):
        params, _w = self._params(tmp_path, assembly_batch_interval=25)
        assert params.get("assembly_batch_interval") == 25

    def test_it_is_no_longer_overridden(self, tmp_path):
        _params, warnings = self._params(tmp_path)
        assert not [w for w in warnings if "switched off" in w.lower()], warnings

    def test_no_warning_when_assembly_was_not_asked_for(self, tmp_path):
        _params, warnings = self._params(tmp_path, enable_assembly=False)
        assert not [w for w in warnings if "assembly" in w.lower()]


class TestMiniasmWithdrawnFromTheGui:
    """It writes no canonical output, so the Reports tab the form named stayed
    blank, and it has no bioconda build for Apple Silicon."""

    def test_the_select_offers_flye_only(self):
        src = (Path(__file__).resolve().parents[1] / "nanometa_live" / "app" /
               "components" / "config_form.py").read_text()
        block = src[src.index('id="assembler-input"'):]
        block = block[:block.index("dbc.FormText")]
        assert '"value": "flye"' in block
        assert '"value": "miniasm"' not in block

    def test_a_saved_miniasm_shows_flye(self, tmp_path):
        from unittest.mock import MagicMock
        from dash import Dash
        from tests.dash_test_utils import get_callback_fn
        from nanometa_live.app.tabs.config_tab import register_config_callbacks
        from nanometa_live.core.config.config_loader import default_config
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_config_callbacks(app, MagicMock())
        for cb_id, spec in app.callback_map.items():
            if "config-form-initialized" in cb_id and any(
                    "refresh-form-trigger" in str(i.get("id")) for i in spec["inputs"]):
                out_ids = [o.rsplit(".", 1)[0] for o in cb_id.strip(".").split("...")]
                fn = getattr(spec["callback"], "__wrapped__", spec["callback"])
                break
        cfg = dict(default_config()); cfg["assembler"] = "miniasm"
        values = dict(zip(out_ids, fn(1, cfg, None)))
        assert values["assembler-input"] == "flye"


# --- Stage 2: the decision record reaches the operator ----------------------


class TestDeclinedIsAResultNotAnAbsence:
    """The pipeline measures and may say no. That is a measurement.

    On a real field corpus nothing reached 2x of its reference where a draft
    needs 30x, so declining is the normal answer and the operator needs the
    arithmetic, not an empty panel (assembly audit, Stage 2).
    """

    DECLINED = [{
        "sample": "barcode06", "taxid": 4007169, "scope": "targeted",
        "decision": "declined", "reason": "insufficient_depth",
        "reason_text": "0.43 Mb assigned; 0.23x of a 1.87 Mb reference. "
                       "30x is needed for a usable draft.",
        "estimated_depth": 0.228, "required_depth": 30.0,
        "shortfall_bases": 55679797,
    }]

    def test_the_reason_and_the_shortfall_are_shown(self):
        out = _text(build_assembly_panel([], enabled=True, decisions=self.DECLINED))
        assert "not enough sequence" in out.lower()
        assert "barcode06" in out and "4007169" in out
        # The shortfall is what makes "keep sequencing" actionable -- and it
        # is stated once, not twice: the pipeline's own reason_text carries it.
        assert "56 Mb more" in out
        assert out.count("Mb more") == 1

    def test_a_progress_bar_shows_how_far_short(self):
        out = _text(build_assembly_panel([], enabled=True, decisions=self.DECLINED))
        assert "Progress" in out

    def test_declined_differs_from_disabled_and_from_failed(self):
        declined = _text(build_assembly_panel([], enabled=True, decisions=self.DECLINED))
        disabled = _text(build_assembly_panel([], enabled=False))
        failed = _text(build_assembly_panel([], enabled=True, failed_samples=["b1"]))
        assert len({declined, disabled, failed}) == 3

    def test_a_failure_outranks_a_decline(self):
        """A task that died is not the same as one that was never attempted."""
        out = _text(build_assembly_panel([], enabled=True, decisions=self.DECLINED,
                                         failed_samples=["barcode06"]))
        assert "failed" in out.lower()

    def test_an_attempt_decision_does_not_render_as_declined(self):
        out = _text(build_assembly_panel(
            [], enabled=True,
            decisions=[{"sample": "b1", "decision": "attempt", "reason": "attempt"}]))
        assert "not enough sequence" not in out.lower()


class TestDecisionLoader:
    def test_missing_and_unreadable_are_empty(self, tmp_path):
        from nanometa_live.core.utils.assembly_loader import load_assembly_decisions
        assert load_assembly_decisions(None) == []
        assert load_assembly_decisions(str(tmp_path)) == []
        d = tmp_path / "canonical" / "assembly"
        d.mkdir(parents=True)
        (d / "bad.assembly_decision.json").write_text("{not json")
        assert load_assembly_decisions(str(tmp_path)) == []

    def test_a_record_is_returned_with_its_sample(self, tmp_path):
        import json
        from nanometa_live.core.utils.assembly_loader import load_assembly_decisions
        d = tmp_path / "canonical" / "assembly"
        d.mkdir(parents=True)
        (d / "barcode05.taxid263.assembly_decision.json").write_text(json.dumps({
            "sample_id": "barcode05", "taxid": 263, "decision": "declined",
            "reason": "insufficient_depth"}))
        got = load_assembly_decisions(str(tmp_path))
        assert len(got) == 1
        assert got[0]["sample"] == "barcode05" and got[0]["taxid"] == 263

    def test_stats_and_decisions_do_not_collide(self, tmp_path):
        """Both live in canonical/assembly/; each loader takes only its own."""
        import json
        from nanometa_live.core.utils.assembly_loader import (
            load_assembly_decisions, load_assembly_stats,
        )
        d = tmp_path / "canonical" / "assembly"
        d.mkdir(parents=True)
        (d / "b1.assembly_stats.json").write_text(json.dumps(
            {"sample_id": "b1", "summary": {"total_contigs": 2}, "contigs": []}))
        (d / "b1.assembly_decision.json").write_text(json.dumps(
            {"sample_id": "b1", "decision": "attempt"}))
        assert len(load_assembly_stats(str(tmp_path))) == 1
        assert len(load_assembly_decisions(str(tmp_path))) == 1


class TestScopeReachesTheLaunch:
    def _params(self, tmp_path, **over):
        from nanometa_live.core.config.parameter_mapping import (
            create_nextflow_params, pop_launch_warnings,
        )
        pop_launch_warnings()
        inbox = tmp_path / "in"; inbox.mkdir(exist_ok=True)
        (inbox / "s.fastq.gz").write_bytes(b"@r\nACGT\n+\n!!!!\n")
        res = tmp_path / "out"; res.mkdir(exist_ok=True)
        cfg = {"nanopore_output_directory": str(inbox),
               "results_output_directory": str(res),
               "kraken_db": str(tmp_path / "db"),
               "processing_mode": "batch", "sample_handling": "per_file",
               "analysis_name": "t", "blast_validation": False,
               "enable_assembly": True}
        cfg.update(over)
        return create_nextflow_params(cfg), pop_launch_warnings()

    def test_scope_and_depth_are_sent(self, tmp_path):
        params, _w = self._params(tmp_path, assembly_scope="targeted",
                                  assembly_min_depth=25)
        assert params["assembly_scope"] == "targeted"
        assert params["assembly_min_depth"] == 25
        assert params["assembly_allow_low_depth"] is False

    def test_an_unknown_scope_is_coerced(self, tmp_path):
        params, _w = self._params(tmp_path, assembly_scope="nonsense")
        assert params["assembly_scope"] == "metagenome"

    def test_targeted_without_confirmation_testing_warns(self, tmp_path):
        _p, warnings = self._params(tmp_path, assembly_scope="targeted")
        assert any("targeted assembly needs confirmation testing" in w.lower()
                   for w in warnings), warnings

    def test_low_depth_override_warns(self, tmp_path):
        _p, warnings = self._params(tmp_path, assembly_allow_low_depth=True)
        assert any("fragments" in w.lower() for w in warnings), warnings

    def test_no_assembly_warnings_when_it_is_off(self, tmp_path):
        _p, warnings = self._params(tmp_path, enable_assembly=False,
                                    assembly_scope="targeted")
        assert not [w for w in warnings if "assembly" in w.lower()]


class TestExportedReportCarriesAssembly:
    """An exported run said nothing about assembly at all, including that it
    declined -- which is the usual outcome (assembly audit, Stage 2)."""

    def _results(self, tmp_path, stats=None, decisions=None):
        import json
        d = tmp_path / "canonical" / "assembly"
        d.mkdir(parents=True, exist_ok=True)
        for entry in (stats or []):
            (d / f"{entry['sample_id']}.assembly_stats.json").write_text(json.dumps(entry))
        for entry in (decisions or []):
            name = entry["sample_id"] + (f".taxid{entry['taxid']}" if entry.get("taxid") else "")
            (d / f"{name}.assembly_decision.json").write_text(json.dumps(entry))
        return tmp_path

    def _html(self, results_dir):
        from nanometa_live.core.export.report_generator import ReportGenerator
        g = ReportGenerator(str(results_dir), {"analysis_name": "T"})
        g.results_dir = str(results_dir)
        data = g._collect_data([None], include_raw=False)
        return g._build_html_report(data), data

    def test_collect_data_carries_both_keys(self, tmp_path):
        rd = self._results(tmp_path, decisions=[{
            "sample_id": "barcode06", "taxid": 4007169, "decision": "declined",
            "reason": "insufficient_depth", "reason_text": "0.23x of a 1.87 Mb reference."}])
        _html, data = self._html(rd)
        assert data["assembly"] == []
        assert len(data["assembly_decisions"]) == 1

    def test_a_declined_run_says_so(self, tmp_path):
        rd = self._results(tmp_path, decisions=[{
            "sample_id": "barcode06", "taxid": 4007169, "decision": "declined",
            "reason": "insufficient_depth",
            "reason_text": "0.43 Mb assigned; 0.23x of a 1.87 Mb reference."}])
        html, _d = self._html(rd)
        assert "<h2>Assembly</h2>" in html
        assert "declined" in html.lower()
        assert "barcode06" in html and "0.23x" in html

    def test_a_produced_assembly_shows_its_depth(self, tmp_path):
        rd = self._results(tmp_path, stats=[{
            "sample_id": "barcode05",
            "summary": {"total_contigs": 29, "total_length": 227821, "n50": 10041},
            "contigs": [{"coverage": 4.0}, {"coverage": 4.0}, {"coverage": 6.0}]}])
        html, _d = self._html(rd)
        assert "barcode05" in html and "10,041" in html
        # The depth is the number that says whether the rest mean anything.
        assert "4x" in html
        assert "fragments rather than" in html

    def test_a_deep_assembly_gets_no_fragments_warning(self, tmp_path):
        rd = self._results(tmp_path, stats=[{
            "sample_id": "barcode05",
            "summary": {"total_contigs": 3, "total_length": 4000000, "n50": 2000000},
            "contigs": [{"coverage": 45.0}, {"coverage": 50.0}]}])
        html, _d = self._html(rd)
        assert "fragments rather than" not in html

    def test_no_assembly_section_when_nothing_ran(self, tmp_path):
        html, _d = self._html(tmp_path)
        assert "<h2>Assembly</h2>" not in html


class TestAssemblyReadiness:
    """Two conditions make it certain no assembly will be produced, and both
    are knowable before the run starts."""

    @pytest.fixture
    def checker(self):
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker
        return ReadinessChecker()

    def test_realtime_says_assembly_will_not_run(self, checker):
        r = checker._check_assembly_preconditions(
            {"enable_assembly": True, "processing_mode": "realtime"})
        assert r.passed is False and "real-time" in r.message

    def test_targeted_without_confirmation_testing(self, checker):
        r = checker._check_assembly_preconditions(
            {"enable_assembly": True, "assembly_scope": "targeted",
             "blast_validation": False})
        assert r.passed is False
        assert "confirmation testing" in r.message
        assert "no assembly" in r.message

    def test_both_scope_still_gets_the_whole_sample(self, checker):
        r = checker._check_assembly_preconditions(
            {"enable_assembly": True, "assembly_scope": "both",
             "blast_validation": False})
        assert r.passed is False and "only the whole-sample" in r.message

    def test_a_workable_configuration_passes_and_states_the_floor(self, checker):
        r = checker._check_assembly_preconditions(
            {"enable_assembly": True, "assembly_scope": "metagenome",
             "processing_mode": "batch", "assembly_min_depth": 30})
        assert r.passed is True and "30x" in (r.details or "")

    def test_the_check_is_absent_when_assembly_is_off(self, checker, tmp_path):
        report = checker.check_readiness(
            {"enable_assembly": False, "processing_mode": "batch",
             "results_output_directory": str(tmp_path)})
        assert not [c for c in report.checks if c.name == "Assembly"]
