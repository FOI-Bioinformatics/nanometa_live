"""The data directory must resolve the same way for every consumer.

Two resolvers in ``core/utils/paths.py`` used to disagree about whether
``NANOMETA_DATA_DIR`` exists:

- ``get_watchlists_dir_from_env()`` honoured it. Its docstring records why it
  had to: when callers hard-coded ``~/.nanometa/watchlists``, a run started
  with ``--data-dir`` put the GUI's uploads somewhere the bundle exporter never
  looked, and the bundle silently shipped without them.
- ``NanometaPaths.from_config()`` did not. It read ``config["data_dir"]`` and
  otherwise fell back to the hard-coded ``DEFAULT_DATA_DIR``.

Fixed 2026-07-28: ``from_config`` now falls back to ``get_data_dir_from_env()``,
keeping precedence at config > environment > default.

That second resolver decides the ROOT of an exported bundle:
``BundleManager.export_bundle`` falls back to
``NanometaPaths.from_config(config).data_dir`` when no explicit home is passed,
and ``nanometa-prepare export`` never passes one -- the subcommand has no
``--home`` flag.

So an operator running with ``NANOMETA_DATA_DIR`` set, and no ``data_dir`` key
in their config, exports a bundle built from ``~/.nanometa`` rather than from
the installation they actually prepared. Genomes, taxid mappings, BLAST
databases and caches are all taken from the wrong place, while the watchlists
come from the right one -- an internally inconsistent bundle, produced without
a warning.

Found on 2026-07-28 by exporting a bundle on one machine and importing it on
another with the exporter's home deleted, which is the only arrangement that
makes the mismatch observable. A same-machine round-trip cannot see it: there,
both homes are present and readable.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.utils.paths import (
    NanometaPaths,
    get_data_dir_from_env,
    get_watchlists_dir_from_env,
)

pytestmark = pytest.mark.unit

ISOLATED = "/tmp/nanometa-isolated-data-dir"


@pytest.fixture
def isolated_env(monkeypatch):
    monkeypatch.setenv("NANOMETA_DATA_DIR", ISOLATED)
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)


class TestResolversAgree:
    def test_the_env_resolver_honours_the_variable(self, isolated_env):
        """The half that already works, asserted so the comparison is fair."""
        assert get_data_dir_from_env() == ISOLATED
        assert get_watchlists_dir_from_env().startswith(ISOLATED)

    def test_from_config_honours_the_variable_when_config_is_silent(
        self, isolated_env
    ):
        """A config with no data_dir key should defer to the environment."""
        resolved = str(NanometaPaths.from_config({}).data_dir)
        assert resolved == ISOLATED, (
            f"from_config resolved the data dir to {resolved!r}, ignoring "
            f"NANOMETA_DATA_DIR={ISOLATED!r}. An export started this way "
            f"bundles the wrong installation."
        )

    def test_an_explicit_config_value_still_wins(self, isolated_env):
        """Precedence must stay config > environment > default.

        Whatever the fix, an operator who names a data_dir in config must not
        have it overridden by a stale environment variable.
        """
        explicit = "/tmp/nanometa-explicit-data-dir"
        resolved = str(NanometaPaths.from_config({"data_dir": explicit}).data_dir)
        assert resolved == explicit


class TestConsistencyWithinOneExport:
    def test_watchlists_and_bundle_root_come_from_the_same_home(
        self, isolated_env
    ):
        """A bundle assembled from two different homes is not a coherent one."""
        root = str(NanometaPaths.from_config({}).data_dir)
        watchlists = get_watchlists_dir_from_env()
        assert watchlists.startswith(root), (
            f"bundle root resolves to {root!r} but watchlists resolve to "
            f"{watchlists!r}; an export would take them from different "
            f"installations"
        )
