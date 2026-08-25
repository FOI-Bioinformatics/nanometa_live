"""The perf harness must be able to generate validation trees.

Round-3 gap: the fixtures built ``validation/`` as a bare directory, so
none of the O(pairs) and O(pairs x batches) validation costs (the
12,384-pair fingerprint, the full-parse file opens, the batch-dir
enumeration) had ever been measured. The builder now takes a
``validation_pairs`` / ``validation_batches`` axis and writes the same
shapes nanometanf publishes -- verified here against the parser itself,
so a drifting fixture fails loudly instead of measuring a dead path.
"""

import pytest

pytestmark = pytest.mark.unit

from scripts.perf import fixtures as fx


def _spec(**kw):
    defaults = dict(n_samples=2, layout="batch", taxa_per_report=50,
                    validation_pairs=6)
    defaults.update(kw)
    return fx.FixtureSpec(**defaults)


class TestValidationFixtureShape:
    def test_pair_files_exist_in_the_real_layout(self, tmp_path):
        root = fx.build_fixture(_spec(), tmp_path)
        blast = list((root / "validation" / "blast").glob("*.blast.tsv"))
        stats = list((root / "validation" / "blast").glob("*.blast_stats.json"))
        mm2 = list((root / "validation" / "minimap2").glob(
            "*.minimap2_stats.json"))
        paf = list((root / "validation" / "minimap2").glob("*.paf"))
        assert len(blast) == 6
        assert len(stats) == 6
        assert len(mm2) == 6
        assert len(paf) == 6

    def test_pairs_are_split_across_samples(self, tmp_path):
        root = fx.build_fixture(_spec(), tmp_path)
        names = [p.name for p in (root / "validation" / "blast").glob("*.tsv")]
        assert any(n.startswith("barcode01_") for n in names)
        assert any(n.startswith("barcode02_") for n in names)

    def test_the_parser_reads_the_fixture(self, tmp_path):
        from nanometa_live.core.parsers.blast_validation_parser import (
            ValidationParser,
        )
        root = fx.build_fixture(_spec(), tmp_path)
        results = ValidationParser(str(root)).get_validation_results()
        methods = {r.validation_method for r in results}
        assert "blast" in methods and "minimap2" in methods, (
            "the fixture layout drifted from what the parser scans -- the "
            f"harness would measure a dead path (got {methods})"
        )
        assert len(results) == 12  # 6 pairs x 2 methods

    def test_batch_files_land_in_the_batch_subdirs(self, tmp_path):
        root = fx.build_fixture(
            _spec(validation_batches=3), tmp_path)
        b_blast = list((root / "validation" / "blast" / "batch").iterdir())
        b_mm2 = list((root / "validation" / "minimap2" / "batch").iterdir())
        assert len(b_blast) == 6 * 3
        assert len(b_mm2) == 6 * 3

    def test_zero_pairs_keeps_the_old_empty_dir(self, tmp_path):
        root = fx.build_fixture(_spec(validation_pairs=0), tmp_path)
        assert (root / "validation").is_dir()
        assert not list((root / "validation").glob("**/*.tsv"))

    def test_spec_key_carries_the_axis(self):
        assert "-v6" in _spec().key
        assert "-v" not in _spec(validation_pairs=0).key


class TestResetCachesCompleteness:
    """Every module-level cache the poll path can populate must empty on
    reset_caches, or 'cold' cells measure warm (round-3 audit: the
    taxonomy map, PAF breadth cache, validation parser singletons, the
    organisms memo and the pathogen memos were all missed)."""

    def test_named_caches_empty_after_reset(self):
        from scripts.perf.instrument import reset_caches
        from nanometa_live.app.tabs import kraken2_helpers as kh
        from nanometa_live.app.tabs import dashboard_helpers as dh
        from nanometa_live.app.utils import organisms_memo as om
        from nanometa_live.core.parsers import paf_coverage_parser as pcp
        from nanometa_live.core.parsers import blast_validation_parser as bvp
        from nanometa_live.core.utils import pathogen_database as pdb
        from nanometa_live.core.utils import staleness

        kh._TAXONOMY_CACHE["/fake/db"] = {1: 1}
        pcp._breadth_cache[("/f.paf", 1, 1, 10)] = object()
        om._memo[("/x", ("a",), 1, "")] = {}
        dh._pathogen_check_memo["k"] = ([], [])
        pdb._dangerous_check_memo["k"] = {}
        bvp.get_validation_parser("/tmp")
        staleness.record_last_good_served("/x", "a")

        reset_caches()

        assert not kh._TAXONOMY_CACHE
        assert not pcp._breadth_cache
        assert not om._memo
        assert not dh._pathogen_check_memo
        assert not pdb._dangerous_check_memo
        assert not bvp._parser_singletons
        assert staleness.stale_sample_count("/x", grace_seconds=0) == 0
