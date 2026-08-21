"""Regression tests for ``update_verdict_banner`` (Phase 5a / B2, Phase 3).

Two generations of bugs are pinned here.

*Phase 5a/B2* -- the per-sample-attribution branch referenced an
``available_samples`` name that was not a declared callback input. The
reference sat inside a try/except logging at DEBUG, so the ``NameError``
was swallowed: the banner rendered without the "Triggered by" subhead and
the operator never saw which barcode caused the alert.

*Phase 3* -- the attribution branch looked the detection up in
``taxid_to_samples`` under the watchlist entry's **NCBI** taxid, while
that dict is keyed by the **Kraken2 report** taxid. On an NCBI database
the two are the same, so the bug was invisible; on GTDB or a custom
database they differ and every lookup missed, again dropping the subhead
with no error. The original version of this file hard-coded
``taxid == kraken_taxid``, which is exactly why the bug survived.
The tests below therefore keep the two taxids deliberately distinct.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest
from dash import Dash

from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks


# -- Helpers --------------------------------------------------------------


def _state_ids(spec) -> list[str]:
    return [
        s.get("id") if isinstance(s, dict) else getattr(s, "component_id", None)
        for s in (spec.get("state", []) or [])
    ]


def _find_callback_by_output(app: Dash, output_id: str):
    """Return the callback spec whose output list includes ``output_id``."""
    for cb_id, spec in app.callback_map.items():
        if output_id in cb_id:
            return cb_id, spec
    return None, None


def _run_verdict_banner(
    tmp_path,
    *,
    detections,
    taxid_to_samples,
    available_samples,
    per_sample_side_effect=None,
):
    """Drive ``update_verdict_banner`` with mocked pathogen/attribution data.

    Returns the rendered outputs serialised to JSON so tests can assert on
    the text the operator actually sees.
    """
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_dashboard_callbacks(app)
    _, spec = _find_callback_by_output(app, "dashboard-verdict-banner")
    assert spec is not None, "Verdict-banner callback was not registered"
    callback_fn = getattr(spec["callback"], "__wrapped__", spec["callback"])

    results_dir = tmp_path / "results"
    (results_dir / "kraken2").mkdir(parents=True, exist_ok=True)
    config = {
        "results_output_directory": str(results_dir),
        "main_dir": str(results_dir),
    }
    status = {"running": True, "completed": False, "start_time": None}

    kraken_df = pd.DataFrame([
        {
            "perc": 99.0, "cumul_reads": 1000, "reads": 1000,
            "rank": "S", "taxid": 88888, "name": "Bacillus anthracis",
            "parent_taxid": 1,
        },
    ])

    per_sample_kwargs = (
        {"side_effect": per_sample_side_effect}
        if per_sample_side_effect is not None
        else {"return_value": taxid_to_samples}
    )

    with patch(
        "nanometa_live.app.tabs.dashboard_tab.load_kraken_data",
        return_value=kraken_df,
    ), patch(
        "nanometa_live.app.tabs.dashboard_tab._species_df_to_organisms",
        return_value=detections,
    ), patch(
        "nanometa_live.app.tabs.dashboard_tab._get_active_watchlist_entries",
        return_value=[{"taxid": 1392, "name": "Bacillus anthracis"}],
    ), patch(
        "nanometa_live.app.tabs.dashboard_tab._check_pathogens_both",
        return_value=(detections, []),
    ), patch(
        "nanometa_live.app.tabs.dashboard_tab._load_per_sample_organisms",
        **per_sample_kwargs,
    ), patch(
        "nanometa_live.app.tabs.dashboard_tab.interval_tick_is_redundant",
        return_value=False,
    ):
        outputs = callback_fn(
            "fp1", None, 0,
            config, status, {"status": "ok"}, {"results": []},
            available_samples,
        )

    assert outputs is not None
    return json.dumps(outputs, default=str)


def _sample(name, reads, abundance=5.0, is_nc=False):
    return {
        "sample": name,
        "reads": reads,
        "abundance": abundance,
        "is_negative_control": is_nc,
    }


# -- Wiring regression ---------------------------------------------------


class TestVerdictBannerCallbackWiring:
    def test_available_samples_is_a_state_input(self):
        """The verdict-banner callback must read ``available-samples``;
        otherwise the per-sample-attribution branch raises NameError on
        every render and the subhead silently disappears.
        """
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_dashboard_callbacks(app)

        cb_id, spec = _find_callback_by_output(app, "dashboard-verdict-banner")
        assert spec is not None, "Verdict-banner callback was not registered"
        assert "available-samples" in _state_ids(spec), (
            "Verdict-banner callback must include `available-samples` in its "
            "State list -- otherwise the per-sample attribution branch "
            "raises NameError under DEBUG-suppressed logging."
        )


# -- Behavioural regression ---------------------------------------------


class TestVerdictBannerAttributionRuns:
    """Drive the attribution branch end-to-end with an NCBI taxid that
    differs from the Kraken2 report taxid -- the GTDB / custom-database
    case the previous test never covered."""

    def test_gtdb_taxid_divergence_still_names_the_sample(self, tmp_path):
        detections = [{
            "taxid": 1392,           # NCBI taxid from the watchlist entry
            "detected_taxid": 88888,  # Kraken2 (GTDB) report taxid
            "name": "Bacillus anthracis",
            "threat_level": "critical",
            "reads": 1000,
            "threshold": 10,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            # Keyed by the Kraken2 taxid, as _load_per_sample_organisms builds it
            taxid_to_samples={88888: [_sample("barcode01", 1000)]},
            available_samples=["barcode01", "barcode02"],
        )
        assert "ACTION REQUIRED" in rendered
        assert "Above threshold" in rendered
        assert "Bacillus anthracis" in rendered
        # The attribution must survive the NCBI-vs-Kraken taxid divergence.
        assert "Triggered by" in rendered
        assert "barcode01" in rendered

    def test_ncbi_taxid_only_detection_still_attributes(self, tmp_path):
        """A detection carrying no ``detected_taxid`` (the check_organisms
        fallback path) must still resolve via the NCBI taxid."""
        detections = [{
            "taxid": 1392,
            "name": "Bacillus anthracis",
            "threat_level": "critical",
            "reads": 1000,
            "threshold": 10,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={1392: [_sample("barcode03", 1000)]},
            available_samples=["barcode03"],
        )
        assert "Triggered by" in rendered
        assert "barcode03" in rendered


class TestPathogenSamplePairing:
    """Two pathogens in two different barcodes must not collapse into one
    undifferentiated sample list."""

    def test_each_pathogen_names_its_own_samples(self, tmp_path):
        detections = [
            {
                "taxid": 1392, "detected_taxid": 88888,
                "name": "Bacillus anthracis", "threat_level": "critical",
                "reads": 900, "threshold": 10,
            },
            {
                "taxid": 632, "detected_taxid": 77777,
                "name": "Yersinia pestis", "threat_level": "high",
                "reads": 400, "threshold": 10,
            },
        ]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={
                88888: [_sample("barcode01", 900)],
                77777: [_sample("barcode07", 400)],
            },
            available_samples=["barcode01", "barcode07"],
        )
        assert "Bacillus anthracis (barcode01)" in rendered
        assert "Yersinia pestis (barcode07)" in rendered

    def test_pathogens_sorted_by_reads_descending(self, tmp_path):
        detections = [
            {
                "taxid": 632, "detected_taxid": 77777,
                "name": "Yersinia pestis", "threat_level": "critical",
                "reads": 50, "threshold": 10,
            },
            {
                "taxid": 1392, "detected_taxid": 88888,
                "name": "Bacillus anthracis", "threat_level": "critical",
                "reads": 5000, "threshold": 10,
            },
        ]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={
                77777: [_sample("barcode07", 50)],
                88888: [_sample("barcode01", 5000)],
            },
            available_samples=["barcode01", "barcode07"],
        )
        attribution = rendered.split("Triggered by")[1]
        assert attribution.index("Bacillus anthracis") < attribution.index(
            "Yersinia pestis"
        ), "Attribution must be ordered by read support, descending"


class TestPerSampleThreshold:
    """The positive verdict is decided on AGGREGATE reads against the
    pathogen's alert_threshold. A sample is only named as triggering when
    it clears that threshold on its own."""

    def test_ten_barcodes_below_threshold_are_not_named(self, tmp_path):
        detections = [{
            "taxid": 1392, "detected_taxid": 88888,
            "name": "Bacillus anthracis", "threat_level": "critical",
            "reads": 500,          # aggregate, above threshold
            "threshold": 100,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={
                88888: [_sample(f"barcode{i:02d}", 50) for i in range(1, 11)]
            },
            available_samples=[f"barcode{i:02d}" for i in range(1, 11)],
        )
        assert "ACTION REQUIRED" in rendered
        # No single barcode cleared 100 reads -- naming them would tell the
        # operator to pull ten samples that are each individually negative.
        assert "barcode01)" not in rendered
        assert "aggregate across 10 samples" in rendered

    def test_only_the_sample_above_threshold_is_named(self, tmp_path):
        detections = [{
            "taxid": 1392, "detected_taxid": 88888,
            "name": "Bacillus anthracis", "threat_level": "critical",
            "reads": 350, "threshold": 100,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={
                88888: [
                    _sample("barcode04", 300),
                    _sample("barcode05", 50),
                ]
            },
            available_samples=["barcode04", "barcode05"],
        )
        assert "Bacillus anthracis (barcode04)" in rendered
        assert "barcode05" not in rendered


class TestAttributionFailureIsVisible:
    """An unattributed positive must not look like a positive in one
    unnamed sample -- the operator has to know the difference."""

    def test_loader_exception_renders_an_explicit_note(self, tmp_path):
        detections = [{
            "taxid": 1392, "detected_taxid": 88888,
            "name": "Bacillus anthracis", "threat_level": "critical",
            "reads": 1000, "threshold": 10,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={},
            available_samples=["barcode01"],
            per_sample_side_effect=OSError("results directory vanished"),
        )
        assert "ACTION REQUIRED" in rendered
        assert "attribution unavailable" in rendered.lower()

    def test_no_matching_taxid_renders_an_explicit_note(self, tmp_path):
        """The loader succeeded but knows nothing about this taxid --
        still an attribution gap, not a silent omission."""
        detections = [{
            "taxid": 1392, "detected_taxid": 88888,
            "name": "Bacillus anthracis", "threat_level": "critical",
            "reads": 1000, "threshold": 10,
        }]
        rendered = _run_verdict_banner(
            tmp_path,
            detections=detections,
            taxid_to_samples={12345: [_sample("barcode01", 900)]},
            available_samples=["barcode01"],
        )
        assert "attribution unavailable" in rendered.lower()


class TestPathogenNaming:
    """`_make_banner_content` names the pathogens above threshold so the
    operator does not have to leave the dashboard to learn which organisms
    triggered ACTION REQUIRED."""

    def _render(self, triggering_pathogens):
        from nanometa_live.app.tabs.dashboard_helpers import _make_banner_content
        content = _make_banner_content(
            "exclamation-octagon-fill", "#dc3545",
            "ACTION REQUIRED", "3 of 35 watched pathogens above alert threshold",
            "ACTIVE", "00:05:00",
            triggering_pathogens=triggering_pathogens,
        )
        return json.dumps(content, default=str)

    def test_names_each_pathogen(self):
        rendered = self._render(["Bacillus anthracis", "Yersinia pestis"])
        assert "Above threshold" in rendered
        assert "Bacillus anthracis" in rendered
        assert "Yersinia pestis" in rendered

    def test_overflow_beyond_five_summarized(self):
        names = [f"Pathogen {i}" for i in range(8)]
        rendered = self._render(names)
        # First five named inline, the remaining three summarized.
        assert "Pathogen 0" in rendered
        assert "Pathogen 4" in rendered
        assert "(+3 more)" in rendered
        assert "Pathogen 7" not in rendered

    def test_no_block_when_empty(self):
        assert "Above threshold" not in self._render(None)
        assert "Above threshold" not in self._render([])
