"""
Mobile lab preparation orchestrator for Nanometa Live.

Runs all steps needed to prepare for offline field operation:
database verification, index building, taxid mapping, genome downloads,
BLAST database construction, and taxonomy cache population.
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PrepStage(str, Enum):
    """Preparation stages in execution order."""
    VERIFY_DB = "verify_db"
    BUILD_INDEX = "build_index"
    GENERATE_MAPPINGS = "generate_mappings"
    DOWNLOAD_GENOMES = "download_genomes"
    BUILD_BLAST_DBS = "build_blast_dbs"
    CACHE_TAXONOMY = "cache_taxonomy"
    CHECK_TOOLS = "check_tools"
    READINESS_CHECK = "readiness_check"


STAGE_LABELS = {
    PrepStage.VERIFY_DB: "Verifying Kraken2 database",
    PrepStage.BUILD_INDEX: "Building taxonomy index",
    PrepStage.GENERATE_MAPPINGS: "Generating taxid mappings",
    PrepStage.DOWNLOAD_GENOMES: "Downloading reference genomes",
    PrepStage.BUILD_BLAST_DBS: "Building BLAST databases",
    PrepStage.CACHE_TAXONOMY: "Caching taxonomy data",
    PrepStage.CHECK_TOOLS: "Checking external tools",
    PrepStage.READINESS_CHECK: "Running readiness check",
}


@dataclass
class PrepProgress:
    """Progress state for the preparation process."""
    stage: PrepStage
    stage_label: str = ""
    stage_index: int = 0
    total_stages: int = len(PrepStage)
    stage_detail: str = ""
    stage_progress: float = 0.0  # 0-100 within current stage
    overall_progress: float = 0.0  # 0-100 across all stages

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "stage_label": self.stage_label,
            "stage_index": self.stage_index,
            "total_stages": self.total_stages,
            "stage_detail": self.stage_detail,
            "stage_progress": self.stage_progress,
            "overall_progress": self.overall_progress,
        }


@dataclass
class PreparationResult:
    """Result of the preparation process."""
    success: bool
    stages_completed: List[str] = field(default_factory=list)
    stages_failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    genomes_downloaded: int = 0
    blast_dbs_built: int = 0
    # Honest breakdown so "N genomes, M BLAST DBs" is explainable: DBs already
    # present from a prior run (correctly skipped) and DBs that failed to build.
    blast_dbs_present: int = 0
    blast_dbs_failed: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stages_completed": self.stages_completed,
            "stages_failed": self.stages_failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "genomes_downloaded": self.genomes_downloaded,
            "blast_dbs_built": self.blast_dbs_built,
            "blast_dbs_present": self.blast_dbs_present,
            "blast_dbs_failed": self.blast_dbs_failed,
        }


# Type alias for progress callback
ProgressCallback = Callable[[PrepProgress], None]


class MobileLabPreparer:
    """
    Orchestrates all preparation steps for offline field operation.

    Calls existing components (TaxidMapper, GenomeDownloadManager, etc.)
    in the correct order and reports progress.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        nanometa_home: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        watchlist_entries: Optional[List[Dict[str, Any]]] = None,
    ):
        if nanometa_home is None:
            # Honor config["data_dir"] (seeded by the CLI entry
            # point from --data-dir); ``~/.nanometa`` is only the
            # last-resort default when neither is supplied.
            from nanometa_live.core.utils.paths import NanometaPaths
            nanometa_home = str(NanometaPaths.from_config(config).data_dir)
        self.config = config
        self.home = Path(nanometa_home)
        self.home.mkdir(parents=True, exist_ok=True)
        self._progress_cb = progress_callback or (lambda p: None)
        self._cancelled = False
        # Watchlist entries injected from the main process via the
        # ``watchlist-entries-snapshot`` store. Required when prepare() runs
        # in a DiskcacheManager background worker, where the WatchlistManager
        # singleton is empty. Each entry: {name, taxid, names_alt, ...}.
        self._injected_entries = watchlist_entries

    def cancel(self):
        """Signal cancellation."""
        self._cancelled = True

    def _report(self, stage: PrepStage, index: int, detail: str = "",
                stage_pct: float = 0.0):
        total = len(PrepStage)
        overall = ((index + stage_pct / 100.0) / total) * 100.0
        progress = PrepProgress(
            stage=stage,
            stage_label=STAGE_LABELS.get(stage, stage.value),
            stage_index=index,
            total_stages=total,
            stage_detail=detail,
            stage_progress=stage_pct,
            overall_progress=min(overall, 100.0),
        )
        self._progress_cb(progress)

    def prepare(
        self,
        skip_existing: bool = True,
    ) -> PreparationResult:
        """
        Run all preparation steps.

        Args:
            skip_existing: Skip steps that are already complete.

        Returns:
            PreparationResult with outcome details.
        """
        result = PreparationResult(success=True)
        stages = list(PrepStage)

        for idx, stage in enumerate(stages):
            if self._cancelled:
                result.errors.append("Preparation cancelled by user")
                result.success = False
                break

            self._report(stage, idx, "Starting...")
            try:
                method = getattr(self, f"_run_{stage.value}")
                method(idx, result, skip_existing)
                result.stages_completed.append(stage.value)
            except Exception as e:
                # Top-level stage dispatcher: each _run_<stage> method runs a
                # different mix of subprocess / network / file I/O work, so
                # any failure must be captured here and reported to the
                # operator without aborting non-critical follow-on stages.
                logger.exception(f"Stage {stage.value} failed: {e}")
                result.stages_failed.append(stage.value)
                result.errors.append(f"{STAGE_LABELS[stage]}: {e}")
                # Critical stages abort; non-critical continue
                if stage in (PrepStage.VERIFY_DB, PrepStage.BUILD_INDEX):
                    result.success = False
                    break

            self._report(stage, idx, "Complete", 100.0)

        return result

    # -- Individual stage implementations --

    def _run_verify_db(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.utils.kraken_utils import verify_kraken_db
        db_path = self.config.get("kraken_db", "")
        if not db_path:
            raise ValueError("No kraken_db configured")
        self._report(PrepStage.VERIFY_DB, idx, f"Checking {db_path}", 50.0)
        if not verify_kraken_db(db_path):
            raise ValueError(f"Invalid Kraken2 database at {db_path}")
        # Ensure inspect file exists
        self._ensure_inspect_file(db_path)

    def _ensure_inspect_file(self, db_path: str):
        """Generate inspect.txt if missing."""
        inspect_path = Path(db_path) / "inspect.txt"
        if inspect_path.exists():
            return
        from nanometa_live.core.utils.kraken_utils import inspect_kraken_db
        import shutil
        if shutil.which("kraken2-inspect"):
            logger.info("Generating inspect.txt for Kraken2 database")
            success, msg = inspect_kraken_db(db_path, str(inspect_path))
            if not success:
                logger.warning(f"Could not generate inspect.txt: {msg}")

    def _run_build_index(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.taxonomy.taxid_mapping import (
            TaxidMapper, get_database_hash
        )
        db_path = self.config.get("kraken_db", "")
        db_hash = get_database_hash(db_path)
        index_file = self.home / "mappings" / f"{db_hash}_index.pkl"

        if skip_existing and index_file.exists():
            self._report(PrepStage.BUILD_INDEX, idx, "Index already exists", 100.0)
            return

        self._report(PrepStage.BUILD_INDEX, idx, "Loading database taxonomy", 30.0)
        mapper = TaxidMapper()
        mapper.load_database(db_path)
        self._report(PrepStage.BUILD_INDEX, idx, "Index built", 100.0)

    def _run_generate_mappings(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.taxonomy.taxid_mapping import (
            TaxidMapper, get_database_hash, get_mapping_cache_path
        )
        db_path = self.config.get("kraken_db", "")
        cache_path = get_mapping_cache_path(db_path)

        if skip_existing and cache_path.exists():
            self._report(PrepStage.GENERATE_MAPPINGS, idx,
                         "Mappings already exist", 100.0)
            return

        # Get watchlist entries
        entries = self._get_watchlist_entries()
        if not entries:
            self._report(PrepStage.GENERATE_MAPPINGS, idx,
                         "No watchlist entries to map", 100.0)
            result.warnings.append("No watchlist entries found for mapping")
            return

        self._report(PrepStage.GENERATE_MAPPINGS, idx,
                      f"Mapping {len(entries)} entries", 30.0)
        mapper = TaxidMapper()
        mapper.load_database(db_path)
        mapper.generate_mappings(entries)

    def _run_download_genomes(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        offline = bool(self.config.get("offline_mode", False))
        # Pass offline_mode explicitly: prepare() runs in a DiskcacheManager
        # worker where the genome-manager singleton starts fresh (offline_mode
        # defaults False), so without this an imported/offline system would
        # still reach out to NCBI.
        manager = get_genome_manager(
            self.config.get("genome_cache_dir") or str(self.home),
            offline_mode=offline,
        )
        entries = self._get_watchlist_entries()
        if not entries:
            return

        if offline:
            # Imported/offline system: rely on the genomes shipped in the
            # bundle; never download. Report any watchlist organism whose
            # genome was not included so the operator knows confirmation
            # testing will be incomplete for it.
            missing = [
                e.get("name", f"taxid {e.get('taxid')}")
                for e in entries
                if not manager.has_genome(e.get("taxid", 0))
            ]
            self._report(PrepStage.DOWNLOAD_GENOMES, idx,
                         "Offline mode: using bundled genomes", 100.0)
            if missing:
                shown = ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
                result.warnings.append(
                    f"Offline mode: skipped genome download; {len(missing)} "
                    f"watchlist genome(s) not present in the bundle: {shown}"
                )
            return

        # On a GTDB database every organism is bacteria/archaea, so hint the
        # kingdom and skip the per-taxid NCBI lookup entirely.
        kingdom_hint = ("Bacteria"
                        if str(self.config.get("kraken_taxonomy", "")).lower() == "gtdb"
                        else None)

        total = len(entries)
        downloaded = 0
        for i, entry in enumerate(entries):
            if self._cancelled:
                return
            taxid = entry.get("taxid", 0)
            name = entry.get("name", f"taxid {taxid}")
            pct = (i / total) * 100.0
            self._report(PrepStage.DOWNLOAD_GENOMES, idx,
                         f"({i+1}/{total}) {name}", pct)

            if skip_existing and manager.has_genome(taxid):
                continue
            if taxid:
                path = manager.download_genome(
                    taxid, name, kingdom=kingdom_hint,
                    gtdb_taxonomy=entry.get("gtdb_taxonomy"),
                )
                if path:
                    downloaded += 1

        result.genomes_downloaded = downloaded

    def _run_build_blast_dbs(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        # makeblastdb is local, but keep the manager offline-consistent so it
        # never lazily fetches anything on an imported/offline system.
        manager = get_genome_manager(
            self.config.get("genome_cache_dir") or str(self.home),
            offline_mode=bool(self.config.get("offline_mode", False)),
        )
        self._report(PrepStage.BUILD_BLAST_DBS, idx,
                     "Building missing BLAST databases", 30.0)
        report = manager.build_missing_blast_dbs_detailed(retry=True)
        result.blast_dbs_built = report["built"]
        result.blast_dbs_present = report["already_present"]
        result.blast_dbs_failed = report["failed"]
        if report["failed"]:
            # Surface failures so the operator understands why the BLAST-DB
            # count is below the genome count (and why BLAST validation may be
            # empty for those species while minimap2 still works).
            names = ", ".join(
                f"{f.get('species') or f['taxid']} ({f['reason']})"
                for f in report["failed"]
            )
            result.warnings.append(
                f"{len(report['failed'])} BLAST database(s) failed to build: {names}"
            )

    def _run_cache_taxonomy(self, idx: int, result: PreparationResult, skip_existing: bool):
        self._report(PrepStage.CACHE_TAXONOMY, idx,
                     "Exporting taxonomy cache snapshot", 50.0)
        try:
            from nanometa_live.core.utils.offline_cache import OfflineTaxonomyCache
            cache = OfflineTaxonomyCache()
            snapshot_path = str(self.home / "cache" / "taxonomy_snapshot.json")
            count = cache.export_snapshot(snapshot_path)
            logger.info(f"Exported {count} taxonomy cache entries")
        except (ImportError, AttributeError, FileNotFoundError, PermissionError, OSError, TypeError, ValueError) as e:
            result.warnings.append(f"Taxonomy cache export: {e}")

    def _run_check_tools(self, idx: int, result: PreparationResult, skip_existing: bool):
        import shutil
        # Tools that run locally (not inside pipeline containers).
        # kraken2 and fastp run inside Nextflow containers, not checked here.
        tools = {
            "nextflow": "pipeline orchestration",
            "kraken2-inspect": "building taxonomy index",
            "datasets": "downloading reference genomes from NCBI",
            "makeblastdb": "building BLAST databases",
        }
        # Only check blastn if validation is enabled
        blast_enabled = self.config.get("blast_validation", False)
        if isinstance(blast_enabled, str):
            blast_enabled = blast_enabled.lower() in ("true", "yes", "1")
        if blast_enabled:
            tools["blastn"] = "on-demand read validation"

        # Check container runtime matching profile
        profile = self.config.get("pipeline_profile", "docker")
        if profile == "conda":
            tools["conda"] = f"pipeline execution (profile: {profile})"
        elif profile in ("singularity", "apptainer"):
            # Accept either
            if not (shutil.which("singularity") or shutil.which("apptainer")):
                result.warnings.append(
                    f"Neither singularity nor apptainer found "
                    f"(required by pipeline_profile: {profile})"
                )
        else:
            tools["docker"] = f"pipeline execution (profile: {profile})"

        tool_list = list(tools.items())
        for i, (tool, purpose) in enumerate(tool_list):
            pct = (i / len(tool_list)) * 100.0
            self._report(PrepStage.CHECK_TOOLS, idx, f"Checking {tool}", pct)
            if not shutil.which(tool):
                result.warnings.append(f"Tool not found: {tool} (needed for {purpose})")

    def _run_readiness_check(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker
        self._report(PrepStage.READINESS_CHECK, idx,
                     "Running final readiness check", 50.0)
        checker = ReadinessChecker()
        report = checker.check_readiness(self.config, str(self.home))
        if not report.ready:
            for fail in report.critical_failures:
                result.warnings.append(f"Readiness: {fail.name} - {fail.message}")

    def _get_watchlist_entries(self) -> List[Dict[str, Any]]:
        """Return watchlist entries for mapping / genome download.

        Prefers entries injected from the main process (the
        ``watchlist-entries-snapshot`` store) so this works inside a
        background worker where the WatchlistManager singleton is empty;
        falls back to the singleton for in-process callers.
        """
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
            mc = get_mapping_collection()

            if self._injected_entries:
                # Snapshot shape: {name, taxid, rank, names_alt}.
                result = []
                for e in self._injected_entries:
                    taxid = e.get("taxid")
                    if not taxid:
                        continue
                    kraken_taxid = mc.get_db_taxid(taxid) if mc else None
                    result.append({
                        "taxid": taxid,
                        "name": e.get("name", ""),
                        "kraken_taxid": kraken_taxid or taxid,
                        "names_alt": e.get("names_alt", []),
                    })
                return result

            from nanometa_live.core.watchlist.watchlist_manager import (
                get_watchlist_manager,
            )
            wm = get_watchlist_manager()
            entries = wm.get_all_entries()

            result = []
            for e in entries:
                kraken_taxid = None
                if mc and e.taxid:
                    kraken_taxid = mc.get_db_taxid(e.taxid)
                result.append({
                    "taxid": e.taxid,
                    "name": e.name,
                    "kraken_taxid": kraken_taxid or e.taxid,
                    "names_alt": e.names_alt,
                })
            return result
        except (ImportError, AttributeError):
            return []
