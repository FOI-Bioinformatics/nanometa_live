"""
Cumulative ``pathogen_genomes.json`` store for on-demand validation.

Split out of ``OnDemandValidator`` (core/workflow/on_demand_validator.py,
2026-08-16 code-size remediation): the load/save/lock/merge sequence only
needs a validation directory, not the rest of the validator's state, so it
was the largest self-contained block left to extract. ``OnDemandValidator``
keeps thin delegating instance methods (``_load_pathogen_genomes``,
``_save_pathogen_genomes``, ``_locked_pathogen_genomes_file``,
``_add_taxid_to_pathogen_genomes``) so its existing public surface -- and the
``TestPathogenGenomesLock`` tests that call/monkeypatch them as methods -- are
unaffected.
"""

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows: file locking not available

from nanometa_live.core.workflow.on_demand_helpers import _is_int_str

logger = logging.getLogger(__name__)

# Single accumulating pathogen genomes JSON. Living in the validator's
# ``validation_dir`` keeps it next to the validation outputs nanometanf
# writes; the same path is read back across calls so each on-demand request
# appends its taxid to a stable file rather than starting fresh.
PATHOGEN_GENOMES_FILENAME = "pathogen_genomes.json"


def load_pathogen_genomes(validation_dir: Path) -> Dict[str, str]:
    """Read the cumulative pathogen_genomes mapping (taxid -> genome FASTA
    path) if it exists. Returns empty dict on first call or when the file is
    missing/corrupt."""
    path = validation_dir / PATHOGEN_GENOMES_FILENAME
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning(f"pathogen_genomes.json unreadable, starting fresh: {e}")
        return {}


def save_pathogen_genomes(validation_dir: Path, mapping: Dict[str, str]) -> Path:
    """Atomically rewrite the cumulative pathogen_genomes mapping."""
    path = validation_dir / PATHOGEN_GENOMES_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)
    tmp.replace(path)
    return path


@contextmanager
def locked_pathogen_genomes_file(validation_dir: Path):
    """Hold an exclusive, blocking file lock across a pathogen_genomes.json
    read-modify-write.

    Two on-demand validation requests in flight at once (e.g. two browser
    tabs/operators -- the background callback's ``running=`` guard only
    disables the button for the triggering session, not server-wide) both
    call ``load_pathogen_genomes`` -> mutate -> ``save_pathogen_genomes``
    with no serialization between them. That is a classic lost-update race:
    B's save can land between A's load and A's save and silently drop A's
    own taxid addition, even though A's already-launched Nextflow subprocess
    still expects to find it. The lock is scoped to a small dedicated
    ``.lock`` file (not the JSON itself) so a reader elsewhere that just
    opens ``pathogen_genomes.json`` directly is unaffected.
    """
    lock_path = validation_dir / (PATHOGEN_GENOMES_FILENAME + ".lock")
    validation_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    try:
        if fcntl:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def add_taxid_to_pathogen_genomes(
    validation_dir: Path, taxid: int, genome_fasta: Path
) -> Tuple[Optional[Path], Dict[str, str]]:
    """Merge one taxid into the cumulative pathogen_genomes.json under an
    exclusive lock (see ``locked_pathogen_genomes_file``).

    Returns ``(mapping_file_path, mapping)`` on success. On a write failure
    returns ``(None, {})`` -- the caller must treat that as fatal for this
    validation request rather than proceeding with a taxid list that was
    never actually persisted.
    """
    try:
        with locked_pathogen_genomes_file(validation_dir):
            mapping = load_pathogen_genomes(validation_dir)
            # Drop any non-numeric keys a corrupted prior file may carry so
            # sorted(key=int) downstream and Nextflow's taxid filter never
            # choke; this also heals the on-disk file when re-saved.
            mapping = {k: v for k, v in mapping.items() if _is_int_str(k)}
            mapping[str(taxid)] = str(genome_fasta)
            path = save_pathogen_genomes(validation_dir, mapping)
            return path, mapping
    except (PermissionError, OSError, TypeError, ValueError) as e:
        logger.exception(f"Failed to write pathogen genomes JSON: {e}")
        return None, {}
