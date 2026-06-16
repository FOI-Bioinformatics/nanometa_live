"""Unit tests for parse_blast_per_read (lazy per-read BLAST parsing)."""

from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import parse_blast_per_read

pytestmark = pytest.mark.unit


def _row(qseqid, sseqid, pident=96.0, length=400, bitscore=700.0,
         evalue="1e-50", qcovs=90, cols=15):
    base = [qseqid, sseqid, pident, length, 2, 0, 1, length, 1, length,
            evalue, bitscore]
    if cols == 15:
        base += [length + 50, 1900000, qcovs]
    return "\t".join(str(v) for v in base)


def _write(path: Path, rows):
    path.write_text("\n".join(rows) + "\n")


def test_dedup_by_qseqid_keeps_best_bitscore(tmp_path):
    p = tmp_path / "s_taxid1.blast.tsv"
    # same read, two HSPs; the higher-bitscore one wins
    _write(p, [
        _row("readA", "NC_1", bitscore=500.0),
        _row("readA", "NC_1", bitscore=900.0),
        _row("readB", "NC_1", bitscore=600.0),
    ])
    res = parse_blast_per_read(p, "s", 1)
    assert res["total_reads"] == 2
    a = [r for r in res["records"] if r["qseqid"] == "readA"][0]
    assert a["bitscore"] == 900.0


def test_top_subjects_and_agreement(tmp_path):
    p = tmp_path / "s_taxid1.blast.tsv"
    rows = [_row(f"r{i}", "NC_1") for i in range(8)]
    rows += [_row(f"x{i}", "NC_2") for i in range(2)]
    _write(p, rows)
    res = parse_blast_per_read(p, "s", 1)
    assert res["total_reads"] == 10
    assert res["top_subjects"][0]["sseqid"] == "NC_1"
    assert res["top_subjects"][0]["reads"] == 8
    assert res["subject_agreement"] == pytest.approx(0.8)


def test_distributions_present(tmp_path):
    p = tmp_path / "s_taxid1.blast.tsv"
    _write(p, [_row(f"r{i}", "NC_1", pident=90.0 + i) for i in range(5)])
    res = parse_blast_per_read(p, "s", 1)
    for key in ("pident", "length", "bitscore", "evalue"):
        assert len(res["distributions"][key]) == 5


def test_row_cap_and_sampling(tmp_path):
    p = tmp_path / "s_taxid1.blast.tsv"
    _write(p, [_row(f"r{i}", "NC_1", bitscore=float(i)) for i in range(100)])
    res = parse_blast_per_read(p, "s", 1, max_rows=10)
    assert res["total_reads"] == 100
    assert res["sampled"] is True
    assert res["returned_rows"] == 10
    # distributions still cover all reads
    assert len(res["distributions"]["pident"]) == 100
    # the 10 returned are the top-bitscore reads
    assert min(r["bitscore"] for r in res["records"]) == 90.0


def test_12_column_file(tmp_path):
    p = tmp_path / "s_taxid1.blast.tsv"
    _write(p, [_row("r1", "NC_1", cols=12), _row("r2", "NC_1", cols=12)])
    res = parse_blast_per_read(p, "s", 1)
    assert res["total_reads"] == 2
    # qcovs defaults to 0 when the column is absent
    assert all(r["qcovs"] == 0.0 for r in res["records"])


def test_empty_or_missing_file(tmp_path):
    missing = tmp_path / "nope.blast.tsv"
    res = parse_blast_per_read(missing, "s", 1)
    assert res["total_reads"] == 0 and res["records"] == []

    empty = tmp_path / "s_taxid1.blast.tsv"
    empty.write_text("")
    res2 = parse_blast_per_read(empty, "s", 1)
    assert res2["total_reads"] == 0
