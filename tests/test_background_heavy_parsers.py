"""Regression tests for audit item #3 (docs/audit/threading-2026-05-10.md):
heavy parser callbacks must run via the DiskcacheManager background worker,
not the Werkzeug request thread.

Without this, a 100 MB Kraken2 report parse holds the main Dash process's
GIL for 1-2 s and stalls every other callback in flight. Backgrounding the
callbacks moves that work into a separate OS process.

These tests pin the wiring at source-code level (no Dash roundtrip):
1. ``main_tab.update_main_results`` is decorated with ``background=True``.
2. ``qc_tab.update_qc_stats`` is decorated with ``background=True``.
3. Both reference ``background_callback_manager`` for the worker pool.
4. ``update_main_results`` reads the watchlist from the dcc.Store
   parameter, not from ``get_watchlist_manager()`` (which would be empty
   in the worker process per CLAUDE.md "Background callback isolation").
"""

from __future__ import annotations

from pathlib import Path
import re


MAIN_TAB = Path(
    "nanometa_live/app/tabs/main_tab.py"
).read_text()
QC_TAB = Path(
    "nanometa_live/app/tabs/qc_tab.py"
).read_text()


class TestMainTabBackgrounded:
    def test_import_present(self):
        assert (
            "from nanometa_live.app.app import background_callback_manager"
            in MAIN_TAB
        )

    def test_update_main_results_is_background(self):
        # Locate the decorator block immediately preceding the callback
        # function. The decorator must contain both ``background=True`` and
        # ``manager=background_callback_manager``.
        decorator_pattern = re.compile(
            r"@app\.callback\((?P<dec>.*?)\)\s*\n\s*def update_main_results\(",
            re.DOTALL,
        )
        match = decorator_pattern.search(MAIN_TAB)
        assert match, "update_main_results decorator not found"
        dec = match.group("dec")
        assert "background=True" in dec
        assert "manager=background_callback_manager" in dec

    def test_watchlist_read_from_store_not_singleton(self):
        # Inside the callback body the watchlist must be built from
        # ``watchlist_store`` (the dcc.Store contents), not from a fresh
        # ``get_watchlist_manager()`` call -- the singleton is empty in
        # the worker process.
        body_pattern = re.compile(
            r"def update_main_results\(.*?\n(?P<body>.*?)\n    @app\.callback",
            re.DOTALL,
        )
        match = body_pattern.search(MAIN_TAB)
        assert match, "update_main_results body not found"
        body = match.group("body")
        # The store-driven path must exist.
        assert "watchlist_store" in body
        # The singleton must not be CALLED in the body. Comments are
        # allowed (the docstring explains why we read from the store).
        # Strip ``#``-prefixed lines before checking for the call site.
        code_only = "\n".join(
            line for line in body.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "get_watchlist_manager(" not in code_only, (
            "update_main_results must not call get_watchlist_manager() -- "
            "the singleton is empty in the DiskcacheManager worker"
        )


class TestQcTabBackgrounded:
    def test_import_present(self):
        assert (
            "from nanometa_live.app.app import background_callback_manager"
            in QC_TAB
        )

    def test_update_qc_stats_is_background(self):
        decorator_pattern = re.compile(
            r"@app\.callback\((?P<dec>.*?)\)\s*\n\s*def update_qc_stats\(",
            re.DOTALL,
        )
        match = decorator_pattern.search(QC_TAB)
        assert match, "update_qc_stats decorator not found"
        dec = match.group("dec")
        assert "background=True" in dec
        assert "manager=background_callback_manager" in dec
