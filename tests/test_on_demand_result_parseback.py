"""On-demand validation must find the results its own run produced.

Two defects from the 2026-08-18 release check, both in the read-back half of
``validate_via_nanometanf`` (the Nextflow run itself succeeded):

1. The Organisms tab passes ``sample="all"`` for an aggregate-scope
   validation, and the launcher forwarded that token verbatim into
   ``ValidationParser.get_validation_results(sample=...)`` -- where it is a
   literal sample name matching nothing. A successful validation of a
   multiplexed run was therefore reported to the operator as
   "nanometanf validation did not return a result".

2. The cumulative on-demand ``pathogen_genomes.json`` started empty instead
   of seeding from the main run's ``pipeline_input/pathogen_genomes.json``.
   The on-demand aggregator rebuilds ``validation/validation_results.json``
   over exactly the taxids in that file, so the first on-demand call SHRANK
   the aggregate to its single taxid, silently dropping every main-run
   validation from the exported raw file. (The GUI's own tabs survive via
   the per-pair file scan; the archived artifact does not.)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.on_demand_helpers import _normalise_sample_filter
from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator


class TestNormaliseSampleFilter:
    @pytest.mark.parametrize("token", ["all", "All", "ALL", "All Samples",
                                       "all samples", "", None])
    def test_aggregate_tokens_mean_no_filter(self, token):
        assert _normalise_sample_filter(token) is None

    def test_real_sample_name_passes_through(self):
        assert _normalise_sample_filter("barcode11") == "barcode11"


def _make_run_tree(tmp_path):
    """Results tree with an aggregate holding one validated pair."""
    results = tmp_path / "results"
    (results / "validation").mkdir(parents=True)
    aggregate = {
        "pipeline_version": "1.6.1",
        "validation_method": "both",
        "thresholds": {"hit_rate": 0.5, "identity": 90.0},
        "results": {
            "barcode11": {
                "4007169": {
                    "taxid": 4007169,
                    "species": "Francisella tularensis",
                    "validation_method": "blast",
                    "kraken_reads": 5344,
                    "extracted_reads": 5344,
                    "blast_hits": 5214,
                    "hit_rate": 0.9757,
                    "avg_identity": 97.30,
                    "avg_coverage": 0.98,
                    "validation_status": "confirmed",
                }
            }
        },
    }
    (results / "validation" / "validation_results.json").write_text(
        json.dumps(aggregate)
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "barcode11.fastq").write_text("@r1\nACGT\n+\nIIII\n")
    return results, input_dir


class TestSampleAllFindsResults:
    def test_sample_all_reports_the_run_success(self, tmp_path):
        results, input_dir = _make_run_tree(tmp_path)
        pipeline = tmp_path / "pipeline_source"
        pipeline.mkdir()
        (pipeline / "main.nf").write_text("// stub\n")
        config = {
            "pipeline_source": str(pipeline),
            "pipeline_profile": "conda",
            "data_dir": str(tmp_path / "datadir"),
        }
        validator = OnDemandValidator(
            results_dir=str(results), input_dir=str(input_dir)
        )
        validator.genomes_dir.mkdir(parents=True, exist_ok=True)
        (validator.genomes_dir / "4007169.fasta").write_text(
            ">ref\nACGTACGTACGTACGTACGT\n"
        )
        mock_proc = MagicMock(pid=1234, returncode=0)
        mock_proc.communicate.return_value = ("", "")
        with patch(
            "nanometa_live.core.workflow.on_demand_validator.subprocess.Popen",
            return_value=mock_proc,
        ):
            result = validator.validate_via_nanometanf(
                taxid=4007169,
                name="Francisella tularensis",
                sample="all",
                method="both",
                config=config,
            )
        assert result is not None and result.success, (
            "a successful validation with results on disk was reported as "
            "no-result because the GUI's 'all' aggregate token was used as a "
            "literal sample name"
        )
        assert result.validated_reads == 5214


class TestPathogenGenomesSeededFromMainRun:
    def test_first_call_unions_with_pipeline_input(self, tmp_path):
        results = tmp_path / "results"
        seed_genome = tmp_path / "genomes" / "4007187.fasta"
        seed_genome.parent.mkdir(parents=True)
        seed_genome.write_text(">seed\nACGT\n")
        (results / "pipeline_input").mkdir(parents=True)
        (results / "pipeline_input" / "pathogen_genomes.json").write_text(
            json.dumps({"4007187": str(seed_genome)})
        )
        validator = OnDemandValidator(results_dir=str(results))
        new_genome = tmp_path / "genomes" / "4007169.fasta"
        new_genome.write_text(">new\nACGT\n")

        path, mapping = validator._add_taxid_to_pathogen_genomes(
            4007169, new_genome
        )

        assert path is not None
        assert set(mapping) == {"4007169", "4007187"}, (
            "the on-demand pathogen_genomes.json must seed from the main "
            "run's pipeline_input copy; without the union the aggregator "
            "rebuilds validation_results.json over the on-demand taxid only "
            "and drops every main-run validation from the exported file"
        )
        saved = json.loads(path.read_text())
        assert set(saved) == {"4007169", "4007187"}

    def test_seed_entries_with_missing_genomes_are_dropped(self, tmp_path):
        results = tmp_path / "results"
        (results / "pipeline_input").mkdir(parents=True)
        (results / "pipeline_input" / "pathogen_genomes.json").write_text(
            json.dumps({"4007187": str(tmp_path / "gone.fasta")})
        )
        validator = OnDemandValidator(results_dir=str(results))
        new_genome = tmp_path / "4007169.fasta"
        new_genome.write_text(">new\nACGT\n")

        _, mapping = validator._add_taxid_to_pathogen_genomes(
            4007169, new_genome
        )

        assert set(mapping) == {"4007169"}, (
            "a seed entry whose genome no longer exists must be dropped -- "
            "nanometanf fails on a pathogen_genomes path it cannot stage"
        )
