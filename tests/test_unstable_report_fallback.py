"""A mid-rewrite report must not drop its sample from the aggregate.

Observed live on the 2026-08-19 realtime banner audit: the dashboard's
cumulative tiles ran BACKWARDS mid-run (Sequences Analyzed 3,943 -> 1,393 ->
9,394; Species Detected 140 -> 139; "above alert threshold" 6 -> 4 -> 8).
nanometanf rewrites each sample's cumulative report per batch; when a poll
lands inside the ~1 s write window, ``_parse_kraken2_report`` returned None
for that sample and the "All Samples" union silently lost the whole barcode
for a poll or two. On a screening dashboard that reads as detections
disappearing.

The parser now keeps the last successful parse per physical report and
serves it when the current file state is transiently unparseable (unstable,
empty, mid-write). For a cumulative report the previous snapshot is strictly
better than dropping the sample. A path with no prior good parse still
returns None, and a file the report-finder no longer lists is never resurrected
(the fallback only answers for paths the caller still asks about).
"""

import os
import time

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import classification_loaders as cl


REPORT = """\
 50.00\t100\t10\tU\t0\tunclassified
 50.00\t100\t0\tR\t1\troot
 50.00\t100\t100\tS\t1392\t  Bacillus anthracis
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    cl.clear_report_frame_cache()
    yield
    cl.clear_report_frame_cache()


def _write_stable(path, content=REPORT):
    path.write_text(content)
    old = time.time() - 60
    os.utime(path, (old, old))


class TestLastGoodFallback:
    def test_unstable_rewrite_serves_the_last_good_parse(self, tmp_path):
        report = tmp_path / "barcode11.cumulative.kraken2.report.txt"
        _write_stable(report)
        first = cl._parse_kraken2_report(str(report))
        assert first is not None

        # The per-batch rewrite: fresh mtime puts the file inside the
        # stability window, where the parse used to return None.
        report.write_text(REPORT)  # mtime = now
        during = cl._parse_kraken2_report(str(report))
        assert during is not None, (
            "a mid-rewrite report dropped its sample from the aggregate -- "
            "cumulative dashboard counters ran backwards (2026-08-19 banner "
            "audit)"
        )
        assert during["taxid"].tolist() == first["taxid"].tolist()

    def test_no_prior_parse_still_returns_none(self, tmp_path):
        report = tmp_path / "barcode11.cumulative.kraken2.report.txt"
        report.write_text(REPORT)  # unstable, never parsed successfully
        assert cl._parse_kraken2_report(str(report)) is None

    def test_stable_rewrite_replaces_the_fallback(self, tmp_path):
        report = tmp_path / "barcode11.cumulative.kraken2.report.txt"
        _write_stable(report)
        cl._parse_kraken2_report(str(report))

        grown = REPORT + " 60.00\t200\t200\tS\t1773\t  Mycobacterium tuberculosis\n"
        _write_stable(report, grown)
        after = cl._parse_kraken2_report(str(report))
        assert after is not None
        assert 1773 in after["taxid"].tolist(), (
            "the fallback must not shadow a newer stable parse"
        )

    def test_stability_skipping_mode_untouched(self, tmp_path):
        # check_stability=False is the test-only raw path; it must neither
        # feed nor consult the last-good map.
        report = tmp_path / "barcode11.cumulative.kraken2.report.txt"
        report.write_text("")  # empty: unparseable
        assert cl._parse_kraken2_report(str(report), check_stability=False) is None


class TestAggregateStaysMonotonic:
    def test_union_keeps_a_sample_whose_report_is_mid_rewrite(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        b11 = kraken / "barcode11.cumulative.kraken2.report.txt"
        b14 = kraken / "barcode14.cumulative.kraken2.report.txt"
        _write_stable(b11)
        _write_stable(b14)

        first = cl.load_kraken_data(str(tmp_path), "All Samples")
        total_before = first["cumul_reads"].sum()

        # barcode11's report is being rewritten right now. Clear the
        # higher-level result caches so the union genuinely re-parses (the
        # per-file last-good map deliberately survives).
        b11.write_text(REPORT)
        from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
        with_last_good = dict(cl._last_good_frame)
        clear_all_loader_caches()
        cl._report_frame_cache.clear()
        cl._last_good_frame.update(with_last_good)
        again = cl.load_kraken_data(str(tmp_path), "All Samples")
        assert again["cumul_reads"].sum() == total_before, (
            "the aggregate lost a barcode during its per-batch report rewrite"
        )
