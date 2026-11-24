"""Two readiness probes that looked at the wrong thing (audit finding 37).

``_check_input_directory`` counted ``*.fastq*`` only at the top level, so a
flat folder of ``.fq.gz`` reads looked empty; ``_check_db_index`` and the
preparer's skip-existing probe accepted or looked for a ``_index.pkl`` that
``TaxidMapper`` deletes and rebuilds.
"""

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

pytestmark = pytest.mark.unit


@pytest.fixture
def checker():
    return ReadinessChecker()


class TestInputDirectoryCountsFq:
    def test_flat_fq_gz_folder_passes(self, checker, tmp_path):
        (tmp_path / "reads.fq.gz").write_text("data")
        result = checker._check_input_directory({
            "nanopore_output_directory": str(tmp_path), "sample_handling": "single_sample",
        })
        assert result.passed is True
        assert "FASTQ" in result.message

    def test_fq_folder_is_not_a_layout_mismatch(self, checker, tmp_path):
        (tmp_path / "a.fq").write_text("data")
        result = checker._check_input_directory({
            "nanopore_output_directory": str(tmp_path), "sample_handling": "per_file",
        })
        assert result.passed is True


class TestDbIndexProbe:
    def _probe(self, checker, tmp_path, monkeypatch, filename):
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash", lambda p: "abc")
        monkeypatch.setattr(
            "nanometa_live.core.utils.paths.get_mappings_dir_from_env", lambda: str(tmp_path))
        if filename:
            (tmp_path / filename).write_text("x")
        return checker._check_db_index({"kraken_db": str(tmp_path / "db")}, tmp_path)

    def test_json_index_is_found(self, checker, tmp_path, monkeypatch):
        assert self._probe(checker, tmp_path, monkeypatch, "abc_index.json").passed is True

    def test_legacy_pickle_alone_is_not_prepared(self, checker, tmp_path, monkeypatch):
        result = self._probe(checker, tmp_path, monkeypatch, "abc_index.pkl")
        assert result.passed is False
        assert "pkl" not in (result.details or "")


class TestPreparerSkipProbe:
    def test_pickle_alone_does_not_skip_the_build(self, tmp_path, monkeypatch):
        from nanometa_live.core.workflow.mobile_lab_preparer import (
            MobileLabPreparer, PreparationResult,
        )
        monkeypatch.setattr(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash", lambda p: "abc")
        loaded = []

        class _Mapper:
            def load_database(self, p):
                loaded.append(p)
        monkeypatch.setattr("nanometa_live.core.taxonomy.taxid_mapping.TaxidMapper", _Mapper)
        prep = MobileLabPreparer({"kraken_db": "/db"}, nanometa_home=str(tmp_path))
        (tmp_path / "mappings").mkdir()
        (tmp_path / "mappings" / "abc_index.pkl").write_text("legacy")
        prep._run_build_index(1, PreparationResult(success=True), True)
        assert loaded == ["/db"]
