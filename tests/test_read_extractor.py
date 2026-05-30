"""
Unit tests for core/utils/read_extractor.py.

ReadExtractor turns a taxid into a FASTA of the reads Kraken2 assigned to it,
for on-demand validation. Tests build a small results/ + input/ tree under
tmp_path and exercise output-file discovery, read-id selection, FASTQ->FASTA
extraction and the full orchestration, including the documented failure modes
(missing Kraken2 output, missing FASTQ, no reads for the taxid).
"""

from nanometa_live.core.utils.read_extractor import ReadExtractor

KRAKEN_OUTPUT = (
    "C\tread1\t562\t150\tlca\n"
    "C\tread2\t562\t150\tlca\n"
    "C\tread3\t1280\t150\tlca\n"
    "U\tread4\t0\t150\tlca\n"
)

FASTQ = (
    "@read1 some description\nACGTACGT\n+\nIIIIIIII\n"
    "@read2\nTTTT\n+\nIIII\n"
    "@read3\nGGGG\n+\nIIII\n"
)


def _make_extractor(tmp_path, *, kraken_name="barcode01.kraken2", with_fastq=True):
    results = tmp_path / "results"
    (results / "kraken2").mkdir(parents=True)
    (results / "kraken2" / kraken_name).write_text(KRAKEN_OUTPUT)
    inp = tmp_path / "input"
    inp.mkdir()
    if with_fastq:
        (inp / "barcode01.fastq").write_text(FASTQ)
    return ReadExtractor(str(results), str(inp))


class TestFindKrakenOutputFile:
    def test_finds_primary_pattern(self, tmp_path):
        ex = _make_extractor(tmp_path)
        found = ex.find_kraken_output_file("barcode01")
        assert found is not None
        assert found.name == "barcode01.kraken2"

    def test_finds_highest_batch_file(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        (results / "kraken2" / "barcode01_batch0.kraken2.output.txt").write_text(KRAKEN_OUTPUT)
        (results / "kraken2" / "barcode01_batch1.kraken2.output.txt").write_text(KRAKEN_OUTPUT)
        ex = ReadExtractor(str(results))
        found = ex.find_kraken_output_file("barcode01")
        assert found.name == "barcode01_batch1.kraken2.output.txt"

    def test_returns_none_when_absent(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        ex = ReadExtractor(str(results))
        assert ex.find_kraken_output_file("missing") is None


class TestGetReadIdsForTaxid:
    def test_selects_only_matching_classified_reads(self, tmp_path):
        ex = _make_extractor(tmp_path)
        kraken = ex.find_kraken_output_file("barcode01")
        assert ex.get_read_ids_for_taxid(kraken, 562) == {"read1", "read2"}

    def test_other_taxid(self, tmp_path):
        ex = _make_extractor(tmp_path)
        kraken = ex.find_kraken_output_file("barcode01")
        assert ex.get_read_ids_for_taxid(kraken, 1280) == {"read3"}


class TestFindFastqFiles:
    def test_flat_layout(self, tmp_path):
        ex = _make_extractor(tmp_path)
        files = ex.find_fastq_files("barcode01")
        assert [p.name for p in files] == ["barcode01.fastq"]

    def test_barcoded_subdir(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        inp = tmp_path / "input"
        (inp / "barcode01").mkdir(parents=True)
        (inp / "barcode01" / "reads.fastq.gz").write_text("")
        ex = ReadExtractor(str(results), str(inp))
        files = ex.find_fastq_files("barcode01")
        assert any(p.name == "reads.fastq.gz" for p in files)

    def test_no_input_dir_returns_empty(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        ex = ReadExtractor(str(results))
        assert ex.find_fastq_files("barcode01") == []


class TestExtractReadsFromFastq:
    def test_writes_matching_reads_as_fasta(self, tmp_path):
        ex = _make_extractor(tmp_path)
        out = tmp_path / "out.fasta"
        count = ex.extract_reads_from_fastq(
            [tmp_path / "input" / "barcode01.fastq"], {"read1", "read2"}, out
        )
        assert count == 2
        text = out.read_text()
        assert ">read1\nACGTACGT\n" in text
        assert ">read2\nTTTT\n" in text
        assert "read3" not in text


class TestExtractReadsForTaxid:
    def test_happy_path(self, tmp_path):
        ex = _make_extractor(tmp_path)
        result = ex.extract_reads_for_taxid("barcode01", 562)
        assert result.success is True
        assert result.total_reads == 2
        assert result.extracted_reads == 2
        assert result.output_file.exists()

    def test_missing_kraken_output_is_failure(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        ex = ReadExtractor(str(results), str(tmp_path / "input"))
        result = ex.extract_reads_for_taxid("barcode01", 562)
        assert result.success is False
        assert "not found" in result.error_message

    def test_no_reads_for_taxid_is_success_with_zero(self, tmp_path):
        ex = _make_extractor(tmp_path)
        result = ex.extract_reads_for_taxid("barcode01", 99999)
        assert result.success is True
        assert result.total_reads == 0
        assert result.extracted_reads == 0

    def test_missing_fastq_is_failure(self, tmp_path):
        ex = _make_extractor(tmp_path, with_fastq=False)
        result = ex.extract_reads_for_taxid("barcode01", 562)
        assert result.success is False
        assert "No FASTQ files" in result.error_message


class TestGetClassifiedTaxids:
    def test_counts_per_taxid(self, tmp_path):
        ex = _make_extractor(tmp_path)
        assert ex.get_classified_taxids("barcode01") == {562: 2, 1280: 1}

    def test_missing_output_returns_empty(self, tmp_path):
        results = tmp_path / "results"
        (results / "kraken2").mkdir(parents=True)
        ex = ReadExtractor(str(results))
        assert ex.get_classified_taxids("missing") == {}
