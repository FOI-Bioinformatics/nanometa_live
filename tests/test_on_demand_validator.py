"""
Tests for core/workflow/on_demand_validator.py (was 46% covered).

Covers the dataclasses, filesystem presence checks, job-id generation, and the
download/build orchestration with a mocked genome manager. The full
validate_via_nanometanf subprocess path is out of scope (slow integration).
All paths use a tmp cache_dir so the real ~/.nanometa is never touched.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanometa_live.core.workflow.on_demand_validator import (
    OnDemandValidator,
    ValidationJob,
    ValidationResult,
    ValidationStatus,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def validator(tmp_path):
    return OnDemandValidator(
        results_dir=str(tmp_path / "results"),
        input_dir=str(tmp_path / "input"),
        cache_dir=str(tmp_path / "cache"),
        genome_manager=MagicMock(),
    )


class TestDataclasses:
    def test_job_defaults(self):
        job = ValidationJob(taxid=562, name="E. coli", sample="bc01")
        assert job.status == ValidationStatus.PENDING
        assert job.progress_percent == 0
        assert job.validated_reads == 0

    def test_result_construction(self):
        r = ValidationResult(
            taxid=562, name="E. coli", sample="bc01", total_classified_reads=100,
            extracted_reads=90, validated_reads=80, validation_rate=88.9,
            avg_identity=97.0, min_identity=90.0, max_identity=99.0, success=True,
        )
        assert r.success is True
        assert r.validated_reads == 80


class TestPresenceChecks:
    def test_has_genome(self, validator):
        assert validator.has_genome(562) is False
        (validator.genomes_dir / "562.fasta").write_text(">x\nACGT\n")
        assert validator.has_genome(562) is True

    def test_has_blast_db(self, validator):
        assert validator.has_blast_db(562) is False
        (validator.blast_dir / "562.fasta.nhr").write_text("x")
        assert validator.has_blast_db(562) is True

    def test_job_id(self, validator):
        assert validator._get_job_id(562, "barcode01") == "barcode01_562"


class TestDownloadGenome:
    def test_returns_existing_without_manager_call(self, validator):
        (validator.genomes_dir / "562.fasta").write_text(">x\nACGT\n")
        path = validator.download_genome(562, "E. coli")
        assert path == validator.genomes_dir / "562.fasta"
        validator.genome_manager.download_genome.assert_not_called()

    def test_delegates_to_genome_manager(self, validator):
        downloaded = validator.genomes_dir / "562.fasta"
        downloaded.write_text(">x\nACGT\n")  # the file the manager "produced"
        validator.genome_manager.download_genome.return_value = downloaded
        # has_genome is now True, so it short-circuits; test the delegate path
        # with a fresh taxid that does not exist yet.
        target = validator.genomes_dir / "1280.fasta"
        target.write_text(">y\nTTTT\n")
        validator.genome_manager.download_genome.return_value = target
        # Remove so has_genome(1280) is False at call time.
        target.unlink()
        def _produce(taxid, name):
            target.write_text(">y\nTTTT\n")
            return target
        validator.genome_manager.download_genome.side_effect = _produce
        result = validator.download_genome(1280, "S. aureus")
        assert result == target

    def test_no_manager_returns_none(self, validator):
        validator._genome_manager = None
        # Force the lazy property to yield None instead of building a real one.
        import nanometa_live.core.workflow.on_demand_validator as mod
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(type(validator), "genome_manager", property(lambda self: None))
            assert validator.download_genome(99999, "x") is None


class TestBuildBlastDb:
    def test_existing_db_returns_true(self, validator):
        (validator.blast_dir / "562.fasta.nhr").write_text("x")
        assert validator.build_blast_db(562) is True

    def test_missing_genome_returns_false(self, validator):
        assert validator.build_blast_db(99999) is False
