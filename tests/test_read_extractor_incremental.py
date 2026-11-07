"""ReadExtractor reads the incremental classifier's layout (audit finding 4).

Every GUI run and every real-time run takes nanometanf's incremental branch,
which publishes per-read output as ``kraken2/<sample>/batches/batch_N.kraken2
.output.txt`` (one per batch) and, at session end,
``kraken2/<sample>.cumulative.kraken2.output.txt``. The extractor looked for
the standard branch's flat names only and found nothing after a default run.
"""

import pytest

from nanometa_live.core.utils.read_extractor import ReadExtractor

pytestmark = pytest.mark.unit

BATCH0 = "C\tr1\t562\t150\tlca\nC\tr2\t1280\t150\tlca\n"
BATCH1 = "C\tr3\t562\t150\tlca\nU\tr4\t0\t150\tlca\n"
BATCH10 = "C\tr5\t562\t150\tlca\n"
CUMULATIVE = BATCH0 + BATCH1 + BATCH10


def _incremental_tree(tmp_path, *, cumulative=False):
    results = tmp_path / "results"
    batches = results / "kraken2" / "barcode01" / "batches"
    batches.mkdir(parents=True)
    (batches / "batch_0.kraken2.output.txt").write_text(BATCH0)
    (batches / "batch_1.kraken2.output.txt").write_text(BATCH1)
    (batches / "batch_10.kraken2.output.txt").write_text(BATCH10)
    if cumulative:
        (results / "kraken2" / "barcode01.cumulative.kraken2.output.txt").write_text(CUMULATIVE)
    inp = tmp_path / "input" / "barcode01"
    inp.mkdir(parents=True)
    (inp / "reads.fastq").write_text(
        "@r1\nAAAA\n+\nIIII\n@r2\nCCCC\n+\nIIII\n@r3\nGGGG\n+\nIIII\n"
        "@r4\nTTTT\n+\nIIII\n@r5\nACGT\n+\nIIII\n"
    )
    return ReadExtractor(str(results), str(tmp_path / "input"))


class TestIncrementalLayout:
    def test_every_batch_file_is_found_in_numeric_order(self, tmp_path):
        ex = _incremental_tree(tmp_path)
        names = [p.name for p in ex.find_kraken_output_files("barcode01")]
        assert names == [
            "batch_0.kraken2.output.txt", "batch_1.kraken2.output.txt",
            "batch_10.kraken2.output.txt",
        ]

    def test_reads_are_collected_across_batches(self, tmp_path):
        ex = _incremental_tree(tmp_path)
        files = ex.find_kraken_output_files("barcode01")
        assert ex.get_read_ids_for_taxid(files, 562) == {"r1", "r3", "r5"}
        assert ex.get_classified_taxids("barcode01") == {562: 3, 1280: 1}

    def test_extraction_spans_the_batches(self, tmp_path):
        ex = _incremental_tree(tmp_path)
        result = ex.extract_reads_for_taxid("barcode01", 562)
        assert result.success
        assert result.total_reads == 3
        assert result.extracted_reads == 3

    def test_cumulative_output_wins_when_present(self, tmp_path):
        ex = _incremental_tree(tmp_path, cumulative=True)
        files = ex.find_kraken_output_files("barcode01")
        assert [p.name for p in files] == ["barcode01.cumulative.kraken2.output.txt"]
        assert ex.get_classified_taxids("barcode01") == {562: 3, 1280: 1}

    def test_single_path_api_still_works(self, tmp_path):
        ex = _incremental_tree(tmp_path)
        one = ex.find_kraken_output_file("barcode01")
        assert one.name == "batch_0.kraken2.output.txt"
        assert ex.get_read_ids_for_taxid(one, 562) == {"r1"}

    def test_absent_sample_is_an_empty_list(self, tmp_path):
        ex = _incremental_tree(tmp_path)
        assert ex.find_kraken_output_files("barcode02") == []
        assert ex.find_kraken_output_file("barcode02") is None
