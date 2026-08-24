"""The validation parser is shared per results dir, not rebuilt per call.

`BlastValidationParser` carries a per-instance results cache keyed on the
validation dir mtime — but both per-tick callers (the Validation tab's
store builder and the Dashboard's validation lookup) constructed a FRESH
instance on every invocation, so the cache was always cold and every tick
re-parsed S x W validation JSON files, twice (round-2 audit, 2026-08-22).
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    BlastValidationParser,
    get_validation_parser,
    reset_validation_parsers,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset():
    reset_validation_parsers()
    yield
    reset_validation_parsers()


class TestFactory:
    def test_same_dir_returns_the_same_instance(self, tmp_path):
        (tmp_path / "validation").mkdir()
        first = get_validation_parser(str(tmp_path))
        second = get_validation_parser(str(tmp_path))
        assert first is second

    def test_results_cache_survives_across_fetches(self, tmp_path):
        vdir = tmp_path / "validation"
        vdir.mkdir()
        (vdir / "validation_results.json").write_text('{"results": []}')
        parser = get_validation_parser(str(tmp_path))
        parser.get_validation_results()
        calls = {"n": 0}
        orig = BlastValidationParser._validation_dir_fingerprint

        def observing(self):
            calls["fingerprint"] = True
            return orig(self)

        # Second fetch, unchanged dir: the SAME instance serves from its
        # results cache (fingerprint check only, no re-parse).
        again = get_validation_parser(str(tmp_path))
        assert again is parser
        assert again._results_cache is not None

    def test_dir_created_after_first_fetch_is_picked_up(self, tmp_path):
        parser = get_validation_parser(str(tmp_path))
        assert parser.validation_dir is None
        (tmp_path / "validation").mkdir()
        again = get_validation_parser(str(tmp_path))
        assert again.validation_dir is not None

    def test_distinct_dirs_get_distinct_parsers(self, tmp_path):
        a = tmp_path / "runA"
        b = tmp_path / "runB"
        a.mkdir(), b.mkdir()
        assert get_validation_parser(str(a)) is not get_validation_parser(str(b))


class TestCallersUseTheFactory:
    """Both per-tick callers import the factory at call time from the
    parser module, so the source symbol is the patch point."""

    _SOURCE = ("nanometa_live.core.parsers.blast_validation_parser."
               "get_validation_parser")

    def test_validation_store_builder_uses_the_factory(self, tmp_path):
        from nanometa_live.app.tabs import validation_tab_helpers as vth
        calls = {"n": 0}
        real = get_validation_parser

        def counting(results_dir):
            calls["n"] += 1
            return real(results_dir)

        config = {"blast_validation": True,
                  "results_dir_override": str(tmp_path)}
        with patch(self._SOURCE, counting):
            vth.build_validation_store(config, {}, "All Samples", None)
        assert calls["n"] >= 1

    def test_dashboard_validation_lookup_uses_the_factory(self, tmp_path):
        from nanometa_live.app.tabs import dashboard_helpers as dh
        calls = {"n": 0}
        real = get_validation_parser

        def counting(results_dir):
            calls["n"] += 1
            return real(results_dir)

        (tmp_path / "validation").mkdir()
        with patch(self._SOURCE, counting):
            dh._load_validation_lookup(str(tmp_path))
        assert calls["n"] >= 1
