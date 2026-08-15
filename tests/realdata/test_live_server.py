"""Drive the real Dash server in a browser against real pipeline output.

Every other callback test in this suite -- all ~206 of them -- extracts the
Python function from ``app.callback_map`` and calls it in-process. That cannot
see anything the HTTP layer does: a callback whose return value is not
JSON-serialisable passes every one of them and returns HTTP 500 in a browser.
Dash surfaces an unhandled callback exception exactly that way, as a 500 on
``/_dash-update-component``, so a walk with zero 500s is strong evidence the UI
layer is healthy.

This is the first test in the project to boot the server at all.

**A watchlist is loaded on purpose.** Round 1's browser walk ran without one,
and that is precisely how the ALL CLEAR defect surfaced -- the banner asserted
a negative screening result that had never been performed. Loading a watchlist
exercises the *other* half: alert generation, per-sample attribution, and the
pathogen panels, none of which render at all when nothing is watched.

Run with::

    NANOMETA_REALDATA_DIR=/path/to/results pytest tests/realdata/test_live_server.py -v

Skipped when that is unset, when playwright is unavailable, or when no browser
is installed, so the default developer loop and CI are unaffected.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest
import yaml

pytestmark = pytest.mark.integration

#: Tabs in the order the operator meets them. Matched on visible text.
TABS = [
    "Dashboard",
    "Organisms",
    "Quality Control",
    "Taxonomy",
    "Validation",
    "Reports",
    "Configuration",
    "Watchlist & Preparation",
    "Deployment",
]

#: How long to wait for the server to start serving.
BOOT_TIMEOUT = 90.0

#: Settle time after a tab click before snapshotting. Callbacks are debounced
#: at 2 s in several tabs, so anything shorter races the update.
TAB_SETTLE = 3.0


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serving(port: int) -> bool:
    with contextlib.closing(socket.socket()) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="module")
def playwright_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed in this environment")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # no browser binary installed
            pytest.skip(f"could not launch chromium: {exc}")
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def live_app(results_dir, tmp_path_factory) -> str:
    """Boot the dashboard against the real results tree, with a watchlist.

    Yields the base URL. The app is a real subprocess; it is terminated and
    reaped on teardown so a failed run cannot leave a port bound.
    """
    tmp = tmp_path_factory.mktemp("liveapp")
    config_path = tmp / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "results_output_directory": str(results_dir),
        "watchlist": {"enabled": True, "builtin": ["cdc_bioterrorism"], "custom": []},
        # Keep the app off the network and out of the developer's real home.
        "offline_mode": True,
        "data_dir": str(tmp / "data"),
    }))

    port = _free_port()
    env = {**os.environ, "NANOMETA_DATA_DIR": str(tmp / "data")}
    log = open(tmp / "app.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "nanometa_live.app",
         "--config", str(config_path),
         "--main_dir", str(results_dir),
         "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT, env=env,
    )

    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.close()
            pytest.fail(
                f"the app exited during startup (code {proc.returncode}):\n"
                f"{(tmp / 'app.log').read_text()[-3000:]}"
            )
        if _serving(port):
            break
        time.sleep(0.5)
    else:
        proc.kill()
        log.close()
        pytest.fail(
            f"the app did not serve within {BOOT_TIMEOUT}s:\n"
            f"{(tmp / 'app.log').read_text()[-3000:]}"
        )

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    log.close()


@pytest.fixture(scope="module")
def walked(live_app, playwright_browser):
    """Visit every tab once, recording failed requests and console errors.

    Module-scoped: booting the app and walking nine tabs is slow, and every
    assertion below reads the same recording.
    """
    page = playwright_browser.new_page()
    failures: list[tuple[str, int, str]] = []
    console_errors: list[str] = []
    rendered: dict[str, int] = {}
    texts: dict[str, str] = {}

    updates: list[int] = []

    def on_response(response):
        if "_dash-update-component" not in response.url:
            return
        updates.append(response.status)
        if response.status >= 400:
            failures.append(("response", response.status, response.url))

    page.on("response", on_response)
    page.on("console", lambda m: console_errors.append(m.text)
            if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    page.goto(live_app, wait_until="networkidle")

    # Dismiss the first-run welcome modal if present; it overlays the tabs.
    with contextlib.suppress(Exception):
        page.get_by_role("button", name="Close").first.click(timeout=3000)

    for tab in TABS:
        try:
            page.get_by_role("tab", name=tab, exact=False).first.click(timeout=15000)
        except Exception as exc:
            failures.append(("click", 0, f"{tab}: {exc}"))
            continue
        page.wait_for_timeout(int(TAB_SETTLE * 1000))
        body = (page.inner_text("body") or "").strip()
        rendered[tab] = len(body)
        # Keep the text, not just its length. The watchlist guard below has
        # to read what the banner actually says; a character count cannot
        # distinguish a real verdict from "NOT SCREENED".
        texts[tab] = body

    result = {
        "failures": failures,
        "console_errors": console_errors,
        "rendered": rendered,
        "texts": texts,
        "updates": updates,
    }
    yield result
    page.close()


class TestEveryTabRenders:
    def test_all_tabs_were_reachable(self, walked):
        missing = [t for t in TABS if t not in walked["rendered"]]
        assert not missing, (
            f"these tabs could not be opened: {missing}. "
            f"Failures: {walked['failures']}"
        )

    @pytest.mark.parametrize("tab", TABS)
    def test_tab_renders_content(self, walked, tab):
        """A tab that opens but paints nothing is a silent failure.

        The threshold is deliberately low -- this catches a blank or
        error-only panel, not a sparse one.
        """
        if tab not in walked["rendered"]:
            pytest.skip(f"{tab} was not reachable; see test_all_tabs_were_reachable")
        assert walked["rendered"][tab] > 200, (
            f"the {tab} tab rendered only {walked['rendered'][tab]} characters "
            f"of text, which is a blank or error panel rather than content"
        )


class TestNoCallbackRaised:
    def test_the_walk_actually_exercised_callbacks(self, walked):
        """Guard on the assertion below, which is vacuous without traffic.

        If a layout change broke tab selection, or the welcome modal stopped
        being dismissed, the walk would observe no callback traffic at all and
        the 500-check would pass having tested nothing. A healthy walk of the
        nine tabs produced 208 requests when this was written.
        """
        assert len(walked["updates"]) > 50, (
            f"only {len(walked['updates'])} /_dash-update-component requests "
            f"were seen during the whole walk; the browser is not reaching the "
            f"callbacks, so the error-status assertion below proves nothing"
        )

    def test_no_dash_update_returned_an_error_status(self, walked):
        """The core assertion, and the reason this test exists.

        Dash reports an unhandled callback exception as an HTTP 500 on
        /_dash-update-component. In-process callback tests cannot produce one:
        they never cross the HTTP boundary, so a non-serialisable return value
        passes them and fails here.
        """
        http = [f for f in walked["failures"] if f[0] == "response"]
        assert not http, (
            "callbacks failed over HTTP while walking the tabs:\n  "
            + "\n  ".join(f"{status} {url}" for _, status, url in http)
        )

    def test_no_browser_console_errors(self, walked):
        """Catches client-side breakage the server never sees.

        AG-Grid emits a small number of warnings on a healthy app; only
        error-level entries are counted.
        """
        assert not walked["console_errors"], (
            "browser console errors during the tab walk:\n  "
            + "\n  ".join(walked["console_errors"][:10])
        )


class TestWatchlistIsActuallyLoaded:
    """Guards the premise of this whole module.

    If the watchlist silently fails to load, every assertion above still
    passes while exercising the no-watchlist path -- the same blind spot that
    hid the ALL CLEAR defect. So assert the screening is live before trusting
    a green run.
    """

    #: Every terminal state select_verdict can reach with data present. The
    #: guard does not care which one the run earns -- only that the banner
    #: reports a screening outcome rather than the absence of screening.
    _SCREENED_VERDICTS = (
        "ACTION REQUIRED", "MONITORING", "ALL CLEAR", "INSUFFICIENT READS",
    )

    def test_the_dashboard_is_not_reporting_an_unscreened_state(self, walked, live_app):
        """Assert on what the banner SAYS, not on how much text it painted.

        This asserted ``len(page_text) > 0`` until 2026-08-08, which is a
        character count: it passes identically whether the banner reads
        ACTION REQUIRED or NOT SCREENED. So the guard written to catch a
        silently-unloaded watchlist could not catch one, and the whole module
        had been walking the unscreened path -- the exact blind spot named in
        this class's docstring.

        It really had: the fixture boots with ``--config X --main_dir Y``, and
        the entry point discarded ``--config`` outright in that combination
        (fixed in the commit before this one).
        """
        page_text = walked["texts"].get("Dashboard", "")
        assert page_text, "the Dashboard tab never rendered"

        banner = page_text.upper()
        assert "NOT SCREENED" not in banner, (
            "the Dashboard reports NOT SCREENED, so the configured watchlist "
            "never reached the running app and every assertion in this module "
            "is exercising the unscreened path"
        )
        assert any(v in banner for v in self._SCREENED_VERDICTS), (
            "the Dashboard shows no screening verdict at all (expected one of "
            f"{', '.join(self._SCREENED_VERDICTS)}); the banner is not "
            "reporting a screening outcome, so a green run here proves nothing"
        )

    def test_the_configured_watchlist_loads_outside_the_browser(self):
        """Cheap, direct check of the same config the fixture writes."""
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

        manager = WatchlistManager()
        manager.load_config({
            "watchlist": {"enabled": True,
                          "builtin": ["cdc_bioterrorism"], "custom": []},
        })
        assert manager.get_active_entries(), (
            "the cdc_bioterrorism watchlist loaded no entries, so the live "
            "server walk is exercising the unscreened path by accident"
        )
