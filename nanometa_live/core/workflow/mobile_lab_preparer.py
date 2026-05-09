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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stages_completed": self.stages_completed,
            "stages_failed": self.stages_failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "genomes_downloaded": self.genomes_downloaded,
            "blast_dbs_built": self.blast_dbs_built,
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
        manager = get_genome_manager(self.config.get("genome_cache_dir") or str(self.home))
        entries = self._get_watchlist_entries()
        if not entries:
            return

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
                path = manager.download_genome(taxid, name)
                if path:
                    downloaded += 1

        result.genomes_downloaded = downloaded

    def _run_build_blast_dbs(self, idx: int, result: PreparationResult, skip_existing: bool):
        from nanometa_live.core.utils.genome_manager import get_genome_manager
        manager = get_genome_manager(self.config.get("genome_cache_dir") or str(self.home))
        self._report(PrepStage.BUILD_BLAST_DBS, idx,
                     "Building missing BLAST databases", 30.0)
        built = manager.build_missing_blast_dbs()
        result.blast_dbs_built = built

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
        """Load watchlist entries from config or watchlist files."""
        try:
            from nanometa_live.core.watchlist.watchlist_manager import (
                get_watchlist_manager,
            )
            from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection

            wm = get_watchlist_manager()
            entries = wm.get_all_entries()
            mc = get_mapping_collection()

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
