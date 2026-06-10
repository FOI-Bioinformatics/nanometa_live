"""Cross-cutting regression tests for the three sample-handling layouts
(by_barcode / single_sample / per_file) and their edge cases.

These pin behaviour that earlier sessions found fragile or that an audit flagged
as a likely bug; several of the "likely bugs" turned out to be safe and are kept
here as guards so they cannot regress.
"""

import os
import time

import pytest

from nanometa_live.core.config.parameter_mapping import (
    generate_samplesheet,
    validate_sample_handling_layout,
)


def _backdate(path, seconds=30):
    old = time.time() - seconds
    os.utime(str(path), (old, old))


# --------------------------------------------------------------------------- #
# Prefix-boundary safety: barcode1 must not pick up barcode10's files.
# The `{sample}_*` glob has an implicit '_' boundary, so this is SAFE -- guard it.
# --------------------------------------------------------------------------- #

def test_sample_glob_does_not_overmatch_longer_prefix(tmp_path):
    from nanometa_live.core.utils.qc_loaders import _find_sample_files
    for name in ["barcode1.fastp.json", "barcode1_batch0.fastp.json",
                 "barcode10.fastp.json", "barcode10_batch0.fastp.json"]:
        (tmp_path / name).write_text("{}")
    got = [os.path.basename(f) for f in _find_sample_files(str(tmp_path), "barcode1", ["fastp.json"])]
    assert "barcode1.fastp.json" in got
    assert "barcode1_batch0.fastp.json" in got
    assert not any("barcode10" in g for g in got), f"barcode10 leaked into barcode1: {got}"


# --------------------------------------------------------------------------- #
# per_file name sanitisation must keep distinct files as distinct samples.
# --------------------------------------------------------------------------- #

def test_per_file_sanitisation_keeps_distinct_samples(tmp_path):
    for n in ["sample-A.fastq", "sample.A.fastq", "clean.fastq"]:
        (tmp_path / n).write_text("")
    out = tmp_path / "ss.csv"
    generate_samplesheet(str(tmp_path), str(out), "per_file")
    rows = [l.split(",")[0] for l in out.read_text().splitlines()[1:] if l.strip()]
    # 3 files -> 3 distinct sample names (the two that sanitise to 'sample_A'
    # must be disambiguated, not merged).
    assert len(rows) == 3
    assert len(set(rows)) == 3, f"distinct files merged into one sample: {rows}"


def test_per_file_distinct_names_unchanged(tmp_path):
    for n in ["alpha.fastq", "beta.fastq"]:
        (tmp_path / n).write_text("")
    out = tmp_path / "ss.csv"
    generate_samplesheet(str(tmp_path), str(out), "per_file")
    rows = [l.split(",")[0] for l in out.read_text().splitlines()[1:] if l.strip()]
    assert sorted(rows) == ["alpha", "beta"]


# --------------------------------------------------------------------------- #
# Single-read, root-only classification must report 1 sequence, not 0
# (the documented reads.sum()==0 trap). SAFE -- guard it (with a stable file).
# --------------------------------------------------------------------------- #

def test_single_read_root_only_counts_one(tmp_path):
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    from nanometa_live.app.utils.callback_helpers import get_classification_stats
    kr = tmp_path / "kraken2"
    kr.mkdir()
    f = kr / "s.kraken2.report.txt"
    f.write_text("  0.00\t0\t0\tU\t0\tunclassified\n100.00\t1\t1\tR\t1\troot\n")
    _backdate(f)
    df = load_kraken_data(str(tmp_path), "All Samples")
    assert not df.empty
    classified, unclassified, _rate = get_classification_stats(df)
    assert classified == 1, f"single root read miscounted: classified={classified}"


# --------------------------------------------------------------------------- #
# Layout validation: per_file/single_sample reject a barcode layout; by_barcode accepts.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode,should_raise", [
    ("per_file", True), ("single_sample", True), ("by_barcode", False),
])
def test_layout_validation_symmetry(tmp_path, mode, should_raise):
    (tmp_path / "barcode01").mkdir()
    (tmp_path / "barcode01" / "r.fastq").write_text("")
    if should_raise:
        with pytest.raises(ValueError):
            validate_sample_handling_layout(mode, str(tmp_path))
    else:
        validate_sample_handling_layout(mode, str(tmp_path))  # no raise


# --------------------------------------------------------------------------- #
# Auto-detection: a barcode-named subdir signals by_barcode even before reads
# land (the sequencer creates barcodeNN/ ahead of FASTQs); a flat dir of files
# does not. This guards the pattern-based detection in detect_sample_handling.
# --------------------------------------------------------------------------- #

def test_barcode_named_dir_detects_by_barcode_even_when_empty(tmp_path):
    from nanometa_live.core.utils.auto_detect import detect_sample_handling
    inp = tmp_path / "input"
    (inp / "barcode01").mkdir(parents=True)
    mode_empty, _ = detect_sample_handling(str(inp))
    assert mode_empty == "by_barcode"
    (inp / "barcode01" / "reads.fastq").write_text("")
    mode_full, _ = detect_sample_handling(str(inp))
    assert mode_full == "by_barcode"


def test_flat_files_do_not_detect_by_barcode(tmp_path):
    from nanometa_live.core.utils.auto_detect import detect_sample_handling
    inp = tmp_path / "input"
    inp.mkdir()
    for n in ["readsA.fastq", "readsB.fastq", "readsC.fastq"]:
        (inp / n).write_text("")
    mode, _ = detect_sample_handling(str(inp))
    assert mode != "by_barcode"


# --------------------------------------------------------------------------- #
# Sample cache must surface a newly-added sample file.
# --------------------------------------------------------------------------- #

def test_available_samples_cache_sees_new_file(tmp_path):
    from nanometa_live.core.utils.sample_detector import get_available_samples
    kr = tmp_path / "kraken2"
    kr.mkdir()
    f1 = kr / "barcode01.kraken2.report.txt"
    f1.write_text("100.00\t1\t1\tR\t1\troot\n")
    _backdate(f1)
    s1 = get_available_samples(str(tmp_path))
    assert "barcode01" in s1
    f2 = kr / "barcode02.kraken2.report.txt"
    f2.write_text("100.00\t1\t1\tR\t1\troot\n")
    _backdate(f2)
    s2 = get_available_samples(str(tmp_path))
    assert "barcode02" in s2, f"cache did not surface new sample: {s2}"
