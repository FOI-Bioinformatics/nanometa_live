"""The staleness registry: frozen data must announce itself.

Round-3 finding: a permanently corrupt kraken2 report is retried forever
and served from ``_last_good_frame`` indefinitely, at ``logging.debug`` --
the operator sees live-looking numbers for a sample whose data stopped
updating (the disk-full compound case: ENOSPC truncates reports, the
dashboard keeps rendering the last good parse as if it were current).

The registry records, per report path, when a parse last succeeded and
since when the last-good fallback has been served. The verdict banner
reads ``stale_sample_count`` to append "N samples serving stale data".
"""

import time

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import staleness


@pytest.fixture(autouse=True)
def _clean_registry():
    staleness.clear()
    yield
    staleness.clear()


MAIN = "/results/run1"


class TestRecording:
    def test_fresh_registry_reports_nothing_stale(self):
        assert staleness.stale_sample_count(MAIN) == 0

    def test_last_good_served_past_grace_is_stale(self):
        staleness.record_last_good_served(
            MAIN, "barcode01", when=time.time() - 999)
        assert staleness.stale_sample_count(MAIN, grace_seconds=30) == 1

    def test_within_grace_is_not_yet_stale(self):
        # A single transient mid-write miss must not flag the sample.
        staleness.record_last_good_served(MAIN, "barcode01")
        assert staleness.stale_sample_count(MAIN, grace_seconds=30) == 0

    def test_successful_parse_clears_the_flag(self):
        staleness.record_last_good_served(
            MAIN, "barcode01", when=time.time() - 999)
        staleness.record_parse_ok(MAIN, "barcode01")
        assert staleness.stale_sample_count(MAIN) == 0

    def test_first_served_timestamp_is_kept(self):
        # Repeated fallbacks must not slide the window forward -- staleness
        # is measured from the FIRST fallback, not the latest retry.
        t0 = time.time() - 999
        staleness.record_last_good_served(MAIN, "barcode01", when=t0)
        staleness.record_last_good_served(MAIN, "barcode01")
        assert staleness.stale_sample_count(MAIN, grace_seconds=30) == 1
        assert staleness.stale_entries(MAIN)[0].since == pytest.approx(t0)

    def test_scoped_to_the_results_dir(self):
        staleness.record_last_good_served(
            "/results/other", "barcode01", when=time.time() - 999)
        assert staleness.stale_sample_count(MAIN) == 0

    def test_counts_samples_not_paths(self):
        t = time.time() - 999
        staleness.record_last_good_served(MAIN, "barcode01", when=t)
        staleness.record_last_good_served(MAIN, "barcode01", when=t)
        staleness.record_last_good_served(MAIN, "barcode02", when=t)
        assert staleness.stale_sample_count(MAIN, grace_seconds=30) == 2


class TestClear:
    def test_clear_scoped(self):
        t = time.time() - 999
        staleness.record_last_good_served(MAIN, "a", when=t)
        staleness.record_last_good_served("/results/other", "b", when=t)
        staleness.clear(MAIN)
        assert staleness.stale_sample_count(MAIN) == 0
        assert staleness.stale_sample_count("/results/other",
                                            grace_seconds=30) == 1

    def test_clear_all(self):
        staleness.record_last_good_served(MAIN, "a", when=time.time() - 999)
        staleness.clear()
        assert staleness.stale_sample_count(MAIN) == 0


class TestLoaderIntegration:
    """The classification loader records into the registry: a corrupt
    report that falls back to last-good marks its sample stale; a
    successful re-parse clears it."""

    def _write_report(self, path, rows=3):
        lines = ["100.00\t100\t10\tR\t1\troot\n"]
        for i in range(rows):
            lines.append(
                f" 10.00\t{10+i}\t{10+i}\tS\t{100+i}\tSpecies organismus{i}\n")
        path.write_text("".join(lines))

    @pytest.fixture(autouse=True)
    def _fresh_loader_state(self):
        # The loader path is cache-layered (TTL, mtime, frame). Under the
        # full suite another test may have advanced the freshness epoch,
        # which lets the mtime cache serve without a filesystem check and
        # this test's rewrites never reach the parser. Epoch 0 = the
        # unconditional path (CLI/test semantics).
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.core.utils import classification_loaders as cl
        loader_utils.clear_all_loader_caches()
        loader_utils._freshness_epoch = 0
        cl.clear_report_frame_cache()
        yield

    def test_corrupt_rewrite_marks_stale_and_reparse_clears(self, tmp_path):
        import os
        from nanometa_live.core.utils import classification_loaders as cl

        report = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        report.parent.mkdir(parents=True)
        self._write_report(report)
        back = time.time() - 120
        os.utime(report, (back, back))

        df = cl.load_kraken_data(str(tmp_path), "barcode01")
        assert not df.empty
        assert staleness.stale_sample_count(str(tmp_path)) == 0

        # Corrupt the report (permanently truncated by a full disk).
        report.write_text("garbage\tnot\ta\treport")
        os.utime(report, (back + 1, back + 1))
        df2 = cl.load_kraken_data(str(tmp_path), "barcode01")
        assert not df2.empty, "last-good fallback must still serve data"
        entries = staleness.stale_entries(str(tmp_path), grace_seconds=0)
        assert len(entries) == 1

        # A good rewrite clears the flag.
        self._write_report(report, rows=4)
        os.utime(report, (back + 2, back + 2))
        cl.load_kraken_data(str(tmp_path), "barcode01")
        assert staleness.stale_sample_count(str(tmp_path),
                                            grace_seconds=0) == 0
