"""Properties every ``background=True`` Dash callback must satisfy.

Dash runs background callbacks in a SEPARATE OS PROCESS via
``DiskcacheManager``. That process boundary breaks assumptions which hold
everywhere else in the app, and it breaks them QUIETLY -- the callback appears
to run and the UI simply never updates. None of the ~206 in-process callback
tests can catch this, because they call the function directly in the main
process where module singletons are populated and any Python object is a valid
return value.

This test walks the source of every module that registers callbacks, finds the
``background=True`` ones by their decorator, and asserts the properties that
are statically checkable. It discovers them by introspection rather than from a
hardcoded list, so a callback added tomorrow is covered without touching this
file.

WHAT THIS TEST DOES NOT COVER
-----------------------------
It does not verify that return values are JSON-serialisable. That is the single
most likely silent failure at the process boundary, but establishing it needs
the callback to actually run, which needs a live DiskcacheManager, real config,
and in several cases a real pipeline. Executing 22 such callbacks is out of
scope here. Treat serialisability as UNVERIFIED, not as covered -- a green run
of this file says nothing about it.

It also does not check runtime behaviour of any kind: whether a callback
honours its own cancel, whether ``set_progress`` is actually called, or whether
the worker can reach the state it needs. Only the declarations are checked.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.unit

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "nanometa_live" / "app"

#: Accessors that read a process-local singleton. A background callback that
#: calls one of these is reading an EMPTY object in the worker: the singleton
#: was populated in the main process and does not cross the fork.
SINGLETON_ACCESSORS = {"get_watchlist_manager"}

#: The two supported ways to get watchlist state into a worker process. Either
#: the main process hydrates a Store and the worker reads it (the pattern
#: documented in CLAUDE.md), or the worker takes the config and loads the
#: manager from it itself. Both cross the boundary; what fails is calling the
#: singleton accessor with neither, which yields an empty manager.
WATCHLIST_SNAPSHOT_STORE = "watchlist-entries-snapshot"
APP_CONFIG_STORE = "app-config"
WATCHLIST_STATE_SOURCES = (WATCHLIST_SNAPSHOT_STORE, APP_CONFIG_STORE)

#: Background callbacks that currently declare no ``cancel=``, recorded as of
#: 2026-07-28. This is a RATCHET, not an endorsement: the list pins the status
#: quo so a newly added background callback cannot quietly ship without a
#: cancel control, while not turning an existing design choice into 17 red
#: tests.
#:
#: Most entries are defensible -- polling and recompute callbacks are bounded
#: and idempotent, so cancelling buys the operator nothing. Several are not
#: obviously so and are worth revisiting: ``download_kraken_database`` fetches
#: several GB, ``export_bundle`` / ``import_bundle_worker`` move a whole
#: installation, and the genome import workers walk arbitrary directories. An
#: operator who starts one of those on a field laptop cannot stop it.
#:
#: Shrinking this set is an improvement. Growing it needs a reason.
#: Background callbacks with neither running= nor progress=, recorded as a
#: RATCHET (round-2 audit, 2026-08-24). Every entry is tick- or startup-
#: driven -- no operator click starts it, so there is no interaction to
#: leave frozen. Anything an operator triggers must declare feedback.
FEEDBACK_NOT_DECLARED = {
    "check_internet_on_startup",   # startup probe, no operator action
    "update_main_results",         # tick recompute (Organisms tab)
    "update_qc_stats",             # tick recompute (QC tiles)
    "populate_pipeline_branch_options",  # config dropdown fill on load
}

CANCEL_NOT_DECLARED = {
    "check_internet_on_startup",
    "download_kraken_database",
    "download_single_genome",
    # export_bundle / force_export_bundle / import_bundle_worker now declare
    # cancel= (2026-08-27) and are deliberately NOT in this set.
    #
    # Dry-run verify: extraction + checksumming of a local file, bounded by
    # bundle size; running= disables the button and nothing is written, so
    # an interrupt has no state to strand.
    "verify_bundle_worker",
    # One NCBI/GTDB lookup, bounded by 5 s HTTP timeouts and the per-host
    # circuit breaker (~20 s worst case); the running= disable prevents
    # stacking clicks and there is no meaningful mid-flight state to save.
    "lookup_species",
    # Four kaleido PNG renders, bounded and unresumable; the
    # confirm button is disabled while it runs.
    "export_qc_plots",
    # Native OS dialogs: they end when the operator dismisses them;
    # running= already prevents a second dialog.
    "browse_export_directory",
    "browse_import_bundle",
    "browse_import_kraken_db",
    # The report export writes into the operator-chosen output dir;
    # killing it mid-copy strands a half-written export, and both
    # modal buttons are disabled while it runs.
    "generate_export",
    # Local file validation + copy of one YAML, a few seconds even at 500
    # entries; there is no long-running phase for a cancel to interrupt,
    # and an interrupted copy would strand a half-imported file.
    "import_watchlist_worker",
    "import_genomes_from_archive_worker",
    "import_genomes_from_dir_worker",
    "import_mapped_genomes_worker",
    "populate_pipeline_branch_options",
    "regenerate_mappings",
    "run_on_demand_validation",
    "run_rescan",
    "test_genome_download",
    "update_main_results",
    "update_qc_stats",
    "update_readiness_state",
    "validate_entries",
}


@dataclass
class BackgroundCallback:
    """One registered ``background=True`` callback, as declared in source."""

    name: str
    module: pathlib.Path
    lineno: int
    params: list[str]
    running: list[ast.expr] = field(default_factory=list)
    has_progress: bool = False
    has_cancel: bool = False
    state_ids: list[str] = field(default_factory=list)
    singleton_calls: set[str] = field(default_factory=set)

    @property
    def where(self) -> str:
        return f"{self.module.name}:{self.lineno} {self.name}()"


def _decorator_kwargs(dec: ast.expr) -> dict[str, ast.expr]:
    if not isinstance(dec, ast.Call):
        return {}
    return {kw.arg: kw.value for kw in dec.keywords if kw.arg}


def _is_background(kwargs: dict[str, ast.expr]) -> bool:
    node = kwargs.get("background")
    return isinstance(node, ast.Constant) and node.value is True


def _component_ids(dec: ast.Call) -> list[str]:
    """Component ids of every ``State(...)`` in the decorator.

    Both Dash argument styles are in use here: States passed as bare
    positional arguments, and States grouped inside a list. Walking the whole
    decorator subtree covers both -- an earlier version inspected only
    ``dec.args`` and so reported the list-style callbacks as declaring no
    State at all.
    """
    ids = []
    for node in ast.walk(dec):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "State"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            ids.append(node.args[0].value)
    return ids


def _called_names(fn: ast.FunctionDef) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _collect() -> list[BackgroundCallback]:
    found: list[BackgroundCallback] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for dec in fn.decorator_list:
                kwargs = _decorator_kwargs(dec)
                if not _is_background(kwargs):
                    continue
                running = kwargs.get("running")
                found.append(
                    BackgroundCallback(
                        name=fn.name,
                        module=path,
                        lineno=fn.lineno,
                        params=[a.arg for a in fn.args.args],
                        running=list(running.elts) if isinstance(running, ast.List) else [],
                        has_progress="progress" in kwargs,
                        has_cancel="cancel" in kwargs,
                        state_ids=_component_ids(dec) if isinstance(dec, ast.Call) else [],
                        singleton_calls=_called_names(fn) & SINGLETON_ACCESSORS,
                    )
                )
    return found


BACKGROUND_CALLBACKS = _collect()


def _ids(cbs):
    return [c.name for c in cbs]


class TestDiscovery:
    def test_background_callbacks_are_found(self):
        """A guard on the introspection itself.

        If a Dash upgrade or a refactor changed how these are declared, this
        file would silently pass by finding nothing and asserting nothing.
        """
        assert len(BACKGROUND_CALLBACKS) >= 22, (
            f"found only {len(BACKGROUND_CALLBACKS)} background callbacks; "
            f"there were 22 on 2026-07-28. The AST introspection has probably "
            f"stopped matching the decorator form, which would make every test "
            f"below vacuous. Note a plain grep for 'background=True' reports 23 "
            f"because one occurrence is inside a comment in preparation_tab.py."
        )


@pytest.mark.parametrize("cb", BACKGROUND_CALLBACKS, ids=_ids(BACKGROUND_CALLBACKS))
class TestPerCallbackContract:
    def test_running_entries_declare_a_restore_value(self, cb):
        """``running`` entries must be (Output, active, restore) triples.

        With no restore value the control keeps whatever the active value set
        it to. In practice that means a button disabled at the start of the
        callback stays disabled for the rest of the session if the callback
        raises, and the operator has to restart the app to get it back.
        """
        for entry in cb.running:
            assert isinstance(entry, ast.Tuple), (
                f"{cb.where}: running entry is {type(entry).__name__}, expected "
                f"a (Output, active, restore) tuple"
            )
            assert len(entry.elts) == 3, (
                f"{cb.where}: running entry has {len(entry.elts)} elements, "
                f"expected 3. Without a restore value an exception leaves the "
                f"control stuck in its active state until the app restarts."
            )

    def test_progress_callbacks_take_set_progress_first(self, cb):
        """Dash passes ``set_progress`` as the first positional argument.

        A mismatch is a TypeError raised inside the worker process, where it
        surfaces as the UI never updating rather than as a visible error.
        """
        if not cb.has_progress:
            pytest.skip("declares no progress=")
        assert cb.params and cb.params[0] == "set_progress", (
            f"{cb.where} declares progress= but its first parameter is "
            f"{cb.params[0] if cb.params else '<none>'!r}, not 'set_progress'"
        )

    def test_background_callbacks_declare_visible_feedback(self, cb):
        """Every background callback declares running= or progress=.

        Round-2 acceptance criterion: the operator must ALWAYS see
        progress instead of a frozen screen. running= (disable the
        button, reveal a spinner/modal) is the minimum; progress= for
        anything staged. FEEDBACK_NOT_DECLARED is a ratchet for the
        tick-driven recompute callbacks that no operator click starts --
        shrinking it is an improvement, growing it needs a reason.
        """
        if cb.name in FEEDBACK_NOT_DECLARED:
            pytest.skip("recorded in the FEEDBACK_NOT_DECLARED baseline")
        assert cb.running or cb.has_progress, (
            f"{cb.where} is a background callback with neither running= "
            f"nor progress=: whoever triggers it stares at a frozen "
            f"screen. Declare at least a running= affordance, or baseline "
            f"it with a reason."
        )

    def test_new_background_callbacks_declare_a_cancel(self, cb):
        """A ratchet against CANCEL_NOT_DECLARED, not a blanket requirement.

        A background callback added after 2026-07-28 has to either declare a
        cancel= or be added to the list with a justification, which makes the
        omission a deliberate decision rather than an oversight.
        """
        if cb.name in CANCEL_NOT_DECLARED:
            pytest.skip("recorded in the CANCEL_NOT_DECLARED baseline")
        assert cb.has_cancel, (
            f"{cb.where} is a new background callback with no cancel=. An "
            f"operator who starts it cannot stop it. Add a cancel= or, if it is "
            f"genuinely too short to need one, add it to CANCEL_NOT_DECLARED "
            f"with a reason."
        )

    def test_watchlist_state_crosses_the_process_boundary_via_the_store(self, cb):
        """The singleton is EMPTY in the worker; the Store is how state travels.

        ``get_watchlist_manager()`` returns a module-level singleton populated
        in the main process. The DiskcacheManager worker is a different process,
        so it gets a fresh empty one. A callback that reads it there sees no
        watchlist entries and silently concludes nothing is being watched --
        which, in a biothreat tool, is the direction that loses detections.
        """
        if not cb.singleton_calls:
            pytest.skip("does not read a process-local singleton")
        assert any(s in cb.state_ids for s in WATCHLIST_STATE_SOURCES), (
            f"{cb.where} calls {sorted(cb.singleton_calls)} in a background "
            f"callback but takes neither State({WATCHLIST_SNAPSHOT_STORE!r}) "
            f"nor State({APP_CONFIG_STORE!r}), so it has no way to populate "
            f"the manager. In the worker process that singleton is empty, so "
            f"every watchlist check silently reports nothing is being watched. "
            f"States declared: {cb.state_ids}"
        )
