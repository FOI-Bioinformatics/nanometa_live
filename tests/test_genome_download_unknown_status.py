""""Nothing to download" must not be said by a check that never ran.

`download_missing_genomes` is a background callback, so it cannot read the
WatchlistManager singleton (empty in the worker process). It instead reads the
`genome-status-data` store, which `update_genome_stats` populates in the main
process with the list of watchlist entries whose reference genome is absent.

The store starts unpopulated. The callback did:

    missing = missing_store if missing_store else []
    if not missing:
        ... "All genomes already downloaded" / green "Complete" badge

so an unpopulated store took the same branch as a genuinely empty one. Clicking
Download All before the statistics had loaded reported success having checked
nothing, and the operator went on to export a bundle with no genomes in it.
Reference genomes are what confirmatory validation aligns against, so the
first evidence would have been a validation that could not run, in the field.

Found 2026-07-29. Same shape as the ALL CLEAR, exported-report, failed-sample
and wizard-ready defects from this campaign: a surface stating a reassuring
conclusion it had not earned.

The store now defaults to None and the callback distinguishes the three
states: None (not computed -> "Unknown"), [] (computed, nothing missing ->
"Complete"), non-empty (download).
"""

from __future__ import annotations

from unittest.mock import patch

import dash
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def download_fn():
    from nanometa_live.app.tabs import preparation_tab
    from tests.dash_test_utils import get_callback_fn

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    preparation_tab.register_preparation_callbacks(app)
    return get_callback_fn(
        app, "genome-download-complete",
        input_contains="genome-download-all-btn",
    )


def _run(fn, missing_store):
    """Drive the callback, returning the set_progress tuples it emitted."""
    seen = []
    with patch(
        "nanometa_live.core.utils.genome_manager.get_genome_manager"
    ):
        fn(lambda v: seen.append(v), 1, {}, missing_store)
    return seen


def _badge_text(progress_tuple):
    badge = progress_tuple[4]
    children = getattr(badge, "children", badge)
    return str(children)


def _log_text(progress_tuple):
    return " ".join(str(e) for e in progress_tuple[3])


class TestTheThreeStatesAreDistinct:
    def test_an_uncomputed_store_is_not_reported_as_complete(self, download_fn):
        """The defect."""
        last = _run(download_fn, None)[-1]
        assert "Complete" not in _badge_text(last), (
            "an inventory that was never computed was reported as complete; "
            "the operator would ship a bundle with no reference genomes"
        )
        assert _badge_text(last) == "Unknown"

    def test_an_uncomputed_store_says_what_to_do(self, download_fn):
        last = _run(download_fn, None)[-1]
        text = _log_text(last)
        assert "not a report that nothing is missing" in text, (
            "the operator must be told this is an absent measurement rather "
            "than a negative result"
        )

    def test_the_legacy_empty_dict_default_is_also_treated_as_unknown(
        self, download_fn
    ):
        """A stale session store may still hold the old {} default."""
        last = _run(download_fn, {})[-1]
        assert _badge_text(last) == "Unknown"

    def test_a_genuinely_empty_list_still_reports_complete(self, download_fn):
        """Control: the real all-clear must survive the fix."""
        last = _run(download_fn, [])[-1]
        assert "Complete" in _badge_text(last)
        assert "already present" in _log_text(last)

    def test_offline_mode_still_short_circuits_first(self, download_fn):
        """Offline mode must win over the unknown-status branch.

        Offline is a deliberate operator choice with its own message; being
        unable to download is expected there, so surfacing "Unknown" instead
        would be noise.
        """
        seen = []
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager"):
            download_fn(lambda v: seen.append(v), 1, {"offline_mode": True},
                        None)
        assert "Offline" in _badge_text(seen[-1])


class TestTheStoreDefaultCarriesTheDistinction:
    def test_the_store_starts_as_none_not_empty_dict(self):
        """The guard relies on the layout default being None."""
        import re
        import pathlib

        src = pathlib.Path(
            "nanometa_live/app/app.py"
        ).read_text()
        match = re.search(
            r"dcc\.Store\(id='genome-status-data', data=(\w+)\)", src
        )
        assert match, "store definition moved; update this test"
        assert match.group(1) == "None", (
            "the store must start as None so 'not computed' stays "
            "distinguishable from 'nothing missing'"
        )
