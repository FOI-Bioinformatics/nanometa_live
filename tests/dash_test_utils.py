"""
Shared helpers for Dash callback / component tests.

Centralises the callback-extraction and component-tree utilities that were
previously copy-pasted across test_core_callbacks, test_config_tab,
test_watchlist_tab, test_start_stop_callbacks, test_deep_callbacks,
test_components_smoke and test_layouts_structure. Importable from any test
because pytest puts the tests/ directory on sys.path.

The extraction approach (walk app.callback_map, unwrap the add_context
decorator via __wrapped__) is inherently coupled to Dash internals; keeping it
in one place means a Dash-version change is a single-file fix rather than a
seven-file sweep.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

from dash.development.base_component import Component


def get_callback_fn(app, output_id, *, input_contains=None):
    """Return the unwrapped callback whose output set includes ``output_id``.

    When several callbacks share an output (allow_duplicate), pass
    ``input_contains`` to disambiguate by an input component id substring.
    Raises AssertionError if no unique-enough match is found.
    """
    cands = []
    for cb_id, spec in app.callback_map.items():
        if output_id not in cb_id:
            continue
        if input_contains is not None:
            ids = []
            for i in spec.get("inputs", []):
                cid = i.get("id") if isinstance(i, dict) else getattr(i, "component_id", None)
                ids.append(str(cid))
            if not any(input_contains in x for x in ids):
                continue
        cands.append(spec)
    assert cands, f"no callback for output {output_id!r} (input_contains={input_contains!r})"
    fn = cands[0]["callback"]
    return getattr(fn, "__wrapped__", fn)


@contextmanager
def ctx_with(triggered_id):
    """Patch the dash callback context's triggered_id for the duration.

    Patches ``nanometa_live.app.callbacks.ctx`` (imported lazily so this module
    can be imported in environments where callbacks have not been touched yet).
    """
    from unittest.mock import patch
    import nanometa_live.app.callbacks as cb

    with patch.object(cb, "ctx", MagicMock(triggered_id=triggered_id)):
        yield


def collect_string_ids(component, acc=None):
    """Recursively collect string ids from a Dash component tree."""
    if acc is None:
        acc = []
    cid = getattr(component, "id", None)
    if isinstance(cid, str):
        acc.append(cid)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for c in children:
            if isinstance(c, Component):
                collect_string_ids(c, acc)
    elif isinstance(children, Component):
        collect_string_ids(children, acc)
    return acc


def assert_no_duplicate_ids(component):
    """Assert a component tree carries no duplicate string ids."""
    ids = collect_string_ids(component)
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate ids: {dupes}"
