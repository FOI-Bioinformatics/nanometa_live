"""The GUI should use the manifest's own failure record, not only infer it.

nanometanf now records ``failed_samples`` in ``canonical/_manifest.json``: the
samples it attempted that emitted no QC output. Until this, nanometa_live read
that manifest for its sample list and ignored the field entirely, inferring
failures instead by diffing ``available-samples`` against
``sample-file-mapping``.

The inference is sound and stays -- it catches outputs that vanished after the
manifest was written, which the manifest cannot know about. But it has one
blind spot the authoritative field does not: it is guarded on the file mapping
being populated, because marking every sample before the first scan would be
worse than marking none. In that window a sample whose QC failed is offered
exactly like a healthy one, which is the situation the whole mechanism exists
to prevent.

``failed_samples`` is null when the pipeline could not determine the answer.
That is not "nothing failed" and must not be read as such.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from nanometa_live.core.utils.sample_detector import get_failed_samples

pytestmark = pytest.mark.unit


def _manifest(tmp_path: pathlib.Path, payload) -> str:
    canonical = tmp_path / "canonical"
    canonical.mkdir(parents=True, exist_ok=True)
    (canonical / "_manifest.json").write_text(json.dumps(payload))
    return str(tmp_path)


class TestReadingTheRecordedFailures:
    def test_named_failures_are_returned(self, tmp_path):
        main_dir = _manifest(tmp_path, {
            "samples": ["barcode01", "barcode02"],
            "failed_samples": ["barcode02"],
        })

        assert get_failed_samples(main_dir) == {"barcode02"}

    def test_an_empty_list_means_nothing_failed(self, tmp_path):
        """Determined, and the answer is none -- distinct from unknown."""
        main_dir = _manifest(tmp_path, {
            "samples": ["barcode01"], "failed_samples": [],
        })

        assert get_failed_samples(main_dir) == set()

    def test_null_means_undetermined_and_yields_nothing(self, tmp_path):
        """Not 'nothing failed'. The caller must not mark on this basis."""
        main_dir = _manifest(tmp_path, {
            "samples": ["barcode01"], "failed_samples": None,
        })

        assert get_failed_samples(main_dir) == set()

    def test_a_manifest_without_the_field_yields_nothing(self, tmp_path):
        """Older pipeline output predates the field."""
        main_dir = _manifest(tmp_path, {"samples": ["barcode01"]})

        assert get_failed_samples(main_dir) == set()

    def test_no_manifest_at_all_yields_nothing(self, tmp_path):
        assert get_failed_samples(str(tmp_path)) == set()

    def test_a_corrupt_manifest_does_not_raise(self, tmp_path):
        """A broken manifest must not take the sample selector down."""
        canonical = tmp_path / "canonical"
        canonical.mkdir()
        (canonical / "_manifest.json").write_text("{not json")

        assert get_failed_samples(str(tmp_path)) == set()


class TestTheSelectorMarksManifestFailures:
    """The gap the inference alone leaves open.

    ``sample-file-mapping`` is empty until the first filesystem scan, and the
    inference is deliberately disabled while it is -- marking every sample
    then would be worse than marking none. In that window a barcode whose QC
    failed was offered exactly like a healthy one. The manifest knows, so use
    it.
    """

    @staticmethod
    def _selector_fn():
        import dash

        from nanometa_live.app.callbacks import samples as samples_mod
        from tests.dash_test_utils import get_callback_fn

        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        samples_mod.register_samples(app, backend_manager=None)
        return get_callback_fn(
            app, "sample-selector", input_contains="available-samples"
        )

    def test_a_failed_sample_is_marked_before_any_file_scan(self, tmp_path):
        main_dir = _manifest(tmp_path, {
            "samples": ["barcode01", "barcode02"],
            "failed_samples": ["barcode02"],
        })
        fn = self._selector_fn()

        options, _value = fn(
            ["All Samples", "barcode01", "barcode02"], {}, "All Samples",
            {},  # file mapping still empty: inference cannot fire
            {"results_output_directory": main_dir},
        )

        rendered = str(options)
        marked = str([o for o in options if o["value"] == "barcode02"])
        healthy = str([o for o in options if o["value"] == "barcode01"])

        assert "no data" in marked, (
            "the sample the pipeline recorded as failed was offered like a "
            f"healthy one: {rendered[:400]}"
        )
        assert "no data" not in healthy, (
            "a healthy sample was marked; the manifest named only barcode02"
        )

    def test_an_undetermined_manifest_marks_nothing(self, tmp_path):
        """null is not 'nothing failed', but it is not 'something failed'."""
        main_dir = _manifest(tmp_path, {
            "samples": ["barcode01", "barcode02"], "failed_samples": None,
        })
        fn = self._selector_fn()

        options, _ = fn(
            ["All Samples", "barcode01", "barcode02"], {}, "All Samples",
            {}, {"results_output_directory": main_dir},
        )

        assert "no data" not in str(options)

    def test_no_config_does_not_break_the_selector(self):
        """The selector must render with no config at all."""
        fn = self._selector_fn()

        options, _ = fn(["All Samples", "barcode01"], {}, "All Samples", {}, None)

        assert len(options) == 2
