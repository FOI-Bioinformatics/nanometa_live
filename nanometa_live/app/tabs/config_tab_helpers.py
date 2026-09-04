"""
Pure helpers for the Configuration tab.

Extracted from config_tab.py so the registration function there stays focused on
Dash callback declarations. config_tab.py re-exports these names.
"""

import glob
import logging
import os
from datetime import datetime

from dash import html
import dash_bootstrap_components as dbc


def _validate_nanopore_dir(nanopore_dir, sample_handling, processing_mode):
    """Existence and sample-handling-layout checks for the input directory.

    Returns a list of error strings (empty when valid or unset). "by_barcode"
    means subdirectory-per-sample (conventional barcode<NN> plus custom-named
    subdirs); the canonical detector in core.utils.auto_detect is delegated to
    so the rules cannot drift.
    """
    errors = []
    if not (nanopore_dir and nanopore_dir.strip()):
        return errors
    if not os.path.exists(nanopore_dir):
        errors.append(f"Nanopore directory does not exist: {nanopore_dir}")
        return errors
    if not os.path.isdir(nanopore_dir):
        errors.append(f"Nanopore path is not a directory: {nanopore_dir}")
        return errors

    from nanometa_live.core.utils.auto_detect import (
        detect_sample_handling,
        find_sample_subdirs,
    )
    detected_mode, detected_reason = detect_sample_handling(nanopore_dir)
    # In realtime mode the watched directory is legitimately empty at
    # config-save time (files arrive during the run), so an EMPTY directory
    # passes. A directory that already holds files is checked like batch
    # input: by_barcode on a flat directory used to pass Apply and the
    # readiness list in silence, while batch rejected the same pair with a
    # suggestion (audit round 5, C13).
    if processing_mode != "batch":
        try:
            has_content = any(
                not entry.startswith(".") for entry in os.listdir(nanopore_dir)
            )
        except OSError:
            has_content = False
        if not has_content:
            return errors
    if sample_handling == "by_barcode":
        sample_dirs = find_sample_subdirs(nanopore_dir)
        if not sample_dirs:
            suggestion = ""
            if detected_mode and detected_mode != "by_barcode":
                suggestion = (
                    f" Auto-detection suggests '{detected_mode}' "
                    f"for this directory ({detected_reason})."
                )
            errors.append(
                "By-barcode mode selected but no per-sample "
                f"subdirectories with FASTQ files found in "
                f"{nanopore_dir}. by_barcode accepts "
                "conventional 'barcode01', 'barcode02', ... "
                "and any custom-named folder containing "
                "FASTQ files (e.g. 'Turex/', 'Zymo/'). For "
                "flat file directories, switch to 'Single "
                "sample' or 'Per file' mode."
                + suggestion
            )
    elif sample_handling in ["single_sample", "per_file"]:
        # Check for FASTQ files directly in directory.
        fastq_files = glob.glob(os.path.join(nanopore_dir, "*.fastq*"))
        sample_dirs = find_sample_subdirs(nanopore_dir)
        if not fastq_files and sample_dirs:
            suggestion = ""
            if detected_mode == "by_barcode":
                suggestion = (
                    f" Auto-detection confirms 'by_barcode' "
                    f"({detected_reason})."
                )
            errors.append(
                f"No FASTQ files found directly in {nanopore_dir}, "
                "but per-sample subdirectories exist "
                f"({', '.join(d.name for d in sample_dirs[:3])}"
                + (", ..." if len(sample_dirs) > 3 else "")
                + "). For per-sample directories, use "
                "'By barcode' handling mode."
                + suggestion
            )
    return errors


def _validate_kraken_db_path(kraken_db):
    """Existence and Kraken2-format checks for the database directory.

    Delegates format validation to core.utils.kraken_utils.check_kraken_db,
    the single source of truth shared with the launch-time gate.
    """
    errors = []
    if not (kraken_db and kraken_db.strip()):
        return errors
    if not os.path.exists(kraken_db):
        errors.append(f"Kraken2 database does not exist: {kraken_db}")
    elif not os.path.isdir(kraken_db):
        errors.append(f"Kraken2 database path is not a directory: {kraken_db}")
    else:
        from nanometa_live.core.utils.kraken_utils import check_kraken_db
        valid, missing_files = check_kraken_db(kraken_db)
        if not valid:
            errors.append(
                f"Invalid Kraken2 database format. "
                f"Missing required files: {', '.join(missing_files)}"
            )
    return errors


def _validate_read_filter_ranges(*, chopper_minlength, chopper_quality,
                                 chopper_maxlength, filtlong_minlength):
    """Bounds for the read-filter card: the length floors, the quality floor
    and the optional upper bound.

    Floors are 1, not 0: nanometanf's schema sets ``minimum: 1`` on both
    length filters, so a 0 saved here fails nf-schema at launch. 1 disables
    the filter in practice (no nanopore read is shorter).
    """
    errors = []
    if chopper_minlength is not None and chopper_minlength < 1:
        errors.append("Chopper minimum length must be 1 or greater "
                      "(the pipeline rejects 0; 1 disables the filter)")
    if chopper_quality is not None and not (0 <= chopper_quality <= 50):
        errors.append("Minimum mean read quality must be between 0-50")
    if filtlong_minlength is not None and filtlong_minlength < 1:
        errors.append("Filtlong minimum length must be 1 or greater "
                      "(the pipeline rejects 0; 1 disables the filter)")
    if chopper_maxlength is not None and chopper_maxlength != "":
        floor = chopper_minlength if chopper_minlength is not None else 1
        if chopper_maxlength < max(1, floor):
            errors.append("Maximum read length must be at least the "
                          "minimum read length (leave it empty for no "
                          "limit)")
    return errors


def _validate_numeric_ranges(
    *,
    update_interval,
    realtime_timeout_minutes,
    min_reads_per_level,
    e_value_cutoff,
    cores,
    gui_port,
    minimap2_min_mapq,
    validation_identity,
    kraken2_confidence,
    chopper_minlength,
    chopper_quality,
    filtlong_minlength,
    max_file_age_minutes,
    min_reads_for_validation,
    chopper_maxlength=None,
    kraken2_hitgroups=None,
):
    """Server-side bounds checks for every numeric form input.

    The widgets carry browser-level min/max, but those are advisory only -- a
    programmatic post or devtools edit can submit out-of-range values that
    would otherwise reach last-session.yaml and Nextflow. Returns error strings.
    """
    errors = []
    # Floor of 5 matches the widget; a 1 s poll of the results tree is
    # never useful and the two bounds disagreed (audit round 5, A10).
    if update_interval is not None and not (5 <= update_interval <= 300):
        errors.append("Update Interval must be between 5-300 seconds")
    if realtime_timeout_minutes is not None and realtime_timeout_minutes != "":
        try:
            if not (1 <= int(realtime_timeout_minutes) <= 10080):
                errors.append("Realtime Timeout must be between 1-10080 minutes (or empty for no timeout)")
        except (TypeError, ValueError):
            errors.append("Realtime Timeout must be an integer number of minutes")
    if min_reads_per_level is not None and min_reads_per_level < 1:
        errors.append("Minimum Reads per Level must be at least 1")
    if e_value_cutoff is not None and not (0 <= e_value_cutoff <= 1):
        errors.append("E-value Cutoff must be between 0-1")
    # Empty = pipeline default; the blank widget submits "" (audit round 5).
    if cores not in (None, ""):
        try:
            if int(cores) < 1:
                errors.append("CPU Cores must be at least 1")
        except (TypeError, ValueError):
            errors.append("CPU Cores must be a whole number")
    if gui_port is not None and not (1024 <= int(gui_port) <= 65535):
        errors.append("GUI Port must be between 1024-65535")
    if minimap2_min_mapq is not None and not (0 <= minimap2_min_mapq <= 60):
        errors.append("Alignment Confidence (MAPQ) must be between 0-60")
    if validation_identity is not None and not (0 <= validation_identity <= 100):
        errors.append("Validation identity must be between 0-100%")
    if kraken2_confidence is not None and not (0 <= kraken2_confidence <= 1):
        errors.append("Kraken2 confidence must be between 0.0-1.0")
    # The only numeric field with no server bound; a non-numeric value raised
    # inside build_config_from_form instead of reporting (audit round 5, A10).
    if kraken2_hitgroups is not None and kraken2_hitgroups != "":
        try:
            if int(kraken2_hitgroups) < 0:
                errors.append("Kraken2 minimum hit groups must be 0 or greater")
        except (TypeError, ValueError):
            errors.append("Kraken2 minimum hit groups must be a whole number")
    errors += _validate_read_filter_ranges(
        chopper_minlength=chopper_minlength,
        chopper_quality=chopper_quality,
        chopper_maxlength=chopper_maxlength,
        filtlong_minlength=filtlong_minlength,
    )
    if max_file_age_minutes is not None and max_file_age_minutes != "":
        try:
            if int(max_file_age_minutes) < 0:
                errors.append("Maximum file age must be 0 or greater")
        except (TypeError, ValueError):
            errors.append("Maximum file age must be an integer number of minutes")
    if min_reads_for_validation is not None and min_reads_for_validation < 1:
        errors.append("Minimum reads to offer validation must be at least 1")
    return errors


def optional_int(value):
    """An optional numeric form field: empty means None, else int."""
    return int(value) if value not in (None, "") else None


def build_config_from_form(
    current_config,
    *,
    analysis_name,
    nanopore_dir,
    kraken_db,
    results_dir,
    update_interval,
    realtime_timeout_minutes,
    min_reads_per_level,
    memory_mapping,
    blast_validation,
    validation_method,
    e_value_cutoff,
    genome_cache_dir,
    cores,
    gui_port,
    pipeline_profile,
    pipeline_source_type,
    pipeline_branch,
    minimap2_preset,
    minimap2_min_mapq,
    pipeline_local_path,
    processing_mode,
    sample_handling,
    sample_name,
    negative_controls,
    qc_tool,
    skip_nanoplot,
    kraken2_incremental,
    enable_krona,
    enable_nanopore_stats,
    chopper_minlength,
    chopper_quality,
    filtlong_minlength,
    validation_identity,
    kraken2_confidence,
    kraken2_hitgroups,
    chopper_maxlength=None,
    max_file_age_minutes,
    min_reads_for_validation,
    enable_assembly,
    assembler,
    assembly_scope,
    assembly_min_depth,
    assembly_allow_low_depth,
):
    """Validate Configuration-form inputs and build the updated config dict.

    Returns ``(config, errors)``. When ``errors`` is non-empty the config is
    ``None`` and the caller should surface the messages without writing
    anything. Filesystem *reads* (existence/format checks) happen here, but no
    writes -- session persistence is the caller's job via
    :func:`autosave_session_config`. Kept pure of Dash so it is unit-testable.
    """
    errors = []

    # Canonicalise paths up-front so every check below uses the
    # absolute, expanded form. Prevents "~/foo" and relative paths
    # from silently failing existence checks. The canonical value
    # is what gets written to the config dict at the bottom of
    # this function (see normalise_config_paths down there).
    from nanometa_live.core.utils.path_utils import normalise_path
    nanopore_dir = normalise_path(nanopore_dir) if nanopore_dir else nanopore_dir
    kraken_db = normalise_path(kraken_db) if kraken_db else kraken_db
    if results_dir:
        results_dir = normalise_path(results_dir)

    # Validate required fields.
    if not nanopore_dir or not nanopore_dir.strip():
        errors.append("Nanopore Sequence Data Folder (input) is required")
    if not kraken_db or not kraken_db.strip():
        errors.append("Kraken2 Database is required")

    # Path/layout, database-format, and numeric-range checks. The legacy
    # min_identity input was collapsed into validation_identity_threshold on
    # 2026-04-30, so it has no separate validation here.
    errors += _validate_nanopore_dir(nanopore_dir, sample_handling, processing_mode)
    errors += _validate_kraken_db_path(kraken_db)
    errors += _validate_numeric_ranges(
        update_interval=update_interval,
        realtime_timeout_minutes=realtime_timeout_minutes,
        min_reads_per_level=min_reads_per_level,
        e_value_cutoff=e_value_cutoff,
        cores=cores,
        gui_port=gui_port,
        minimap2_min_mapq=minimap2_min_mapq,
        validation_identity=validation_identity,
        kraken2_confidence=kraken2_confidence,
        chopper_minlength=chopper_minlength,
        chopper_quality=chopper_quality,
        filtlong_minlength=filtlong_minlength,
        max_file_age_minutes=max_file_age_minutes,
        min_reads_for_validation=min_reads_for_validation,
        chopper_maxlength=chopper_maxlength,
        kraken2_hitgroups=kraken2_hitgroups,
    )

    # If there are validation errors, return them
    if errors:
        return None, errors

    # Create a completely new config object to avoid reference issues
    config = dict(current_config)

    # Update fields if they have valid values
    if analysis_name is not None:
        config["analysis_name"] = analysis_name

    if nanopore_dir is not None:
        config["nanopore_output_directory"] = nanopore_dir

    if kraken_db is not None:
        config["kraken_db"] = kraken_db

    # Results directory. The form field is the operator OVERRIDE: empty =
    # derive <project>/results/<run-name slug> from analysis_name; a path =
    # use verbatim. We store it in results_dir_override and (re)compute the
    # concrete results_output_directory from it. Because the override is
    # kept separate, changing the Run name and re-applying always moves the
    # run folder -- the previously-derived path never sticks.
    from nanometa_live.app.utils.outdir_resolution import resolve_run_outdir
    config["results_dir_override"] = (results_dir or "").strip()
    config["results_output_directory"] = resolve_run_outdir(config)

    if update_interval is not None:
        config["update_interval_seconds"] = update_interval

    # Empty/None -> null (run indefinitely); numeric -> int
    config["realtime_timeout_minutes"] = (
        int(realtime_timeout_minutes)
        if realtime_timeout_minutes not in (None, "")
        else None
    )

    if min_reads_per_level is not None:
        config["default_reads_per_level"] = min_reads_per_level

    # Handle boolean values consistently as true/false
    if memory_mapping is not None:
        config["kraken_memory_mapping"] = bool(memory_mapping)

    if blast_validation is not None:
        config["blast_validation"] = bool(blast_validation)

    if validation_method is not None:
        config["validation_method"] = validation_method

    if minimap2_preset is not None:
        config["minimap2_preset"] = minimap2_preset

    if minimap2_min_mapq is not None:
        config["minimap2_min_mapq"] = minimap2_min_mapq

    # min_perc_identity is now sourced from validation_identity_threshold
    # (single canonical input in the Read Filtering and Validation card).
    # See parameter_mapping.create_nextflow_params -- both nanometanf
    # params (blast_perc_identity AND validation_identity_threshold)
    # are populated from the same operator-facing value.

    if e_value_cutoff is not None:
        config["e_val_cutoff"] = e_value_cutoff

    if genome_cache_dir is not None and genome_cache_dir.strip():
        config["genome_cache_dir"] = genome_cache_dir.strip()

    # The CPU Cores field is nanometanf's --max_cpus, the one CPU knob the
    # pipeline documents (its Kraken2 directive scales from it). The former
    # pipeline_cores / validation_cores / blast_cores keys reached nothing:
    # the first was never read by the launcher and the other two pinned
    # cpus on process names that do not exist (audit round 5, A9 and A9b).
    # Empty means the pipeline default and is stored as None.
    config["max_cpus"] = optional_int(cores)

    if gui_port is not None:
        config["gui_port"] = int(gui_port)


    if pipeline_profile is not None:
        config["pipeline_profile"] = pipeline_profile

    # Build pipeline_source from source type, branch, and local path
    if pipeline_source_type == "remote":
        # Use remote repository with selected branch
        branch = pipeline_branch if pipeline_branch else "master"
        config["pipeline_source"] = f"remote:{branch}"
    elif pipeline_source_type == "local" and pipeline_local_path:
        # Validate local path exists
        if not os.path.isdir(pipeline_local_path):
            errors.append(f"Local pipeline path does not exist: {pipeline_local_path}")
        else:
            config["pipeline_source"] = pipeline_local_path
    elif pipeline_source_type == "local":
        # Local selected but no path given: fail loudly instead of
        # silently leaving the previous pipeline_source in place.
        errors.append("Local pipeline path is required when 'Local Path' is selected")

    # Input mode settings
    if processing_mode is not None:
        config["processing_mode"] = processing_mode

    if sample_handling is not None:
        config["sample_handling"] = sample_handling

    if sample_name is not None:
        config["sample_name"] = sample_name if sample_name.strip() else "sample"
    # Normalised to a list of trimmed names. The dropdown yields a list, but a
    # config edited by hand may hold a string, and is_negative_control matches
    # exactly -- so untrimmed or scalar values would look declared and do
    # nothing.
    if negative_controls is not None:
        if isinstance(negative_controls, str):
            negative_controls = [negative_controls]
        config["negative_control_samples"] = [
            str(s).strip() for s in negative_controls if str(s).strip()
        ]

    # Pipeline options
    if qc_tool is not None:
        config["qc_tool"] = qc_tool
    if skip_nanoplot is not None:
        config["skip_nanoplot"] = bool(skip_nanoplot)
    if kraken2_incremental is not None:
        config["kraken2_enable_incremental"] = bool(kraken2_incremental)
    if enable_krona is not None:
        config["enable_krona_plots"] = bool(enable_krona)
    if enable_nanopore_stats is not None:
        config["enable_nanopore_stats_mqc"] = bool(enable_nanopore_stats)

    # Read filtering and validation overrides for amplicon support.
    # See docs/audit-2026-04-29-short-amplicons.md for the rationale
    # behind making each of these operator-tunable.
    if chopper_minlength is not None:
        config["chopper_minlength"] = int(chopper_minlength)
    if chopper_quality is not None:
        config["chopper_quality"] = int(chopper_quality)
    # An empty field is "no limit", stored as None so the saved config and
    # the form compare equal (the dirty check) and the launch omits it.
    config["chopper_maxlength"] = optional_int(chopper_maxlength)
    if filtlong_minlength is not None:
        config["filtlong_min_length"] = int(filtlong_minlength)
    if validation_identity is not None:
        config["validation_identity_threshold"] = float(validation_identity)
    if kraken2_confidence is not None:
        config["kraken2_confidence"] = float(kraken2_confidence)
    if kraken2_hitgroups is not None and kraken2_hitgroups != "":
        config["kraken2_minimum_hit_groups"] = int(kraken2_hitgroups)

    # Newly exposed settings (2026-05-31).
    # Empty means "process every pre-existing file", stored as None so the
    # saved config and the form compare equal and the launch omits it.
    config["max_file_age_minutes"] = optional_int(max_file_age_minutes)
    if min_reads_for_validation is not None:
        config["min_reads_for_validation"] = int(min_reads_for_validation)

    # Assembly (experimental nanometanf step; Reports tab renders the stats).
    if enable_assembly is not None:
        config["enable_assembly"] = bool(enable_assembly)
    if assembler is not None:
        config["assembler"] = assembler if assembler in ("flye", "miniasm") else "flye"
    if assembly_scope is not None:
        config["assembly_scope"] = (
            assembly_scope if assembly_scope in ("metagenome", "targeted", "both")
            else "metagenome")
    if assembly_min_depth not in (None, ""):
        config["assembly_min_depth"] = float(assembly_min_depth)
    if assembly_allow_low_depth is not None:
        config["assembly_allow_low_depth"] = bool(assembly_allow_low_depth)

    # Note: Species watchlist is now managed via the Watchlist & Preparation tab
    # and WatchlistManager, not through this config form

    # Apply Settings is the operator's explicit signal that they
    # are taking ownership of pipeline configuration, not just
    # browsing existing results. Clear visualization_only so the
    # Start Analysis button, header status, and dashboard cards
    # come back online. The flag is set in __main__.py whenever
    # the app is launched with --main_dir; without this clear, an
    # operator who opened the app on an existing outdir to peek
    # at the data would have no way to launch a new run from the
    # GUI without restarting the process.
    if (
        config.get("nanopore_output_directory")
        and config.get("kraken_db")
        and config.get("visualization_only")
    ):
        config["visualization_only"] = False

    # Canonicalise every path-bearing value: strip whitespace,
    # expand "~", and resolve to an absolute path. Prevents the
    # most common cause of "Kraken2 database directory not found"
    # at launch time, where a literal "~/data/..." string never
    # passes os.path.exists. See core/utils/path_utils.py.
    from nanometa_live.core.utils.path_utils import normalise_config_paths
    normalise_config_paths(config)

    # If validation errors occurred during pipeline source setup, return them
    if errors:
        return None, errors

    return config, []


def _pipeline_source_from_form(source_type, branch, local_path):
    """Reconstruct the stored ``pipeline_source`` string from the three form
    fields, mirroring build_config_from_form (remote:<branch> or a normalised
    local path)."""
    if source_type == "remote":
        return f"remote:{branch or 'master'}"
    if source_type == "local" and local_path:
        from nanometa_live.core.utils.path_utils import normalise_path
        return normalise_path(local_path)
    return ""


def config_form_dirty(snapshot, *, form):
    """Return True when the form state differs from the saved snapshot.

    ``form`` is the dict of current widget values keyed by config name. This
    mirrors what build_config_from_form would write, so the "Modified" badge
    reflects every operator-editable field -- the prior inline detector watched
    only a subset, leaving ~14 fields (processing mode, sample handling,
    pipeline source, the QC/feature toggles, ...) able to change silently.
    """
    if not snapshot:
        return False

    bool_keys = {
        "kraken_memory_mapping", "blast_validation",
        "skip_nanoplot", "kraken2_enable_incremental", "enable_krona_plots",
        "enable_nanopore_stats_mqc", "enable_assembly",
        "assembly_allow_low_depth",
    }
    for key, current_val in form.items():
        snapshot_val = snapshot.get(key)
        if key == "kraken_memory_mapping" and key not in snapshot:
            # Deliberately absent from create_default_config (the resolver's
            # "explicit override wins" rule); the resolver treats absent as
            # True, so the switch's default must compare equal to it.
            snapshot_val = True
        if key in bool_keys:
            current_val = bool(current_val)
            if isinstance(snapshot_val, str):
                snapshot_val = snapshot_val.lower() in (
                    "true", "yes", "y", "1", "--memory-mapping"
                )
            else:
                snapshot_val = bool(snapshot_val)
        if current_val is None and snapshot_val is None:
            continue
        if current_val != snapshot_val:
            return True
    return False


def _existing_session_watchlist(configs_dir):
    """Return the ``watchlist`` block already persisted in last-session.yaml, or
    None. Used to avoid clobbering it when autosave runs where the
    WatchlistManager singleton is empty (a background worker).
    """
    import yaml
    from pathlib import Path
    session_path = Path(configs_dir) / "last-session.yaml"
    if not session_path.exists():
        return None
    try:
        data = yaml.safe_load(session_path.read_text()) or {}
        return data.get("watchlist")
    except (OSError, yaml.YAMLError):
        return None


def autosave_session_config(config):
    """Persist the applied config (plus current watchlist) to last-session.yaml.

    Best-effort: any failure is logged and swallowed so a save problem never
    blocks the operator's Apply Settings action.
    """
    try:
        from nanometa_live.core.config.config_loader import ConfigLoader
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
        save_config = dict(config)
        from nanometa_live.core.utils.paths import NanometaPaths
        paths = NanometaPaths.from_config(save_config)
        # Include current watchlist state if loaded. When the singleton is empty
        # -- e.g. this runs in a DiskcacheManager background worker, whose
        # WatchlistManager is a fresh, unloaded instance in a separate process
        # -- do NOT overwrite the watchlist away: preserve whatever
        # last-session.yaml already holds, since the worker's action (a Kraken2
        # DB download) does not change the watchlist.
        manager = get_watchlist_manager()
        if manager._loaded:
            save_config["watchlist"] = manager.export_config()
        else:
            existing = _existing_session_watchlist(paths.configs)
            if existing is not None:
                save_config["watchlist"] = existing
        loader = ConfigLoader(str(paths.configs))
        loader.save_config(save_config, "last-session.yaml")
        logging.debug("Auto-saved configuration to last-session.yaml")
    except Exception as e:
        logging.warning(f"Failed to auto-save configuration: {e}")


def _build_config_list_items(configs):
    """Build ListGroupItem components for a list of config metadata dicts."""
    items = []
    for i, config in enumerate(configs):
        timestamp = config.get("timestamp", "Unknown")
        try:
            dt = datetime.fromisoformat(timestamp)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

        filename = config.get("filename", "Unknown")
        is_autosave = filename == "last-session.yaml"

        buttons = [
            dbc.Button(
                "Load",
                id={"type": "load-config-item", "index": i},
                color="primary",
                size="sm",
                className="me-1",
            ),
        ]
        if not is_autosave:
            buttons.append(
                dbc.Button(
                    html.I(className="bi bi-trash"),
                    id={"type": "delete-config-item", "index": i},
                    color="danger",
                    outline=True,
                    size="sm",
                    title="Delete this preset",
                )
            )

        display_name = config.get("name", "Unnamed Configuration")
        if is_autosave:
            display_name = "Last Session (auto-saved)"

        items.append(dbc.ListGroupItem(
            [
                html.Div([
                    html.H5(display_name, className="mb-1"),
                    html.Small(f"Created: {timestamp}", className="text-muted"),
                ]),
                html.Div(buttons, className="d-flex align-items-center"),
            ],
            className="d-flex justify-content-between align-items-center",
        ))
    return items


# Keys that name where the RUNNING pipeline reads and writes. Apply must not
# move them under a live run: the viewer would follow the new
# results_output_directory to an empty folder while the pipeline kept writing
# to the old one, and the header would count a different inbox.
# results_dir_override rides along with the computed directory: pinning only
# the latter left a mid-run Apply free to move where the NEXT run writes, so
# the operator who changed the folder mid-run got no collision modal and no
# Continue on the folder they were watching (round-5 drills, RT4).
RUNNING_RUN_PATH_KEYS = (
    "results_output_directory",
    "results_dir_override",
    "nanopore_output_directory",
)


def pin_running_run_paths(config, current_config, backend_status) -> bool:
    """Keep the live run's input and results folders while it runs.

    ``build_config_from_form`` recomputes ``results_output_directory`` from
    the analysis name on every Apply, and Apply had no view of the backend
    (round-4 audit, H11). While ``backend_status.running`` is set, the two
    path keys are restored from ``current_config`` in place. Returns True
    when a running run was found (whether or not any value differed), so the
    caller can word its confirmation accordingly.
    """
    if not (backend_status or {}).get("running"):
        return False
    for key in RUNNING_RUN_PATH_KEYS:
        live = (current_config or {}).get(key)
        if live:
            config[key] = live
    return True

