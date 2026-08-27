"""
Readiness checker for offline/mobile lab operation.

Validates that all prerequisites are in place for running Nanometa Live
without network access, including databases, mappings, genomes, and tools.

Tool location logic:
- nextflow: runs LOCALLY to orchestrate the pipeline. Always required.
- container runtime (docker/singularity/apptainer): runs LOCALLY,
  matched to the pipeline_profile setting. Required for pipeline execution.
- kraken2-inspect: runs LOCALLY during preparation to build the taxonomy
  index from the Kraken2 database. Required for preparation.
- datasets (NCBI CLI): runs LOCALLY to download reference genomes.
  Required for preparation (genome download step).
- makeblastdb: runs LOCALLY to build BLAST databases from downloaded
  genomes. Required for preparation (BLAST DB build step).
- blastn: runs LOCALLY for on-demand validation. Required only when
  blast_validation is enabled in config.
- kraken2, fastp: run INSIDE the Nextflow pipeline containers, NOT on
  the local machine. Not checked here.
"""

import logging
import os
import platform as _platform
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Mount-point prefixes where removable and network volumes appear, per OS.
# Used by _database_on_removable_volume; deliberately a prefix table rather
# than filesystem-type sniffing -- statvfs cannot name the fstype portably,
# and the prefix convention covers the cases operators actually hit (USB
# sticks and network shares auto-mounted by the desktop).
_REMOVABLE_MOUNT_PREFIXES = {
    "Darwin": ("/Volumes",),
    "Linux": ("/media", "/mnt", "/run/media"),
}


def _database_on_removable_volume(db_path: str, system: Optional[str] = None) -> bool:
    """True when ``db_path`` sits under a removable/network mount prefix.

    Kraken2 memory-maps ``hash.k2d`` in place and classification touches it
    in random page-sized reads; on a USB or network volume that access
    pattern is pathological even when sequential throughput is fine
    (measured 2026-08-18: 63 MB/s sequential, 20+ minutes of paging per
    task). Matching is on a path-component boundary so ``/mnt2/db`` does
    not false-positive on ``/mnt``.
    """
    prefixes = _REMOVABLE_MOUNT_PREFIXES.get(system or _platform.system(), ())
    try:
        parts = Path(db_path).resolve().parts
    except OSError:
        parts = Path(db_path).parts
    for prefix in prefixes:
        p = Path(prefix).parts
        if parts[: len(p)] == p:
            return True
    return False


class Severity(str, Enum):
    """Severity level for readiness checks."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class CheckResult:
    """Result of a single readiness check."""
    name: str
    passed: bool
    severity: Severity
    message: str
    details: Optional[str] = None


@dataclass
class ReadinessReport:
    """Aggregated readiness report."""
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True if no critical checks failed."""
        return all(
            c.passed for c in self.checks if c.severity == Severity.CRITICAL
        )

    @property
    def critical_failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == Severity.CRITICAL]

    @property
    def warnings(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == Severity.WARNING]

    def summary(self) -> Dict[str, Any]:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        return {
            "ready": self.ready,
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "critical_failures": len(self.critical_failures),
            "warnings": len(self.warnings),
        }


class ReadinessChecker:
    """Validates prerequisites for offline Nanometa Live operation."""

    def check_readiness(
        self,
        config: Dict[str, Any],
        nanometa_home: Optional[str] = None,
        watchlist_entries: Optional[List[Dict[str, Any]]] = None,
        reload_genomes: bool = False,
    ) -> ReadinessReport:
        """
        Run all readiness checks.

        Args:
            config: Application configuration dict.
            nanometa_home: Path to ~/.nanometa (or equivalent).
            watchlist_entries: Optional snapshot of watchlist entries (dicts with
                ``taxid``/``name``/``enabled``). REQUIRED when this runs in a
                DiskcacheManager background worker, where the WatchlistManager
                singleton is empty: without it the watchlist checks would always
                report "not enabled" even when the operator has enabled entries
                in the main process. When omitted, the singleton is consulted
                (correct for in-process callers).

        Returns:
            ReadinessReport with all check results.
        """
        active_watchlist = self._resolve_active_watchlist(watchlist_entries)

        if nanometa_home is None:
            # Prefer the operator-configured data_dir; the legacy
            # ``~/.nanometa`` fallback only fires when no config has
            # the key set (e.g. unit tests with bare dicts).
            from nanometa_live.core.utils.paths import NanometaPaths
            nanometa_home = str(NanometaPaths.from_config(config).data_dir)
        home = Path(nanometa_home)

        # The genome/BLAST-DB checks below read gm.has_genome/has_blast_db off
        # the in-memory genome-manager singleton. When the genome set on disk
        # just changed in another process (a background import/download/delete),
        # this worker's singleton is stale; reload it -- keyed by the SAME
        # cache_dir the checks use -- so the checks see the current set.
        if reload_genomes:
            try:
                from nanometa_live.core.utils.genome_manager import (
                genome_cache_taxid, get_genome_manager,
            )
                get_genome_manager(
                    config.get("genome_cache_dir") or str(home)
                ).reload_metadata()
            except Exception as e:
                logger.debug(f"genome-manager reload before readiness skipped: {e}")

        report = ReadinessReport()

        # === Data checks (critical) ===
        report.checks.append(self._check_kraken_db(config))
        report.checks.append(self._check_kraken_db_location(config))
        report.checks.append(self._check_db_index(config, home))
        report.checks.append(self._check_taxid_mappings(config, home, active_watchlist))

        # === Pipeline execution tools (critical) ===
        # Nextflow runs locally to orchestrate the pipeline
        report.checks.append(self._check_tool(
            "nextflow", Severity.CRITICAL,
            purpose="pipeline orchestration",
        ))
        # Container runtime must match pipeline_profile setting
        report.checks.append(self._check_container_runtime(config))

        # === Preparation tools (warning) ===
        # These are needed to build indices and download genomes.
        # Not needed at runtime if preparation was done elsewhere
        # (e.g. imported via bundle).
        report.checks.append(self._check_tool(
            "kraken2-inspect", Severity.WARNING,
            purpose="building taxonomy index from Kraken2 database",
        ))
        report.checks.append(self._check_tool(
            "datasets", Severity.WARNING,
            purpose="downloading reference genomes from NCBI",
        ))
        report.checks.append(self._check_tool(
            "makeblastdb", Severity.WARNING,
            purpose="building BLAST databases from genomes",
        ))

        # === Conditional tools ===
        # blastn is only needed when BLAST validation is enabled
        blast_enabled = config.get("blast_validation", False)
        if isinstance(blast_enabled, str):
            blast_enabled = blast_enabled.lower() in ("true", "yes", "1")
        if blast_enabled:
            report.checks.append(self._check_tool(
                "blastn", Severity.WARNING,
                purpose="on-demand read validation",
            ))

        # minimap2 is only needed when validation_method includes minimap2
        validation_method = config.get("validation_method", "")
        if validation_method in ("minimap2", "both"):
            report.checks.append(self._check_tool(
                "minimap2", Severity.WARNING,
                purpose="coverage validation",
            ))

        # === Input/output checks (warning) ===
        report.checks.append(self._check_input_directory(config))
        report.checks.append(self._check_input_read_length(config))
        report.checks.append(self._check_output_directory(config))
        report.checks.append(self._check_disk_space(config))
        report.checks.append(self._check_cache_disk_space(config))

        # === Data completeness (warning) ===
        report.checks.append(self._check_watchlist_active(config, active_watchlist))
        report.checks.append(self._check_watchlist_genomes(config, home, active_watchlist))
        report.checks.append(self._check_blast_dbs(config, home, active_watchlist))

        # === Informational ===
        report.checks.append(self._check_nextflow_version())
        report.checks.append(self._check_nextflow_plugins(config))
        report.checks.append(self._check_offline_conda_cache(config))
        report.checks.extend(self._check_network_connectivity(config))
        report.checks.append(self._check_taxonomy_cache(home))
        report.checks.append(self._check_pipeline_cached(config))

        return report

    # -- Data checks --

    def _check_kraken_db(self, config: Dict[str, Any]) -> CheckResult:
        db_path = config.get("kraken_db", "")
        if not db_path:
            return CheckResult(
                "Kraken2 Database", False, Severity.CRITICAL,
                "No Kraken2 database path configured"
            )
        # Single source of truth for the required-files list. See
        # core.utils.kraken_utils.check_kraken_db.
        from nanometa_live.core.utils.kraken_utils import check_kraken_db
        valid, missing = check_kraken_db(db_path)
        p = Path(db_path)
        if not valid:
            if not p.is_dir():
                return CheckResult(
                    "Kraken2 Database", False, Severity.CRITICAL,
                    f"Database directory not found: {db_path}",
                    details=str(p)
                )
            return CheckResult(
                "Kraken2 Database", False, Severity.CRITICAL,
                f"Database missing files: {', '.join(missing)}",
                details=str(p)
            )
        return CheckResult(
            "Kraken2 Database", True, Severity.CRITICAL,
            f"Valid database at {p.name}"
        )

    def _check_kraken_db_location(self, config: Dict[str, Any]) -> CheckResult:
        """Warn when the database sits on a removable or network volume.

        A WARNING, not a blocker: the run works, just slowly. Unset or
        missing paths pass silently here -- they are the Kraken2 Database
        check's finding, and double-reporting one problem teaches operators
        to skim the list.
        """
        db_path = config.get("kraken_db", "")
        if not db_path or not Path(db_path).is_dir():
            return CheckResult(
                "Database Location", True, Severity.INFO,
                "Not applicable (no database directory)"
            )
        if _database_on_removable_volume(db_path):
            return CheckResult(
                "Database Location", False, Severity.WARNING,
                "Database is on a removable or network volume "
                f"({db_path}). Kraken2 memory-maps it in place, and random "
                "page access over USB/network is very slow. Copy the "
                "database to local disk and point kraken_db there — cached "
                "indexes and mappings remain valid (content-derived hash).",
                details=str(db_path)
            )
        return CheckResult(
            "Database Location", True, Severity.WARNING,
            "Database is on local storage"
        )

    def _check_db_index(self, config: Dict[str, Any], home: Path) -> CheckResult:
        db_path = config.get("kraken_db", "")
        if not db_path:
            return CheckResult(
                "DB Taxonomy Index", False, Severity.CRITICAL,
                "No database configured"
            )
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
            db_hash = get_database_hash(db_path)
        except (ImportError, AttributeError, OSError, ValueError) as e:
            return CheckResult(
                "DB Taxonomy Index", False, Severity.CRITICAL,
                f"Could not compute database hash: {e}"
            )
        if not db_hash:
            return CheckResult(
                "DB Taxonomy Index", False, Severity.CRITICAL,
                "Could not compute database hash"
            )
        from nanometa_live.core.utils.paths import get_mappings_dir_from_env
        mappings_dir = Path(get_mappings_dir_from_env())
        index_file_json = mappings_dir / f"{db_hash}_index.json"
        index_file_pkl = mappings_dir / f"{db_hash}_index.pkl"
        if index_file_json.exists() or index_file_pkl.exists():
            return CheckResult(
                "DB Taxonomy Index", True, Severity.CRITICAL,
                "Taxonomy index found"
            )
        return CheckResult(
            "DB Taxonomy Index", False, Severity.CRITICAL,
            "Taxonomy index not built (run preparation)",
            details=f"expected at {index_file_json} or {index_file_pkl}"
        )

    def _check_taxid_mappings(
        self, config: Dict[str, Any], home: Path,
        active_watchlist: Optional[List[Dict[str, Any]]] = None,
    ) -> CheckResult:
        db_path = config.get("kraken_db", "")
        if not db_path:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                "No database configured"
            )
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
            db_hash = get_database_hash(db_path)
        except (ImportError, AttributeError, OSError, ValueError) as e:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                f"Could not compute database hash: {e}"
            )
        if not db_hash:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                "Could not compute database hash"
            )
        from nanometa_live.core.utils.paths import get_mappings_dir_from_env
        mapping_file = Path(get_mappings_dir_from_env()) / f"{db_hash}_mappings.json"
        if mapping_file.exists():
            # Staleness: a mapping file generated before the operator added
            # entries passed as green, so newly added organisms were never
            # resolved against the database (2026-08-17 reaudit, G9). Warn
            # -- not fail -- when active entries are missing from the file;
            # operator-declared db_taxids do not need a scan.
            missing = self._count_unmapped_active(
                mapping_file, active_watchlist
            )
            if missing:
                return CheckResult(
                    "Taxid Mappings", False, Severity.WARNING,
                    f"Taxid mappings found, but {missing} active watchlist "
                    f"entr{'y is' if missing == 1 else 'ies are'} not in "
                    f"them - run Scan Database to refresh",
                )
            return CheckResult(
                "Taxid Mappings", True, Severity.CRITICAL,
                "Taxid mappings found"
            )
        return CheckResult(
            "Taxid Mappings", False, Severity.CRITICAL,
            "Taxid mappings not generated (run preparation)"
        )


    @staticmethod
    def _count_unmapped_active(
        mapping_file: Path,
        active_watchlist: Optional[List[Dict[str, Any]]],
    ) -> int:
        """Active entries absent from the mapping file (0 when unknowable)."""
        if not active_watchlist:
            return 0
        try:
            import json as _json
            with open(mapping_file) as fh:
                data = _json.load(fh)
            mapped = {
                int(m.get("ncbi_taxid", 0))
                for m in (data.get("mappings") or [])
                if m.get("ncbi_taxid")
            }
        except (OSError, ValueError):
            return 0
        missing = 0
        for e in active_watchlist:
            taxid = e.get("taxid") or 0
            if e.get("db_taxid"):
                continue  # operator-declared; no scan needed
            if taxid and int(taxid) not in mapped:
                missing += 1
        return missing

    # -- Tool checks --

    def _check_tool(
        self,
        name: str,
        severity: Severity,
        purpose: str = "",
    ) -> CheckResult:
        path = shutil.which(name)
        label = f"Tool: {name}"
        purpose_suffix = f" (needed for {purpose})" if purpose else ""
        if path:
            return CheckResult(
                label, True, severity,
                f"Found at {path}"
            )
        return CheckResult(
            label, False, severity,
            f"{name} not found in PATH{purpose_suffix}"
        )

    def _check_container_runtime(self, config: Dict[str, Any]) -> CheckResult:
        """Check container runtime matching the pipeline_profile setting."""
        profile = config.get("pipeline_profile", "conda")
        # First component decides the engine; "conda,server" is a supported
        # comma-form (extra components are plain Nextflow profiles).
        profile = str(profile).split(",", 1)[0].strip()

        if profile == "standard":
            return CheckResult(
                "Container Runtime", True, Severity.INFO,
                "Local profile: no container runtime required"
            )

        if profile == "conda":
            path = shutil.which("conda")
            if path:
                return CheckResult(
                    "Container Runtime", True, Severity.CRITICAL,
                    f"conda available at {path} (profile: conda)"
                )
            return CheckResult(
                "Container Runtime", False, Severity.CRITICAL,
                "conda not found in PATH (required by pipeline_profile: conda)"
            )

        if profile in ("singularity", "apptainer"):
            # Accept either singularity or apptainer
            for name in ("singularity", "apptainer"):
                path = shutil.which(name)
                if path:
                    return CheckResult(
                        "Container Runtime", True, Severity.CRITICAL,
                        f"{name} available at {path} (profile: {profile})"
                    )
            return CheckResult(
                "Container Runtime", False, Severity.CRITICAL,
                f"Neither singularity nor apptainer found in PATH "
                f"(required by pipeline_profile: {profile})"
            )

        # Default: docker
        path = shutil.which("docker")
        if not path:
            return CheckResult(
                "Container Runtime", False, Severity.CRITICAL,
                f"docker not found in PATH (required by pipeline_profile: {profile})"
            )
        # Verify Docker daemon is running (not just binary installed)
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                return CheckResult(
                    "Container Runtime", False, Severity.CRITICAL,
                    "Docker installed but daemon is not running (start Docker Desktop)",
                )
        except (subprocess.TimeoutExpired, OSError):
            return CheckResult(
                "Container Runtime", False, Severity.CRITICAL,
                "Docker installed but daemon check timed out",
            )
        return CheckResult(
            "Container Runtime", True, Severity.CRITICAL,
            f"docker running (profile: {profile})"
        )

    def _check_nextflow_plugins(self, config: Dict[str, Any]) -> CheckResult:
        """Offline: the bundled Nextflow plugins must be present.

        An empty or missing plugins dir makes Nextflow fall back to the
        online plugin registry, which fails air-gapped. Online this is
        informational -- Nextflow can fetch plugins itself.
        """
        if not config.get("offline_mode"):
            return CheckResult(
                "Nextflow Plugins", True, Severity.INFO,
                "Online mode: Nextflow can fetch plugins from the registry",
            )
        plugins_dir = str(config.get("nxf_plugins_dir", "") or "")
        if plugins_dir:
            p = Path(plugins_dir)
            if p.is_dir() and any(child.is_dir() for child in p.iterdir()):
                return CheckResult(
                    "Nextflow Plugins", True, Severity.CRITICAL,
                    f"Bundled plugins present at {plugins_dir}",
                )
            return CheckResult(
                "Nextflow Plugins", False, Severity.CRITICAL,
                f"nxf_plugins_dir '{plugins_dir}' is missing or empty; "
                "offline, Nextflow will probe the online plugin registry "
                "and fail. Re-import the bundle or restore the plugins dir.",
            )
        return CheckResult(
            "Nextflow Plugins", False, Severity.CRITICAL,
            "offline_mode is on but no nxf_plugins_dir is configured; "
            "Nextflow will probe the online plugin registry and fail. "
            "Import a deployment bundle (which wires the plugins) or set "
            "nxf_plugins_dir in config.yaml.",
        )

    def _check_offline_conda_cache(self, config: Dict[str, Any]) -> CheckResult:
        """Offline + conda profile: the pre-warmed env cache must exist.

        Without it every pipeline process tries to solve its environment
        from bioconda over the network -- the run fails cryptically on the
        air-gapped machine. Mirrors the launch-time hard refusal in
        ``NextflowManager._build_nextflow_env``.
        """
        profile = str(config.get("pipeline_profile", "conda"))
        engine = profile.split(",", 1)[0].strip()
        if not config.get("offline_mode") or engine != "conda":
            return CheckResult(
                "Conda Cache", True, Severity.INFO,
                "Not applicable (online mode or non-conda profile)",
            )
        cachedir = str(config.get("nxf_conda_cachedir", "") or "")
        if not cachedir:
            return CheckResult(
                "Conda Cache", False, Severity.WARNING,
                "offline_mode with the conda profile but no pre-warmed env "
                "cache is configured (nxf_conda_cachedir); the first run "
                "will need network access to build environments. Import a "
                "bundle exported with pre-warmed conda envs.",
            )
        from nanometa_live.core.workflow.conda_cache_utils import (
            list_complete_env_dirs,
        )

        cache = Path(cachedir)
        envs = list_complete_env_dirs(cache)
        if envs:
            return CheckResult(
                "Conda Cache", True, Severity.CRITICAL,
                f"{len(envs)} pre-warmed conda env(s) at {cachedir}",
            )
        return CheckResult(
            "Conda Cache", False, Severity.CRITICAL,
            f"nxf_conda_cachedir '{cachedir}' is missing or holds no "
            "complete env; offline, every process would try a network "
            "solve. Re-import the deployment bundle.",
        )

    # -- Input/output checks --

    def _check_input_directory(self, config: Dict[str, Any]) -> CheckResult:
        """Check that the configured input directory exists and has expected content."""
        nanopore_dir = config.get("nanopore_output_directory") or config.get("nanopore_dir", "")
        if not nanopore_dir:
            return CheckResult(
                "Input Directory", False, Severity.WARNING,
                "No input directory configured"
            )
        p = Path(nanopore_dir)
        if not p.exists():
            return CheckResult(
                "Input Directory", False, Severity.WARNING,
                f"Input directory does not exist: {p}",
                details="This is expected if the sequencing run has not started yet"
            )
        # Look for FASTQ files or per-sample subdirectories. The
        # canonical detector lives in core.utils.auto_detect; using it
        # here keeps the readiness panel in sync with the validation
        # error messages and the samplesheet generator.
        from nanometa_live.core.utils.auto_detect import find_sample_subdirs
        fastq_files = list(p.glob("*.fastq*"))
        sample_dirs = find_sample_subdirs(str(p))
        if fastq_files or sample_dirs:
            content = []
            if sample_dirs:
                content.append(f"{len(sample_dirs)} sample dir(s)")
            if fastq_files:
                content.append(f"{len(fastq_files)} FASTQ file(s)")
            return CheckResult(
                "Input Directory", True, Severity.WARNING,
                f"Found {', '.join(content)} in {p.name}"
            )
        return CheckResult(
            "Input Directory", False, Severity.WARNING,
            f"No FASTQ files or per-sample directories found in {p.name}",
            details="This is expected if the sequencing run has not started yet"
        )

    def _check_input_read_length(self, config: Dict[str, Any]) -> CheckResult:
        """Warn when the input reads are shorter than the QC length filter.

        The filter defaults to 1000 bp and discards ALL reads of a short-
        amplicon run: chopper exits 0 on total loss and the run completes
        green with every panel blank, so this pre-flight sample is the only
        warning the operator gets. Median-based: a warning fires when more
        than half of the sampled reads would be discarded.
        """
        name = "Input Read Length"
        qc_tool = str(config.get("qc_tool") or "chopper").lower()
        if qc_tool == "fastp":
            return CheckResult(
                name, True, Severity.WARNING,
                "fastp QC applies no long-read length floor",
            )

        # Effective floor: the lower of the configured chopper/filtlong
        # values (which of the two runs depends on the pipeline QC profile;
        # taking the min avoids false alarms at the cost of missing the
        # mixed case where only the inactive tool was lowered).
        floors: Dict[str, int] = {}
        for key in ("chopper_minlength", "filtlong_min_length"):
            try:
                floors[key] = int(config.get(key))
            except (TypeError, ValueError):
                continue
        if not floors:
            floors = {"chopper_minlength": 1000}
        floor_key, floor = min(floors.items(), key=lambda kv: kv[1])
        if floor <= 1:
            return CheckResult(
                name, True, Severity.WARNING,
                "Length filter is disabled (minimum length 1 bp or lower)",
            )

        input_dir = config.get("nanopore_output_directory") or config.get("nanopore_dir", "")
        if not input_dir or not Path(input_dir).is_dir():
            return CheckResult(
                name, True, Severity.WARNING,
                "No input directory to sample yet",
                details="This is expected if the sequencing run has not started yet",
            )

        from nanometa_live.core.utils.read_length_probe import median_input_read_length
        median, n_reads, example = median_input_read_length(input_dir)
        if median is None:
            return CheckResult(
                name, True, Severity.WARNING,
                "No input FASTQ to sample yet",
                details="This is expected if the sequencing run has not started yet",
            )
        if median < floor:
            return CheckResult(
                name, False, Severity.WARNING,
                f"Median input read length is ~{median} bp ({n_reads} reads "
                f"sampled from {example}), below the length filter "
                f"({floor_key} = {floor}). Most reads would be discarded "
                "before classification.",
                details="For amplicon or other short-read protocols, lower the "
                        "filter in Configuration -> Read Filtering (e.g. "
                        "100-300 bp).",
            )
        return CheckResult(
            name, True, Severity.WARNING,
            f"Median input read length ~{median:,} bp clears the length "
            f"filter ({floor} bp)",
        )

    def _check_output_directory(self, config: Dict[str, Any]) -> CheckResult:
        """Check that the configured output directory exists or can be created."""
        main_dir = config.get("results_output_directory") or config.get("main_dir", "")
        if not main_dir:
            return CheckResult(
                "Output Directory", False, Severity.WARNING,
                "No output directory configured"
            )
        p = Path(main_dir)
        if p.exists():
            if os.access(str(p), os.W_OK):
                return CheckResult(
                    "Output Directory", True, Severity.WARNING,
                    f"Output directory exists: {p.name}"
                )
            return CheckResult(
                "Output Directory", False, Severity.WARNING,
                f"Output directory not writable: {p}",
            )
        # Check if the parent exists (directory can be created)
        parent = p.parent
        if parent.exists() and os.access(str(parent), os.W_OK):
            return CheckResult(
                "Output Directory", True, Severity.WARNING,
                f"Output directory will be created: {p.name}",
            )
        return CheckResult(
            "Output Directory", False, Severity.WARNING,
            f"Cannot create output directory (parent does not exist): {p}",
        )

    def _check_disk_space(self, config: Dict[str, Any]) -> CheckResult:
        """Check available disk space in the output directory."""
        main_dir = config.get("results_output_directory") or config.get("main_dir", "")
        if not main_dir:
            return CheckResult(
                "Disk Space", False, Severity.WARNING,
                "No output directory configured"
            )
        p = Path(main_dir)
        # Use the directory itself or its closest existing parent
        check_path = p
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent
        if not check_path.exists():
            return CheckResult(
                "Disk Space", False, Severity.WARNING,
                "Could not determine disk space (path does not exist)"
            )
        try:
            usage = shutil.disk_usage(str(check_path))
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 5:
                # Round 3: below the hard floor the check FAILS and gates
                # Start. A run launched onto a nearly full volume hits
                # ENOSPC mid-run, which truncates reports -- the compound
                # case where the dashboard then serves last-good data
                # behind a staleness badge. The explicit env override is
                # for operators who know their volume.
                allow = os.environ.get("NANOMETA_ALLOW_LOW_DISK") == "1"
                return CheckResult(
                    "Disk Space", False,
                    Severity.WARNING if allow else Severity.CRITICAL,
                    f"Only {free_gb:.1f} GB free in the output volume -- "
                    "below the 5 GB floor for a run",
                    details=(
                        "Free space or choose another results folder. To "
                        "start anyway, export NANOMETA_ALLOW_LOW_DISK=1."
                    ),
                )
            if free_gb < 10:
                return CheckResult(
                    "Disk Space", False, Severity.WARNING,
                    f"Low disk space: {free_gb:.1f} GB free in output directory",
                    details="At least 10 GB recommended for analysis output"
                )
            return CheckResult(
                "Disk Space", True, Severity.WARNING,
                f"{free_gb:.1f} GB free in output directory"
            )
        except OSError as e:
            return CheckResult(
                "Disk Space", False, Severity.WARNING,
                f"Could not check disk space: {e}"
            )

    def _check_cache_disk_space(self, config: Dict[str, Any]) -> CheckResult:
        """Free space on the app-data volume (diskcache, logs, genomes).

        Round 3: a full data volume makes every background callback fail
        in ways the running=/progress= machinery cannot report (the
        DiskcacheManager cannot store results). WARNING, not CRITICAL --
        the run itself writes to the results volume.
        """
        try:
            from nanometa_live.core.utils.paths import NanometaPaths
            data_dir = str(NanometaPaths.from_config(config or {}).data_dir)
            usage = shutil.disk_usage(data_dir)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 2:
                return CheckResult(
                    "App Data Disk Space", False, Severity.WARNING,
                    f"Only {free_gb:.1f} GB free on the app-data volume "
                    f"({data_dir}) -- background operations (export, "
                    "import, rescans) may fail",
                )
            return CheckResult(
                "App Data Disk Space", True, Severity.WARNING,
                f"{free_gb:.1f} GB free on the app-data volume",
            )
        except (OSError, Exception) as e:
            return CheckResult(
                "App Data Disk Space", False, Severity.WARNING,
                f"Could not check app-data disk space: {e}",
            )

    # -- Data completeness checks --

    def _resolve_active_watchlist(
        self, watchlist_entries: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Return enabled watchlist entries as ``[{name, taxid}]`` dicts.

        Prefers the injected snapshot (so the watchlist checks work in a
        DiskcacheManager background worker, where the WatchlistManager singleton
        is empty); falls back to the singleton for in-process callers. Returns
        ``None`` only when neither source is available -- the checks treat that
        as "could not determine" and use their directory/config fallback, which
        is distinct from an empty list ("watchlist loaded but nothing enabled").
        """
        if watchlist_entries is not None:
            resolved: List[Dict[str, Any]] = []
            for e in watchlist_entries:
                if not e.get("enabled", True):
                    continue
                taxid = e.get("taxid")
                if not taxid:
                    continue
                resolved.append({"name": e.get("name", f"taxid {taxid}"), "taxid": taxid})
            return resolved
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            wm = get_watchlist_manager()
            active = wm.get_active_entries()
            return [
                {"name": v.name, "taxid": v.taxid}
                for v in active.values() if v.taxid
            ]
        except (ImportError, AttributeError, OSError):
            return None

    def _check_watchlist_active(
        self, config: Dict[str, Any],
        active_entries: Optional[List[Dict[str, Any]]],
    ) -> CheckResult:
        """Check whether at least one watchlist entry is enabled for screening."""
        if active_entries is not None:
            if active_entries:
                return CheckResult(
                    "Watchlist Active", True, Severity.WARNING,
                    f"{len(active_entries)} pathogen(s) enabled for screening"
                )
            return CheckResult(
                "Watchlist Active", False, Severity.WARNING,
                "No watchlist enabled - enable pathogens in the Watchlist & Preparation tab"
            )
        # Could not determine from snapshot/singleton -- fall back to config.
        #
        # This branch read ``wl.get("enabled_watchlists")``, which the app never
        # writes: WatchlistManager._load_config_locked reads "enabled",
        # "builtin", "custom", "custom_files" and "overrides". So it was dead,
        # and every undeterminable case fell through to "No watchlist enabled".
        #
        # That is the safe direction -- it under-claims rather than over-claims
        # -- but it is still wrong, and it fires exactly when the singleton is
        # empty, which is the documented background-worker case. Telling an
        # operator to go enable pathogens they have already enabled trains them
        # to ignore the readiness panel.
        wl = config.get("watchlist", {})
        if isinstance(wl, dict) and wl.get("enabled", True) and (
            wl.get("builtin") or wl.get("custom") or wl.get("custom_files")
        ):
            return CheckResult(
                "Watchlist Active", True, Severity.WARNING,
                "Watchlist configured (not yet loaded)"
            )
        return CheckResult(
            "Watchlist Active", False, Severity.WARNING,
            "No watchlist enabled - enable pathogens in the Watchlist & Preparation tab"
        )

    def _check_watchlist_genomes(
        self, config: Dict[str, Any], home: Path,
        active_entries: Optional[List[Dict[str, Any]]],
    ) -> CheckResult:
        try:
            from nanometa_live.core.utils.genome_manager import (
                genome_cache_taxid, get_genome_manager,
            )
            gm = get_genome_manager(config.get("genome_cache_dir") or str(home))
            if active_entries is None:
                raise AttributeError("watchlist unavailable")
            if not active_entries:
                return CheckResult(
                    "Watchlist Genomes", False, Severity.WARNING,
                    "No enabled watchlist entries — enable pathogens in the Watchlist & Preparation tab"
                )
            # Genomes are cached under the DATABASE taxid; keying on the
            # entry taxid reported every Bioshield genome missing.
            missing = [e["name"] for e in active_entries
                       if genome_cache_taxid(e)
                       and not gm.has_genome(genome_cache_taxid(e))]
            total = sum(1 for e in active_entries if genome_cache_taxid(e))
            have = total - len(missing)
            if not missing:
                return CheckResult(
                    "Watchlist Genomes", True, Severity.WARNING,
                    f"All {total} enabled entries have genomes"
                )
            names_preview = ", ".join(missing[:5])
            suffix = f" (+{len(missing)-5} more)" if len(missing) > 5 else ""
            return CheckResult(
                "Watchlist Genomes", False, Severity.WARNING,
                f"{have}/{total} enabled entries have genomes",
                details=f"Missing: {names_preview}{suffix}"
            )
        except (ImportError, AttributeError, OSError) as e:
            logger.warning(f"Could not check watchlist genomes: {e}")
            # Fallback: just check directory
            genomes_dir = home / "genomes"
            fasta_files = list(genomes_dir.glob("*.fasta")) if genomes_dir.exists() else []
            if fasta_files:
                return CheckResult(
                    "Watchlist Genomes", True, Severity.WARNING,
                    f"{len(fasta_files)} genome(s) downloaded (could not check watchlist)"
                )
            return CheckResult(
                "Watchlist Genomes", False, Severity.WARNING,
                "No reference genomes downloaded"
            )

    def _check_blast_dbs(
        self, config: Dict[str, Any], home: Path,
        active_entries: Optional[List[Dict[str, Any]]],
    ) -> CheckResult:
        blast_enabled = config.get("blast_validation", False)
        if isinstance(blast_enabled, str):
            blast_enabled = blast_enabled.lower() in ("true", "yes", "1")
        if not blast_enabled:
            return CheckResult(
                "BLAST Databases", True, Severity.INFO,
                "BLAST validation not enabled"
            )
        try:
            from nanometa_live.core.utils.genome_manager import (
                genome_cache_taxid, get_genome_manager,
            )
            gm = get_genome_manager(config.get("genome_cache_dir") or str(home))
            if active_entries is None:
                raise AttributeError("watchlist unavailable")
            if not active_entries:
                return CheckResult(
                    "BLAST Databases", False, Severity.WARNING,
                    "No enabled watchlist entries — enable pathogens in the Watchlist & Preparation tab"
                )
            missing = [e["name"] for e in active_entries
                       if genome_cache_taxid(e)
                       and not gm.has_blast_db(genome_cache_taxid(e))]
            total = sum(1 for e in active_entries if genome_cache_taxid(e))
            have = total - len(missing)
            if not missing:
                return CheckResult(
                    "BLAST Databases", True, Severity.WARNING,
                    f"All {total} enabled entries have BLAST databases"
                )
            names_preview = ", ".join(missing[:5])
            suffix = f" (+{len(missing)-5} more)" if len(missing) > 5 else ""
            return CheckResult(
                "BLAST Databases", False, Severity.WARNING,
                f"{have}/{total} enabled entries have BLAST databases",
                details=f"Missing: {names_preview}{suffix}"
            )
        except (ImportError, AttributeError, OSError) as e:
            logger.warning(f"Could not check BLAST databases: {e}")
            blast_dir = home / "blast"
            nhr_files = list(blast_dir.glob("*.nhr")) if blast_dir.exists() else []
            if nhr_files:
                return CheckResult(
                    "BLAST Databases", True, Severity.WARNING,
                    f"{len(nhr_files)} BLAST database(s) built"
                )
            return CheckResult(
                "BLAST Databases", False, Severity.WARNING,
                "No BLAST databases built"
            )

    # -- Informational checks --

    def _check_nextflow_version(self) -> CheckResult:
        """Check Nextflow against the real toolchain floor.

        nanometanf's manifest floors at ``_NEXTFLOW_MIN_VERSION`` (26.04.0,
        also recorded in every bundle's ``min_versions``). The check used to
        accept anything >= 23.0, so a field machine on 24.x got a green
        checklist and failed at Start Analysis (2026-08-27 audit, GUI
        finding 7).
        """
        from nanometa_live.core.workflow.bundle_manager import (
            _NEXTFLOW_MIN_VERSION,
        )

        floor = tuple(int(p) for p in _NEXTFLOW_MIN_VERSION.split(".")[:2])
        floor_str = _NEXTFLOW_MIN_VERSION
        try:
            result = subprocess.run(
                ["nextflow", "-version"],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout + result.stderr
            # Nextflow version output typically contains a line like
            # "nextflow version 26.04.6.6018"
            import re
            match = re.search(r"version\s+(\d+)\.(\d+)", output)
            if match:
                major = int(match.group(1))
                minor = int(match.group(2))
                version_str = f"{major}.{minor}"
                if (major, minor) >= floor:
                    return CheckResult(
                        "Nextflow Version", True, Severity.INFO,
                        f"Nextflow {version_str} (>= {floor_str})",
                    )
                return CheckResult(
                    "Nextflow Version", False, Severity.CRITICAL,
                    f"Nextflow {version_str} found but nanometanf requires "
                    f">= {floor_str}; the run will refuse to start. Update "
                    "the nf-core conda environment.",
                )
            return CheckResult(
                "Nextflow Version", False, Severity.WARNING,
                "Could not parse Nextflow version from output",
            )
        except FileNotFoundError:
            return CheckResult(
                "Nextflow Version", False, Severity.WARNING,
                "Nextflow not found (checked separately in tool checks)",
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                PermissionError, OSError):
            return CheckResult(
                "Nextflow Version", False, Severity.WARNING,
                "Could not determine Nextflow version",
            )

    def _check_network_connectivity(self, config: Dict[str, Any] | None = None) -> List[CheckResult]:
        """Test network connectivity to NCBI and GTDB APIs.

        Skipped when ``config['offline_mode']`` is true: in offline mode the
        probe blocks the readiness panel for the full timeout per endpoint
        and surfaces a warning operators are trained to treat as actionable.
        """
        cfg = config or {}
        if cfg.get("offline_mode"):
            return [CheckResult(
                "Network", True, Severity.INFO,
                "Offline mode -- network probe skipped",
            )]

        # An explicit ``network_check_enabled: false`` disables the probe
        # without switching the whole app to offline mode -- useful on a
        # connected machine where the NCBI/GTDB endpoints are firewalled and
        # the ~5s-per-endpoint timeout would otherwise stall the panel. The
        # key is absent by default, so the probe runs unless opted out.
        if cfg.get("network_check_enabled") is False:
            return [CheckResult(
                "Network", True, Severity.INFO,
                "Network probe disabled by configuration",
            )]

        import urllib.request

        results = []
        endpoints = [
            ("NCBI API", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"),
            ("GTDB API", "https://api.gtdb.ecogenomic.org/"),
        ]
        for name, url in endpoints:
            try:
                urllib.request.urlopen(url, timeout=5)  # noqa: S310
                results.append(CheckResult(
                    name, True, Severity.INFO,
                    f"{name} reachable",
                ))
            except Exception as e:
                # Connectivity probe: any failure (URLError, HTTPError, socket
                # error, SSL issue, timeout, proxy misconfiguration, even a
                # surprising upstream exception) means "unreachable" for the
                # operator. Keep broad catch so the readiness report stays
                # useful regardless of why the probe failed.
                results.append(CheckResult(
                    name, False, Severity.WARNING,
                    f"{name} unreachable: {e}. Genome downloads may fail.",
                ))
        return results

    def _check_taxonomy_cache(self, home: Path) -> CheckResult:
        cache_dir = home / "cache"
        if not cache_dir.exists():
            return CheckResult(
                "Taxonomy Cache", False, Severity.INFO,
                "No taxonomy cache directory"
            )
        cache_files = list(cache_dir.glob("*.json"))
        if cache_files:
            return CheckResult(
                "Taxonomy Cache", True, Severity.INFO,
                f"{len(cache_files)} cached entries"
            )
        return CheckResult(
            "Taxonomy Cache", False, Severity.INFO,
            "Taxonomy cache is empty"
        )

    def _check_pipeline_cached(self, config: Dict[str, Any]) -> CheckResult:
        source = config.get("pipeline_source", "")
        if not source:
            return CheckResult(
                "Pipeline Source", False, Severity.CRITICAL,
                "No pipeline_source configured. Set pipeline_source in "
                "config.yaml to 'remote:dev' or a local path (e.g. "
                "'local:/path/to/nanometanf'); otherwise the pipeline "
                "cannot be launched.",
            )
        # Strip "local:" prefix if present (used by nextflow_manager convention)
        normalized = source
        if normalized.startswith("local:"):
            normalized = normalized[len("local:"):]
        # Local path (doesn't look like a remote URI)
        if not normalized.startswith(("http://", "https://", "remote")):
            p = Path(normalized)
            if p.exists():
                if (p / "main.nf").exists():
                    return CheckResult(
                        "Pipeline Source", True, Severity.INFO,
                        f"Local pipeline at {p}",
                    )
                return CheckResult(
                    "Pipeline Source", False, Severity.CRITICAL,
                    f"Local pipeline directory exists at {p} but is missing "
                    f"main.nf; this does not look like a Nextflow pipeline "
                    f"checkout.",
                )
            return CheckResult(
                "Pipeline Source", False, Severity.CRITICAL,
                f"Local pipeline path does not exist: {p}. Set "
                f"pipeline_source in config.yaml to a valid local path or "
                f"to a remote spec such as 'remote:dev'.",
            )
        # Remote source: verify it's a recognised form
        if not (normalized.startswith("remote:")
                or normalized in ("master", "main", "dev")):
            return CheckResult(
                "Pipeline Source", False, Severity.WARNING,
                f"Pipeline source '{source}' is not a recognised remote "
                f"form. Expected 'remote:<branch>' (e.g. 'remote:dev').",
            )
        # A remote source cannot be fetched offline, and the launch path
        # (backend_manager.setup) refuses it outright -- so the readiness
        # panel must say so here rather than showing green and letting the
        # operator find out at Start Analysis (2026-08-17 audit, finding G6).
        if config.get("offline_mode"):
            return CheckResult(
                "Pipeline Source", False, Severity.CRITICAL,
                f"Offline mode is enabled but pipeline_source is remote "
                f"({source}). Point pipeline_source at a local nanometanf "
                f"checkout (e.g. the bundle's pipeline_source directory).",
            )
        # Remote source (well-formed): first run will fetch the pipeline
        # from GitHub. Surfaced as INFO rather than silently skipped.
        return CheckResult(
            "Pipeline Source", True, Severity.INFO,
            f"Pipeline source is remote ({source}); requires network "
            f"access on first run.",
        )
