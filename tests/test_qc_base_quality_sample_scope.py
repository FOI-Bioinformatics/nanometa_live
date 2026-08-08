"""The Base Quality card must report the sample it is labelled with.

``update_base_quality_card`` takes ``selected-sample`` as an Input, but its
FASTP branch globbed every ``*.fastp.json`` in the directory and summed them,
so the card always showed the all-samples total no matter which sample was
picked. Only the seqkit fallback honoured the selection.

The sharpest case is a sample that produced nothing. Selecting a barcode whose
QC failed left this card showing a large, real, measured figure -- taken from
the other barcodes -- directly beside tiles correctly reporting zero for that
same sample. A number that was measured, presented as belonging to something
it does not describe, is the failure class this project guards against, one
tile down from the verdict banner.
"""

from __future__ import annotations

import json
import os
import pathlib
import time

import pytest

pytestmark = pytest.mark.unit


def _fastp(path: pathlib.Path, total_bases: int) -> None:
    """A minimal fastp report with a known base count."""
    path.write_text(json.dumps({
        "summary": {"after_filtering": {
            "total_bases": total_bases,
            "q20_bases": int(total_bases * 0.9),
            "q30_bases": int(total_bases * 0.8),
        }},
        "read1_after_filtering": {"quality_curves": {"mean": [30.0, 31.0]}},
    }))
    old = time.time() - 300  # past the loaders' file-stability window
    os.utime(path, (old, old))


@pytest.fixture
def results(tmp_path):
    """Three samples with distinct, non-round base counts."""
    fastp_dir = tmp_path / "fastp"
    fastp_dir.mkdir()
    counts = {"barcode01": 45_890_009, "barcode02": 29_650_414,
              "barcode03": 25_469_870}
    for sample, bases in counts.items():
        _fastp(fastp_dir / f"{sample}.fastp.json", bases)
    return tmp_path, counts


def _total_bases_for(results_dir, selected_sample):
    """Total bases the card's FASTP branch would report for a selection.

    Mirrors the production selection logic via the helper it now uses, so the
    test pins behaviour rather than re-implementing the glob.
    """
    from nanometa_live.app.tabs.qc_tab import _fastp_files_for_sample

    total = 0
    for path in _fastp_files_for_sample(
        os.path.join(str(results_dir), "fastp"), selected_sample
    ):
        with open(path) as fh:
            data = json.load(fh)
        total += data["summary"]["after_filtering"]["total_bases"]
    return total


class TestTheCardFollowsTheSelection:
    def test_a_selected_sample_reports_only_its_own_bases(self, results):
        results_dir, counts = results

        assert _total_bases_for(results_dir, "barcode01") == counts["barcode01"], (
            "the card summed every sample's fastp.json while labelled as "
            "scoped to barcode01"
        )

    def test_each_sample_differs_from_the_aggregate(self, results):
        results_dir, counts = results
        aggregate = sum(counts.values())

        for sample, expected in counts.items():
            assert _total_bases_for(results_dir, sample) == expected
            assert _total_bases_for(results_dir, sample) != aggregate

    def test_all_samples_still_aggregates(self, results):
        """The aggregate view is legitimate and must keep working."""
        results_dir, counts = results

        assert _total_bases_for(results_dir, "All Samples") == sum(counts.values())
        assert _total_bases_for(results_dir, None) == sum(counts.values())

    def test_a_sample_that_produced_nothing_reports_nothing(self, results):
        """The ghost-sample case, stated on its own.

        A barcode listed in the manifest whose QC died has no fastp.json. The
        card must report zero for it, not the other barcodes' total, which
        would fabricate a measurement for a sample that produced none.
        """
        results_dir, _ = results

        assert _total_bases_for(results_dir, "barcode04") == 0, (
            "a sample with no QC output was credited with other samples' "
            "bases"
        )
