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
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
    ) -> ReadinessReport:
        """
        Run all readiness checks.

        Args:
            config: Application configuration dict.
            nanometa_home: Path to ~/.nanometa (or equivalent).

        Returns:
            ReadinessReport with all check results.
        """
        if nanometa_home is None:
            nanometa_home = os.path.expanduser("~/.nanometa")
        home = Path(nanometa_home)

        report = ReadinessReport()

        # === Data checks (critical) ===
        report.checks.append(self._check_kraken_db(config))
        report.checks.append(self._check_db_index(config, home))
        report.checks.append(self._check_taxid_mappings(config, home))

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

        # === Input/output checks (warning) ===
        report.checks.append(self._check_input_directory(config))
        report.checks.append(self._check_output_directory(config))
        report.checks.append(self._check_disk_space(config))

        # === Data completeness (warning) ===
        report.checks.append(self._check_watchlist_active(config))
        report.checks.append(self._check_watchlist_genomes(config, home))
        report.checks.append(self._check_blast_dbs(config, home))

        # === Informational ===
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
        p = Path(db_path)
        required = ["hash.k2d", "opts.k2d", "taxo.k2d"]
        missing = [f for f in required if not (p / f).exists()]
        if missing:
            return CheckResult(
                "Kraken2 Database", False, Severity.CRITICAL,
                f"Database missing files: {', '.join(missing)}",
                details=str(p)
            )
        return CheckResult(
            "Kraken2 Database", True, Severity.CRITICAL,
            f"Valid database at {p.name}"
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
        except Exception as e:
            return CheckResult(
                "DB Taxonomy Index", False, Severity.CRITICAL,
                f"Could not compute database hash: {e}"
            )
        if not db_hash:
            return CheckResult(
                "DB Taxonomy Index", False, Severity.CRITICAL,
                "Could not compute database hash"
            )
        index_file = home / "mappings" / f"{db_hash}_index.pkl"
        if index_file.exists():
            return CheckResult(
                "DB Taxonomy Index", True, Severity.CRITICAL,
                "Taxonomy index found"
            )
        return CheckResult(
            "DB Taxonomy Index", False, Severity.CRITICAL,
            "Taxonomy index not built (run preparation)",
            details=str(index_file)
        )

    def _check_taxid_mappings(self, config: Dict[str, Any], home: Path) -> CheckResult:
        db_path = config.get("kraken_db", "")
        if not db_path:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                "No database configured"
            )
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
            db_hash = get_database_hash(db_path)
        except Exception as e:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                f"Could not compute database hash: {e}"
            )
        if not db_hash:
            return CheckResult(
                "Taxid Mappings", False, Severity.CRITICAL,
                "Could not compute database hash"
            )
        mapping_file = home / "mappings" / f"{db_hash}_mappings.json"
        if mapping_file.exists():
            return CheckResult(
                "Taxid Mappings", True, Severity.CRITICAL,
                "Taxid mappings found"
            )
        return CheckResult(
            "Taxid Mappings", False, Severity.CRITICAL,
            "Taxid mappings not generated (run preparation)"
        )

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
        profile = config.get("pipeline_profile", "docker")

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
        # Look for FASTQ files or barcode subdirectories
        fastq_files = list(p.glob("*.fastq*"))
        barcode_dirs = [d for d in p.iterdir() if d.is_dir() and d.name.startswith("barcode")]
        if fastq_files or barcode_dirs:
            content = []
            if barcode_dirs:
                content.append(f"{len(barcode_dirs)} barcode dir(s)")
            if fastq_files:
                content.append(f"{len(fastq_files)} FASTQ file(s)")
            return CheckResult(
                "Input Directory", True, Severity.WARNING,
                f"Found {', '.join(content)} in {p.name}"
            )
        return CheckResult(
            "Input Directory", False, Severity.WARNING,
            f"No FASTQ files or barcode directories found in {p.name}",
            details="This is expected if the sequencing run has not started yet"
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

    # -- Data completeness checks --

    def _check_watchlist_active(self, config: Dict[str, Any]) -> CheckResult:
        """Check whether at least one watchlist is enabled for pathogen screening."""
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            wm = get_watchlist_manager()
            active = wm.get_active_entries()
            if active:
                count = len(active)
                return CheckResult(
                    "Watchlist Active", True, Severity.WARNING,
                    f"{count} pathogen(s) enabled for screening"
                )
            return CheckResult(
                "Watchlist Active", False, Severity.WARNING,
                "No watchlist enabled - enable pathogens in the Watchlist tab"
            )
        except Exception:
            # Check config for watchlist section as fallback
            wl = config.get("watchlist", {})
            if isinstance(wl, dict) and wl.get("enabled_watchlists"):
                return CheckResult(
                    "Watchlist Active", True, Severity.WARNING,
                    "Watchlist configured (not yet loaded)"
                )
            return CheckResult(
                "Watchlist Active", False, Severity.WARNING,
                "No watchlist enabled - enable pathogens in the Watchlist tab"
            )

    def _check_watchlist_genomes(self, config: Dict[str, Any], home: Path) -> CheckResult:
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            wm = get_watchlist_manager()
            gm = get_genome_manager(str(home))
            active = wm.get_active_entries()
            if not active:
                return CheckResult(
                    "Watchlist Genomes", False, Severity.WARNING,
                    "No enabled watchlist entries — enable pathogens in the Watchlist tab"
                )
            missing = [e.name for e in active.values()
                       if e.taxid and not gm.has_genome(e.taxid)]
            total = sum(1 for e in active.values() if e.taxid)
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
        except Exception as e:
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

    def _check_blast_dbs(self, config: Dict[str, Any], home: Path) -> CheckResult:
        blast_enabled = config.get("blast_validation", False)
        if isinstance(blast_enabled, str):
            blast_enabled = blast_enabled.lower() in ("true", "yes", "1")
        if not blast_enabled:
            return CheckResult(
                "BLAST Databases", True, Severity.INFO,
                "BLAST validation not enabled"
            )
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            wm = get_watchlist_manager()
            gm = get_genome_manager(str(home))
            active = wm.get_active_entries()
            if not active:
                return CheckResult(
                    "BLAST Databases", False, Severity.WARNING,
                    "No enabled watchlist entries — enable pathogens in the Watchlist tab"
                )
            missing = [e.name for e in active.values()
                       if e.taxid and not gm.has_blast_db(e.taxid)]
            total = sum(1 for e in active.values() if e.taxid)
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
        except Exception as e:
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
                "Pipeline Source", False, Severity.INFO,
                "No pipeline source configured"
            )
        # Strip "local:" prefix if present (used by nextflow_manager convention)
        if source.startswith("local:"):
            source = source[len("local:"):]
        # Local path (doesn't look like a remote URI)
        if not source.startswith(("http://", "https://", "remote")):
            p = Path(source)
            if p.exists():
                return CheckResult(
                    "Pipeline Source", True, Severity.INFO,
                    f"Local pipeline at {p}"
                )
            return CheckResult(
                "Pipeline Source", False, Severity.WARNING,
                f"Local pipeline path does not exist: {p}"
            )
        # Remote source
        return CheckResult(
            "Pipeline Source", False, Severity.INFO,
            "Pipeline source is remote (requires network for first run)"
        )
