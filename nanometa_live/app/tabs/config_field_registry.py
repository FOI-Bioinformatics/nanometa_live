"""Single source of truth for the Configuration-form field set.

The Configuration tab references the same set of form widgets from four places
that historically drifted by hand (see CLAUDE.md "save / load / dirty-state
symmetry"):

1. ``apply_config_changes``        -- reads them as ``State`` to build the saved config.
2. ``initialize_form_from_config`` -- writes them as ``Output`` from the config.
3. ``detect_form_changes``         -- reads them as ``Input`` to flag "Modified" and build the autosave draft.
4. ``build_config_from_form``      -- assembles the config dict from the same values.

A field added to one list but not the others silently mis-reports the form or
launches a stale config. This registry is the one place the field set lives;
``tests/test_config_field_registry.py`` asserts every consumer matches it, so a
future divergence fails CI instead of shipping silently.

Every Configuration-form widget uses the component id ``"<name>-input"`` with
the Dash ``value`` property; each entry pairs that id with the keyword
``build_config_from_form`` (and the ``apply``/``detect`` callback signatures)
expect. Order follows ``apply_config_changes``; the set -- not the order -- is
what the consumers must agree on (the three callbacks legitimately list the
widgets in slightly different orders).
"""

#: Ordered ``(component_id, build_config_from_form keyword)`` for every
#: operator-editable Configuration-form widget.
CONFIG_FORM_FIELDS = (
    ("analysis-name-input", "analysis_name"),
    ("nanopore-dir-input", "nanopore_dir"),
    ("kraken-db-input", "kraken_db"),
    ("results-dir-input", "results_dir"),
    ("update-interval-input", "update_interval"),
    ("danger-threshold-input", "danger_threshold"),
    ("kraken-taxonomy-input", "taxonomy"),
    ("check-interval-input", "check_interval"),
    ("realtime-timeout-minutes-input", "realtime_timeout_minutes"),
    ("min-reads-per-level-input", "min_reads_per_level"),
    ("memory-mapping-input", "memory_mapping"),
    ("blast-validation-input", "blast_validation"),
    ("validation-method-input", "validation_method"),
    ("e-value-cutoff-input", "e_value_cutoff"),
    ("genome-cache-dir-input", "genome_cache_dir"),
    ("cores-input", "cores"),
    ("gui-port-input", "gui_port"),
    ("clean-temp-input", "clean_temp"),
    ("pipeline-profile-input", "pipeline_profile"),
    ("pipeline-source-type-input", "pipeline_source_type"),
    ("pipeline-branch-input", "pipeline_branch"),
    ("minimap2-preset-input", "minimap2_preset"),
    ("minimap2-min-mapq-input", "minimap2_min_mapq"),
    ("pipeline-local-path-input", "pipeline_local_path"),
    ("processing-mode-input", "processing_mode"),
    ("sample-handling-input", "sample_handling"),
    ("sample-name-input", "sample_name"),
    ("qc-tool-input", "qc_tool"),
    ("skip-nanoplot-input", "skip_nanoplot"),
    ("kraken2-incremental-input", "kraken2_incremental"),
    ("enable-krona-input", "enable_krona"),
    ("enable-nanopore-stats-input", "enable_nanopore_stats"),
    ("chopper-minlength-input", "chopper_minlength"),
    ("chopper-quality-input", "chopper_quality"),
    ("filtlong-minlength-input", "filtlong_minlength"),
    ("validation-identity-input", "validation_identity"),
    ("kraken2-confidence-input", "kraken2_confidence"),
    ("kraken2-hitgroups-input", "kraken2_hitgroups"),
    ("max-file-age-input", "max_file_age_minutes"),
    ("min-reads-for-validation-input", "min_reads_for_validation"),
)

#: Component ids of all Configuration-form widgets (order-independent set).
FORM_FIELD_IDS = frozenset(cid for cid, _ in CONFIG_FORM_FIELDS)

#: ``build_config_from_form`` keyword names for the form fields.
FORM_FIELD_KWARGS = frozenset(kw for _, kw in CONFIG_FORM_FIELDS)
