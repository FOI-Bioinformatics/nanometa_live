"""
Tests for the previously-untested functions in core/config/parameter_mapping.py.

The big create_nextflow_params/config and layout validation are covered in
test_parameter_mapping.py; this fills the gaps: format_duration,
generate_samplesheet (all three sample-handling modes + error paths),
validate_nanometanf_params (the launch-time gate), and get_validation_species.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.config import parameter_mapping as pm
from nanometa_live.core.config.parameter_mapping import (
    format_duration,
    generate_samplesheet,
    get_validation_species,
    validate_nanometanf_params,
)

pytestmark = pytest.mark.unit


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(15, "15s"), (59, "59s"), (90, "1m"), (3599, "59m"), (3600, "1h"), (7200, "2h")],
    )
    def test_durations(self, seconds, expected):
        assert format_duration(seconds) == expected


class TestGenerateSamplesheet:
    def _fastqs(self, d, names):
        for n in names:
            (d / n).write_text("@r\nACGT\n+\nIIII\n")

    def test_single_sample_groups_all_files(self, tmp_path):
        self._fastqs(tmp_path, ["a.fastq", "b.fastq"])
        out = tmp_path / "ss.csv"
        generate_samplesheet(str(tmp_path), str(out), "single_sample", "mysample")
        lines = out.read_text().strip().splitlines()
        assert lines[0] == "sample,fastq"
        assert len(lines) == 3  # header + 2 files
        assert all(line.startswith("mysample,") for line in lines[1:])

    def test_per_file_derives_names(self, tmp_path):
        self._fastqs(tmp_path, ["barcode01.fastq", "barcode02.fastq"])
        out = tmp_path / "ss.csv"
        generate_samplesheet(str(tmp_path), str(out), "per_file")
        text = out.read_text()
        assert "barcode01," in text
        assert "barcode02," in text

    def test_by_barcode_uses_subdir_names(self, tmp_path):
        for bc in ("barcode01", "barcode02"):
            sub = tmp_path / bc
            sub.mkdir()
            (sub / "reads.fastq").write_text("@r\nACGT\n+\nIIII\n")
        out = tmp_path / "ss.csv"
        generate_samplesheet(str(tmp_path), str(out), "by_barcode")
        text = out.read_text()
        assert "barcode01," in text and "barcode02," in text

    def test_no_fastq_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No FASTQ files"):
            generate_samplesheet(str(tmp_path), str(tmp_path / "ss.csv"), "single_sample")

    def test_by_barcode_without_subdirs_raises(self, tmp_path):
        self._fastqs(tmp_path, ["flat.fastq"])  # flat, no subdirs
        with pytest.raises(ValueError, match="subdirectories"):
            generate_samplesheet(str(tmp_path), str(tmp_path / "ss.csv"), "by_barcode")


@pytest.fixture
def kraken_db(tmp_path):
    db = tmp_path / "kraken2_db"
    db.mkdir()
    for f in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (db / f).write_text("x")
    return db


class TestValidateNanometanfParams:
    def test_missing_required_param(self, tmp_path):
        ok, msg = validate_nanometanf_params({"outdir": str(tmp_path)})
        assert ok is False and "kraken2_db" in msg

    def test_empty_required_param(self, tmp_path):
        ok, msg = validate_nanometanf_params({"kraken2_db": "", "outdir": str(tmp_path)})
        assert ok is False

    def test_no_input_mode(self, kraken_db, tmp_path):
        ok, msg = validate_nanometanf_params(
            {"kraken2_db": str(kraken_db), "outdir": str(tmp_path)}
        )
        assert ok is False and "Missing input" in msg

    def test_kraken_db_not_a_dir(self, tmp_path):
        ok, msg = validate_nanometanf_params(
            {"kraken2_db": str(tmp_path / "nope"), "outdir": str(tmp_path),
             "input": "x"}
        )
        assert ok is False and "not found" in msg

    def test_kraken_db_missing_files(self, tmp_path):
        incomplete = tmp_path / "db"
        incomplete.mkdir()
        (incomplete / "hash.k2d").write_text("x")  # missing opts/taxo
        ss = tmp_path / "s.csv"
        ss.write_text("sample,fastq\ns1,/a.fastq\n")
        ok, msg = validate_nanometanf_params(
            {"kraken2_db": str(incomplete), "outdir": str(tmp_path), "input": str(ss)}
        )
        assert ok is False and "missing required files" in msg

    def test_valid_samplesheet_mode(self, kraken_db, tmp_path):
        ss = tmp_path / "s.csv"
        ss.write_text("sample,fastq\ns1,/a.fastq\n")
        ok, msg = validate_nanometanf_params(
            {"kraken2_db": str(kraken_db), "outdir": str(tmp_path), "input": str(ss)}
        )
        assert ok is True

    def test_empty_samplesheet_rejected(self, kraken_db, tmp_path):
        ss = tmp_path / "s.csv"
        ss.write_text("sample,fastq\n")  # header only
        ok, msg = validate_nanometanf_params(
            {"kraken2_db": str(kraken_db), "outdir": str(tmp_path), "input": str(ss)}
        )
        assert ok is False and "empty" in msg


class TestGetValidationSpecies:
    def test_maps_kraken_taxids(self):
        species = [{"taxid": 562, "kraken_taxid": 99562, "name": "E. coli"}]
        with patch.object(pm, "get_validation_species_from_watchlist",
                          return_value=(species, ["/g/562.fasta"])):
            taxids, genomes = get_validation_species({})
        assert taxids == ["99562"]
        assert genomes == ["/g/562.fasta"]

    def test_empty_watchlist(self):
        with patch.object(pm, "get_validation_species_from_watchlist", return_value=([], [])):
            assert get_validation_species({}) == ([], [])
