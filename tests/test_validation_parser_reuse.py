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


class TestFilteredCallsShareTheCache:
    """A (sample=/taxid=)-filtered call must subset the cached full parse.

    Round-3 audit: filtered calls ran the whole O(pairs) parse and
    DISCARDED it (cache_this_call was False), so get_species_validation /
    get_sample_validation_status paid ~5 file opens per pair on every
    call while the unfiltered cache sat cold beside them.
    """

    def _tree(self, tmp_path, pairs=6):
        import json, os, time
        blast = tmp_path / "validation" / "blast"
        blast.mkdir(parents=True)
        t = time.time() - 120
        for i in range(pairs):
            stem = f"barcode{i % 2 + 1:02d}_taxid{500 + i}"
            f = blast / f"{stem}.blast.tsv"
            f.write_text("r1\tref\t99.0\t500\t2\t0\t1\t500\t10\t510"
                         "\t1e-50\t900\n")
            os.utime(f, (t, t))
        return tmp_path

    def test_filtered_call_populates_the_cache(self, tmp_path):
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        p = ValidationParser(str(self._tree(tmp_path)))
        got = p.get_validation_results(sample="barcode01")
        assert got and all(r.sample_id == "barcode01" for r in got)
        assert p._results_cache is not None, (
            "the filtered call parsed everything and threw the parse away"
        )

    def test_unfiltered_after_filtered_reads_no_files(self, tmp_path):
        import builtins
        from unittest.mock import patch
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        p = ValidationParser(str(self._tree(tmp_path)))
        p.get_validation_results(taxid=503)

        calls = {"n": 0}
        orig = builtins.open

        def counting(file, *a, **kw):
            if "validation" in str(file):
                calls["n"] += 1
            return orig(file, *a, **kw)

        with patch.object(builtins, "open", counting):
            full = p.get_validation_results()
        assert calls["n"] == 0
        assert len(full) == 6


class TestFingerprintEpochFastPath:
    """A quiet poll must not pay the O(pairs) fingerprint walk.

    check_data_freshness already walks validation/ once per poll and bumps
    the freshness epoch on change; within an unchanged epoch the parser
    reuses its stored fingerprint, mirroring _mtime_cache_state. Epoch 0
    (CLI/tests, no poll loop) keeps the unconditional walk.
    """

    def test_same_epoch_skips_the_walk(self, tmp_path, monkeypatch):
        import os
        from unittest.mock import patch
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        tree = TestFilteredCallsShareTheCache()._tree(tmp_path, pairs=20)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 7)
        p = ValidationParser(str(tree))
        p.get_validation_results()

        calls = {"n": 0}
        orig = os.stat

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(os, "stat", counting):
            p.get_validation_results()
        assert calls["n"] < 10, (
            f"quiet-poll fingerprint walked {calls['n']} stats; the epoch "
            "fast-path should make it O(1)"
        )

    def test_epoch_bump_rewalks(self, tmp_path, monkeypatch):
        import os, time
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        tree = TestFilteredCallsShareTheCache()._tree(tmp_path, pairs=2)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 7)
        p = ValidationParser(str(tree))
        assert len(p.get_validation_results()) == 2
        # New pair lands; the poll's check_data_freshness bumps the epoch.
        blast = tree / "validation" / "blast"
        f = blast / "barcode09_taxid999.blast.tsv"
        f.write_text("r1\tref\t99.0\t500\t2\t0\t1\t500\t10\t510\t1e-50\t900\n")
        t = time.time() - 120
        os.utime(f, (t, t))
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 8)
        assert len(p.get_validation_results()) == 3

    def test_epoch_zero_keeps_unconditional_freshness(self, tmp_path,
                                                      monkeypatch):
        import os, time
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        tree = TestFilteredCallsShareTheCache()._tree(tmp_path, pairs=2)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 0)
        p = ValidationParser(str(tree))
        assert len(p.get_validation_results()) == 2
        blast = tree / "validation" / "blast"
        f = blast / "barcode09_taxid999.blast.tsv"
        f.write_text("r1\tref\t99.0\t500\t2\t0\t1\t500\t10\t510\t1e-50\t900\n")
        t = time.time() - 120
        os.utime(f, (t, t))
        assert len(p.get_validation_results()) == 3
