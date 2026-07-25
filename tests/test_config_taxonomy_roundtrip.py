"""A non-path config value must survive a load unchanged.

``kraken_taxonomy`` was listed in ``PATH_CONFIG_KEYS``, so
``ConfigLoader.load_config`` ran ``os.path.abspath`` over it and turned
``"ncbi"`` into ``"<cwd>/ncbi"``. Every comparison against ``"ncbi"`` then
failed, and ``validate_config`` -- seeing a value outside its allowed set --
silently rewrote it to ``"gtdb"``. The shipped ``config.yaml`` itself carries
``kraken_taxonomy: "ncbi"``, so the default was inverted on every load.

The failure was invisible from the unit level in both directions: a test of
``normalise_path`` alone would not show the validator reset, and a test of
``validate_config`` alone would not show the corruption that triggers it. These
tests therefore go through the real load path end to end.

They are written against the *behaviour* (an enum-like value survives), not
against the membership of ``PATH_CONFIG_KEYS``, so they keep their meaning if
the key is later removed or renamed.
"""

from __future__ import annotations

import os

import pytest

from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.utils.path_utils import (
    PATH_CONFIG_KEYS,
    normalise_config_paths,
)

pytestmark = pytest.mark.unit


def _write(tmp_path, body: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return str(path)


class TestEnumValuesSurviveLoad:
    def test_kraken_taxonomy_ncbi_survives_a_full_load(self, tmp_path):
        """The exact end-to-end failure: ncbi in, ncbi out."""
        cfg_path = _write(tmp_path, 'kraken_taxonomy: "ncbi"\n')
        loaded = ConfigLoader(str(tmp_path)).load_config(cfg_path)
        assert loaded["kraken_taxonomy"] == "ncbi", (
            "kraken_taxonomy was rewritten during load; an operator setting "
            "'ncbi' would silently run against the GTDB code paths"
        )

    def test_kraken_taxonomy_gtdb_survives_a_full_load(self, tmp_path):
        """The other arm, so a fix cannot work by pinning one value."""
        cfg_path = _write(tmp_path, 'kraken_taxonomy: "gtdb"\n')
        loaded = ConfigLoader(str(tmp_path)).load_config(cfg_path)
        assert loaded["kraken_taxonomy"] == "gtdb"

    def test_value_is_not_turned_into_a_filesystem_path(self, tmp_path):
        """Guards the specific corruption, not just inequality.

        Without this, a fix that happened to map the mangled value back to a
        valid enum member would pass the tests above while still writing an
        absolute path into the config dict that other code may persist.
        """
        cfg_path = _write(tmp_path, 'kraken_taxonomy: "ncbi"\n')
        loaded = ConfigLoader(str(tmp_path)).load_config(cfg_path)
        value = loaded["kraken_taxonomy"]
        assert not os.path.isabs(value), (
            f"kraken_taxonomy became an absolute path: {value!r}"
        )
        assert os.sep not in value


class TestPathNormalisationScope:
    def test_normalisation_leaves_kraken_taxonomy_alone(self):
        config = {"kraken_taxonomy": "ncbi"}
        rewritten = normalise_config_paths(config)
        assert "kraken_taxonomy" not in rewritten
        assert config["kraken_taxonomy"] == "ncbi"

    def test_real_path_keys_are_still_normalised(self, tmp_path):
        """The fix must not have disabled normalisation wholesale."""
        config = {"kraken_db": "~/somewhere/db"}
        rewritten = normalise_config_paths(config)
        assert "kraken_db" in rewritten
        assert os.path.isabs(config["kraken_db"])
        assert "~" not in config["kraken_db"]

    def test_local_pipeline_source_prefix_survives(self):
        """"local:<path>" is an identifier, not a bare path.

        The same corruption as kraken_taxonomy, found in the same function:
        abspath() turned "local:/path/to/checkout" into
        "<cwd>/local:/path/to/checkout", which no longer satisfies the
        startswith("local:") test that nextflow_manager (:277),
        readiness_checker (:781) and bundle_manager (:1913) all dispatch on,
        so a configured local checkout stopped being recognised as local.
        The shipped config.yaml uses this form.
        """
        config = {"pipeline_source": "local:/Users/someone/nanometanf"}
        normalise_config_paths(config)
        assert config["pipeline_source"] == "local:/Users/someone/nanometanf"
        assert config["pipeline_source"].startswith("local:")

    def test_local_prefix_is_stripped_before_the_existence_check(self, tmp_path):
        """An existing local: checkout must not be reported as missing."""
        from nanometa_live.core.utils.path_utils import report_missing_paths

        assert report_missing_paths(
            {"pipeline_source": f"local:{tmp_path}"}
        ) == {}
        assert "pipeline_source" in report_missing_paths(
            {"pipeline_source": f"local:{tmp_path / 'absent'}"}
        )

    @pytest.mark.parametrize("key", PATH_CONFIG_KEYS)
    def test_every_listed_key_reads_as_a_path(self, key):
        """A guard against re-adding an enum-like key to the list.

        Every entry in PATH_CONFIG_KEYS is run through ``abspath``, so the
        list must only contain keys whose values are genuinely filesystem
        locations. The naming convention is the cheapest available proxy;
        it is what would have caught the original mistake at review time.
        """
        assert key.endswith(("_dir", "_directory", "_db", "_source", "dir")), (
            f"{key!r} does not read as a path-bearing key. Values of every "
            f"key in PATH_CONFIG_KEYS are rewritten with abspath(), which "
            f"silently corrupts enum-like values such as 'ncbi'."
        )
