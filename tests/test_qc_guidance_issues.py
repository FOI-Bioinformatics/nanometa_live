"""QC guidance judges a pass rate only where one was measured.

update_qc_action_guidance took seqkit read count / Kraken2 read total as the
pass rate on chopper runs (both count FILTERED reads) and 0 when seqkit was
absent, so every sample of a NanoPlot-only run read "Action needed: Pass
rate is below 60% ... Re-sequencing may be needed" at 75% classified (live
test 2026-11-24). The "Fewer than 1,000 sequences" note was gated on the
same pre-filter count, so it never fired on chopper runs.
"""

import pytest

from nanometa_live.app.tabs.qc_tab_helpers import qc_guidance_issues

pytestmark = pytest.mark.unit


def test_no_pre_filter_count_means_no_pass_rate_judgement():
    issues, action = qc_guidance_issues(pre_filter=None, passed=5000,
                                        classified=3750, total_classified_input=5000)
    assert not any("Pass rate" in i for i in issues)
    assert action is False


def test_measured_low_pass_rate_is_an_action():
    issues, action = qc_guidance_issues(pre_filter=10000, passed=5000,
                                        classified=4000, total_classified_input=5000)
    assert any("below 60%" in i for i in issues)
    assert action is True


def test_few_sequences_uses_what_was_sequenced_or_classified():
    issues, _ = qc_guidance_issues(pre_filter=None, passed=600,
                                   classified=500, total_classified_input=600)
    assert any("Fewer than 1,000" in i for i in issues)


def test_low_classification_is_an_action():
    issues, action = qc_guidance_issues(pre_filter=None, passed=5000,
                                        classified=1000, total_classified_input=5000)
    assert any("40%" in i for i in issues)
    assert action is True
