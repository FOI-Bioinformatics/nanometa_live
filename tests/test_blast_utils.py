"""
Unit tests for core/utils/blast_utils.py.

The pure filesystem helpers (db presence checks, read counting, summary) are
exercised directly against tmp_path; the two subprocess-invoking builders
(makeblastdb / blastn) are tested with subprocess.run mocked so no external
binary is required and no real command runs.
"""

from unittest.mock import MagicMock, patch

from nanometa_live.core.utils.blast_utils import (
    build_blast_databases,
    check_blast_dbs_exist,
    count_validated_reads,
    get_blast_validation_summary,
    run_blast_validation,
)


class TestCheckBlastDbsExist:
    def test_reports_only_missing_taxids(self, tmp_path):
        blast_dir = tmp_path / "blast"
        blast_dir.mkdir()
        (blast_dir / "562.fasta.nhr").write_text("x")  # present for E. coli
        missing = check_blast_dbs_exist(
            {"Escherichia coli": 562, "Staphylococcus aureus": 1280}, str(tmp_path)
        )
        assert missing == ["1280"]

    def test_creates_blast_dir_when_absent(self, tmp_path):
        check_blast_dbs_exist({"E. coli": 562}, str(tmp_path))
        assert (tmp_path / "blast").is_dir()


class TestCountValidatedReads:
    def test_counts_unique_qseqids(self, tmp_path):
        f = tmp_path / "562.txt"
        f.write_text("read1\tref\t98.0\nread1\tref\t95.0\nread2\tref\t92.0\n")
        assert count_validated_reads(str(f)) == 2

    def test_missing_file_returns_zero(self, tmp_path):
        assert count_validated_reads(str(tmp_path / "nope.txt")) == 0

    def test_empty_file_returns_zero(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert count_validated_reads(str(f)) == 0


class TestGetBlastValidationSummary:
    def test_summary_per_species(self, tmp_path):
        blast_dir = tmp_path / "blast"
        blast_dir.mkdir()
        (blast_dir / "562.txt").write_text("read1\tref\nread2\tref\n")
        summary = get_blast_validation_summary(
            str(blast_dir),
            {"Escherichia coli": 562, "Staphylococcus aureus": 1280},
        )
        assert summary["Escherichia coli"] == {"taxid": "562", "validated_reads": 2}
        assert summary["Staphylococcus aureus"] == {"taxid": "1280", "validated_reads": 0}

    def test_missing_dir_returns_empty(self, tmp_path):
        assert get_blast_validation_summary(str(tmp_path / "nope"), {"x": 1}) == {}


class TestBuildBlastDatabases:
    def test_missing_input_folder_returns_false(self, tmp_path):
        assert build_blast_databases(str(tmp_path)) is False

    def test_no_missing_databases_short_circuits_true(self, tmp_path):
        (tmp_path / "genomes").mkdir()
        (tmp_path / "genomes" / "562.fasta").write_text(">x\nACGT\n")
        # An empty (not None) missing list means "nothing to build".
        assert build_blast_databases(str(tmp_path), missing_databases=[]) is True

    def test_builds_with_makeblastdb_invocation(self, tmp_path):
        genomes = tmp_path / "genomes"
        genomes.mkdir()
        (genomes / "562.fasta").write_text(">x\nACGT\n")
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert build_blast_databases(str(tmp_path)) is True
        assert run.called
        assert run.call_args[0][0][0] == "makeblastdb"


class TestRunBlastValidation:
    def test_missing_query_returns_false(self, tmp_path):
        assert run_blast_validation(
            str(tmp_path / "q.fasta"), str(tmp_path / "db"), str(tmp_path / "out.txt")
        ) is False

    def test_missing_db_returns_false(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">r\nACGT\n")
        assert run_blast_validation(
            str(query), str(tmp_path / "db"), str(tmp_path / "out.txt")
        ) is False

    def test_runs_blastn_when_inputs_present(self, tmp_path):
        query = tmp_path / "q.fasta"
        query.write_text(">r\nACGT\n")
        (tmp_path / "db.nsq").write_text("x")  # db presence marker
        out = tmp_path / "out" / "result.txt"
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run:
            ok = run_blast_validation(str(query), str(tmp_path / "db"), str(out))
        assert ok is True
        assert run.call_args[0][0][0] == "blastn"
