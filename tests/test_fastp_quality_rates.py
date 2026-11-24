"""One computation of Q20/Q30/GC for the QC card and the QC export.

The export read fastp keys the loader does not produce (q20_rate,
q30_rate, gc_content) and wrote "N/A" while the card showed 89.0% / 78.9% /
50.6% (live test 2026-11-24). Both now use fastp_quality_rates.
"""

import pytest

from nanometa_live.app.tabs.qc_tab_helpers import fastp_quality_rates

pytestmark = pytest.mark.unit


def _payload(bases, q20, q30, gc):
    return {"summary": {"after_filtering": {
        "total_bases": bases, "q20_bases": q20, "q30_bases": q30, "gc_content": gc}}}


def test_rates_are_base_weighted():
    rates = fastp_quality_rates([_payload(1000, 900, 800, 0.5),
                                 _payload(3000, 2400, 1800, 0.4)])
    assert rates["q20"] == pytest.approx(3300 / 4000 * 100)
    assert rates["q30"] == pytest.approx(2600 / 4000 * 100)
    assert rates["gc"] == pytest.approx((0.5 * 1000 + 0.4 * 3000) / 4000 * 100)


def test_missing_quality_fields_are_none():
    rates = fastp_quality_rates([{"summary": {"after_filtering": {"total_bases": 1000}}}])
    assert rates["q20"] is None and rates["q30"] is None
