"""Harness for the time-to-first-result audit: a synthetic backlog and its analysis.

The builder makes N barcode directories with M files each from a small source
corpus by symlink, round-robin over the source barcodes, so a 24-barcode
backlog costs no disk and the sample ids are the directory names the pipeline
uses. The analyser (Task 2) reads the sampler's timeline and the pipeline
trace.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _source_corpus(tmp_path, barcodes=("barcode05", "barcode06"), files=3):
    src = tmp_path / "src"
    for bc in barcodes:
        d = src / bc
        d.mkdir(parents=True)
        for k in range(files):
            (d / f"reads_{bc}_{k}.fastq.gz").write_bytes(b"\x1f\x8b" + bytes([k]))
    return src


class TestBuildBacklog:
    def test_makes_n_barcodes_with_m_symlinks_each(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        out = tmp_path / "input"
        layout = build_backlog(src, out, barcodes=4, files_per_barcode=2, include_unclassified=False)
        assert sorted(layout) == ["barcode01", "barcode02", "barcode03", "barcode04"]
        for bc, files in layout.items():
            assert len(files) == 2
            for f in files:
                assert f.is_symlink() and f.resolve().is_file()
                assert f.parent.name == bc

    def test_sources_rotate_round_robin(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        layout = build_backlog(src, tmp_path / "input", barcodes=3, files_per_barcode=1, include_unclassified=False)
        origins = [layout[bc][0].resolve().parent.name for bc in sorted(layout)]
        assert origins == ["barcode05", "barcode06", "barcode05"]

    def test_refuses_more_files_than_the_source_has(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path, files=2)
        with pytest.raises(ValueError, match="only 2"):
            build_backlog(src, tmp_path / "input", barcodes=1, files_per_barcode=5, include_unclassified=False)

    def test_writes_a_layout_manifest(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path)
        out = tmp_path / "input"
        build_backlog(src, out, barcodes=2, files_per_barcode=2, include_unclassified=False)
        manifest = json.loads((out / "backlog_layout.json").read_text())
        assert manifest["barcodes"] == 2 and manifest["files_per_barcode"] == 2
        assert set(manifest["samples"]) == {"barcode01", "barcode02"}
        assert manifest["concat"] == 1

    def test_concat_makes_real_concatenated_files(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path, barcodes=("barcode05", "barcode06"), files=3)
        # Overwrite with distinct one-byte contents so concatenated sizes are checkable.
        one_byte_sizes = {}
        for bc in ("barcode05", "barcode06"):
            for k in range(3):
                p = src / bc / f"reads_{bc}_{k}.fastq.gz"
                p.write_bytes(bytes([k]))
                one_byte_sizes[p] = 1

        out = tmp_path / "input"
        layout = build_backlog(src, out, barcodes=1, files_per_barcode=2,
                               include_unclassified=False, concat=2)

        assert sorted(layout) == ["barcode01"]
        files = layout["barcode01"]
        assert len(files) == 2
        for f in files:
            assert f.is_file() and not f.is_symlink()
            assert f.name.startswith("concat2_")
            assert f.stat().st_size == 2  # sum of its two one-byte sources

        manifest = json.loads((out / "backlog_layout.json").read_text())
        assert manifest["concat"] == 2

    def test_concat_refuses_when_pool_too_small(self, tmp_path):
        from scripts.ttfr_backlog import build_backlog

        src = _source_corpus(tmp_path, barcodes=("barcode05",), files=2)
        with pytest.raises(ValueError, match="pool holds only 2"):
            build_backlog(src, tmp_path / "input", barcodes=1, files_per_barcode=2,
                          include_unclassified=False, concat=2)


def _write_run(tmp_path, ticks, trace_rows, t0=1000.0):
    run = tmp_path / "run"
    run.mkdir()
    timeline = run / "timeline.jsonl"
    with timeline.open("w") as fh:
        for ts, per_sample in ticks:
            fh.write(json.dumps({
                "ts": ts,
                "samples": sorted(per_sample),
                "unmeasured": [s for s, v in per_sample.items() if v["total_reads"] is None],
                "per_sample": per_sample,
                "trace": {}, "run_meta": {}, "input": {},
            }) + "\n")
    trace = run / "trace.txt"
    header = "task_id\thash\tnative_id\tprocess\ttag\tname\tstatus\texit\tsubmit\tstart\tcomplete\tduration\trealtime\tqueue\t%cpu\t%mem\tpeak_rss\tpeak_vmem\trchar\twchar\tattempt\n"
    with trace.open("w") as fh:
        fh.write(header)
        for row in trace_rows:
            fh.write("\t".join(row) + "\n")
    (run / "run.json").write_text(json.dumps({
        "t0": t0, "t_end": t0 + 100, "mode": "batch", "results_dir": str(run),
        "trace": str(trace), "timeline": str(timeline), "input_dir": "", "command": [], "returncode": 0,
    }))
    return run


def _ps(reads, watched=0):
    return {"tier": "cumulative" if reads else "none", "report_stat": None,
            "total_reads": reads, "watched": watched}


class TestAnalyse:
    def test_first_report_completion_and_spread(self, tmp_path):
        from scripts.ttfr_analyse import analyse

        ticks = [
            (1002.0, {"barcode01": _ps(None), "barcode02": _ps(None)}),
            (1010.0, {"barcode01": _ps(100), "barcode02": _ps(None)}),
            (1020.0, {"barcode01": _ps(100), "barcode02": _ps(50, watched=1)}),
            (1030.0, {"barcode01": _ps(300), "barcode02": _ps(50, watched=1)}),
        ]
        run = _write_run(tmp_path, ticks, [])
        s = analyse(run)
        assert s["per_sample"]["barcode01"]["first_report_s"] == 10.0
        assert s["per_sample"]["barcode01"]["complete_s"] == 30.0
        assert s["per_sample"]["barcode02"]["first_report_s"] == 20.0
        assert s["per_sample"]["barcode02"]["first_watched_s"] == 20.0
        assert s["spread_first_report_s"] == 10.0
        assert s["all_first_report_s"] == 20.0

    def test_classifier_concurrency_from_trace(self, tmp_path):
        from scripts.ttfr_analyse import analyse

        def row(tid, process, tag, start, complete, realtime, rss, attempt="1"):
            return [tid, "aa/bb", "1", process, tag, f"{process} ({tag})", "COMPLETED", "0",
                    start, start, complete, "10s", realtime, "0ms", "300%", "5%", rss, "1 GB", "1", "1", attempt]

        rows = [
            row("1", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode01",
                "2026-09-06 12:00:00.000", "2026-09-06 12:00:40.000", "40s", "1.5 GB"),
            row("2", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode02",
                "2026-09-06 12:00:10.000", "2026-09-06 12:00:20.000", "10s", "1.2 GB"),
            row("3", "NANOMETANF:TAX:KRAKEN2_INCREMENTAL_CLASSIFIER", "barcode03",
                "2026-09-06 12:00:41.000", "2026-09-06 12:00:50.000", "9s", "1.2 GB"),
            row("4", "NANOMETANF:QC:CHOPPER", "barcode01",
                "2026-09-06 11:59:50.000", "2026-09-06 11:59:59.000", "9s", "200 MB"),
        ]
        run = _write_run(tmp_path, [(1002.0, {"barcode01": _ps(1)})], rows)
        s = analyse(run)
        c = s["classifier"]
        assert c["tasks"] == 3
        assert c["max_concurrency"] == 2
        assert c["first_task_s"] == 40.0
        assert c["median_task_s"] == 10.0
        assert c["peak_rss_gb"] == 1.5
        assert s["per_process"]["CHOPPER"]["count"] == 1

    def test_render_lists_every_sample(self, tmp_path):
        from scripts.ttfr_analyse import analyse, render

        run = _write_run(tmp_path, [(1005.0, {"barcode01": _ps(1), "barcode02": _ps(None)})], [])
        text = render(analyse(run))
        assert "barcode01" in text and "barcode02" in text
        assert "never" in text  # barcode02 got no report


REPORT_A = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n40.00\t40\t40\tS\t562\t  Escherichia coli\n"
REPORT_B = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n40.00\t40\t40\tS\t562\t  Escherichia coli\n"
REPORT_C = "50.00\t50\t50\tU\t0\tunclassified\n50.00\t50\t0\tR\t1\troot\n39.00\t39\t39\tS\t562\t  Escherichia coli\n"


class TestCompareReports:
    def test_identical_counts_agree(self, tmp_path):
        from scripts.ttfr_analyse import compare_reports

        a = tmp_path / "a.txt"; a.write_text(REPORT_A)
        b = tmp_path / "b.txt"; b.write_text(REPORT_B)
        result = compare_reports(a, b)
        assert result["equal"] is True and result["differences"] == {}

    def test_a_differing_taxid_is_named(self, tmp_path):
        from scripts.ttfr_analyse import compare_reports

        a = tmp_path / "a.txt"; a.write_text(REPORT_A)
        c = tmp_path / "c.txt"; c.write_text(REPORT_C)
        result = compare_reports(a, c)
        assert result["equal"] is False
        assert result["differences"] == {"562": (40, 39)}

    def test_compare_runs_pairs_samples(self, tmp_path):
        from scripts.ttfr_analyse import compare_runs

        for name, text in (("chunked/kraken2/barcode01.cumulative.kraken2.report.txt", REPORT_A),
                           ("single/kraken2/barcode01.kraken2.report.txt", REPORT_C)):
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        result = compare_runs(tmp_path / "chunked", tmp_path / "single")
        assert result["samples"] == ["barcode01"]
        assert result["equal"] is False
        assert result["per_sample"]["barcode01"]["differences"] == {"562": (40, 39)}
