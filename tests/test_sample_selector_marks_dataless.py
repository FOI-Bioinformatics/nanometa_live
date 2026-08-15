"""A sample that produced no files must not look like one that found nothing.

End of the chain traced in tests/test_manifest_failed_sample.py:

    unreadable FASTQ -> CHOPPER exit 1 -> error isolation absorbs it ->
    run reports SUCCESS -> manifest lists the sample -> selector offers it

``bin/write_manifest.py`` does not discover outputs, it predicts them, and
cannot verify them because MANIFEST_WRITER runs in its own work directory. So
the fix belongs at the consumer, which does have the results tree.

``sample-file-mapping`` is built from files actually on disk. A sample present
in ``available-samples`` but absent from that mapping produced nothing, and is
now marked in the dropdown. It is still offered: hiding it would lose the fact
that the barcode was attempted at all.
"""

from __future__ import annotations

import pytest

from dash_test_utils import get_callback_fn, make_callback_app
from nanometa_live.app.callbacks.samples import register_samples

pytestmark = pytest.mark.unit


def _texts(component):
    """Every string anywhere in a component tree."""
    if isinstance(component, str):
        return [component]
    if isinstance(component, (list, tuple)):
        return [s for c in component for s in _texts(c)]
    children = getattr(component, "children", None)
    out = _texts(children) if children is not None else []
    for attr in ("title",):
        v = getattr(component, attr, None)
        if isinstance(v, str):
            out.append(v)
    return out


@pytest.fixture
def selector_fn():
    from unittest.mock import MagicMock

    app = make_callback_app(lambda a: register_samples(a, MagicMock()))
    return get_callback_fn(app, "sample-selector", input_contains="available-samples")


def _labels(fn, samples, mapping):
    options, _value = fn(samples, {}, "All Samples", mapping)
    return {o["value"]: " ".join(_texts(o["label"])) for o in options}


class TestDatalessSamplesAreMarked:
    def test_a_sample_with_no_files_is_marked(self, selector_fn):
        labels = _labels(
            selector_fn,
            ["All Samples", "healthy", "failed_qc"],
            {"healthy": {"kraken2": ["healthy.kraken2.report.txt"]}},
        )
        assert "no data" in labels["failed_qc"].lower(), (
            f"a sample that produced nothing is offered identically to one "
            f"with results: {labels['failed_qc']!r}"
        )

    def test_a_sample_with_files_is_not_marked(self, selector_fn):
        labels = _labels(
            selector_fn,
            ["All Samples", "healthy", "failed_qc"],
            {"healthy": {"kraken2": ["healthy.kraken2.report.txt"]}},
        )
        assert "no data" not in labels["healthy"].lower()

    def test_the_marked_sample_is_still_offered(self, selector_fn):
        """Hiding it would lose the fact that the barcode was attempted."""
        labels = _labels(
            selector_fn,
            ["All Samples", "healthy", "failed_qc"],
            {"healthy": {"kraken2": ["x"]}},
        )
        assert "failed_qc" in labels

    def test_the_marker_explains_itself(self, selector_fn):
        """A badge reading 'no data' invites the wrong reading on its own."""
        labels = _labels(
            selector_fn,
            ["All Samples", "failed_qc"],
            {"other": {"kraken2": ["x"]}},
        )
        text = labels["failed_qc"].lower()
        assert "not a negative result" in text, (
            f"the marker should say what it means, since an empty view of the "
            f"sample otherwise reads as a clean result: {text!r}"
        )


class TestNothingIsMarkedWithoutEvidence:
    def test_an_empty_mapping_marks_nothing(self, selector_fn):
        """Before the first scan the mapping is empty; marking everything then
        would be worse than marking nothing."""
        labels = _labels(selector_fn, ["All Samples", "a", "b"], {})
        assert all("no data" not in v.lower() for v in labels.values())

    def test_a_missing_mapping_marks_nothing(self, selector_fn):
        labels = _labels(selector_fn, ["All Samples", "a", "b"], None)
        assert all("no data" not in v.lower() for v in labels.values())

    def test_the_aggregate_entry_is_never_marked(self, selector_fn):
        labels = _labels(selector_fn, ["All Samples", "a"], {"a": {"kraken2": ["x"]}})
        assert "no data" not in labels["All Samples"].lower()
