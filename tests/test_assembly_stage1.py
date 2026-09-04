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


class TestRealtimeOverrideReachesTheOperator:
    """Dropping assembly in real time used to be a log line only."""

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

    def test_the_drop_is_announced(self, tmp_path):
        params, warnings = self._params(tmp_path)
        assert params.get("enable_assembly") is False
        assert any("assembly is switched off" in w.lower() for w in warnings), warnings

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
