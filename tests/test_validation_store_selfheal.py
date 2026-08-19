"""The validation store must self-heal when the browser missed a write.

Reproduced live on 2026-08-19 (field bug report, realtime run): the Validation
tab showed "Results directory not found" for the remainder of a run while
confirmed results sat on disk and the server had demonstrably built them
("Loaded 10 validation results" in the app log). The sequence:

1. ``load_validation_data`` renders and calls ``mark_rendered`` -- an
   IN-PROCESS memo saying "fingerprint X has been delivered".
2. The browser never applies that response (superseded/discarded request);
   the ``validation-data-store`` keeps its previous payload -- in the field
   case the pre-run "no results dir" diagnostic.
3. Every subsequent interval tick consults the in-process memo, concludes
   the refresh is redundant, and raises PreventUpdate.
4. When the realtime run goes quiet (all files processed -- exactly the
   reporter's situation) the fingerprint never changes again, so no
   non-interval trigger ever arrives and the stale panel is permanent.

The defence is the same one ``interval_tick_is_redundant_store`` documents
for background callbacks: the rendered-fingerprint memo must ride THE SAME
RESPONSE as the data, round-tripping through the browser. Then a discarded
response also discards the memo update, the next tick sees the mismatch, and
the store repairs itself within one interval.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash import Dash

from nanometa_live.app.utils.debounce import fp_to_store, mark_rendered
from tests.dash_test_utils import get_callback_fn


@contextmanager
def _ctx(triggered_id):
    """validation_tab binds ``ctx`` module-locally (``from dash import ctx``),
    so patch the module attribute, not ``dash.ctx``."""
    import nanometa_live.app.tabs.validation_tab as vt

    with patch.object(vt, "ctx", MagicMock(triggered_id=triggered_id)):
        yield


FP = {"fp": "abc123", "ts": 1.0, "first_batch_seen": True}


@pytest.fixture()
def load_validation_data():
    from nanometa_live.app.tabs.validation_tab import register_validation_callbacks

    app = Dash(__name__)
    register_validation_callbacks(app)
    return get_callback_fn(app, "validation-data-store.data")


@pytest.fixture()
def load_consensus_data():
    from nanometa_live.app.tabs.validation_tab import register_validation_callbacks

    app = Dash(__name__)
    register_validation_callbacks(app)
    return get_callback_fn(app, "consensus-data-store.data")


class TestSelfHealGate:
    def _call(self, fn, rendered_fp, trigger="update-interval.n_intervals"):
        with _ctx(trigger), \
             patch(
                 "nanometa_live.app.tabs.validation_tab.build_validation_store",
                 return_value={"results": [{"x": 1}], "summary": {},
                               "message": None},
             ):
            return fn(FP, None, 7, "cumulative", None, rendered_fp,
                      {"blast_validation": True}, {"running": True})

    def test_interval_tick_with_matching_store_memo_is_skipped(
            self, load_validation_data):
        from dash.exceptions import PreventUpdate

        with pytest.raises(PreventUpdate):
            self._call(load_validation_data, rendered_fp=fp_to_store(FP))

    def test_interval_tick_rebuilds_when_browser_never_applied_the_write(
            self, load_validation_data):
        # The in-process memo claims this fingerprint was already rendered --
        # the exact state after a response the browser discarded. The
        # store-backed memo (None: the browser holds the old payload) must
        # win, or the panel stays stale for the rest of a quiet run.
        mark_rendered("load_validation_data", FP)
        payload, rendered = self._call(load_validation_data, rendered_fp=None)
        assert payload["results"], "the rebuild did not run"
        assert rendered == fp_to_store(FP), (
            "the rendered-fingerprint memo must ride the same response as "
            "the data, or the two can diverge again"
        )

    def test_stale_store_memo_triggers_rebuild(self, load_validation_data):
        payload, rendered = self._call(
            load_validation_data, rendered_fp="older-fp")
        assert payload["results"]
        assert rendered == fp_to_store(FP)

    def test_non_interval_trigger_always_rebuilds(self, load_validation_data):
        payload, rendered = self._call(
            load_validation_data, rendered_fp=fp_to_store(FP),
            trigger="results-fingerprint.data")
        assert payload["results"]
        assert rendered == fp_to_store(FP)


class TestConsensusSelfHealGate:
    def _call(self, fn, rendered_fp, tmp_path,
              trigger="update-interval.n_intervals"):
        class _R:
            has_sequence = False

            def __init__(self):
                self.__dict__.update({"sample_id": "s", "taxid": 1})

        with _ctx(trigger), \
             patch(
                 "nanometa_live.app.tabs.validation_tab.collect_consensus_results",
                 return_value=[_R()],
             ):
            return fn(FP, None, 7, rendered_fp,
                      {"results_output_directory": str(tmp_path)})

    def test_interval_tick_with_matching_store_memo_is_skipped(
            self, load_consensus_data, tmp_path):
        from dash.exceptions import PreventUpdate

        with pytest.raises(PreventUpdate):
            self._call(load_consensus_data, rendered_fp=fp_to_store(FP),
                       tmp_path=tmp_path)

    def test_interval_tick_rebuilds_when_browser_never_applied_the_write(
            self, load_consensus_data, tmp_path):
        mark_rendered("load_consensus_data", FP)
        payload, rendered = self._call(load_consensus_data, rendered_fp=None,
                                       tmp_path=tmp_path)
        assert payload["results"]
        assert rendered == fp_to_store(FP)
