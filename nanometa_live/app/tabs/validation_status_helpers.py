"""Pure diagnostic logic for the Validation tab.

When the Validation tab has no results the operator should be told *why* --
whether validation is disabled, whether any organism is enabled, whether the
reference genomes / BLAST databases are present, or simply that the run is
still in progress -- instead of a bare "Waiting for validation results...".

``compute_validation_status`` is a pure function of plain inputs so it is
unit-testable without a running app, mirroring the ``*_tab.py`` ->
``*_helpers.py`` split used across the dashboard.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationStatus:
    """Describes the no-results state of the Validation tab.

    ``code`` is a stable identifier for tests/branches; ``severity`` maps to a
    Bootstrap colour (``secondary``/``info``/``warning``/``success``);
    ``headline`` and ``detail`` are operator-facing text.
    """

    code: str
    severity: str
    headline: str
    detail: str

    @property
    def message(self) -> str:
        return f"{self.headline} {self.detail}".strip()


def _missing_reference_status(no_db, no_genome, n_taxids):
    """Warning ValidationStatus when organisms lack a genome or BLAST DB.

    ``no_db`` = genome present but BLAST database missing (buildable);
    ``no_genome`` = no reference genome at all (not buildable). Returns None
    when nothing is missing.
    """
    if not no_db and not no_genome:
        return None
    n_no_db, n_no_genome = len(no_db), len(no_genome)
    if no_db and no_genome:
        headline = (f"{n_no_db} organism(s) have no BLAST database and "
                    f"{n_no_genome} have no reference genome.")
    elif no_db:
        headline = (f"{n_no_db} of {n_taxids} organism(s) have a reference "
                    "genome but no BLAST database.")
    else:
        headline = f"{n_no_genome} of {n_taxids} organism(s) have no reference genome."
    detail_parts = []
    if no_db:
        detail_parts.append("Build the missing databases in the Watchlist & Preparation tab.")
    if no_genome:
        detail_parts.append("Organisms without a reference genome cannot be BLAST- or "
                            "minimap2-validated; minimap2 still runs where a genome exists.")
    return ValidationStatus("missing_dbs", "warning", headline, " ".join(detail_parts))


def compute_validation_status(
    *,
    blast_enabled: bool,
    results_dir_ok: bool,
    validation_taxids: List[str],
    db_status: Optional[Dict[str, List[int]]],
    has_results: bool,
    pipeline_running: bool,
    realtime: bool,
    results_count: int = 0,
) -> ValidationStatus:
    """Decide what the Validation tab should tell the operator.

    Precedence (first match wins): disabled -> no results dir -> no enabled
    organism -> missing genomes/databases -> results present -> run in progress
    (realtime refreshes each batch, batch runs to completion) -> waiting.
    """
    if not blast_enabled:
        return ValidationStatus(
            "disabled", "secondary",
            "Validation is disabled.",
            "Enable it in the Configuration tab to confirm detections with BLAST and minimap2.",
        )

    if not results_dir_ok:
        return ValidationStatus(
            "no_results_dir", "secondary",
            "Results directory not found.",
            "Start or configure a run before validation can produce results.",
        )

    n_taxids = len(validation_taxids or [])
    if n_taxids == 0:
        return ValidationStatus(
            "no_species", "info",
            "No watchlist organisms are enabled, so there is nothing to validate.",
            "Enable organisms in the Watchlist & Preparation tab.",
        )

    missing = _missing_reference_status(
        list((db_status or {}).get("missing", [])),
        list((db_status or {}).get("no_genome", [])),
        n_taxids,
    )
    if missing is not None:
        return missing

    if has_results:
        return ValidationStatus(
            "results", "success",
            f"Validation results available for {results_count} organism(s).",
            "",
        )

    if pipeline_running:
        if realtime:
            return ValidationStatus(
                "running_realtime", "info",
                "Validation is running.",
                "Results refresh as each batch is processed and should appear within a "
                "minute or two of the first classified reads.",
            )
        return ValidationStatus(
            "running_batch", "info",
            f"Validation is in progress for {n_taxids} organism(s).",
            "Results appear when the run completes.",
        )

    return ValidationStatus(
        "waiting", "info",
        "Waiting for validation results from the pipeline.",
        "",
    )


def build_validation_status_payload(config, results_dir_ok, backend_status,
                                    has_results, results_count):
    """Resolve run state into the diagnostic dict stored for the Validation tab.

    Looks up the enabled validation taxids and their BLAST-database state (best
    effort; the network is never touched) and delegates wording to
    :func:`compute_validation_status`.
    """
    blast_enabled = bool(config and config.get("blast_validation", False))
    validation_taxids: List[str] = []
    db_status = None
    if blast_enabled and config:
        try:
            from nanometa_live.core.config.parameter_mapping import get_validation_species
            validation_taxids, _genomes = get_validation_species(config)
        except Exception as e:  # noqa: BLE001 - diagnostic must not raise
            logger.debug("validation status: get_validation_species failed: %s", e)
        if validation_taxids:
            try:
                from nanometa_live.core.utils.genome_manager import get_genome_manager
                mgr = get_genome_manager(cache_dir=config.get("genome_cache_dir"))
                int_taxids = [int(t) for t in validation_taxids if str(t).isdigit()]
                db_status = mgr.blast_db_status(int_taxids)
            except Exception as e:  # noqa: BLE001 - diagnostic must not raise
                logger.debug("validation status: blast_db_status failed: %s", e)

    status = compute_validation_status(
        blast_enabled=blast_enabled,
        results_dir_ok=results_dir_ok,
        validation_taxids=[str(t) for t in (validation_taxids or [])],
        db_status=db_status,
        has_results=has_results,
        pipeline_running=bool(backend_status and backend_status.get("running")),
        realtime=bool(config and config.get("processing_mode") == "realtime"),
        results_count=results_count,
    )
    return {
        "code": status.code,
        "severity": status.severity,
        "headline": status.headline,
        "detail": status.detail,
        "message": status.message,
    }


_EMPTY_STATE_VIEW = {
    "disabled": ("Validation Disabled", "bi-shield-x"),
    "no_results_dir": ("Results Directory Missing", "bi-folder-x"),
    "no_species": ("Nothing To Validate", "bi-shield-slash"),
    "missing_dbs": ("Reference Databases Missing", "bi-database-exclamation"),
    "running_realtime": ("Validation Running", "bi-hourglass-split"),
    "running_batch": ("Validation In Progress", "bi-hourglass-split"),
    "waiting": ("Awaiting Results", "bi-hourglass-split"),
}


def empty_state_view(status: Optional[Dict], message: str):
    """Return ``(title, icon)`` for the BLAST empty-state panel.

    Keyed off the diagnostic ``code`` when present, with a text fallback for
    legacy store payloads that carry only a ``message``.
    """
    code = (status or {}).get("code")
    if code in _EMPTY_STATE_VIEW:
        return _EMPTY_STATE_VIEW[code]
    low = (message or "").lower()
    if "disabled" in low:
        return "Validation Disabled", "bi-shield-x"
    if "waiting" in low or "running" in low:
        return "Awaiting Results", "bi-hourglass-split"
    return "No Validation Results", "bi-shield-check"
