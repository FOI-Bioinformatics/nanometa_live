"""``genome_manager._validate_fasta`` -- the gate on downloaded reference genomes.

Everything downstream of this function assumes the file it blessed is a usable
reference: BLAST database construction and minimap2 validation both run against
it. If an unusable file passes, the confirmatory step for a select agent
returns no hits, and no-hits is rendered to the operator as "not confirmed" --
a FALSE NEGATIVE that looks exactly like a true negative.

The failure modes tested here are the ones seen in the field: an HTTP/S3 error
page saved with a ``.fasta`` extension (the ``external_kraken2_info`` URLs in
config.yaml are 2023-dated S3 links), a download interrupted mid-stream, and a
compressed payload written where plain text was expected.

Tests are written against what the code ACTUALLY does. Three cases are accepted
that arguably should not be -- a truncated FASTA, a header with no sequence,
and an all-N sequence. Those are pinned as-is and reported separately rather
than being asserted the way we might wish they behaved; changing them is a
production-code decision, and this file must fail loudly if any of them
changes silently.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from nanometa_live.core.utils.genome_manager import _validate_fasta

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, name: str, data) -> Path:
    p = tmp_path / name
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data)
    return p


VALID_FASTA = (
    ">NC_006570.2 Francisella tularensis subsp. tularensis SCHU S4\n"
    "ACGTACGTNNACGTACGTAC\n"
    "GTACGTACGTACGTACGTAC\n"
)


class TestAcceptsRealGenomes:
    def test_valid_fasta_is_accepted(self, tmp_path):
        p = _write(tmp_path, "263.fasta", VALID_FASTA)
        assert _validate_fasta(p) is True, (
            "a well-formed reference genome was rejected; the download would be "
            "discarded and the organism left unvalidated"
        )

    def test_multi_record_fasta_is_accepted(self, tmp_path):
        p = _write(
            tmp_path,
            "multi.fasta",
            ">chr1\nACGTACGT\n>plasmid_pFNL10\nGGCCTTAA\n",
        )
        assert _validate_fasta(p) is True, (
            "multi-contig assemblies are the norm for draft genomes; rejecting "
            "them would drop most RefSeq downloads"
        )

    def test_lowercase_and_ambiguity_codes_are_accepted(self, tmp_path):
        p = _write(tmp_path, "soft.fasta", ">x\nacgtRYSWKMbdhvNn\n")
        assert _validate_fasta(p) is True, (
            "soft-masked and IUPAC-ambiguous bases are valid nucleotide data; "
            "rejecting them discards legitimate RefSeq records"
        )

    def test_gapped_alignment_characters_are_accepted(self, tmp_path):
        p = _write(tmp_path, "gapped.fasta", ">x\nACGT--ACGT..ACGT\n")
        assert _validate_fasta(p) is True


class TestRejectsUnusableDownloads:
    def test_zero_byte_file_is_rejected(self, tmp_path):
        p = _write(tmp_path, "empty.fasta", b"")
        assert _validate_fasta(p) is False, (
            "an empty file passed as a reference genome; BLAST/minimap2 would "
            "return zero hits and the select agent would read as not confirmed"
        )

    def test_html_error_page_is_rejected(self, tmp_path):
        p = _write(
            tmp_path,
            "263.fasta",
            "<!DOCTYPE html>\n<html><head><title>404 Not Found</title></head>\n"
            "<body>The requested URL was not found on this server.</body></html>\n",
        )
        assert _validate_fasta(p) is False, (
            "an HTTP error page saved with a .fasta extension passed validation; "
            "this is the live failure mode for the 2023-dated S3 genome URLs"
        )

    def test_s3_xml_error_document_is_rejected(self, tmp_path):
        p = _write(
            tmp_path,
            "263.fasta",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Error><Code>NoSuchKey</Code><Message>The specified key does not "
            "exist.</Message></Error>\n",
        )
        assert _validate_fasta(p) is False, (
            "an S3 NoSuchKey document passed as a genome; every validation run "
            "against it would silently produce no alignments"
        )

    def test_plain_text_error_without_header_is_rejected(self, tmp_path):
        p = _write(tmp_path, "263.fasta", "Error: rate limit exceeded\n")
        assert _validate_fasta(p) is False

    def test_leading_blank_line_is_rejected(self, tmp_path):
        """The header check is on the FIRST line, not the first non-blank one."""
        p = _write(tmp_path, "263.fasta", "\n>NC_006570.2\nACGTACGT\n")
        assert _validate_fasta(p) is False

    def test_gzip_payload_written_as_plain_fasta_is_rejected(self, tmp_path):
        p = _write(tmp_path, "263.fasta", gzip.compress(VALID_FASTA.encode()))
        assert _validate_fasta(p) is False, (
            "a still-compressed payload passed as plain FASTA; downstream tools "
            "would index binary noise as a reference sequence"
        )

    def test_truncated_gzip_payload_is_rejected(self, tmp_path):
        raw = gzip.compress((">x\n" + "ACGT" * 500).encode())
        p = _write(tmp_path, "263.fasta", raw[: len(raw) // 2])
        assert _validate_fasta(p) is False, (
            "an interrupted download of a compressed genome must be discarded "
            "and retried, not indexed"
        )

    def test_protein_sequence_is_rejected(self, tmp_path):
        """Despite the docstring's mention of amino acids, the charset is nucleotide-only."""
        p = _write(tmp_path, "prot.fasta", ">p\nMKVLEWQFGHILPT\n")
        assert _validate_fasta(p) is False, (
            "a protein FASTA would break nucleotide alignment; the docstring "
            "claims amino acids are allowed but the character set is DNA/RNA only"
        )

    def test_html_appended_early_in_the_sequence_is_rejected(self, tmp_path):
        p = _write(tmp_path, "263.fasta", ">x\nACGTACGT\n<html>404</html>\n")
        assert _validate_fasta(p) is False

    def test_missing_file_is_rejected(self, tmp_path):
        assert _validate_fasta(tmp_path / "does_not_exist.fasta") is False, (
            "a missing file must be reported as invalid, not raise out of the "
            "download path and abort the whole watchlist genome fetch"
        )

    def test_directory_path_is_rejected(self, tmp_path):
        d = tmp_path / "263.fasta"
        d.mkdir()
        assert _validate_fasta(d) is False


class TestAcceptedButArguablyUnusable:
    """Cases the gate currently PASSES that yield no usable alignment target.

    Each is a potential false negative on a select agent. They are pinned here
    so a future change to the validator is a deliberate, visible one -- not so
    that the behaviour is endorsed. See the report accompanying this file.
    """

    def test_truncated_fasta_is_accepted(self, tmp_path):
        """FASTA carries no length record, so truncation is not locally detectable."""
        p = _write(tmp_path, "263.fasta", ">NC_006570.2\nACGTACGTNN\nACG")
        assert _validate_fasta(p) is True, (
            "behaviour change: the validator now rejects truncated FASTA -- "
            "update this test and the accompanying finding"
        )

    def test_header_with_no_sequence_is_accepted(self, tmp_path):
        """FINDING: a zero-base genome is indexed and can never produce a hit."""
        p = _write(tmp_path, "263.fasta", ">NC_006570.2 Francisella tularensis\n")
        assert _validate_fasta(p) is True, (
            "behaviour change: header-only FASTA is now rejected -- update this "
            "test and the accompanying finding"
        )

    def test_all_n_sequence_is_accepted(self, tmp_path):
        """FINDING: an all-N reference aligns nothing; reads as a clean negative."""
        p = _write(tmp_path, "263.fasta", ">NC_006570.2\n" + "N" * 5000 + "\n")
        assert _validate_fasta(p) is True, (
            "behaviour change: all-N FASTA is now rejected -- update this test "
            "and the accompanying finding"
        )

    def test_junk_beyond_the_10000_character_scan_window_is_accepted(self, tmp_path):
        """FINDING: only the first ~10 kB of sequence is character-checked.

        A download that begins as valid FASTA and degrades later -- a proxy
        injecting an error body mid-stream -- passes the gate.
        """
        p = _write(
            tmp_path,
            "263.fasta",
            ">NC_006570.2\n" + "ACGT" * 3000 + "\n<html>504 Gateway Timeout</html>\n",
        )
        assert _validate_fasta(p) is True, (
            "behaviour change: the scan window no longer stops at 10000 "
            "characters -- update this test and the accompanying finding"
        )


class TestNoSideEffects:
    """The validator inspects; it must never mutate or delete the candidate."""

    def test_rejected_file_is_left_on_disk(self, tmp_path):
        p = _write(tmp_path, "263.fasta", "<html>404</html>\n")
        _validate_fasta(p)
        assert p.exists(), (
            "the validator deleted its input; callers own the discard decision "
            "and one of them extracts the accession before cleaning up"
        )

    def test_accepted_file_is_unchanged(self, tmp_path):
        p = _write(tmp_path, "263.fasta", VALID_FASTA)
        before = p.read_bytes()
        _validate_fasta(p)
        assert p.read_bytes() == before
