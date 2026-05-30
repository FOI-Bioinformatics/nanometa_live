"""
Unit tests for the pure helpers in app/tabs/dashboard_helpers.py (was 22%).

These private functions hold the dashboard's pure logic (file counting, rate
estimates, alert-badge colour, species-frame conversion, banner style). They are
deterministic and testable in isolation, independent of the Dash callbacks that
call them.
"""

import pandas as pd
import pytest

from nanometa_live.app.tabs.dashboard_helpers import (
    _count_input_files,
    _estimate_classified_rate,
    _estimate_pass_rate_from_quality,
    _get_alerts_badge_color,
    _species_df_to_organisms,
    _verdict_banner_style,
)

pytestmark = pytest.mark.unit


class TestCountInputFiles:
    def test_flat_directory(self, tmp_path):
        for n in ("a.fastq", "b.fastq.gz", "c.fq", "notes.txt"):
            (tmp_path / n).write_text("")
        assert _count_input_files(str(tmp_path)) == 3

    def test_barcoded_subdirs(self, tmp_path):
        bc = tmp_path / "barcode01"
        bc.mkdir()
        (bc / "r1.fastq").write_text("")
        (bc / "r2.fastq.gz").write_text("")
        assert _count_input_files(str(tmp_path)) == 2

    def test_missing_dir_returns_zero(self, tmp_path):
        assert _count_input_files(str(tmp_path / "nope")) == 0

    def test_empty_string(self):
        assert _count_input_files("") == 0


class TestEstimatePassRate:
    def test_none_defaults_to_100(self):
        assert _estimate_pass_rate_from_quality(None) == 100.0

    def test_clamped_to_range(self):
        assert _estimate_pass_rate_from_quality(150) == 100.0
        assert _estimate_pass_rate_from_quality(-5) == 0.0

    def test_passthrough(self):
        assert _estimate_pass_rate_from_quality(73) == 73.0


class TestEstimateClassifiedRate:
    def test_zero_organisms(self):
        assert _estimate_classified_rate(0) == 0.0

    def test_heuristic_increases_and_caps(self):
        assert _estimate_classified_rate(10) == 35.0  # 30 + 10*0.5
        assert _estimate_classified_rate(1000) == 100  # capped


class TestAlertsBadgeColor:
    def test_empty_secondary(self):
        assert _get_alerts_badge_color([]) == "secondary"

    @pytest.mark.parametrize(
        "severity,expected",
        [("critical", "danger"), ("danger", "danger"),
         ("warning", "warning"), ("info", "info")],
    )
    def test_severity_to_colour(self, severity, expected):
        assert _get_alerts_badge_color([{"severity": severity}]) == expected

    def test_highest_severity_wins(self):
        alerts = [{"severity": "info"}, {"severity": "critical"}, {"severity": "warning"}]
        assert _get_alerts_badge_color(alerts) == "danger"


class TestSpeciesDfToOrganisms:
    def test_empty_df(self):
        assert _species_df_to_organisms(pd.DataFrame()) == []

    def test_uses_percent_column(self):
        df = pd.DataFrame({
            "taxid": [562], "name": ["Escherichia coli"], "reads": [150], "%": [12.5],
        })
        out = _species_df_to_organisms(df)
        assert out == [{"taxid": 562, "name": "Escherichia coli", "reads": 150, "abundance": 12.5}]

    def test_fraction_column_scaled_to_percent(self):
        df = pd.DataFrame({
            "taxid": [1], "name": ["x"], "reads": [10], "fraction_total_reads": [0.25],
        })
        out = _species_df_to_organisms(df)
        assert out[0]["abundance"] == pytest.approx(25.0)


class TestVerdictBannerStyle:
    def test_colours_applied(self):
        style = _verdict_banner_style("#fee", "#f00")
        assert style["backgroundColor"] == "#fee"
        assert style["borderLeftColor"] == "#f00"
        assert "6px solid #f00" in style["borderLeft"]
