"""The reference-genome guard must see the rank that changes the diagnosis.

Measured on the real cache: ``4007187.fasta`` was labelled *Francisella
tularensis* subsp. *holarctica* and contained subsp. *novicida*
(NZ_CP009607.1). ``check_reference_organism`` compared GENUS only, so it
returned "cannot tell" and the wrong reference was used silently for every
coverage figure attributed to Type B.

Subspecies is exactly the rank that matters clinically here: Type A
(*tularensis*) is markedly more virulent than Type B (*holarctica*), and
*novicida* is a different organism again. A guard that cannot separate them
is not guarding the thing that hurts.

The opposite failure is just as real. GTDB suffixes polyphyletic genera
(``Bacillus_A anthracis``), so a naive string comparison against a database
name reports a mismatch for a perfectly correct genome. Nothing may fire on
that.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.parsers.validation_guards import check_reference_organism


def _fasta(tmp_path, header, name="ref.fasta"):
    p = tmp_path / name
    p.write_text(f">{header}\nACGTACGTAC\n")
    return str(p)


class TestSubspeciesMismatchIsCaught:
    def test_novicida_filed_as_holarctica_warns(self, tmp_path):
        g = _fasta(tmp_path, "NZ_CP009607.1 Francisella tularensis subsp. novicida D9876")
        warn = check_reference_organism(
            g, "Francisella tularensis subsp. holarctica")
        assert warn, (
            "the exact corruption found in the real cache passed silently: "
            "coverage for Type B was measured against a novicida reference"
        )
        assert "novicida" in warn and "holarctica" in warn

    def test_type_a_filed_as_type_b_warns(self, tmp_path):
        g = _fasta(tmp_path, "NC_006570.2 Francisella tularensis subsp. tularensis SCHU S4")
        assert check_reference_organism(
            g, "Francisella tularensis subsp. holarctica")


class TestCorrectReferencesStaySilent:
    @pytest.mark.parametrize("header,expected", [
        ("NC_007880.1 Francisella tularensis subsp. holarctica LVS",
         "Francisella tularensis subsp. holarctica"),
        ("NC_007530.2 Bacillus anthracis str. 'Ames Ancestor'", "Bacillus anthracis"),
        ("NC_003143.1 Yersinia pestis CO92", "Yersinia pestis"),
        # Strain suffixes and assembly cruft must not read as a mismatch.
        ("NC_002971.4 Coxiella burnetii RSA 493", "Coxiella burnetii"),
        ("NC_003317.1 Brucella melitensis bv. 1 str. 16M chromosome I",
         "Brucella melitensis"),
    ])
    def test_matching_reference_is_silent(self, tmp_path, header, expected):
        assert check_reference_organism(_fasta(tmp_path, header), expected) is None


class TestGtdbSuffixesAreNotMismatches:
    """A GTDB polyphyly suffix names the same organism."""

    @pytest.mark.parametrize("expected", [
        "Bacillus_A anthracis",
        "Escherichia coli_E",
        "Clostridium_J argentinense",
    ])
    def test_suffixed_expected_name_does_not_warn(self, tmp_path, expected):
        base = expected.split()[0].split("_")[0]
        species = expected.split()[-1]
        g = _fasta(tmp_path, f"NC_000000.1 {base} {species} str. test")
        assert check_reference_organism(g, expected) is None, (
            "a GTDB-suffixed genus was reported as the wrong organism; the "
            "guard would cry wolf on every correct field-database genome"
        )


class TestUninformativeSidesStillPass:
    def test_empty_expected_name_cannot_tell(self, tmp_path):
        g = _fasta(tmp_path, "NC_000000.1 Bacillus anthracis")
        assert check_reference_organism(g, "") is None
        assert check_reference_organism(g, None) is None

    def test_headerless_genome_cannot_tell(self, tmp_path):
        p = tmp_path / "bare.fasta"
        p.write_text(">contig1\nACGT\n")
        assert check_reference_organism(str(p), "Bacillus anthracis") is None

    def test_genus_only_expectation_still_compares_genus(self, tmp_path):
        g = _fasta(tmp_path, "NC_000000.1 Yersinia pestis CO92")
        assert check_reference_organism(g, "Bacillus") is not None
        assert check_reference_organism(g, "Yersinia") is None


class TestGtdbLumpingIsNotAMismatch:
    """GTDB files some species as a subspecies of a sibling.

    The Bioshield database calls *Burkholderia pseudomallei*
    "Burkholderia mallei subsp. pseudomallei", and *Brucella suis*
    "Brucella melitensis subsp. suis". The correct RefSeq reference for those
    entries is the NCBI species genome, whose header therefore reads
    ``Burkholderia pseudomallei`` -- same organism, different nomenclature.
    Warning about it would cry wolf on every correct genome for the field
    database, which trains operators to ignore the warning that matters.
    """

    @pytest.mark.parametrize("header,expected", [
        ("NC_006350.1 Burkholderia pseudomallei K96243 chromosome 1",
         "Burkholderia mallei subsp. pseudomallei"),
        ("NC_003317.1 Brucella suis 1330 chromosome I",
         "Brucella melitensis subsp. suis"),
        ("NZ_CP009257.1 Yersinia pseudotuberculosis IP 32953",
         "Yersinia pestis subsp. pseudotuberculosis"),
    ])
    def test_species_matching_the_subspecies_epithet_is_accepted(
            self, tmp_path, header, expected):
        assert check_reference_organism(_fasta(tmp_path, header), expected) is None

    def test_a_genuinely_wrong_species_still_warns(self, tmp_path):
        # Not the lumping pattern: the epithet does not match either.
        g = _fasta(tmp_path, "NC_000000.1 Burkholderia cepacia ATCC 25416")
        assert check_reference_organism(g, "Burkholderia mallei subsp. pseudomallei")
