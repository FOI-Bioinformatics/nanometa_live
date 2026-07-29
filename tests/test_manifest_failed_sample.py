"""A sample that produced no data must not be offered as if it had.

The chain, verified end to end on 2026-07-29:

1. A FASTQ that is not readable (truncated transfer, wrong extension) makes
   CHOPPER exit 1 with "not in gzip format".
2. ``conf/error_isolation.config`` -- included unconditionally by
   ``nextflow.config`` -- ignores exit 1 and 2 for CHOPPER, so the pipeline
   reports SUCCESS. That is correct: one bad barcode must not abort the other
   23 in a multiplexed run.
3. ``bin/write_manifest.py`` lists the sample anyway. It does not discover
   files, it PREDICTS them -- ``<sample>.classification.json`` and
   ``<sample>.qc_stats.json`` for every sample and every active tool -- and its
   own comment explains why it cannot verify: MANIFEST_WRITER runs in its own
   work directory, not the publishDir.
4. ``sample_detector._samples_from_manifest`` returns that list verbatim.
5. The operator is offered the sample in the selector, picks it, and sees
   nothing.

"Nothing" for a sample whose reads were unreadable looks exactly like
"nothing detected" for a clean sample. Those are opposite statements: a
missing measurement versus a negative result someone may act on.

The remedy is a product decision, so this pins the current behaviour rather
than asserting an unagreed fix. Two options, both defensible:

- Cross-check the manifest against data on disk in the detector, and mark
  (not hide -- hiding loses the information that the sample existed) samples
  with no data.
- Have the pipeline record per-sample status, which needs the manifest writer
  to learn what error isolation swallowed.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from nanometa_live.core.utils import sample_detector as sd

pytestmark = pytest.mark.unit

KRAKEN_REPORT = (
    "100.00\t500\t0\tR\t1\troot\n"
    " 90.00\t450\t450\tS\t263\t  Francisella tularensis\n"
)


@pytest.fixture
def tree_with_a_dataless_sample(tmp_path) -> pathlib.Path:
    """A results tree as the pipeline writes it after one sample fails QC."""
    (tmp_path / "canonical").mkdir(parents=True)
    (tmp_path / "kraken2").mkdir()

    # The healthy sample produced a real report.
    (tmp_path / "kraken2" / "healthy.kraken2.report.txt").write_text(KRAKEN_REPORT)

    # The manifest lists both, because it predicts filenames per sample and
    # never checks whether they were written.
    (tmp_path / "canonical" / "_manifest.json").write_text(json.dumps({
        "format_version": "1.0.0",
        "samples": ["healthy", "failed_qc"],
        "outputs": {
            "classification": {
                "available": True,
                "files": [
                    "healthy.classification.json",
                    "failed_qc.classification.json",
                ],
            }
        },
    }))
    sd.invalidate_sample_cache()
    return tmp_path


class TestTheManifestIsAPredictionNotAnInventory:
    def test_the_manifest_claims_files_it_never_verified(
        self, tree_with_a_dataless_sample
    ):
        """Pins the root cause, so the reason is visible where it is fixed."""
        manifest = json.loads(
            (tree_with_a_dataless_sample / "canonical" / "_manifest.json").read_text()
        )
        claimed = manifest["outputs"]["classification"]["files"]
        missing = [
            f for f in claimed
            if not list(tree_with_a_dataless_sample.rglob(f))
        ]
        assert missing, (
            "fixture no longer represents the reported situation; it should "
            "contain a claimed-but-absent output file"
        )


class TestDatalessSampleIsDistinguishable:
    def test_a_sample_with_data_is_offered(self, tree_with_a_dataless_sample):
        """Control: the healthy sample must still appear."""
        samples = sd.get_available_samples(str(tree_with_a_dataless_sample))
        assert "healthy" in samples

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "OPEN DEFECT, reported 2026-07-29. A sample whose QC failed is "
            "offered in the selector exactly like a healthy one, because the "
            "manifest lists it and the detector trusts the manifest. Selecting "
            "it shows nothing, which is indistinguishable from a clean "
            "negative. The remedy is a product decision -- mark the sample, or "
            "have the pipeline record per-sample status -- so the behaviour is "
            "pinned rather than patched. strict=True turns this into a failure "
            "once fixed, which is the signal to delete the marker."
        ),
    )
    def test_a_sample_with_no_data_is_not_silently_offered(
        self, tree_with_a_dataless_sample
    ):
        samples = sd.get_available_samples(str(tree_with_a_dataless_sample))
        assert "failed_qc" not in samples, (
            "a sample with no data on disk is offered to the operator "
            "identically to one with results; an empty view of it reads as "
            "'nothing detected' rather than 'this sample was never processed'"
        )

    def test_the_detector_can_at_least_see_the_difference(
        self, tree_with_a_dataless_sample
    ):
        """Whatever the remedy, the information needed for it is available.

        The filesystem knows which samples produced data. This asserts the
        detector's own directory scan disagrees with the manifest, so a
        cross-check is possible without pipeline changes.
        """
        from_scan = sd.detect_samples_from_kraken(
            str(tree_with_a_dataless_sample / "kraken2")
        )
        assert "healthy" in from_scan
        assert "failed_qc" not in from_scan, (
            "the directory scan should not find a sample that produced no "
            "files; if it does, the cross-check suggested in the module "
            "docstring will not work"
        )
