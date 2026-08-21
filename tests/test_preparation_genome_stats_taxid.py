"""The Preparation tab must count genomes in the space they are cached in.

Observed live on 2026-08-19 with 8 Bioshield reference genomes sitting in the
configured cache (`4005020.fasta`, `4007486.fasta`, …): the panel reported

    Downloaded 0   Missing 129   With BLAST 0   Size 0 MB

`update_genome_stats` looks each genome up by ``entry["taxid"]`` — a
pseudo-taxid (>= 2e9) for every entry with no NCBI identity, i.e. all 76
bacterial Bioshield agents — while the genome is cached under the DATABASE
taxid the reads are extracted for, which the same entry dict already carries
as ``db_taxid``.

Consequences for an operator on a flextaxd/GTDB deployment (the primary
field deployment): prepared references are invisible, the readiness panel
claims nothing is ready, and "Download Missing" targets 129 organisms by a
taxid NCBI cannot resolve. The same taxid-space rule the validation launch
path now follows (`_genome_lookup_taxids`) applies here.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.tabs.preparation_tab import _genome_taxid_for_entry


class TestGenomeTaxidForEntry:
    def test_prefers_db_taxid(self):
        entry = {"taxid": 2_057_967_092, "db_taxid": 4_005_020,
                 "name": "Bacillus anthracis"}
        assert _genome_taxid_for_entry(entry) == 4_005_020

    def test_falls_back_to_entry_taxid(self):
        entry = {"taxid": 11292, "name": "Lyssavirus rabies"}
        assert _genome_taxid_for_entry(entry) == 11292

    def test_db_taxid_none_falls_back(self):
        entry = {"taxid": 11292, "db_taxid": None}
        assert _genome_taxid_for_entry(entry) == 11292

    def test_no_identifier_returns_zero(self):
        assert _genome_taxid_for_entry({"name": "x"}) == 0
        assert _genome_taxid_for_entry({"taxid": 0, "db_taxid": 0}) == 0


class TestStatsCountDbKeyedGenomes:
    """End-to-end through the callback: a genome cached under its db taxid
    must be counted as downloaded, not reported missing."""

    def _app_and_fn(self):
        from dash import Dash
        from nanometa_live.app.tabs.preparation_tab import (
            register_preparation_callbacks,
        )
        from tests.dash_test_utils import get_callback_fn

        app = Dash(__name__)
        register_preparation_callbacks(app)
        return get_callback_fn(app, "genome-stat-downloaded")

    def test_db_keyed_genome_counts_as_downloaded(self, tmp_path, monkeypatch):
        genomes = tmp_path / "genomes"
        genomes.mkdir()
        (genomes / "4005020.fasta").write_text(">NZ_X Bacillus anthracis\nACGT\n")

        from nanometa_live.app.tabs import preparation_tab as pt

        class _Mgr:
            _loaded = True

            def get_entries_with_toggle_state(self):
                return [
                    {"taxid": 2_057_967_092, "db_taxid": 4_005_020,
                     "name": "Bacillus anthracis", "enabled": True},
                    {"taxid": 2_068_236_289, "db_taxid": 4_003_795,
                     "name": "Burkholderia mallei subsp. mallei", "enabled": True},
                ]

            def load_config(self, _cfg):
                pass

        class _Genomes:
            _metadata = {}

            def has_genome(self, taxid):
                return (genomes / f"{taxid}.fasta").exists()

            def has_blast_db(self, taxid):
                return False

            def get_all_genomes(self):
                return []

        monkeypatch.setattr(
            "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager",
            lambda: _Mgr())
        monkeypatch.setattr(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            lambda cache_dir=None: _Genomes())

        fn = self._app_and_fn()
        from unittest.mock import patch as _patch
        from nanometa_live.app.tabs import preparation_tab
        with _patch.object(preparation_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "genome-refresh-btn"
            out = fn(1, None, "watchlist-tab",
                     {"genome_cache_dir": str(tmp_path)})
        downloaded, missing = out[0], out[1]

        assert downloaded == "1", (
            "a reference genome cached under its database taxid was reported "
            "as not downloaded; on a Bioshield deployment the panel claimed "
            "0 downloaded / 129 missing with 8 genomes on disk"
        )
        assert missing == "1"
