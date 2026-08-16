"""
Tests for the previously-untested functions in core/config/parameter_mapping.py.

The big create_nextflow_params/config and layout validation are covered in
test_parameter_mapping.py; this fills the gaps: format_duration,
generate_samplesheet (all three sample-handling modes + error paths),
validate_nanometanf_params (the launch-time gate), and get_validation_species.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestUnmappedValidationTaxidWarning:
    """A custom/GTDB DB whose taxids differ from NCBI silently extracts 0 reads
    when the watchlist was never mapped. get_validation_species_from_watchlist
    must WARN at that fallback instead of failing silently."""

    def _entry(self, taxid, name, db_taxid=None):
        e = MagicMock()
        e.taxid = taxid
        e.name = name
        e.db_taxid = db_taxid
        e.names_alt = []
        return e

    def _run(self, entries, mapping_collection):
        wm = MagicMock()
        wm._loaded = True
        wm.get_active_entries.return_value = {e.taxid: e for e in entries}
        gm = MagicMock()
        gm.get_genome_path.return_value = None
        with patch.object(pm, "get_watchlist_manager", return_value=wm), \
             patch.object(pm, "get_genome_manager", return_value=gm), \
             patch("nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
                   return_value=mapping_collection):
            return pm.get_validation_species_from_watchlist({"kraken_db": "/db"})

    def test_no_mapping_warns_run_scan(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            species, _ = self._run([self._entry(263, "Francisella tularensis")], None)
        assert species and species[0]["kraken_taxid"] == 263  # raw NCBI fallback
        assert any("Scan Database" in r.message for r in caplog.records)

    def test_scanned_all_mapped_no_warning(self, caplog):
        import logging
        coll = MagicMock()
        coll.get_db_taxid.return_value = 4007169  # 263 -> custom DB taxid
        with caplog.at_level(logging.WARNING):
            species, _ = self._run([self._entry(263, "Francisella tularensis")], coll)
        assert species[0]["kraken_taxid"] == 4007169
        assert not any("could not be mapped" in r.message or "Scan Database" in r.message
                       for r in caplog.records)

    def test_scanned_partial_warns_specific(self, caplog):
        import logging
        coll = MagicMock()
        coll.get_db_taxid.side_effect = lambda t: 4007169 if t == 263 else None
        with caplog.at_level(logging.WARNING):
            self._run([self._entry(263, "F. tularensis"),
                       self._entry(1392, "B. anthracis")], coll)
        assert any("could not be mapped" in r.message for r in caplog.records)

    def test_explicit_db_taxid_not_warned(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            species, _ = self._run([self._entry(263, "F. tularensis", db_taxid=4007169)], None)
        assert species[0]["kraken_taxid"] == 4007169
        assert not any("Scan Database" in r.message for r in caplog.records)


class TestPathogenGenomesLocation:
    """Operator feedback #2: archive/rerun crashed with 'No such file:
    .../validation/pathogen_genomes.json'. The launch input must live OUTSIDE
    the archived/published validation/ dir so it survives a Move/rerun."""

    def _fake_manager(self):
        manager = MagicMock()
        manager.get_statistics.return_value = {}
        manager.has_genome.return_value = True
        manager.get_genome_path.return_value = None
        manager.blast_db_status.return_value = {"present": [263], "missing": [], "no_genome": []}

        def _gen(taxids, output_path=None, taxid_mapping=None):
            # Mirror the real manager: write the JSON at the requested path.
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w") as fh:
                json.dump({"263": {"path": "/g/263.fasta"}}, fh)
            return Path(output_path)

        manager.generate_pathogen_genomes_json.side_effect = _gen
        return manager

    def test_written_under_pipeline_input_not_validation(self, tmp_path):
        species = [{"taxid": 263, "kraken_taxid": 263, "name": "F. tularensis"}]
        with patch.object(pm, "get_genome_manager", return_value=self._fake_manager()), \
                patch.object(pm, "get_validation_species_from_watchlist",
                             return_value=(species, ["/g/263.fasta"])):
            path = pm._generate_pathogen_genomes_json({}, str(tmp_path))
        assert path is not None
        assert os.path.exists(path)
        assert os.path.basename(os.path.dirname(path)) == "pipeline_input"
        assert "validation" not in Path(path).parts

    def test_survives_archive_of_validation_dir(self, tmp_path):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        # Populate validation/ so archive_existing_results moves it away.
        (tmp_path / "validation").mkdir()
        (tmp_path / "validation" / "old.txt").write_text("stale")
        species = [{"taxid": 263, "kraken_taxid": 263, "name": "F. tularensis"}]
        with patch.object(pm, "get_genome_manager", return_value=self._fake_manager()), \
                patch.object(pm, "get_validation_species_from_watchlist",
                             return_value=(species, ["/g/263.fasta"])):
            path = pm._generate_pathogen_genomes_json({}, str(tmp_path))
            BackendManager.archive_existing_results(str(tmp_path))
        # The launch input must still be present after the archive sweep.
        assert os.path.exists(path)


class TestValidationParamCoercions:
    """Launch-time coercions for values nf-schema or blastn would reject
    (audit 2026-08-16, finding L27)."""

    def test_blast_perc_identity_is_an_integer(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        cfg = _minimal_config(tmp_path)
        cfg["validation_identity_threshold"] = 92.5
        params = create_nextflow_params(cfg)
        assert params["blast_perc_identity"] == 92 or params["blast_perc_identity"] == 93
        assert isinstance(params["blast_perc_identity"], int)

    def test_invalid_minimap2_preset_is_coerced(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        cfg = _minimal_config(tmp_path)
        cfg["minimap2_preset"] = "sr"
        params = create_nextflow_params(cfg)
        assert params["minimap2_preset"] == "map-ont"

    def test_valid_minimap2_preset_passes_through(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        cfg = _minimal_config(tmp_path)
        cfg["minimap2_preset"] = "map-pb"
        params = create_nextflow_params(cfg)
        assert params["minimap2_preset"] == "map-pb"

    def test_nonpositive_evalue_falls_back(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        cfg = _minimal_config(tmp_path)
        cfg["e_val_cutoff"] = 0
        params = create_nextflow_params(cfg)
        assert params["blast_evalue"] > 0


class TestGenerateConsensusStringCoercion:
    """generate_consensus: "false" (string) must not flip to on
    (audit 2026-08-16, finding L27)."""

    def test_string_false_is_false(self):
        from nanometa_live.core.config.config_loader import ConfigLoader

        loader = ConfigLoader.__new__(ConfigLoader)
        cfg = {"generate_consensus": "false"}
        loader._standardize_boolean_params(cfg)
        assert cfg["generate_consensus"] is False

    def test_string_true_is_true(self):
        from nanometa_live.core.config.config_loader import ConfigLoader

        loader = ConfigLoader.__new__(ConfigLoader)
        cfg = {"generate_consensus": "true"}
        loader._standardize_boolean_params(cfg)
        assert cfg["generate_consensus"] is True


def _minimal_config(tmp_path):
    """A minimal batch-mode config create_nextflow_params accepts."""
    nanopore_dir = tmp_path / "input"
    nanopore_dir.mkdir(exist_ok=True)
    (nanopore_dir / "sample1.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir(exist_ok=True)
    return {
        "nanopore_output_directory": str(nanopore_dir),
        "results_output_directory": str(results_dir),
        "kraken_db": str(tmp_path / "kraken2_db"),
        "processing_mode": "batch",
        "sample_handling": "single_sample",
        "sample_name": "test_sample",
        "analysis_name": "TestRun",
        "check_intervals_seconds": 15,
        "blast_validation": False,
    }
