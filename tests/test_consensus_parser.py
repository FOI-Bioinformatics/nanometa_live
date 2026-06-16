"""Unit tests for core/parsers/consensus_parser.py."""

import json
from pathlib import Path

import pytest

from nanometa_live.core.parsers.consensus_parser import (
    ConsensusResult,
    parse_consensus_stats,
    collect_consensus_results,
    read_consensus_fasta,
)

pytestmark = pytest.mark.unit


def _write_consensus(cdir: Path, sample: str, taxid: int, *, span=428,
                     cons_len=428, n_count=4, seq="ACGT" * 107):
    cdir.mkdir(parents=True, exist_ok=True)
    stats = {
        "sample_id": sample, "taxid": taxid, "validation_method": "consensus",
        "ref_name": "chr", "ref_length": 1900000,
        "covered_start": 435, "covered_end": 863, "span": span,
        "mean_depth": 52.3, "min_depth_threshold": 10, "n_count": n_count,
        "consensus_length": cons_len, "total_reads": 400, "mapped_reads": 396,
    }
    (cdir / f"{sample}_taxid{taxid}.consensus_stats.json").write_text(json.dumps(stats))
    (cdir / f"{sample}_taxid{taxid}.consensus.fasta").write_text(
        f">{sample}_taxid{taxid} ref=chr region=435-863\n{seq}\n"
    )


def test_parse_consensus_stats_reads_all_fields(tmp_path):
    cdir = tmp_path / "validation" / "consensus"
    _write_consensus(cdir, "barcode05", 263)
    res = parse_consensus_stats(cdir / "barcode05_taxid263.consensus_stats.json")
    assert isinstance(res, ConsensusResult)
    assert res.sample_id == "barcode05"
    assert res.taxid == 263
    assert res.span == 428
    assert res.covered_start == 435 and res.covered_end == 863
    assert res.has_sequence is True
    assert res.fasta_path.endswith("barcode05_taxid263.consensus.fasta")


def test_n_fraction(tmp_path):
    cdir = tmp_path / "validation" / "consensus"
    _write_consensus(cdir, "s", 1, cons_len=100, n_count=10)
    res = parse_consensus_stats(cdir / "s_taxid1.consensus_stats.json")
    assert res.n_fraction == pytest.approx(0.1)


def test_parse_invalid_taxid_returns_none(tmp_path):
    p = tmp_path / "bad.consensus_stats.json"
    p.write_text(json.dumps({"sample_id": "s"}))  # no taxid
    assert parse_consensus_stats(p) is None


def test_parse_unreadable_returns_none(tmp_path):
    p = tmp_path / "broken.consensus_stats.json"
    p.write_text("{ not json")
    assert parse_consensus_stats(p) is None


def test_collect_filters_by_sample_and_taxid(tmp_path):
    cdir = tmp_path / "validation" / "consensus"
    _write_consensus(cdir, "barcode05", 263)
    _write_consensus(cdir, "barcode06", 562)
    assert len(collect_consensus_results(tmp_path)) == 2
    only5 = collect_consensus_results(tmp_path, sample="barcode05")
    assert len(only5) == 1 and only5[0].taxid == 263
    only562 = collect_consensus_results(tmp_path, taxid=562)
    assert len(only562) == 1 and only562[0].sample_id == "barcode06"


def test_collect_missing_dir_returns_empty(tmp_path):
    assert collect_consensus_results(tmp_path) == []


def test_read_consensus_fasta(tmp_path):
    cdir = tmp_path / "validation" / "consensus"
    _write_consensus(cdir, "s", 1, seq="ACGTACGT")
    res = collect_consensus_results(tmp_path)[0]
    text = read_consensus_fasta(res.fasta_path)
    assert text.startswith(">s_taxid1")
    assert "ACGTACGT" in text


def test_read_consensus_fasta_empty_path():
    assert read_consensus_fasta("") is None
