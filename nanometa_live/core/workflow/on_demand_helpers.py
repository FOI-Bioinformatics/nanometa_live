"""Pure helpers for on-demand validation.

Split out of ``on_demand_validator`` so that module carries the workflow
and these carry no state -- the same split used for ``*_tab.py`` /
``*_helpers.py`` elsewhere in the codebase. They are imported back under
their original names, so call sites are unchanged.
"""

import logging
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default on-demand validation timeout (minutes) when config does not set one.
_DEFAULT_VALIDATION_TIMEOUT_MINUTES = 30


def _is_int_str(value: Any) -> bool:
    """True if ``value`` is a string (or value) that parses as an int."""
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalise_sample_filter(sample: Optional[str]) -> Optional[str]:
    """Map the GUI's aggregate-scope tokens to "no sample filter".

    The Organisms tab passes ``sample="all"`` (and older callers "All
    Samples") when a validation is requested at aggregate scope. Forwarding
    that token into ``ValidationParser.get_validation_results(sample=...)``
    treats it as a literal sample name that matches nothing, so a successful
    validation run was reported to the operator as "did not return a result"
    (2026-08-18). ``None`` means "all samples" to the parser.
    """
    if not sample:
        return None
    if sample.strip().lower() in ("all", "all samples"):
        return None
    return sample


def resolve_launch_context(
    config: Optional[Dict[str, Any]],
) -> Optional[Tuple[Path, Path]]:
    """Return ``(launch_dir, work_dir)`` for an on-demand Nextflow launch.

    ``-resume`` resolves through the run history in
    ``<launch dir>/.nextflow/history`` and the task cache under
    ``-work-dir``, so BOTH must match the main pipeline's launch
    (``NextflowManager``: cwd=data_dir, -work-dir <data_dir>/work). Sharing
    only the outdir shares nothing -resume reads; without these two
    Nextflow printed "It appears you have never run this project before --
    Option `-resume` is ignored" and re-ran every previously-validated pair
    from scratch (2026-08-18). Returns ``None`` when the work dir cannot be
    created.
    """
    from nanometa_live.core.utils.paths import NanometaPaths
    launch_dir = Path(NanometaPaths.from_config(config or {}).data_dir)
    work_dir = launch_dir / "work"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Cannot create Nextflow work dir {work_dir}: {e}")
        return None
    return launch_dir, work_dir


def supervise_validation_process(
    proc: "subprocess.Popen", timeout_seconds: int
) -> Optional[Tuple[int, str, str]]:
    """Wait for the validation subprocess; on timeout, kill its whole group.

    Returns ``(returncode, stdout, stderr)``, or ``None`` after a timeout
    (the process group is escalated SIGTERM -> SIGKILL, mirroring
    ``NextflowManager.stop()`` -- without the group kill, Nextflow's
    already-launched task processes survive as orphans).
    """
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.communicate()
        logger.error(
            "nanometanf validation timed out after %d minute(s); raise "
            "'validation_timeout_minutes' in config for large genomes",
            timeout_seconds // 60,
        )
        return None


def write_failure_log(
    results_dir: Path, cmd: List[str], launch_dir: Path, detail: str
) -> None:
    """Persist a failed launch's full context to ``<results>/logs/``.

    The GUI error message tells the operator to check that directory --
    this makes it true. The launcher runs in a DiskcacheManager background
    worker whose logger output reaches no file the operator (or a debugger)
    can find, so without this file a failed launch is undiagnosable: the
    2026-08-18 release check burned an hour on exactly that. Best effort by
    design; never raises.
    """
    try:
        log_dir = results_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"on_demand_validation_{stamp}.log"
        log_path.write_text(
            f"command: {' '.join(cmd)}\n"
            f"cwd: {launch_dir}\n"
            f"{detail}"
        )
        logger.error(f"Launch details written to {log_path}")
    except OSError as write_err:  # pragma: no cover - best effort
        logger.warning(f"Could not write on-demand failure log: {write_err}")


def _genome_file_looks_valid(path: Path) -> bool:
    """Cheap sanity check that ``path`` is a non-empty FASTA file.

    has_genome() only tests existence; a zero-byte or truncated download
    passes it but fails opaquely once Nextflow tries to align against it.
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            first = fh.readline().lstrip()
        return first.startswith(">")
    except OSError:
        return False


def _validation_timeout_seconds(config: Optional[Dict[str, Any]]) -> int:
    """Resolve the subprocess timeout (seconds) from config, floored at 60s."""
    minutes = (config or {}).get(
        "validation_timeout_minutes", _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    )
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        minutes = _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    return max(60, int(minutes * 60))


def _pick_result_for_method(results: list, method: str):
    """Return the parsed ValidationResult matching the requested method.

    ``ValidationParser.get_validation_results`` filters by (sample, taxid) but
    not by method, so for a pair that already carried a result of the other
    method, ``results[0]`` may be the wrong one. Pick the result whose
    ``validation_method`` matches the request; for ``"both"`` prefer the
    read-centric BLAST summary. Falls back to ``results[0]``.
    """
    order = ["blast", "minimap2"] if method == "both" else [method]
    # An aggregate-scope request can match one result per sample; prefer the
    # deepest one so the summary card reflects the sample that carries the
    # detection rather than filesystem enumeration order.
    ranked = sorted(
        results,
        key=lambda r: getattr(r, "total_reads", 0) or 0,
        reverse=True,
    )
    for m in order:
        for r in ranked:
            if getattr(r, "validation_method", None) == m:
                return r
    return ranked[0]
