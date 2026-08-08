"""Every way of changing the watchlist must re-hydrate the worker snapshot.

Background callbacks run in a separate OS process where the WatchlistManager
singleton is empty, so ``watchlist-entries-snapshot`` is the only thing they
can read. ``watchlist_preparation_layout.py`` states the contract in a
comment: "Keeping watchlist-table-refresh here is what keeps
watchlist-entries-snapshot hydrated for the background prep/rescan workers."

Upload violated it silently. ``handle_upload``, ``add_custom_species`` and
``handle_edit_modal`` all bump ``watchlist-tab-state``; none bumps
``watchlist-table-refresh``; and the hydrator listened only to the latter. So
after an upload the readiness checker, the rescan and the bundle export all
saw the pre-upload watchlist, and a readiness panel reporting on a watchlist
the operator had just replaced is a reassuring wrong answer about whether
screening is armed.

This is a cross-file Input/Output wiring gap: neither file is wrong on its
own, which is why no single-module test caught it. So the assertion here is
deliberately about the wiring itself -- the set of signals the mutators emit
must be a subset of the signals the hydrator listens to.
"""

from __future__ import annotations

import re

import dash
import pytest

from nanometa_live.app.tabs import preparation_tab, watchlist_tab

pytestmark = pytest.mark.callback

#: Callbacks that change the watchlist and therefore must reach the snapshot.
MUTATORS = ("handle_upload", "add_custom_species", "handle_edit_modal")


def _callback_map(register, **kwargs):
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register(app, **kwargs)
    return app.callback_map


#: Component ids inside a callback_map key, e.g.
#: "watchlist-tab-state.data...watchlist-upload-feedback.children".
_ID_IN_KEY = re.compile(r"([A-Za-z0-9_-]+)\.[A-Za-z_]+")


def _outputs_of(callback_map, func_name):
    """Component ids this callback writes, found by its function name.

    Dash encodes a callback's outputs in its callback_map key, so the key is
    the authoritative place to read them from.
    """
    for key, spec in callback_map.items():
        fn = spec.get("callback")
        name = getattr(getattr(fn, "__wrapped__", fn), "__name__", "")
        if name == func_name:
            return set(_ID_IN_KEY.findall(key))
    return None


def _hydrator_inputs():
    """Component ids the snapshot hydrator listens to."""
    cmap = _callback_map(preparation_tab.register_preparation_callbacks)
    for key, spec in cmap.items():
        if "watchlist-entries-snapshot" in key:
            # Pattern-matching ids are dicts; str() keeps them comparable
            # without pretending they are plain ids.
            return {
                i["id"] if isinstance(i["id"], str) else str(i["id"])
                for i in spec["inputs"]
            }
    return None


class TestMutatorsReachTheSnapshot:
    def test_the_hydrator_exists_and_has_inputs(self):
        assert _hydrator_inputs(), (
            "no callback outputs watchlist-entries-snapshot; background "
            "workers would have no watchlist at all"
        )

    @pytest.mark.parametrize("mutator", MUTATORS)
    def test_each_mutator_signal_is_observed_by_the_hydrator(self, mutator):
        """The wiring assertion this defect needed.

        Not "upload writes watchlist-table-refresh" -- that would pin one
        particular fix. What matters is that whatever signal the mutator
        emits, the hydrator is listening for it.
        """
        cmap = _callback_map(watchlist_tab.register_watchlist_callbacks)
        emitted = _outputs_of(cmap, mutator)
        assert emitted is not None, f"{mutator} is not a registered callback"

        observed = _hydrator_inputs()
        assert emitted & observed, (
            f"{mutator} writes {sorted(emitted)}, and the snapshot hydrator "
            f"listens to {sorted(observed)}. They do not intersect, so a "
            f"watchlist changed via {mutator} never reaches the background "
            f"workers: readiness, rescan and bundle export keep reporting on "
            f"the previous watchlist."
        )
