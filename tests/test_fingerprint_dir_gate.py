"""The results-tree walk fires on directory CHANGES, not on config writes.

`compute_results_fingerprint` had app-config as an Input, so every watchlist
toggle, Apply Settings, and offline flip re-walked the whole results tree
and cascaded into every fingerprint-gated callback — the hidden amplifier
behind toggle stalls (round-2 audit, 2026-08-22). A derived Store
`results-dir-path` now carries just the resolved directory; the fingerprint
re-fires only when that path actually changes (preserving the original
intent: Open Results / Apply pointing at a NEW dir rescans immediately).
"""

from unittest.mock import patch

import pytest

from dash.exceptions import PreventUpdate

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


@pytest.fixture
def app():
    from unittest.mock import MagicMock
    from nanometa_live.app.callbacks.status import register_status
    return make_callback_app(lambda a: register_status(a, MagicMock()))


class TestDeriveResultsDir:
    def _fn(self, app):
        return get_callback_fn(app, "results-dir-path")

    def test_watchlist_only_change_is_a_noop(self, app, tmp_path):
        fn = self._fn(app)
        config_a = {"results_dir_override": str(tmp_path),
                    "watchlist": {"custom": []}}
        first = fn(config_a, None)
        assert first == str(tmp_path)
        config_b = dict(config_a, watchlist={"custom": [{"taxid": 1}]})
        with pytest.raises(PreventUpdate):
            fn(config_b, first)

    def test_dir_change_fires(self, app, tmp_path):
        fn = self._fn(app)
        a = tmp_path / "runA"
        b = tmp_path / "runB"
        a.mkdir(), b.mkdir()
        first = fn({"results_dir_override": str(a)}, None)
        second = fn({"results_dir_override": str(b)}, first)
        assert second == str(b)


class TestFingerprintTakesTheDirInput:
    def test_config_is_not_an_input_of_the_fingerprint(self, app):
        """The amplifier itself: app-config must no longer be an Input."""
        for key, spec in app.callback_map.items():
            if "results-fingerprint.data" not in key:
                continue
            input_ids = [
                str(i.get("id") if isinstance(i, dict) else i)
                for i in spec.get("inputs", [])
            ]
            assert any("results-dir-path" in x for x in input_ids)
            assert not any("app-config" in x for x in input_ids)
            return
        pytest.fail("fingerprint callback not found")

    def test_fingerprint_computes_from_the_dir(self, app, tmp_path):
        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "s.kraken2.report.txt").write_text("x")
        fn = get_callback_fn(app, "results-fingerprint")
        result = fn(1, str(tmp_path), None)
        assert result.get("fp")
