"""
Parameter mapping between Nanometa Live and nanometanf.

This module provides functions to convert Nanometa Live configuration parameters
to nanometanf pipeline parameters and Nextflow configuration.

Supported processing modes (set via config["processing_mode"]):
- 'batch': Process existing files. Emits `--input <samplesheet.csv>` by
  default, or `--input_dir <dir>` when config["use_input_dir_mode"] is
  true. `batch` + `sample_handling == "by_barcode"` with no supplied
  samplesheet also auto-enables `--input_dir` so nanometanf's
  INPUT_SCANNER handles layout discovery (Scenario E).
- 'realtime': Live watchPath monitoring via `--realtime_mode true`
  and `--nanopore_output_dir <dir>`.

Callers may also pre-supply `config["input"]` with a path to an existing
samplesheet; it is honoured verbatim and no samplesheet is auto-generated.

The emitted params are validated at the end of create_nextflow_params
to reject mutually exclusive input sources (input, input_dir,
nanopore_output_dir) before the pipeline starts.
"""

import os
import glob
import csv
import platform
import re
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List

from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
from nanometa_live.core.utils.genome_manager import get_genome_manager


def detect_input_mode(input_dir: str) -> str:
    """
    Auto-detect the appropriate input mode based on directory structure.

    Args:
        input_dir: Path to the input directory

    Returns:
        Input mode: 'batch', 'barcode', or 'realtime'

    Detection logic:
    - If directory contains barcode* subdirectories with FASTQ files: 'barcode'
    - If directory contains FASTQ files directly: 'batch'
    - Otherwise: 'realtime' (for watchPath monitoring)
    """
    if not os.path.isdir(input_dir):
        logging.warning(f"Input directory does not exist: {input_dir}")
        return "realtime"

    # Check for barcode subdirectories
    barcode_dirs = glob.glob(os.path.join(input_dir, "barcode*"))
    if barcode_dirs:
        # Verify at least one barcode dir has FASTQ files
        for bdir in barcode_dirs:
            if os.path.isdir(bdir):
                fastq_files = glob.glob(os.path.join(bdir, "*.fastq*"))
                if fastq_files:
                    logging.info(f"Detected barcode mode: found barcode directories with FASTQ files")
                    return "barcode"

    # Check for direct FASTQ files (single sample / batch mode)
    fastq_files = glob.glob(os.path.join(input_dir, "*.fastq*"))
    if fastq_files:
        logging.info(f"Detected batch mode: found {len(fastq_files)} FASTQ files directly in directory")
        return "batch"

    # Default to realtime for empty or monitoring directories
    logging.info("Defaulting to realtime mode (no existing FASTQ files found)")
    return "realtime"


def validate_sample_handling_layout(sample_handling: str, input_dir: str) -> None:
    """
    Validate that `sample_handling` matches the actual directory layout.

    The `per_file` and `single_sample` modes expect FASTQ files directly in
    `input_dir`; the `by_barcode` mode expects `barcode*` subdirectories. A
    common misconfiguration is selecting `per_file` but pointing at a barcoded
    layout: the pipeline then groups per-file samples into a single sample by
    filename stem, silently discarding barcode identity.

    Args:
        sample_handling: One of 'per_file', 'single_sample', 'by_barcode'.
        input_dir: Path to the Nanopore output directory.

    Raises:
        ValueError: If the layout contradicts the declared handling mode.
    """
    if not os.path.isdir(input_dir):
        # Other code paths already raise a clearer error for a missing input
        # directory; don't double-warn here.
        return

    barcode_dirs = [
        d for d in glob.glob(os.path.join(input_dir, "barcode*"))
        if os.path.isdir(d)
    ]
    has_barcode_subdirs = any(
        glob.glob(os.path.join(d, "*.fastq*")) for d in barcode_dirs
    )

    if sample_handling in ("per_file", "single_sample") and has_barcode_subdirs:
        raise ValueError(
            f"sample_handling={sample_handling!r} but {input_dir!r} contains "
            f"barcode subdirectories with FASTQ files. This is almost always "
            f"a misconfiguration: either set sample_handling='by_barcode' to "
            f"demultiplex, or point nanopore_output_directory at a flat "
            f"directory of FASTQ files."
        )


def format_duration(seconds: int) -> str:
    """
    Convert seconds to Nextflow duration string.

    Args:
        seconds: Duration in seconds

    Returns:
        Nextflow duration string (e.g., "15s", "1m", "2h")

    Examples:
        >>> format_duration(15)
        '15s'
        >>> format_duration(90)
        '1m'
        >>> format_duration(3600)
        '1h'
    """
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    else:
        hours = seconds // 3600
        return f"{hours}h"


def get_validation_species_from_watchlist(
    config: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Get enabled species for validation from the Watchlist system.

    Returns species with their mapped Kraken2 taxids and available genome paths.

    Args:
        config: Application configuration dict

    Returns:
        Tuple of (species_list, genome_paths):
        - species_list: List of dicts with 'taxid', 'kraken_taxid', 'name'
        - genome_paths: List of paths to downloaded genome FASTA files
    """
    try:
        # Initialize watchlist manager with config
        manager = get_watchlist_manager()
        if not manager._loaded:
            manager.load_config(config)

        # Get genome manager
        genome_manager = get_genome_manager()

        # Get enabled entries (returns dict of taxid -> WatchlistEntry)
        entries_dict = manager.get_active_entries()
        if not entries_dict:
            logging.debug("No enabled watchlist entries found")
            return [], []

        entries = list(entries_dict.values())

        # Try to get taxid mapping collection (NCBI -> Kraken2 database mapping)
        mapping_collection = None
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
            mapping_collection = get_mapping_collection()
            if mapping_collection:
                logging.debug(
                    f"Using taxid mapping collection with {len(mapping_collection.mappings)} mappings"
                )
        except (ImportError, AttributeError, FileNotFoundError) as e:
            logging.debug(f"No taxid mapping collection available: {e}")

        species_list = []
        genome_paths = []

        for entry in entries:
            ncbi_taxid = getattr(entry, 'taxid', 0)
            if not ncbi_taxid:
                continue

            # Try to get mapped Kraken2 taxid from mapping collection
            kraken_taxid = ncbi_taxid  # Default to NCBI taxid
            if mapping_collection:
                db_taxid = mapping_collection.get_db_taxid(ncbi_taxid)
                if db_taxid:
                    kraken_taxid = db_taxid
                    logging.debug(
                        f"Mapped NCBI {ncbi_taxid} -> Kraken2 {db_taxid} for {getattr(entry, 'name', '')}"
                    )

            species_info = {
                'taxid': ncbi_taxid,
                'kraken_taxid': kraken_taxid,
                'name': getattr(entry, 'name', ''),
            }
            species_list.append(species_info)

            # Check if genome is downloaded (by NCBI taxid)
            genome_path = genome_manager.get_genome_path(ncbi_taxid)
            if genome_path:
                genome_paths.append(str(genome_path))

        logging.info(
            f"Found {len(species_list)} enabled watchlist species, "
            f"{len(genome_paths)} with downloaded genomes"
        )
        return species_list, genome_paths

    except (ImportError, AttributeError) as e:
        logging.warning(f"Watchlist subsystem unavailable: {e}")
        return [], []
    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.warning(f"Failed to read watchlist data: {e}")
        return [], []
    except (ValueError, KeyError, TypeError) as e:
        logging.warning(f"Failed to parse watchlist entries: {e}")
        return [], []


def get_validation_species(config: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Get species taxids for BLAST validation.

    Uses the Watchlist system to retrieve enabled species for validation.

    Args:
        config: Application configuration dict

    Returns:
        Tuple of (taxid_list, genome_paths):
        - taxid_list: List of taxid strings for validation
        - genome_paths: List of paths to genome FASTA files
    """
    species_list, genome_paths = get_validation_species_from_watchlist(config)

    if species_list:
        # Use kraken_taxid for pipeline (mapped to database)
        taxids = [str(s['kraken_taxid']) for s in species_list if s.get('kraken_taxid')]
        return taxids, genome_paths

    return [], []


def generate_samplesheet(
    input_dir: str,
    output_path: str,
    sample_handling: str = "single_sample",
    sample_name: str = "sample"
) -> str:
    """
    Generate a samplesheet CSV from existing FASTQ files.

    This function scans a directory for FASTQ files and creates a samplesheet
    in the format required by nanometanf (sample, fastq columns).

    Args:
        input_dir: Directory containing FASTQ files
        output_path: Path to write the samplesheet CSV
        sample_handling: How to handle files:
            - "single_sample": All files belong to one sample (use sample_name)
            - "per_file": Each file is a separate sample (name derived from filename)
            - "by_barcode": Files organized in barcode subdirectories
        sample_name: Name to use when sample_handling is "single_sample"

    Returns:
        Path to the generated samplesheet

    Note:
        - For single_sample mode, all files get the same sample name (grouped together)
        - For per_file mode, sample names are derived from filenames
        - For by_barcode mode, sample names are the barcode directory names
    """
    rows = []

    if sample_handling == "by_barcode":
        # Look for barcode subdirectories
        barcode_dirs = sorted(glob.glob(os.path.join(input_dir, "barcode*")))
        # Also include unclassified reads if present
        unclassified_dir = os.path.join(input_dir, "unclassified")
        if os.path.isdir(unclassified_dir):
            barcode_dirs.append(unclassified_dir)
        if not barcode_dirs:
            raise ValueError(f"No barcode directories found in {input_dir}")

        for barcode_dir in barcode_dirs:
            if os.path.isdir(barcode_dir):
                barcode_name = os.path.basename(barcode_dir)
                fastq_files = glob.glob(os.path.join(barcode_dir, "*.fastq*"))
                for fastq_file in sorted(fastq_files):
                    rows.append([barcode_name, str(Path(fastq_file).resolve())])

        if not rows:
            raise ValueError(f"No FASTQ files found in barcode directories under {input_dir}")

    else:
        # Direct FASTQ files in directory
        fastq_files = glob.glob(os.path.join(input_dir, "*.fastq*"))
        fastq_files.sort()

        if not fastq_files:
            raise ValueError(f"No FASTQ files found in {input_dir}")

        for fastq_file in fastq_files:
            if sample_handling == "single_sample":
                # All files belong to one sample
                rows.append([sample_name, str(Path(fastq_file).resolve())])
            else:
                # per_file mode: each file is a separate sample
                basename = os.path.basename(fastq_file)
                file_sample_name = basename
                for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq']:
                    if file_sample_name.endswith(ext):
                        file_sample_name = file_sample_name[:-len(ext)]
                        break
                # Clean sample name
                file_sample_name = re.sub(r'[^\w]', '_', file_sample_name)
                rows.append([file_sample_name, str(Path(fastq_file).resolve())])

    # Write samplesheet
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['sample', 'fastq'])
        writer.writerows(rows)

    # Count unique samples
    unique_samples = len(set(row[0] for row in rows))
    logging.info(
        f"Generated samplesheet: {len(rows)} files, {unique_samples} sample(s) at {output_path}"
    )
    return output_path


_INPUT_SOURCE_KEYS = (
    "input",
    "input_dir",
    "fastq_input_dir",
    "barcode_input_dir",
    "nanopore_output_dir",
)


def _validate_single_input_source(params: Dict[str, Any]) -> None:
    """
    Verify that exactly one nanometanf input-source parameter is populated.

    nanometanf treats the input-source keys as mutually exclusive. Setting
    more than one results in an opaque "Multiple input modes detected"
    error at Nextflow start; setting none means INPUT_SCANNER has nothing
    to scan. Detecting both conditions in Python yields a precise,
    actionable error before the pipeline launches.

    Args:
        params: Dictionary of nanometanf parameters about to be passed to
            Nextflow.

    Raises:
        ValueError: If zero or multiple input-source keys are populated.
    """
    populated = [key for key in _INPUT_SOURCE_KEYS if params.get(key)]

    if not populated:
        raise ValueError(
            "no input mode configured: one of "
            f"{list(_INPUT_SOURCE_KEYS)} must be set so nanometanf "
            "INPUT_SCANNER has a source to read from."
        )

    if len(populated) > 1:
        raise ValueError(
            "multiple input modes configured: "
            f"{populated}. Only one of "
            "--input, --input_dir, --fastq_input_dir, "
            "--barcode_input_dir, or --nanopore_output_dir may be set; "
            "check processing_mode and sample_handling settings."
        )


def create_nextflow_params(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create nanometanf parameter dictionary from Nanometa Live configuration.

    Supports two processing modes:
    - 'batch': Process all existing files at once (samplesheet input)
    - 'realtime': Watch directory for new files (watchPath)

    And three sample handling modes:
    - 'single_sample': All files in directory belong to one sample
    - 'per_file': Each file is treated as a separate sample
    - 'by_barcode': Files organized in barcode subdirectories

    Args:
        config: Nanometa Live configuration dictionary

    Returns:
        Dictionary suitable for writing to params.json for nanometanf

    Example:
        >>> config = {
        ...     "nanopore_output_directory": "/data/sequencer",
        ...     "kraken_db": "/data/kraken2_std",
        ...     "main_dir": "/data/results",
        ...     "processing_mode": "batch",
        ...     "sample_handling": "single_sample",
        ...     "sample_name": "my_sample"
        ... }
        >>> params = create_nextflow_params(config)
    """
    # Extract configuration values with defaults
    nanopore_dir = config.get("nanopore_output_directory", "")
    kraken_db = config.get("kraken_db", "")
    # IMPORTANT: Use results_output_directory from UI, falling back to main_dir
    main_dir = config.get("results_output_directory") or config.get("main_dir", "")

    # Log configuration for debugging
    logging.info(f"Output directory (results_output_directory/main_dir): {main_dir}")

    # Validate critical parameters early
    if not main_dir:
        raise ValueError(
            "No output directory configured. Please set 'Results Output Directory' in the UI."
        )

    # In batch mode an operator may bring their own samplesheet
    # (config["input"]) instead of pointing the run at a sequencer
    # output directory. The samplesheet path itself is the input
    # source, so an empty nanopore_output_directory is legitimate.
    # Realtime mode always needs a watch directory, and any batch
    # path that does not resolve to an existing samplesheet still
    # needs nanopore_output_directory to drive samplesheet generation
    # or input_dir auto-discovery.
    samplesheet_input = config.get("input")
    samplesheet_provided = bool(samplesheet_input) and os.path.isfile(
        str(samplesheet_input)
    )
    processing_mode_for_check = config.get("processing_mode", "batch")
    samplesheet_only_mode = (
        processing_mode_for_check == "batch" and samplesheet_provided
    )

    if not nanopore_dir and not samplesheet_only_mode:
        raise ValueError(
            "No input directory configured. Please set 'Nanopore Output Directory' in the UI."
        )

    check_interval = config.get("check_intervals_seconds", 15)
    analysis_name = config.get("analysis_name", "Nanometa Live Analysis")

    # Get processing mode and sample handling configuration
    processing_mode = config.get("processing_mode", "batch")
    sample_handling = config.get("sample_handling", "by_barcode")
    sample_name = config.get("sample_name", "sample")

    logging.info(f"Processing mode: {processing_mode}, Sample handling: {sample_handling}")
    logging.info(f"Input directory: {nanopore_dir}")

    # Get validation species from Watchlist system
    validation_taxids, genome_paths = get_validation_species(config)
    has_species = bool(validation_taxids)

    logging.debug(f"blast_validation={config.get('blast_validation', False)}, has_species={has_species}, taxids={validation_taxids}")

    # Generate pathogen_genomes.json if validation is requested
    # The nanometanf pipeline's VALIDATION workflow requires:
    # 1. run_validation = true
    # 2. pathogen_genomes = path to JSON file with genome info
    # 3. taxids_to_validate = 'auto' or comma-separated list
    pathogen_genomes_path = None
    has_genomes = False

    if config.get("blast_validation", False) and has_species:
        # Generate pathogen_genomes.json from downloaded genomes
        # Use configurable genome cache directory from config
        genome_cache_dir = config.get("genome_cache_dir", "~/.nanometa")
        logging.debug(f"Using genome cache directory for validation: {genome_cache_dir}")

        genome_manager = get_genome_manager(cache_dir=genome_cache_dir)

        # Log genome manager stats
        try:
            stats = genome_manager.get_statistics()
            logging.debug(f"Genome manager stats: {stats}")
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.debug(f"Could not read genome cache: {e}")
        except AttributeError as e:
            logging.debug(f"Genome manager missing get_statistics: {e}")

        # Get the full species list with both NCBI and Kraken taxids
        # We need NCBI taxids for genome file lookup, and Kraken taxids for pipeline filtering
        species_list_full, _ = get_validation_species_from_watchlist(config)

        # Build mapping: NCBI taxid -> Kraken taxid (for GTDB database compatibility)
        ncbi_to_kraken_mapping = {}
        ncbi_taxids = []
        for species in species_list_full:
            ncbi_taxid = species.get('taxid', 0)
            kraken_taxid = species.get('kraken_taxid', ncbi_taxid)
            if ncbi_taxid:
                ncbi_taxids.append(ncbi_taxid)
                if kraken_taxid and kraken_taxid != ncbi_taxid:
                    ncbi_to_kraken_mapping[ncbi_taxid] = kraken_taxid
                    logging.debug(
                        f"Taxid mapping: NCBI {ncbi_taxid} -> Kraken2 db {kraken_taxid}"
                    )

        # Check which taxids have genomes (by NCBI taxid)
        for taxid in ncbi_taxids:
            has_genome = genome_manager.has_genome(taxid)
            logging.debug(f"Taxid {taxid} has_genome={has_genome}")

        # Generate JSON file in the results directory
        # Uses NCBI taxids for file lookup, Kraken taxids as JSON keys
        json_output_path = os.path.join(main_dir, "validation", "pathogen_genomes.json")
        os.makedirs(os.path.dirname(json_output_path), exist_ok=True)

        logging.debug(f"Generating pathogen_genomes.json at {json_output_path}")
        if ncbi_to_kraken_mapping:
            logging.debug(
                f"Applying taxid mapping for {len(ncbi_to_kraken_mapping)} species"
            )

        pathogen_genomes_path = genome_manager.generate_pathogen_genomes_json(
            ncbi_taxids,
            output_path=json_output_path,
            taxid_mapping=ncbi_to_kraken_mapping if ncbi_to_kraken_mapping else None
        )

        has_genomes = pathogen_genomes_path is not None

        if has_genomes:
            logging.info(f"Generated pathogen_genomes.json at {pathogen_genomes_path}")
            # Log the contents for debugging
            try:
                import json
                with open(pathogen_genomes_path, 'r') as f:
                    content = json.load(f)
                logging.debug(f"pathogen_genomes.json contains {len(content)} entries")
            except (FileNotFoundError, PermissionError, OSError) as e:
                logging.debug(f"Could not read pathogen_genomes.json: {e}")
            except json.JSONDecodeError as e:
                logging.debug(f"Malformed pathogen_genomes.json: {e}")
        else:
            logging.warning(
                "No downloaded genomes found for enabled watchlist species. "
                "Download genomes using the Watchlist tab to enable validation."
            )

    # blast_validation and run_validation must both be false if we can't actually run validation
    can_run_validation = has_species and has_genomes
    blast_validation_enabled = config.get("blast_validation", False) and can_run_validation
    run_validation_enabled = can_run_validation

    if config.get("blast_validation", False) and not can_run_validation:
        if not has_species:
            logging.warning(
                "blast_validation is enabled but no watchlist species configured. "
                "Disabling validation (requires species to validate against). "
                "Enable pathogens in the Watchlist tab to use validation."
            )
        elif not has_genomes:
            logging.warning(
                "blast_validation is enabled but no pathogen genomes downloaded. "
                "Disabling validation (requires reference genomes). "
                "Download pathogen genomes in the Watchlist tab first."
            )

    # Kraken2 memory mapping: auto-disable on ARM unless the user set an
    # explicit override. nanometanf's KRAKEN2 module falls back to a plain
    # (non-mmap) load on ARM regardless, but emitting the explicit False
    # here silences the per-run WARN and matches the behaviour operators see.
    if "kraken_memory_mapping" in config:
        kraken2_memory_mapping = bool(config["kraken_memory_mapping"])
    elif platform.machine().lower() in {"arm64", "aarch64"}:
        logging.info(
            "ARM host detected (%s); defaulting kraken2_memory_mapping=False",
            platform.machine(),
        )
        kraken2_memory_mapping = False
    else:
        kraken2_memory_mapping = True

    # Create base nanometanf parameters
    params = {
        "outdir": main_dir,

        # Kraken2 classification
        "kraken2_db": kraken_db,
        "kraken2_memory_mapping": kraken2_memory_mapping,

        # Save reads assignment and classified FASTQs (required for validation to work)
        # The VALIDATION workflow needs:
        # 1. save_reads_assignment - per-read Kraken2 output to know which reads belong to which taxid
        # 2. save_output_fastqs - the classified reads to extract and BLAST against reference genomes
        "save_reads_assignment": run_validation_enabled,
        "save_output_fastqs": run_validation_enabled,

        # Validation parameters - nanometanf VALIDATION subworkflow
        "run_validation": run_validation_enabled,
        "validation_method": config.get("validation_method", "blast"),
        "blast_evalue": config.get("e_val_cutoff", 1e-10),
        "blast_perc_identity": config.get("min_perc_identity", 90),
        "validation_hit_rate_threshold": config.get("validation_hit_rate_threshold", 0.5),
        "validation_identity_threshold": config.get("validation_identity_threshold", 90.0),
        "minimap2_preset": config.get("minimap2_preset", "map-ont"),
        "minimap2_min_mapq": config.get("minimap2_min_mapq", 10),

        # Legacy parameter (deprecated, nanometanf maps to run_validation internally)
        "blast_validation": blast_validation_enabled,

        # QC settings
        "qc_tool": config.get("qc_tool", "chopper"),
        "skip_fastp": False,
        "skip_nanoplot": config.get("skip_nanoplot", False),

        # Read-filter overrides surfaced by the Configuration tab's
        # Advanced Settings -> Read Filtering and Validation card.
        # Defaults match nanometanf's pipeline-side defaults so an
        # operator who has not touched the new GUI fields keeps the
        # current long-read behaviour. See
        # docs/audit-2026-04-29-short-amplicons.md for rationale on
        # why each is operator-tunable.
        "chopper_minlength": config.get("chopper_minlength", 1000),
        "chopper_quality": config.get("chopper_quality", 10),
        "filtlong_min_length": config.get("filtlong_min_length", 1000),
        "kraken2_confidence": config.get("kraken2_confidence", 0.0),
        "kraken2_minimum_hit_groups": config.get(
            "kraken2_minimum_hit_groups", 0
        ),

        # Visualization
        # Disable Krona plots by default - container has permissions issues with taxonomy update
        "enable_krona_plots": config.get("enable_krona_plots", False),

        # Disable nanopore stats for MultiQC - container missing PyYAML dependency
        "enable_nanopore_stats_mqc": config.get("enable_nanopore_stats_mqc", False),

        # Reporting
        "multiqc_title": analysis_name,
    }

    # Add validation species if configured (from Watchlist or legacy config)
    if has_species and validation_taxids:
        # Convert to comma-separated string for taxids_to_validate (schema type: string)
        if isinstance(validation_taxids, list):
            taxids_str = ",".join(str(t) for t in validation_taxids)
        else:
            taxids_str = str(validation_taxids)

        # priority_samples must be a list for Nextflow (.size(), .any{}, .join())
        params["priority_samples"] = [str(t) for t in validation_taxids]
        params["taxids_to_validate"] = taxids_str  # For VALIDATION subworkflow (string)
        logging.info(f"Configured {len(validation_taxids)} species for validation")

        # Add pathogen_genomes JSON path if available
        if pathogen_genomes_path:
            params["pathogen_genomes"] = str(pathogen_genomes_path)
            logging.info(f"Pathogen genomes JSON: {pathogen_genomes_path}")
        elif genome_paths:
            logging.info(f"Found {len(genome_paths)} downloaded genomes for validation")

    # Set input parameters based on processing mode and sample handling.
    # Batch mode offers four input paths, checked in priority order:
    #   1. config["input"] is an existing file -> pass through verbatim
    #      (supports the "bring your own samplesheet" workflow).
    #   2. config["use_input_dir_mode"] is true -> emit --input_dir for the
    #      nanometanf INPUT_SCANNER subworkflow (explicit opt-in).
    #   3. Scenario E: batch + by_barcode with no pre-built samplesheet
    #      auto-enables --input_dir so the INPUT_SCANNER can discover the
    #      barcode* subdirectory layout itself. This removes a silent GUI
    #      regression where the missing flag caused the run to fall back
    #      to realtime mode without any user-visible warning.
    #   4. Otherwise -> auto-generate a samplesheet from nanopore_dir.
    if processing_mode == "batch":
        user_input = config.get("input")
        use_input_dir = bool(config.get("use_input_dir_mode", False))

        # Scenario E auto-trigger: batch + by_barcode + no samplesheet.
        # Scoped narrowly to by_barcode so single_sample and per_file
        # continue to generate their samplesheets as before.
        samplesheet_provided = bool(user_input) and os.path.isfile(user_input)
        if (
            not use_input_dir
            and not samplesheet_provided
            and sample_handling == "by_barcode"
        ):
            use_input_dir = True
            logging.info(
                "Batch mode + by_barcode with no samplesheet supplied: "
                "auto-enabling --input_dir so nanometanf INPUT_SCANNER "
                "can discover the barcode layout."
            )

        if samplesheet_provided:
            params["input"] = str(user_input)
            logging.info(
                f"Batch mode: using pre-supplied samplesheet at {user_input}"
            )
        elif use_input_dir:
            params["input_dir"] = nanopore_dir
            logging.info(
                f"Batch mode (input_dir): nanometanf INPUT_SCANNER will "
                f"auto-discover layout under {nanopore_dir}"
            )
        else:
            if user_input:
                logging.warning(
                    f"config['input']={user_input!r} does not point at an "
                    f"existing file; falling back to samplesheet generation"
                )
            # Validate the declared sample_handling matches the directory
            # shape before we commit to samplesheet generation.
            validate_sample_handling_layout(sample_handling, nanopore_dir)

            samplesheet_dir = os.path.join(main_dir, "samplesheets")
            os.makedirs(samplesheet_dir, exist_ok=True)
            samplesheet_path = os.path.join(samplesheet_dir, "input_samplesheet.csv")

            try:
                generate_samplesheet(
                    nanopore_dir,
                    samplesheet_path,
                    sample_handling=sample_handling,
                    sample_name=sample_name
                )
                params["input"] = samplesheet_path
                logging.info(f"Batch mode ({sample_handling}): Generated samplesheet at {samplesheet_path}")
            except ValueError as e:
                # Fall back to realtime mode if samplesheet generation fails
                logging.warning(f"Samplesheet generation failed: {e}")
                logging.warning("Falling back to realtime mode")
                params["realtime_mode"] = True
                params["nanopore_output_dir"] = nanopore_dir
                params["batch_size"] = config.get("batch_size", 10)
                params["batch_interval"] = format_duration(check_interval)

    else:
        # Realtime mode: Use watchPath for new files
        params["realtime_mode"] = True
        params["nanopore_output_dir"] = nanopore_dir
        # nanopore_output_dir is sufficient for realtime FASTQ monitoring.
        # Do NOT also set input_dir — the pipeline treats input_dir and
        # nanopore_output_dir as mutually exclusive input modes and will
        # raise "Multiple input modes detected" if both are non-null.

        # Pass sample_name for single-sample mode
        # The pipeline will use this instead of deriving sample ID from filenames
        if sample_handling == "single_sample":
            params["sample_name"] = sample_name
            logging.info(f"Single-sample mode: Using sample name '{sample_name}'")

        # For realtime mode, default to batch_size=1 to process files immediately
        # This ensures existing files in the folder are processed right away
        # without waiting for 10 files to accumulate
        params["batch_size"] = config.get("batch_size", 1)
        params["min_batch_size"] = config.get("min_batch_size", 1)
        params["batch_interval"] = format_duration(check_interval)

        # Set file age filtering to allow processing of demo/archived data
        # The pipeline requires minimum 0.1, so use a very high value to effectively disable
        # Using 1000000 minutes (~1.9 years) to allow processing of old demo data
        params["max_avg_file_age_minutes"] = config.get("max_file_age_minutes", 1000000)

        # Enable incremental Kraken2 classification for realtime mode
        # This enables batch-by-batch processing with cumulative report generation:
        # - Each batch is classified independently (avoiding O(n^2) reprocessing)
        # - Batch outputs are merged via KRAKEN2_OUTPUT_MERGER
        # - Cumulative reports generated via KRAKEN2_REPORT_GENERATOR using combine_kreports.py
        params["kraken2_enable_incremental"] = config.get("kraken2_enable_incremental", True)

        # Set a timeout for realtime mode to prevent indefinite running
        # Default to None (indefinite) for true realtime monitoring
        # Can be set via config to limit runtime for testing/demo
        realtime_timeout = config.get("realtime_timeout_minutes")
        if realtime_timeout:
            params["realtime_timeout_minutes"] = int(realtime_timeout)
            logging.info(f"Realtime timeout set to {realtime_timeout} minutes")

        # Set max_files if specified (useful for testing with limited data)
        max_files = config.get("max_files")
        if max_files:
            params["max_files"] = int(max_files)
            logging.info(f"Max files limit set to {max_files}")

        # Note: The nanometanf pipeline's REALTIME_MONITORING subworkflow now handles
        # both existing and new files by combining Channel.fromPath() with Channel.watchPath()
        # No samplesheet generation needed here - existing files will be detected automatically

        barcode_mode = "with barcode directories" if sample_handling == "by_barcode" else "single sample"
        logging.info(f"Realtime mode ({barcode_mode}): Monitoring {nanopore_dir}")
        if params["kraken2_enable_incremental"]:
            logging.info("Incremental Kraken2 classification enabled for cumulative reporting")

    # Add email if provided
    if "email" in config and config["email"]:
        params["email"] = config["email"]

    # Dual-input guard. nanometanf rejects a run that specifies more than
    # one input source because INPUT_SCANNER would not know which mode to
    # use. _validate_single_input_source raises a precise Python message
    # before Nextflow starts, instead of the opaque "Multiple input modes
    # detected" error.
    _validate_single_input_source(params)

    return params


def create_nextflow_config(config: Dict[str, Any]) -> str:
    """
    Create custom nextflow.config content for resource limits and profile.

    Notes on 2026-04-21 audit cleanup:
    - The legacy ``params { max_cpus / max_memory / max_time }`` block has
      been removed; those keys are not part of nanometanf's schema and
      Nextflow emitted invalid-param warnings each run.
    - The FASTP ``withName`` block is only emitted when ``qc_tool == "fastp"``
      so the default (chopper) pipeline does not carry dead config.
    - Braces are emitted literally (no Python f-string double-brace artefacts).

    Args:
        config: Nanometa Live configuration dictionary

    Returns:
        String content suitable for writing to a Nextflow ``-c`` config file.
    """
    max_cores = config.get("pipeline_cores") or config.get("snakemake_cores", 4)
    kraken_cores = config.get("kraken_cores", max_cores)
    blast_cores = config.get("blast_cores", 2)
    validation_cores = config.get("validation_cores", 2)
    qc_tool = str(config.get("qc_tool", "chopper")).lower()

    profile = config.get("pipeline_profile", "docker")

    # Profile-specific container runtime settings. Using explicit string
    # concatenation (rather than nested f-strings with doubled braces) to avoid
    # the Groovy interpolation artefact called out in the audit.
    if profile in ("singularity", "apptainer"):
        profile_block = (
            "// Singularity configuration\n"
            "singularity {\n"
            "    enabled = true\n"
            "    autoMounts = true\n"
            "}\n\n"
            "// Docker configuration\n"
            "docker {\n"
            "    enabled = false\n"
            "}\n"
        )
    elif profile == "conda":
        profile_block = (
            "// Conda profile selected - no container runtime configured\n"
            "docker {\n"
            "    enabled = false\n"
            "}\n\n"
            "singularity {\n"
            "    enabled = false\n"
            "}\n"
        )
    else:
        profile_block = (
            "// Docker configuration\n"
            "docker {\n"
            "    enabled = true\n"
            "    runOptions = '-u $(id -u):$(id -g)'\n"
            "}\n\n"
            "// Singularity configuration\n"
            "singularity {\n"
            "    enabled = false\n"
            "}\n"
        )

    withname_blocks = [
        "    // Kraken2 classification (most CPU-intensive)\n"
        "    withName: 'KRAKEN2_KRAKEN2' {\n"
        f"        cpus = {kraken_cores}\n"
        "        memory = '8.GB'\n"
        "    }\n",
        "    // BLAST validation\n"
        "    withName: 'BLAST_BLASTN' {\n"
        f"        cpus = {blast_cores}\n"
        "        memory = '4.GB'\n"
        "    }\n",
        "    // NanoPlot QC\n"
        "    withName: 'NANOPLOT' {\n"
        "        cpus = 2\n"
        "        memory = '4.GB'\n"
        "    }\n",
        "    // Validation sequence extraction\n"
        "    withName: 'EXTRACT_VALIDATION_SEQS' {\n"
        f"        cpus = {validation_cores}\n"
        "        memory = '4.GB'\n"
        "    }\n",
    ]
    if qc_tool == "fastp":
        withname_blocks.insert(
            2,
            "    // FASTP quality filtering\n"
            "    withName: 'FASTP' {\n"
            "        cpus = 2\n"
            "        memory = '4.GB'\n"
            "    }\n",
        )
    process_block = "process {\n" + "\n".join(withname_blocks) + "}\n"

    config_content = (
        "// Custom Nextflow configuration for Nanometa Live\n"
        "// Auto-generated from Nanometa Live configuration\n"
        "\n"
        "// Allow overwriting report files from previous runs\n"
        "report {\n"
        "    overwrite = true\n"
        "}\n"
        "\n"
        "timeline {\n"
        "    overwrite = true\n"
        "}\n"
        "\n"
        "trace {\n"
        "    overwrite = true\n"
        "}\n"
        "\n"
        + process_block
        + "\n"
        + profile_block
    )

    return config_content


def validate_nanometanf_params(params: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate that all required nanometanf parameters are present and valid.

    Supports three input modes:
    - batch: requires fastq_input_dir
    - barcode: requires barcode_input_dir
    - realtime: requires nanopore_output_dir

    Args:
        params: Dictionary of nanometanf parameters

    Returns:
        Tuple of (success: bool, message: str)

    Example:
        >>> params = {
        ...     "fastq_input_dir": "/data/seq",
        ...     "kraken2_db": "/data/kraken",
        ...     "outdir": "/data/results"
        ... }
        >>> valid, msg = validate_nanometanf_params(params)
        >>> # Returns True if paths exist
    """
    import re

    # Always required parameters
    always_required = ["kraken2_db", "outdir"]

    for param in always_required:
        if param not in params:
            return False, f"Missing required parameter: {param}"
        if not params[param]:
            return False, f"Required parameter is empty: {param}"

    # Determine which input mode is being used
    has_samplesheet_input = "input" in params and params["input"]
    has_input_dir = "input_dir" in params and params["input_dir"]
    has_fastq_input = "fastq_input_dir" in params and params["fastq_input_dir"]
    has_barcode_input = "barcode_input_dir" in params and params["barcode_input_dir"]
    has_realtime_input = "nanopore_output_dir" in params and params["nanopore_output_dir"]

    # Validate at least one input mode is specified
    if not (has_samplesheet_input or has_input_dir or has_fastq_input or has_barcode_input or has_realtime_input):
        return (
            False,
            "Missing input. Must specify one of: "
            "input (samplesheet), input_dir, fastq_input_dir, barcode_input_dir, or nanopore_output_dir"
        )

    # Validate Kraken2 database exists
    kraken_db = params["kraken2_db"]
    if not os.path.isdir(kraken_db):
        return False, f"Kraken2 database directory not found: {kraken_db}"

    # Check for key Kraken2 database files
    required_kraken_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]
    missing_files = []

    for file in required_kraken_files:
        file_path = os.path.join(kraken_db, file)
        if not os.path.isfile(file_path):
            missing_files.append(file)

    if missing_files:
        return (
            False,
            f"Kraken2 database missing required files: {', '.join(missing_files)}"
        )

    # Validate input based on mode
    if has_samplesheet_input:
        samplesheet_path = params["input"]
        if not os.path.isfile(samplesheet_path):
            return False, f"Samplesheet not found: {samplesheet_path}"
        # Verify samplesheet has content
        with open(samplesheet_path, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                return False, f"Samplesheet is empty or has no samples: {samplesheet_path}"
        logging.info(f"Samplesheet mode: Using {samplesheet_path} with {len(lines) - 1} samples")

    elif has_input_dir:
        input_dir = params["input_dir"]
        if not os.path.isdir(input_dir):
            return False, f"input_dir not found: {input_dir}"
        logging.info(f"input_dir mode: nanometanf INPUT_SCANNER will discover layout under {input_dir}")

    elif has_fastq_input:
        input_dir = params["fastq_input_dir"]
        if not os.path.isdir(input_dir):
            return False, f"FASTQ input directory not found: {input_dir}"
        # Verify FASTQ files exist
        fastq_files = glob.glob(os.path.join(input_dir, "*.fastq*"))
        if not fastq_files:
            return False, f"No FASTQ files found in: {input_dir}"
        logging.info(f"Batch mode: Found {len(fastq_files)} FASTQ files in {input_dir}")

    elif has_barcode_input:
        input_dir = params["barcode_input_dir"]
        if not os.path.isdir(input_dir):
            return False, f"Barcode input directory not found: {input_dir}"
        # Verify barcode subdirectories exist
        barcode_dirs = glob.glob(os.path.join(input_dir, "barcode*"))
        if not barcode_dirs:
            return False, f"No barcode subdirectories found in: {input_dir}"
        logging.info(f"Barcode mode: Found {len(barcode_dirs)} barcode directories in {input_dir}")

    elif has_realtime_input:
        input_dir = params["nanopore_output_dir"]
        if not os.path.isdir(input_dir):
            logging.warning(f"Input directory does not exist yet: {input_dir}")
            logging.warning("Pipeline will wait for directory to appear...")
        logging.info(f"Realtime mode: Monitoring {input_dir} for new files")

    # Validate output directory can be created
    outdir = params["outdir"]
    outdir_parent = os.path.dirname(outdir)

    if outdir_parent and not os.path.isdir(outdir_parent):
        return (
            False,
            f"Output directory parent does not exist: {outdir_parent}"
        )

    # Validate batch_interval format only if present (realtime mode)
    batch_interval = params.get("batch_interval")
    if batch_interval:
        if not isinstance(batch_interval, str):
            return False, f"batch_interval must be a string, got {type(batch_interval)}"

        # Check duration format (e.g., "15s", "1m", "2h")
        if not re.match(r'^\d+[smhd]$', batch_interval):
            return (
                False,
                f"Invalid batch_interval format: {batch_interval}. "
                f"Expected format: <number><unit> (e.g., '15s', '1m', '2h')"
        )

    return True, "Validation successful"


def convert_legacy_config(snakemake_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert legacy Snakemake configuration to nanometanf parameters.

    This function provides backward compatibility for existing Nanometa Live
    configurations that were designed for the Snakemake backend.

    Args:
        snakemake_config: Legacy Snakemake configuration dictionary

    Returns:
        Dictionary of nanometanf parameters

    Example:
        >>> legacy_config = {
        ...     "nanopore_output_directory": "/data/seq",
        ...     "kraken_db": "/data/kraken",
        ...     "main_dir": "/data/results",
        ...     "kraken_memory_mapping": True,
        ...     "check_intervals_seconds": 30
        ... }
        >>> params = convert_legacy_config(legacy_config)
        >>> params["realtime_mode"]
        True
        >>> params["batch_interval"]
        '30s'
    """
    # Handle boolean parameter conversions from Snakemake
    # Old Snakemake format used "--memory-mapping" or "" strings
    kraken_memory_mapping = snakemake_config.get("kraken_memory_mapping", True)

    # Convert string flags to boolean if needed
    if isinstance(kraken_memory_mapping, str):
        kraken_memory_mapping = kraken_memory_mapping == "--memory-mapping"

    # Handle remove_temp_files conversion
    # Old format: "yes"/"no", new format: boolean
    remove_temp_files = snakemake_config.get("remove_temp_files", True)
    if isinstance(remove_temp_files, str):
        remove_temp_files = remove_temp_files.lower() in ["yes", "true", "y", "1"]

    # Create updated config with boolean values
    updated_config = dict(snakemake_config)
    updated_config["kraken_memory_mapping"] = kraken_memory_mapping
    updated_config["remove_temp_files"] = remove_temp_files

    # Use standard parameter mapping
    return create_nextflow_params(updated_config)


def map_cleanup_mode(remove_temp_files: bool) -> str:
    """
    Map cleanup boolean to Nextflow publish_dir_mode.

    Args:
        remove_temp_files: Whether to remove temporary files

    Returns:
        Nextflow publish_dir_mode value

    Note:
        - If remove_temp_files is True, use 'copy' mode (originals deleted after copy)
        - If False, use 'symlink' mode (originals preserved as symlinks)
    """
    return "copy" if remove_temp_files else "symlink"
