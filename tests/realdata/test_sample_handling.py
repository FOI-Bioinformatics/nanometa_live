"""Sample handling must not change which organisms were found.

The same reads can be presented to the pipeline three ways: one sample per
barcode directory, one sample per file, or every file merged into a single
sample. Which one an operator picks is a bookkeeping decision about how results
are grouped. It must not change the biology.

That property has never been tested, and it is exactly where taxonomy bugs have
hidden before: the GTDB/flextaxd attribution defect found in July 2025 was
invisible on an NCBI database because the two taxid spaces coincided, and
surfaced only when a detection had to be resolved back to a sample.

The failure mode here is quiet in both directions. Losing an organism when
files are merged is a false negative. Inventing one when they are split is a
false positive on a sample that never contained it.

Run against two trees over the SAME input, processed differently::

    NANOMETA_REALDATA_DIR=/path/to/per_file_run \\
    NANOMETA_REALDATA_COMPARE_DIR=/path/to/single_sample_run \\
      pytest tests/realdata/test_sample_handling.py -v
"""

from __future__ import annotations

import pytest

from .kreport import Report

pytestmark = pytest.mark.integration

#: Taxa below this many reads are tail noise: present in one grouping and
#: absent in another for reasons of rounding rather than biology. The
#: assertions below are about organisms the operator would act on.
READ_FLOOR = 5


def _taxa_above_floor(report: Report, floor: int = READ_FLOOR) -> set[int]:
    return {r.taxid for r in report.species() if r.cumulative_reads >= floor}


def _union_over(reports: dict) -> set[int]:
    out: set[int] = set()
    for path in reports.values():
        out |= _taxa_above_floor(Report.from_file(path))
    return out


def _total_classified(reports: dict) -> int:
    return sum(Report.from_file(p).classified_reads for p in reports.values())


class TestGroupingPreservesOrganisms:
    """The core property, in both directions."""

    def test_merging_files_loses_no_organism(
        self, kraken_reports, compare_kraken_reports
    ):
        """Every taxon seen per-file must survive being merged into one sample.

        A taxon that vanishes when the same reads are analysed together is a
        false negative produced purely by a grouping choice.
        """
        per_file = _union_over(kraken_reports)
        merged = _union_over(compare_kraken_reports)

        lost = per_file - merged
        assert not lost, (
            f"{len(lost)} taxa were found per-file but disappeared when the "
            f"same reads were merged into one sample: {sorted(lost)}. The "
            f"grouping choice changed the biological result."
        )

    def test_splitting_files_invents_no_organism(
        self, kraken_reports, compare_kraken_reports
    ):
        """And nothing may appear only when the reads are split apart."""
        per_file = _union_over(kraken_reports)
        merged = _union_over(compare_kraken_reports)

        invented = merged - per_file
        assert not invented, (
            f"{len(invented)} taxa appear only in the merged analysis and in "
            f"no individual file: {sorted(invented)}. Merging is creating "
            f"detections that no constituent sample supports."
        )


class TestNoReadsAreLost:
    """Grouping changes how reads are labelled, not how many there are."""

    def test_total_classified_reads_agree(
        self, kraken_reports, compare_kraken_reports
    ):
        """Allows a small margin: classification is per-batch, and merging can
        shift a handful of reads across the confidence boundary. A large gap
        means reads are being dropped or double-counted."""
        left = _total_classified(kraken_reports)
        right = _total_classified(compare_kraken_reports)
        assert left > 0 and right > 0, (
            f"one side classified nothing (per-file {left}, merged {right})"
        )

        drift = abs(left - right) / max(left, right)
        assert drift < 0.05, (
            f"classified read totals differ by {drift:.1%} "
            f"(per-file {left}, merged {right}). Grouping should relabel reads, "
            f"not gain or lose them."
        )


class TestPerFileAttributionIsSpecific:
    """Splitting must actually attribute, not copy everything everywhere."""

    def test_not_every_sample_carries_every_taxon(self, kraken_reports):
        """The point of per-file handling is telling samples apart.

        If each sample reports the same taxon set, attribution has collapsed
        and the operator cannot tell which specimen a detection came from --
        which is the whole reason to split.
        """
        if len(kraken_reports) < 2:
            pytest.skip("needs at least two samples to compare attribution")

        sets = {
            name: _taxa_above_floor(Report.from_file(path))
            for name, path in kraken_reports.items()
        }
        non_empty = {n: s for n, s in sets.items() if s}
        if len(non_empty) < 2:
            pytest.skip("fewer than two samples have taxa above the floor")

        distinct = {frozenset(s) for s in non_empty.values()}
        assert len(distinct) > 1, (
            f"all {len(non_empty)} samples report an identical taxon set "
            f"{sorted(next(iter(distinct)))}. Per-file attribution is not "
            f"discriminating between samples."
        )

    def test_each_sample_has_its_own_report(self, kraken_reports):
        """Per-file handling must produce one report per input file."""
        assert len(kraken_reports) > 1, (
            f"per-file handling produced {len(kraken_reports)} report(s); the "
            f"input had multiple files, so they were merged rather than split"
        )
