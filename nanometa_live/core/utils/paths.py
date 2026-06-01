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
    """Resolved directory layout, split across two scopes.

    Two roots, single source of truth:

    * ``data_dir`` -- per-installation GLOBAL state, shared across every
      analysis: the taxonomy ``cache``, downloaded ``genomes``/``blast``
      databases, the kraken2 download registry, ``logs``. Defaults to
      ``~/.nanometa`` and is moved with ``--data-dir``.
    * ``project_dir`` -- the operator's current analysis directory. PROJECT
      state lives in ``<project_dir>/.nanometa/`` (the ``project_state``
      root): the session ``configs`` (incl. ``last-session.yaml``), the
      ``watchlists`` selection + ``watchlist_toggle_state``, and the taxid
      ``mappings``. Different projects therefore do not clobber each other.

    Backward compatible: when ``project_dir`` is unset, the project-scoped
    properties fall back to ``data_dir`` (the pre-split layout), so callers
    and tests that never set a project keep working.

    Construct via :meth:`from_config` (preferred). The class is frozen so an
    instance can be threaded through callbacks without worrying about
    mutation.
    """

    data_dir: Path
    project_dir: Path | None = None

    @staticmethod
    def _norm(raw: object) -> Path:
        return Path(os.path.abspath(os.path.expanduser(str(raw))))

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "NanometaPaths":
        """Build a resolver from the application config dict.

        Reads ``config["data_dir"]`` (global root; falls back to
        :data:`DEFAULT_DATA_DIR`) and ``config["project_dir"]`` (project
        root; ``None`` when empty, which collapses the project scope back
        onto ``data_dir``). Values are expanduser+abspath-normalised.
        """
        raw_data = config.get("data_dir") or DEFAULT_DATA_DIR
        raw_project = config.get("project_dir") or ""
        project = cls._norm(raw_project) if str(raw_project).strip() else None
        return cls(cls._norm(raw_data), project)

    @classmethod
    def from_data_dir(cls, data_dir: str | os.PathLike[str]) -> "NanometaPaths":
        """Build a resolver from an explicit ``data_dir`` value.

        Use when the caller has the path but no full config dict (e.g.
        the CLI entry point, before the config has been merged). No project
        scope -- project-scoped properties fall back to ``data_dir``.
        """
        return cls(cls._norm(data_dir))

    # ---- project scope root --------------------------------------------
    @property
    def project_state(self) -> Path:
        """Root for project-local state (``<project_dir>/.nanometa``).

        Falls back to ``data_dir`` when no project is configured, so the
        project-scoped properties behave exactly as before the split."""
        if self.project_dir is not None:
            return self.project_dir / ".nanometa"
        return self.data_dir

    # ---- project-scoped subdirectories ---------------------------------
    @property
    def configs(self) -> Path:
        return self.project_state / "configs"

    @property
    def mappings(self) -> Path:
        return self.project_state / "mappings"

    @property
    def watchlists(self) -> Path:
        return self.project_state / "watchlists"

    @property
    def watchlist_toggle_state(self) -> Path:
        return self.project_state / "watchlist_toggle_state.yaml"

    @property
    def last_session_yaml(self) -> Path:
        return self.configs / "last-session.yaml"

    @property
    def results(self) -> Path:
        """Container for this project's run folders.

        ``<project_dir>/results`` when a project is set; otherwise the
        legacy ``~/nanometa_results`` so a project-less invocation keeps
        the pre-split default. Each run is a named subfolder (see
        :meth:`run_dir`)."""
        if self.project_dir is not None:
            return self.project_dir / "results"
        return Path(os.path.expanduser("~/nanometa_results"))

    def run_dir(self, run_name: str) -> Path:
        """Results folder for a single named run (``results/<run_name>``)."""
        return self.results / run_name

    # ---- global (per-installation) subdirectories ----------------------
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
    def logs(self) -> Path:
        return self.data_dir / "logs"

    @property
    def kraken2_local_registry(self) -> Path:
        return self.data_dir / "kraken2_databases.local.yaml"

    @property
    def kraken2_databases(self) -> Path:
        """Where GUI-downloaded Kraken2 databases are stored (global)."""
        return self.data_dir / "kraken2_databases"

    def ensure_dirs(self) -> None:
        """Create the standard subdirectories if they do not exist."""
        global_dirs = (
            self.data_dir,
            self.cache,
            self.genomes,
            self.blast,
            self.logs,
        )
        project_dirs = [
            self.configs,
            self.mappings,
            self.watchlists,
        ]
        # The results container is only auto-created for an explicit project
        # (avoid materialising ~/nanometa_results on a project-less run).
        if self.project_dir is not None:
            project_dirs.append(self.results)
        for p in (*global_dirs, *project_dirs):
            p.mkdir(parents=True, exist_ok=True)


# Module-level helper for non-config callers (e.g. module-import-time
# initialisation). The CLI entry point sets ``NANOMETA_DATA_DIR`` early
# so any import-time consumer reads the right path. Falls back to the
# legacy default when unset.
_DATA_DIR_ENV = "NANOMETA_DATA_DIR"
_PROJECT_DIR_ENV = "NANOMETA_PROJECT_DIR"


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


def get_project_dir_from_env() -> str | None:
    """Return the project_dir from the environment, or None if unset."""
    val = os.environ.get(_PROJECT_DIR_ENV)
    return val or None


def set_project_dir_env(project_dir: str | os.PathLike[str]) -> None:
    """Set ``NANOMETA_PROJECT_DIR`` so project-scoped singletons agree.

    Called once by the CLI entry point alongside :func:`set_data_dir_env`.
    Lets writer and reader of project-local artifacts (e.g. taxid mappings)
    meet at the same path even when constructed before a config is loaded.
    """
    os.environ[_PROJECT_DIR_ENV] = str(project_dir)


def get_mappings_dir_from_env() -> str:
    """Resolve the taxid-mappings directory from the environment.

    Project-local (``<project_dir>/.nanometa/mappings``) when
    ``NANOMETA_PROJECT_DIR`` is set, else the legacy global
    ``<data_dir>/mappings``. Mirrors :pyattr:`NanometaPaths.mappings`."""
    project = get_project_dir_from_env()
    if project:
        return os.path.join(
            os.path.abspath(os.path.expanduser(project)), ".nanometa", "mappings"
        )
    return os.path.join(get_data_dir_from_env(), "mappings")
