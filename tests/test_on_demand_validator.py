"""
Tests for core/workflow/on_demand_validator.py (was 46% covered).

Covers the dataclasses, filesystem presence checks, job-id generation, and the
download/build orchestration with a mocked genome manager. The full
validate_via_nanometanf subprocess path is out of scope (slow integration).
All paths use a tmp cache_dir so the real ~/.nanometa is never touched.
"""

import signal
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.on_demand_validator import (
    OnDemandValidator,
    ValidationJob,
    ValidationResult,
    ValidationStatus,
    _pick_result_for_method,
)

pytestmark = pytest.mark.unit


class _R:
    """Minimal stand-in for a parsed ValidationResult."""
    def __init__(self, method, ident):
        self.validation_method = method
        self.percent_identity_mean = ident


class TestPickResultForMethod:
    """validate_via_nanometanf must return the result matching the requested
    method -- get_validation_results filters by (sample, taxid), not method, so
    results[0] can be the wrong method when a pair carried both."""

    def test_minimap2_request_skips_leading_blast(self):
        results = [_R("blast", 97.0), _R("minimap2", 99.0)]
        assert _pick_result_for_method(results, "minimap2").percent_identity_mean == 99.0

    def test_blast_request_picks_blast(self):
        results = [_R("minimap2", 99.0), _R("blast", 97.0)]
        assert _pick_result_for_method(results, "blast").percent_identity_mean == 97.0

    def test_both_prefers_blast(self):
        results = [_R("minimap2", 99.0), _R("blast", 97.0)]
        assert _pick_result_for_method(results, "both").validation_method == "blast"

    def test_falls_back_to_first_when_method_absent(self):
        results = [_R("blast", 97.0)]
        assert _pick_result_for_method(results, "minimap2").percent_identity_mean == 97.0


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


class TestGenomeManagerOfflinePropagation:
    """The lazy genome_manager must come from the shared singleton so the
    app-wide offline_mode (set by _init_offline_mode) reaches on-demand
    genome downloads. Constructing a fresh GenomeDownloadManager here would
    default to offline_mode=False and hit the network in offline mode.
    """

    def test_property_delegates_to_shared_singleton(self, tmp_path):
        from unittest.mock import patch

        validator = OnDemandValidator(
            results_dir=str(tmp_path / "results"),
            cache_dir=str(tmp_path / "cache"),
        )
        sentinel = MagicMock(offline_mode=True)
        with patch(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            return_value=sentinel,
        ) as get_gm:
            result = validator.genome_manager

        assert result is sentinel
        get_gm.assert_called_once()
        # cache_dir is forwarded so the singleton writes genomes to the
        # validator's own cache directory.
        _, kwargs = get_gm.call_args
        assert kwargs.get("cache_dir") == str(tmp_path / "cache")

    def test_explicit_genome_manager_still_wins(self, tmp_path):
        """An injected manager (test/DI path) is used as-is, not overridden."""
        injected = MagicMock()
        validator = OnDemandValidator(
            results_dir=str(tmp_path / "results"),
            cache_dir=str(tmp_path / "cache"),
            genome_manager=injected,
        )
        assert validator.genome_manager is injected


class TestPathogenGenomesLock:
    """W11: two on-demand validation requests in flight at once (two browser
    tabs/operators -- the background callback's ``running=`` guard only
    disables the button for the triggering session) must not lose one
    another's taxid to a read-modify-write race on pathogen_genomes.json."""

    def test_concurrent_merges_preserve_every_taxid(self, validator):
        taxids = list(range(1000, 1030))
        for t in taxids:
            (validator.genomes_dir / f"{t}.fasta").write_text(">x\nACGT\n")

        def _add(t):
            validator._add_taxid_to_pathogen_genomes(
                t, validator.genomes_dir / f"{t}.fasta"
            )

        threads = [threading.Thread(target=_add, args=(t,)) for t in taxids]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        mapping = validator._load_pathogen_genomes()
        assert set(mapping.keys()) == {str(t) for t in taxids}

    def test_merge_preserves_prior_taxids(self, validator):
        (validator.genomes_dir / "1.fasta").write_text(">x\nACGT\n")
        (validator.genomes_dir / "2.fasta").write_text(">x\nACGT\n")
        validator._add_taxid_to_pathogen_genomes(1, validator.genomes_dir / "1.fasta")
        path, mapping = validator._add_taxid_to_pathogen_genomes(
            2, validator.genomes_dir / "2.fasta"
        )
        assert path is not None
        assert set(mapping.keys()) == {"1", "2"}

    def test_write_failure_returns_none_path_and_empty_mapping(self, validator, monkeypatch):
        def _boom(mapping):
            raise OSError("disk full")

        monkeypatch.setattr(validator, "_save_pathogen_genomes", _boom)
        path, mapping = validator._add_taxid_to_pathogen_genomes(
            1, validator.genomes_dir / "1.fasta"
        )
        assert path is None
        assert mapping == {}


class TestValidateViaNanometanfProcessGroupIsolation:
    """W6: a timed-out on-demand validation subprocess must not orphan
    Nextflow's already-launched task/container processes. start_new_session
    puts the whole tree in one process group; on TimeoutExpired the group
    must be killed (SIGTERM escalating to SIGKILL), mirroring
    NextflowManager.stop()."""

    def _validator(self, tmp_path):
        v = OnDemandValidator(
            results_dir=str(tmp_path / "results"),
            input_dir=str(tmp_path / "input"),
            cache_dir=str(tmp_path / "cache"),
            genome_manager=MagicMock(),
        )
        (tmp_path / "input").mkdir(parents=True, exist_ok=True)
        (v.genomes_dir / "1392.fasta").write_text(">x\nACGT\n")
        return v

    def _config(self):
        return {"pipeline_source": "remote:dev", "pipeline_profile": "conda"}

    def test_popen_uses_start_new_session(self, tmp_path):
        v = self._validator(tmp_path)
        mock_proc = MagicMock(pid=4321, returncode=0)
        mock_proc.communicate.return_value = ("", "")
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.subprocess.Popen",
            return_value=mock_proc,
        ) as mock_popen, patch(
            "nanometa_live.core.parsers.blast_validation_parser.ValidationParser.get_validation_results",
            return_value=[],
        ):
            v.validate_via_nanometanf(
                1392, "B. anthracis", "barcode01", config=self._config()
            )
        _, kwargs = mock_popen.call_args
        assert kwargs.get("start_new_session") is True

    def test_timeout_kills_process_group_with_sigterm(self, tmp_path):
        v = self._validator(tmp_path)
        mock_proc = MagicMock(pid=4321)
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="nextflow", timeout=60),
            ("", ""),  # grace-period wait succeeds -- group died on SIGTERM
        ]
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.subprocess.Popen",
            return_value=mock_proc,
        ), patch(
            "nanometa_live.core.workflow.on_demand_validator.os.getpgid",
            return_value=4321,
        ), patch(
            "nanometa_live.core.workflow.on_demand_validator.os.killpg",
        ) as mock_killpg:
            result = v.validate_via_nanometanf(
                1392, "B. anthracis", "barcode01", config=self._config()
            )
        assert result is None
        mock_killpg.assert_called_once_with(4321, signal.SIGTERM)
        mock_proc.kill.assert_not_called()

    def test_timeout_escalates_to_sigkill_if_group_survives_grace_period(self, tmp_path):
        v = self._validator(tmp_path)
        mock_proc = MagicMock(pid=4321)
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="nextflow", timeout=60),
            subprocess.TimeoutExpired(cmd="nextflow", timeout=30),
            ("", ""),
        ]
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.subprocess.Popen",
            return_value=mock_proc,
        ), patch(
            "nanometa_live.core.workflow.on_demand_validator.os.getpgid",
            return_value=4321,
        ), patch(
            "nanometa_live.core.workflow.on_demand_validator.os.killpg",
        ) as mock_killpg:
            result = v.validate_via_nanometanf(
                1392, "B. anthracis", "barcode01", config=self._config()
            )
        assert result is None
        calls = [c.args[1] for c in mock_killpg.call_args_list]
        assert calls == [signal.SIGTERM, signal.SIGKILL]
