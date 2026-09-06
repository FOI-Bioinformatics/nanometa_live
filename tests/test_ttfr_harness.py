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
