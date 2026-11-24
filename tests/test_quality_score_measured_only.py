"""The Dashboard quality score is measured or absent, never a length proxy.

With no seqkit Q20 and no NanoPlot mean quality, _estimate_quality_score
mapped average read length to a score (under 1 kb -> 50), and the alert
panel said "Overall quality is 50.0%" while the quality tile showed "--"
and the sample table "Good" (live test 2026-11-24).
"""

from unittest.mock import patch

import pandas as pd
import pytest

from nanometa_live.app.tabs import dashboard_helpers as dh

pytestmark = pytest.mark.unit


def test_no_measured_quality_gives_no_score(tmp_path):
    with patch.object(dh, "get_qc_stats", return_value={"source": "fastp", "avg_read_length": 800}), \
         patch.object(dh, "load_nanoplot_stats", return_value={}):
        assert dh._estimate_quality_score(str(tmp_path), pd.DataFrame()) is None


def test_no_score_raises_no_quality_alert():
    from nanometa_live.core.utils.alert_engine import AlertEngine
    alerts = AlertEngine()._check_qc_stats({
        "total_reads": 5000,
        "pass_rate": dh._estimate_pass_rate_from_quality(None),
        "classified_rate": 80.0,
    })
    assert not any("quality" in a.message.lower() for a in alerts)
