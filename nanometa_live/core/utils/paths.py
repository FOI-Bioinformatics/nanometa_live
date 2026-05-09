"""Per-installation directory layout resolver for Nanometa Live.

Single source of truth for "where does Nanometa Live keep its state on
disk." Subsystems that previously hard-coded ``~/.nanometa/<subdir>``
construct a :class:`NanometaPaths` from the operator's config and read
the subdir as a property.

This module is a companion to ``path_utils``: ``path_utils`` canonicalises
operator-supplied path strings (Kraken2 DB, results dir, etc.); this
module resolves the implicit per-installation layout (configs, cache,
mappings, genomes, blast, logs).

Usage::

    paths = NanometaPaths.from_config(config)
    paths.ensure_dirs()
    last_session = paths.last_session_yaml
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


# The legacy default. Kept as a constant rather than scattered string
# literals so a future relocation (e.g. XDG_DATA_HOME) is a one-line
# change. Operators currently using ``~/.nanometa`` are unaffected.
DEFAULT_DATA_DIR = "~/.nanometa"


@dataclass(frozen=True)
class NanometaPaths:
    """Resolved per-installation directory layout.

    Construct via :meth:`from_config` (preferred) or directly with an
    already-resolved absolute :class:`pathlib.Path`. The class is frozen
    so an instance can be threaded through callbacks without worrying
    about mutation.
    """

    data_dir: Path

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "NanometaPaths":
        """Build a resolver from the application config dict.

        Reads ``config["data_dir"]`` if set; otherwise falls back to
        :data:`DEFAULT_DATA_DIR` (``~/.nanometa``). The value is
        expanduser+abspath-normalised so a stored ``"~/foo"`` works on
        any process.
        """
        raw = config.get("data_dir") or DEFAULT_DATA_DIR
        return cls(Path(os.path.abspath(os.path.expanduser(str(raw)))))

    @classmethod
    def from_data_dir(cls, data_dir: str | os.PathLike[str]) -> "NanometaPaths":
        """Build a resolver from an explicit ``data_dir`` value.

        Use when the caller has the path but no full config dict (e.g.
        the CLI entry point, before the config has been merged).
        """
        return cls(Path(os.path.abspath(os.path.expanduser(str(data_dir)))))

    @property
    def configs(self) -> Path:
        return self.data_dir / "configs"

    @property
    def cache(self) -> Path:
        return self.data_dir / "cache"

    @property
    def genomes(self) -> Path:
        return self.data_dir / "genomes"

    @property
    def blast(self) -> Path:
        return self.data_dir / "blast"

    @property
    def mappings(self) -> Path:
        return self.data_dir / "mappings"

    @property
    def logs(self) -> Path:
        return self.data_dir / "logs"

    @property
    def last_session_yaml(self) -> Path:
        return self.configs / "last-session.yaml"

    @property
    def kraken2_local_registry(self) -> Path:
        return self.data_dir / "kraken2_databases.local.yaml"

    @property
    def watchlist_toggle_state(self) -> Path:
        return self.data_dir / "watchlist_toggle_state.yaml"

    def ensure_dirs(self) -> None:
        """Create the standard subdirectories if they do not exist."""
        for p in (
            self.data_dir,
            self.configs,
            self.cache,
            self.genomes,
            self.blast,
            self.mappings,
            self.logs,
        ):
            p.mkdir(parents=True, exist_ok=True)


# Module-level helper for non-config callers (e.g. module-import-time
# initialisation). The CLI entry point sets ``NANOMETA_DATA_DIR`` early
# so any import-time consumer reads the right path. Falls back to the
# legacy default when unset.
_DATA_DIR_ENV = "NANOMETA_DATA_DIR"


def get_data_dir_from_env() -> str:
    """Return the data_dir as resolved from the environment, or the default.

    Used by the offline taxonomy cache (which is a module-level singleton
    constructed before any config has been loaded). Most callers should
    use :meth:`NanometaPaths.from_config` instead.
    """
    return os.environ.get(_DATA_DIR_ENV) or os.path.expanduser(DEFAULT_DATA_DIR)


def set_data_dir_env(data_dir: str | os.PathLike[str]) -> None:
    """Set the ``NANOMETA_DATA_DIR`` env var so downstream singletons see it.

    Called once by the CLI entry point after ``--data-dir`` is parsed.
    """
    os.environ[_DATA_DIR_ENV] = str(data_dir)
