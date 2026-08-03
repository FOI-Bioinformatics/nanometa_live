"""Downloading a Kraken2 database must respect offline mode.

Found by the C4 sinkhole run: with every outbound connection rejected but DNS
still answering, ``download_kraken_database`` resolved and reached for
``genome-idx.s3.amazonaws.com`` in offline mode exactly as it did online. The
function takes no offline parameter and never consults one -- it is guarded
solely by its single GUI caller (``preparation_tab.download_kraken_database``,
which checks ``offline_mode`` before invoking it).

That is a guard on the caller, not on the capability. Any other route to this
function -- a CLI path, a new callback, a script, a retry -- reaches the
network on an air-gapped machine, where the operator gets a 60-second timeout
instead of an immediate, accurate refusal.

Note that ``--network none`` could not have found this: with no route at all,
the offline and online runs both simply fail. It took a sinkhole that answers
DNS and refuses TCP to show that the two behave identically, which is the
distinction between "never tried" and "tried and fell back".
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import kraken_utils


DB = {
    "name": "viral",
    "database_url": "https://genome-idx.s3.amazonaws.com/kraken/k2_viral.tar.gz",
}


class TestOfflineRefusesTheDownload:
    def test_offline_does_not_call_requests(self, tmp_path, monkeypatch):
        called = {"n": 0}

        def boom(*a, **k):
            called["n"] += 1
            raise AssertionError(
                "requests.get was called in offline mode: the download reached "
                "for the network on an air-gapped machine."
            )

        monkeypatch.setattr(kraken_utils.requests, "get", boom)

        ok, msg, path = kraken_utils.download_kraken_database(
            DB, str(tmp_path), offline_mode=True
        )

        assert called["n"] == 0
        assert ok is False
        assert "offline" in msg.lower(), (
            f"the refusal must name offline mode so the operator knows why: {msg!r}"
        )

    def test_online_still_reaches_the_network(self, tmp_path, monkeypatch):
        """The guard must not break the normal path.

        Asserted by capturing the call rather than simulating a full download:
        what matters here is that offline_mode=False still gets as far as
        requests.get with the right URL.
        """
        seen = {}

        def fake_get(url, **k):
            seen["url"] = url
            # Must be an exception the function catches, so it returns a
            # normal failure tuple rather than propagating out of the test.
            raise kraken_utils.requests.RequestException("simulated")

        monkeypatch.setattr(kraken_utils.requests, "get", fake_get)

        ok, msg, _ = kraken_utils.download_kraken_database(
            DB, str(tmp_path), offline_mode=False
        )

        assert seen.get("url") == DB["database_url"], (
            f"offline_mode=False did not reach the download: {msg!r}"
        )
        assert ok is False  # the simulated failure, not a refusal

    def test_default_is_online_for_backwards_compatibility(self, tmp_path, monkeypatch):
        """Callers that pass no flag keep their existing behaviour."""
        seen = {}

        def fake_get(url, **k):
            seen["url"] = url
            raise kraken_utils.requests.RequestException("simulated")

        monkeypatch.setattr(kraken_utils.requests, "get", fake_get)

        kraken_utils.download_kraken_database(DB, str(tmp_path))

        assert seen.get("url") == DB["database_url"], (
            "the default changed to offline, which would silently stop "
            "existing callers from downloading"
        )
