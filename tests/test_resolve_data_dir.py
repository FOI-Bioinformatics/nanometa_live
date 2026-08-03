"""The data root must resolve the same way for every entry point.

``nanometa-prepare`` resolved its home through ``get_data_dir_from_env`` and so
honoured ``NANOMETA_DATA_DIR``. Both GUI entry points instead did

    data_dir = args.data_dir if args.data_dir else os.path.expanduser("~/.nanometa")

and then *wrote* the variable from that value. They never read it. So a session
started with ``NANOMETA_DATA_DIR`` exported relocated the CLI while the GUI kept
writing to ``~/.nanometa`` -- half the toolchain moved, which is worse than none
of it moving, because the result looks isolated and is not. Any "fresh install"
or air-gapped test set up that way is silently contaminated by real state, and
warm caches are exactly what mask an offline failure.

``resolve_data_dir`` is now the single implementation: flag > environment >
default.
"""

import os

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils.paths import resolve_data_dir


class TestPrecedence:
    def test_explicit_flag_wins_over_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "from_env"))
        assert resolve_data_dir(str(tmp_path / "from_flag")) == str(
            tmp_path / "from_flag"
        )

    def test_environment_used_when_no_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "from_env"))
        assert resolve_data_dir(None) == str(tmp_path / "from_env")

    def test_default_when_neither(self, monkeypatch):
        monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
        assert resolve_data_dir(None) == os.path.expanduser("~/.nanometa")

    def test_empty_flag_falls_through_to_environment(self, tmp_path, monkeypatch):
        """An unset argparse value arrives as None, but "" must not win either."""
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "from_env"))
        assert resolve_data_dir("") == str(tmp_path / "from_env")


class TestNormalisation:
    def test_expands_user(self, monkeypatch):
        monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
        assert resolve_data_dir("~/somewhere") == os.path.expanduser("~/somewhere")

    def test_collapses_doubled_leading_slash(self, monkeypatch):
        """POSIX preserves a doubled leading slash; the panel should not show it."""
        monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
        assert not resolve_data_dir("//tmp/nanometa").startswith("//")

    def test_returns_absolute(self, monkeypatch):
        monkeypatch.delenv("NANOMETA_DATA_DIR", raising=False)
        assert os.path.isabs(resolve_data_dir("relative/path"))


class TestEntryPointsUseIt:
    """Both GUI entry points must go through the shared resolver.

    Asserted at the source level: importing either module runs argparse-free
    code only, and driving `main()` would start a server.
    """

    @pytest.mark.parametrize(
        "module_path",
        ["nanometa_live/nanometa_live.py", "nanometa_live/app/__main__.py"],
    )
    def test_entry_point_calls_resolver(self, module_path):
        from pathlib import Path

        src = Path(module_path).read_text(encoding="utf-8")
        assert "resolve_data_dir(" in src, (
            f"{module_path} does not use resolve_data_dir, so its precedence "
            "can drift from the CLI's again."
        )
        # The specific anti-pattern: resolving data_dir as flag-or-default,
        # skipping the environment. Not a blanket ban on the literal --
        # `legacy_default` legitimately compares genome_cache_dir against it.
        assert 'args.data_dir else os.path.expanduser("~/.nanometa")' not in src, (
            f"{module_path} still resolves data_dir as flag-or-default, "
            "bypassing NANOMETA_DATA_DIR."
        )
        assert 'args.data_dir or get_data_dir_from_env()' not in src, (
            f"{module_path} inlines the precedence instead of using the "
            "shared resolver, which is how the two drifted apart."
        )
