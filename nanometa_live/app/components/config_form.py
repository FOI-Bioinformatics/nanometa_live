"""
Configuration form component for Nanometa Live v2.0.

The form is organised into three visible tiers so the controls an operator
needs are not buried:

- **Essential Settings** (always visible): input/output folders, species
  database, processing mode, sample handling, how tools are run.
- **Confirmation Testing** (always visible): the validation on/off switch and
  its companion thresholds. Validation is a primary clinical control, so it is
  surfaced rather than hidden in Advanced.
- **Advanced Settings** (a multi-item accordion, collapsed by default): one
  navigable section per concern -- Pipeline Source, Database, Processing, Read
  Filtering, Analysis Options, Display, Performance.

Species watchlist management is handled in the dedicated Watchlist tab.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_config_form():
    """
    Create the configuration form.

    Returns:
        A dash component representing the configuration form
    """
    return html.Div([
        _essential_settings_card(),
        _confirmation_testing_card(),
        dbc.Accordion(
            [
                _pipeline_source_item(),
                _database_settings_item(),
                _processing_settings_item(),
                _read_filtering_item(),
                _analysis_options_item(),
                _display_settings_item(),
                _performance_item(),
            ],
            start_collapsed=True,
            always_open=False,
            className="mb-4",
        ),
    ])


def _essential_settings_card():
    """Essential settings: always visible. Start-here card."""
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-gear-fill me-2", style={"fontSize": "20px"}),
                html.H5("Essential Settings", className="mb-0 d-inline"),
                dbc.Badge("Start here", color="primary", className="ms-2",
                          style={"fontSize": "0.7rem", "verticalAlign": "middle"})
            ], className="d-flex align-items-center")
        ]),
        dbc.CardBody([
            # Data Directory.
            # Label clarified 2026-05-07: "Nanopore Output Directory"
            # was easily confused with "Results Output Directory"
            # because both contained the word *output*. The new label
            # tags this field as INPUT to Nanometa Live (= the
            # sequencer's output directory) so operators do not mix
            # them up. The underlying config key
            # ``nanopore_output_directory`` is unchanged.
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Nanopore Sequence Data Folder ",
                        dbc.Badge("input", color="info", className="me-1",
                                  style={"fontSize": "0.65rem", "verticalAlign": "middle"}),
                        html.Span("*", className="text-danger"),
                        html.I(className="bi bi-info-circle text-muted ms-1", id="nanopore-dir-info")
                    ], html_for="nanopore-dir-input"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="nanopore-dir-input",
                            type="text",
                            placeholder="/path/to/nanopore/output"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                            id="browse-nanopore-dir",
                            color="secondary",
                            outline=True
                        ),
                        dbc.InputGroupText(
                            html.Span(id="nanopore-dir-status", children="")
                        )
                    ]),
                    dbc.FormText([
                        html.I(className="bi bi-arrow-down-circle me-1"),
                        "Where the sequencer writes FASTQ files; this is the input "
                        "Nanometa Live reads from.",
                    ]),
                    dbc.Tooltip(
                        "The folder where your sequencer writes data files. "
                        "Look for a folder containing .fastq or .fastq.gz files. "
                        "This is the INPUT to Nanometa Live, not where results go.",
                        target="nanopore-dir-info"
                    ),
                    html.Div(id="nanopore-dir-feedback", className="mt-1")
                ], md=12)
            ], className="mb-4"),

            # Input Mode Section
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.I(className="bi bi-sliders me-2", style={"fontSize": "16px"}),
                        html.Strong("Input Mode Settings", className="mb-0 d-inline")
                    ], className="d-flex align-items-center mb-2 text-muted"),
                ], md=12)
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Processing Mode ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="processing-mode-info")
                    ], html_for="processing-mode-input"),
                    dbc.Select(
                        id="processing-mode-input",
                        options=[
                            {"label": "Batch (process existing files)", "value": "batch"},
                            {"label": "Realtime (watch for new files)", "value": "realtime"}
                        ],
                        value="batch"
                    ),
                    dbc.Tooltip(
                        "Batch: Process all existing files at once. "
                        "Realtime: Continuously watch for new files during active sequencing.",
                        target="processing-mode-info"
                    ),
                    dbc.FormText("Batch is recommended for completed sequencing runs")
                ], md=4),
                dbc.Col([
                    dbc.Label([
                        "Sample Handling ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="sample-handling-info")
                    ], html_for="sample-handling-input"),
                    dbc.Select(
                        id="sample-handling-input",
                        options=[
                            {
                                "label": "single_sample - one merged sample (flat folder, e.g. nanorunner singleplex)",
                                "value": "single_sample",
                            },
                            {
                                "label": "per_file - each file is its own sample (flat folder)",
                                "value": "per_file",
                            },
                            {
                                "label": "by_barcode - multiplexed (barcode01/, barcode02/, ...)",
                                "value": "by_barcode",
                            },
                        ],
                        value="by_barcode"
                    ),
                    dbc.Tooltip(
                        "single_sample: all FASTQ files in one flat folder are pooled into a single sample "
                        "(matches nanorunner singleplex output). "
                        "per_file: each FASTQ file in a flat folder is its own sample. "
                        "by_barcode: each barcode<NN>/ subdirectory is one sample (multiplexed run).",
                        target="sample-handling-info"
                    ),
                    # Auto-detect preview line, populated by a callback
                    # in config_tab.py that watches the Nanopore Sequence
                    # Data Folder input and the sample-handling selection.
                    # Empty until a path is entered.
                    html.Div(
                        id="sample-handling-autodetect",
                        className="mt-1",
                        children="",
                    ),
                    dbc.FormText("How to group input files into samples"),
                ], md=4),
                dbc.Col([
                    dbc.Label([
                        "Sample Name ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="sample-name-info")
                    ], html_for="sample-name-input"),
                    dbc.Input(
                        id="sample-name-input",
                        type="text",
                        value="sample",
                        placeholder="sample"
                    ),
                    dbc.Tooltip(
                        "Name to use when all files belong to one sample. "
                        "Only used with 'Single sample' handling mode.",
                        target="sample-name-info"
                    ),
                    dbc.FormText("Used when 'Single sample' is selected")
                ], md=4, id="sample-name-col")
            ], className="mb-4"),

            # Kraken2 Database
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Species Identification Database ",
                        html.Span("*", className="text-danger"),
                        html.I(className="bi bi-info-circle text-muted ms-1", id="kraken-db-info")
                    ], html_for="kraken-db-input"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="kraken-db-input",
                            type="text",
                            placeholder="/path/to/kraken2/database"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                            id="browse-kraken-db",
                            color="secondary",
                            outline=True
                        ),
                        dbc.InputGroupText(
                            html.Span(id="kraken-db-status", children="")
                        )
                    ]),
                    dbc.Tooltip(
                        "Folder containing the Kraken2 reference database used to identify organisms. "
                        "If you do not have one, download it from the Preparation tab.",
                        target="kraken-db-info"
                    ),
                    html.Div(id="kraken-db-feedback", className="mt-1")
                ], md=12)
            ], className="mb-4"),

            # Run name. Surfaced here (moved out of Advanced) because it now
            # names this run's results folder: <project>/results/<run name>.
            # The backend key remains ``analysis_name``.
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Run name ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="analysis-name-info")
                    ], html_for="analysis-name-input"),
                    dbc.Input(
                        id="analysis-name-input",
                        type="text",
                        placeholder="e.g. patient_0042_blood",
                    ),
                    dbc.FormText([
                        html.I(className="bi bi-folder me-1"),
                        "Names this run's results folder under the project's "
                        "results/ directory. Spaces and symbols are simplified "
                        "to a safe folder name.",
                    ]),
                    dbc.Tooltip(
                        "A short label for this analysis run. It becomes the "
                        "results folder (project/results/<run name>) so each "
                        "run is kept separate. Reusing a name reuses that "
                        "folder (you will be prompted to archive or resume).",
                        target="analysis-name-info"
                    ),
                ], md=12)
            ], className="mb-4"),

            # Results folder -- optional override. Empty means the per-run
            # folder is derived from the Run name above
            # (<project>/results/<run name>). Backend key
            # ``results_output_directory`` is unchanged.
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Results folder ",
                        dbc.Badge("advanced override", color="secondary", className="me-1",
                                  style={"fontSize": "0.65rem", "verticalAlign": "middle"}),
                        html.I(className="bi bi-info-circle text-muted ms-1", id="results-dir-info")
                    ], html_for="results-dir-input"),
                    dbc.InputGroup([
                        dbc.Input(
                            id="results-dir-input",
                            type="text",
                            placeholder="Leave empty to use <project>/results/<run name>"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                            id="browse-results-dir",
                            color="secondary",
                            outline=True
                        ),
                        dbc.InputGroupText(
                            html.Span(id="results-dir-status", children="")
                        )
                    ]),
                    dbc.Tooltip(
                        "Leave empty (recommended) to keep results inside the "
                        "project at results/<run name>. Set an explicit path "
                        "only to write somewhere else, e.g. a scratch disk. "
                        "This is OUTPUT, not the sequencer's data folder.",
                        target="results-dir-info"
                    ),
                    dbc.FormText([
                        html.I(className="bi bi-arrow-up-circle me-1"),
                        "Leave empty to use the project's results/<run name> "
                        "folder. Created if it does not exist.",
                    ]),
                    # Advisory warning when the chosen folder already holds
                    # results (populated by validate_results_directory).
                    html.Div(id="results-dir-feedback", className="mt-1"),
                ], md=12)
            ], className="mb-4"),

            # Pipeline Profile (essential - determines how pipeline runs).
            # Default is ``conda`` per the project convention documented in
            # CLAUDE.md ("pipeline_profile: conda; always conda for
            # nanometanf"). Conda is reordered to the top and marked
            # Recommended; Docker is kept as a secondary option for
            # workstations that already have Docker Desktop installed.
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "How tools are run ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="profile-info")
                    ], html_for="pipeline-profile-input"),
                    dbc.Select(
                        id="pipeline-profile-input",
                        options=[
                            {"label": "Conda (recommended)", "value": "conda"},
                            {"label": "Docker", "value": "docker"},
                            {"label": "Singularity (HPC)", "value": "singularity"},
                            {"label": "Local (tools already on PATH)", "value": "standard"}
                        ],
                        value="conda",
                        persistence=True,
                        persistence_type="session",
                    ),
                    dbc.Tooltip(
                        "How pipeline tools (Kraken2, fastp, BLAST, etc.) are "
                        "supplied to the Nextflow run. "
                        "Conda: builds isolated environments per tool from a "
                        "lockfile -- the canonical setup for nanometanf and "
                        "the only profile this project tests against. "
                        "Docker: pulls pre-built images; faster startup but "
                        "needs Docker Desktop running. "
                        "Singularity: HPC clusters. "
                        "Local: tools must already be installed in your PATH.",
                        target="profile-info"
                    ),
                    dbc.FormText("Conda is the canonical setup; switch only if Conda is unavailable")
                ], md=12)
            ], className="mb-4"),

        ])
    ], className="mb-4", style={"boxShadow": "0 4px 6px rgba(0,0,0,0.1)"})


def _confirmation_testing_card():
    """
    Confirmation Testing (validation): always visible.

    Promoted out of Advanced Settings -- the validation on/off switch is a
    primary clinical control, so the operator should not have to expand an
    accordion to find it. All validation controls live here together,
    including the percent-identity threshold that previously sat in the Read
    Filtering card.
    """
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-shield-check me-2"),
            html.H5("Confirmation Testing", className="mb-0 d-inline"),
            dbc.Badge("Validation", color="info", className="ms-2",
                      style={"fontSize": "0.7rem", "verticalAlign": "middle"}),
            html.I(className="bi bi-info-circle text-muted ms-2",
                   id="validation-section-info",
                   style={"fontSize": "0.85rem", "cursor": "help"}),
            dbc.Tooltip(
                "After initial species identification, confirmation testing "
                "compares DNA sequences against known reference genomes to "
                "verify results. This reduces false positives.",
                target="validation-section-info",
            ),
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    # Enabled by default. The on-demand validation
                    # path now uses ``nextflow run -resume`` against
                    # nanometanf so previously-validated taxids hit
                    # the work cache and only the new pair runs --
                    # cheap enough to be on by default. Operators
                    # who want pure classification can still toggle
                    # this off.
                    dbc.Switch(
                        id="blast-validation-input",
                        label="Enable confirmation testing",
                        value=True
                    ),
                    dbc.FormText("Double-check detected species against reference genomes")
                ], md=4),
                dbc.Col([
                    dbc.Label([
                        "Confirmation Method ",
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="validation-method-info"),
                    ], html_for="validation-method-input"),
                    dcc.Dropdown(
                        id="validation-method-input",
                        options=[
                            {"label": "Genome alignment (recommended)", "value": "minimap2"},
                            {"label": "Sequence search", "value": "blast"},
                            {"label": "Both (highest confidence, 2x compute)", "value": "both"}
                        ],
                        # Default to minimap2: fast, ONT-optimised,
                        # gives coverage-depth plots + mapping
                        # confidence. BLAST is more thorough but
                        # 5-10x slower per pair. Operators can
                        # switch to "Both" when sample volume is
                        # low and final-confidence matters.
                        value="minimap2",
                        clearable=False
                    ),
                    dbc.Tooltip(
                        "Sequence search (BLAST) checks individual DNA reads against "
                        "a reference. Genome alignment (minimap2) maps reads to a full "
                        "genome. Using both gives the highest confidence.",
                        target="validation-method-info"
                    )
                ], md=4),
                dbc.Col([
                    dbc.Label([
                        "Strictness Filter ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="evalue-info")
                    ], html_for="e-value-cutoff-input"),
                    dbc.Input(
                        id="e-value-cutoff-input",
                        type="number",
                        min=0,
                        max=1,
                        step=0.001,
                        value=0.01
                    ),
                    dbc.FormText("0.01 is recommended"),
                    dbc.Tooltip(
                        "Controls how strict sequence matching is. "
                        "Lower values are stricter (fewer false positives). "
                        "0.01 is recommended for most uses.",
                        target="evalue-info"
                    )
                ], md=4)
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Sequencing Platform ",
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="minimap2-preset-info"),
                    ], html_for="minimap2-preset-input"),
                    dbc.Select(
                        id="minimap2-preset-input",
                        options=[
                            {"label": "Oxford Nanopore (default)", "value": "map-ont"},
                            {"label": "Short reads <500 bp (amplicons)", "value": "sr"},
                            {"label": "PacBio HiFi", "value": "map-hifi"},
                            {"label": "PacBio CLR", "value": "map-pb"}
                        ],
                        value="map-ont"
                    ),
                    dbc.FormText("Select your sequencing instrument type or sr for short amplicons"),
                    dbc.Tooltip(
                        "Choose the sequencing technology that produced your data. "
                        "Use 'Short reads' (sr) for amplicons under ~500 bp where "
                        "the long-read preset under-aligns. "
                        "This adjusts alignment sensitivity to match the error profile "
                        "of your instrument.",
                        target="minimap2-preset-info"
                    )
                ], md=6),
                dbc.Col([
                    dbc.Label([
                        "Alignment Confidence ",
                        html.I(className="bi bi-info-circle text-muted ms-1", id="mapq-info")
                    ], html_for="minimap2-min-mapq-input"),
                    dbc.Input(
                        id="minimap2-min-mapq-input",
                        type="number",
                        min=0,
                        max=60,
                        step=1,
                        value=30
                    ),
                    dbc.FormText("30 is recommended (scale 0-60)"),
                    dbc.Tooltip(
                        "Minimum confidence score (0-60) for genome alignments. "
                        "Higher values keep only highly confident matches. "
                        "30 is recommended; use 0 to accept all.",
                        target="mapq-info"
                    )
                ], md=6)
            ], className="mt-3"),
            # Percent-identity threshold (moved here from the Read Filtering
            # card on 2026-05-31 so every validation control lives together)
            # and the minimum-read gate for the on-demand Validate button.
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Validation identity threshold (%) ",
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="validation-identity-info"),
                    ], html_for="validation-identity-input"),
                    dbc.Input(
                        id="validation-identity-input",
                        type="number",
                        min=0,
                        max=100,
                        step=1,
                        value=90,
                    ),
                    dbc.FormText("Percent identity required to confirm a read (try 80 for amplicons)"),
                    dbc.Tooltip(
                        "Minimum percent identity for a read to "
                        "count as confirming validation. The 90% "
                        "default is hard for short ONT reads to "
                        "clear because Q-score noise hits short "
                        "reads proportionally harder. Try 80% for "
                        "amplicons.",
                        target="validation-identity-info",
                    ),
                ], md=6),
                dbc.Col([
                    dbc.Label([
                        "Minimum reads to offer validation ",
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="min-reads-for-validation-info"),
                    ], html_for="min-reads-for-validation-input"),
                    dbc.Input(
                        id="min-reads-for-validation-input",
                        type="number",
                        min=1,
                        step=1,
                        value=50,
                    ),
                    dbc.FormText("On-demand Validate appears once an organism has this many reads"),
                    dbc.Tooltip(
                        "An organism must have at least this many classified "
                        "reads before the on-demand Validate action is offered "
                        "on the Organisms tab. Too few reads give an unreliable "
                        "alignment. Default: 50.",
                        target="min-reads-for-validation-info",
                    ),
                ], md=6),
            ], className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label([
                        "Reference Genome Storage ",
                        html.I(className="bi bi-info-circle text-muted ms-1",
                               id="genome-cache-info"),
                    ], html_for="genome-cache-dir-input"),
                    dbc.Input(
                        id="genome-cache-dir-input",
                        type="text",
                        value="~/.nanometa",
                        placeholder="Path to genome cache (default: ~/.nanometa)"
                    ),
                    dbc.FormText("Where downloaded reference genomes are stored on this computer"),
                    dbc.Tooltip(
                        "Folder where reference genomes are cached locally. "
                        "These are downloaded once and reused across analyses.",
                        target="genome-cache-info"
                    )
                ], md=12)
            ], className="mt-3"),
            html.Div([
                html.I(className="bi bi-info-circle me-2"),
                html.Span(
                    "Reference genomes are downloaded in the Preparation tab. "
                    "Enable the organisms you want to monitor in the Watchlist tab first.",
                    className="text-muted small"
                )
            ], className="mt-2")
        ])
    ], className="mb-4", style={"boxShadow": "0 4px 6px rgba(0,0,0,0.1)"})


def _pipeline_source_item():
    """Advanced: where the nanometanf pipeline is loaded from, plus offline mode."""
    return dbc.AccordionItem([
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Pipeline Location ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="pipeline-source-info")
                ], html_for="pipeline-source-type-input"),
                dbc.Select(
                    id="pipeline-source-type-input",
                    options=[
                        {"label": "Remote (GitHub)", "value": "remote"},
                        {"label": "Local Path", "value": "local"}
                    ],
                    value="remote"
                ),
                dbc.FormText("Where to load the nanometanf pipeline from"),
                dbc.Tooltip(
                    "Remote: Downloads from GitHub (requires internet). "
                    "Local: Use a local copy of the pipeline.",
                    target="pipeline-source-info"
                )
            ], md=4),
            dbc.Col([
                dbc.Label([
                    "Branch/Version ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="pipeline-branch-info")
                ], html_for="pipeline-branch-input"),
                dbc.Select(
                    id="pipeline-branch-input",
                    options=[
                        {"label": "master (Stable)", "value": "master"},
                        {"label": "dev (Development)", "value": "dev"}
                    ],
                    value="dev"
                ),
                dbc.FormText("Pipeline version to use"),
                dbc.Tooltip(
                    "master: Stable release, recommended for production. "
                    "dev: Latest features, may be less stable.",
                    target="pipeline-branch-info"
                )
            ], md=4, id="pipeline-branch-col"),
            dbc.Col([
                dbc.Label([
                    "Local Pipeline Path ",
                    html.Span(id="pipeline-path-status", className="ms-1")
                ], html_for="pipeline-local-path-input"),
                dbc.InputGroup([
                    dbc.Input(
                        id="pipeline-local-path-input",
                        type="text",
                        placeholder="/path/to/nanometanf"
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                        id="browse-pipeline-path",
                        color="secondary",
                        outline=True
                    )
                ]),
                dbc.FormText("Path to local nanometanf directory (must contain main.nf)")
            ], md=4, id="pipeline-local-path-col", style={"display": "none"})
        ]),
        # Note: offline mode is toggled from the header (live, with immediate
        # effect and persistence) rather than buried here -- see the
        # offline-mode-toggle switch and set_offline_mode callback.
        dbc.FormText(
            "Tip: toggle Offline mode from the switch in the header bar.",
            className="mt-2 d-block",
        ),
    ], title="Pipeline Source")


def _database_settings_item():
    """Advanced: database notes (taxonomy auto-detected) + hidden compat field."""
    return dbc.AccordionItem([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-info-circle text-info me-2"),
                    html.Span(
                        "Taxonomy mapping is handled automatically. "
                        "Database downloads are available in the Preparation tab.",
                        className="text-muted small"
                    )
                ], className="mt-2"),
            ], md=12),
        ]),
        # Hidden input to maintain backward compatibility
        dbc.Input(id="kraken-taxonomy-input", type="hidden", value="gtdb"),
    ], title="Database Settings")


def _processing_settings_item():
    """Advanced: run-level processing knobs."""
    return dbc.AccordionItem([
        # Note: the run name (analysis_name) moved to Essential Settings -- it
        # now names this run's results folder.
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Check Interval (seconds) ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="check-interval-info")
                ], html_for="check-interval-input"),
                dbc.Input(
                    id="check-interval-input",
                    type="number",
                    min=5,
                    max=300,
                    step=5,
                    value=15
                ),
                dbc.FormText("How often the pipeline checks for new input files"),
                dbc.Tooltip(
                    "Controls how frequently the Nextflow pipeline scans for new FASTQ files. "
                    "Lower values detect files faster but use more resources. "
                    "Different from the dashboard Update Interval which controls GUI refresh.",
                    target="check-interval-info"
                )
            ], md=6)
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Realtime Timeout (minutes) ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="realtime-timeout-minutes-info")
                ], html_for="realtime-timeout-minutes-input"),
                dbc.Input(
                    id="realtime-timeout-minutes-input",
                    type="number",
                    min=1,
                    max=10080,
                    step=1,
                    value=60,
                    placeholder="Leave empty to run indefinitely"
                ),
                dbc.FormText(
                    "Stop real-time monitoring after this many minutes without new files. "
                    "Empty = run until manually stopped."
                ),
                dbc.Tooltip(
                    "Only applies in real-time mode. The pipeline watches for new FASTQ files "
                    "and stops when no new files appear within this window. Maps to nanometanf's "
                    "--realtime_timeout_minutes. Default 60; clear the field for no timeout.",
                    target="realtime-timeout-minutes-info"
                )
            ], md=6),
            dbc.Col([
                dbc.Label([
                    "Maximum file age (minutes) ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="max-file-age-info")
                ], html_for="max-file-age-input"),
                dbc.Input(
                    id="max-file-age-input",
                    type="number",
                    min=0,
                    step=60,
                    value=1000000,
                    placeholder="Leave high to process all files"
                ),
                dbc.FormText("Realtime only: ignore input files older than this"),
                dbc.Tooltip(
                    "Only applies in real-time mode. Files whose modification "
                    "time is older than this many minutes are skipped, so a "
                    "fresh run does not reprocess stale data left in the input "
                    "folder. The default is intentionally very large so demo "
                    "and test data are not skipped; lower it (e.g. 10080 = 7 "
                    "days) for production monitoring.",
                    target="max-file-age-info"
                )
            ], md=6)
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Minimum Detection Count ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="min-reads-info")
                ], html_for="min-reads-per-level-input"),
                dbc.Input(
                    id="min-reads-per-level-input",
                    type="number",
                    min=1,
                    step=1,
                    value=10
                ),
                dbc.FormText("Hide organisms detected fewer times than this"),
                dbc.Tooltip(
                    "Organisms detected fewer times than this value are hidden "
                    "from the classification charts. Higher values reduce noise "
                    "but may hide rare species. Default: 10.",
                    target="min-reads-info"
                )
            ], md=6),
            dbc.Col([
                html.Div([
                    dbc.Switch(
                        id="memory-mapping-input",
                        label="Low-memory mode",
                        value=True,
                        className="mt-3"
                    ),
                    html.I(className="bi bi-info-circle text-muted ms-1", id="memory-mapping-info"),
                    dbc.Badge("Recommended", color="success", className="ms-2",
                              style={"fontSize": "0.65rem"}),
                ], className="d-flex align-items-center"),
                dbc.FormText("Uses less memory; recommended for laptops and field computers"),
                dbc.Tooltip(
                    "When enabled, the species database is read from disk instead of "
                    "being loaded entirely into memory. Recommended for portable "
                    "computers and large databases.",
                    target="memory-mapping-info"
                )
            ], md=6)
        ])
    ], title="Processing Settings")


def _read_filtering_item():
    """
    Advanced: amplicon-friendly overrides for the long-read defaults.

    Operators running V3-V4 / 16S / ITS amplicons (any read pile under 1 kb)
    need to relax the chopper / filtlong length filter or all reads are dropped
    at QC. See docs/audit-2026-04-29-short-amplicons.md for the rationale. The
    validation percent-identity field that used to live here moved to the
    Confirmation Testing card so all validation controls are together.
    """
    return dbc.AccordionItem([
        dbc.Alert(
            [
                html.I(className="bi bi-info-circle me-2"),
                html.Strong("For amplicon or short-read protocols: "),
                "lower the length filter. The defaults below assume ONT "
                "whole-genome reads (5-50 kb). The validation identity "
                "threshold is in the Confirmation Testing section above.",
            ],
            color="light",
            className="small py-2 mb-3 border",
        ),

        # Row 1: chopper / filtlong length filters
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Chopper minimum length (bp) ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="chopper-minlength-info"),
                ], html_for="chopper-minlength-input"),
                dbc.Input(
                    id="chopper-minlength-input",
                    type="number",
                    min=0,
                    max=50000,
                    step=50,
                    value=1000,
                ),
                dbc.FormText("Reads shorter than this are dropped (set to 100 for V3-V4 amplicons; 0 disables)"),
                dbc.Tooltip(
                    "Chopper's --minlength filter. Default 1000 is "
                    "tuned for whole-genome ONT reads. For V3-V4 "
                    "(~460 bp) set to 100; for ITS/16S amplicons "
                    "use 250-500. Set to 0 to disable length "
                    "filtering entirely.",
                    target="chopper-minlength-info",
                ),
            ], md=4),
            dbc.Col([
                dbc.Label([
                    "Chopper minimum quality (Q) ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="chopper-quality-info"),
                ], html_for="chopper-quality-input"),
                dbc.Input(
                    id="chopper-quality-input",
                    type="number",
                    min=0,
                    max=30,
                    step=1,
                    value=10,
                ),
                dbc.FormText("Per-read mean Q-score threshold (lower for short ONT reads)"),
                dbc.Tooltip(
                    "Chopper's --quality filter. ONT short-read "
                    "Q-scores trend lower than long-read because "
                    "the Q-score ramp-up region is a larger "
                    "fraction of a short read. Try 7 for amplicons.",
                    target="chopper-quality-info",
                ),
            ], md=4),
            dbc.Col([
                dbc.Label([
                    "Filtlong minimum length (bp) ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="filtlong-minlength-info"),
                ], html_for="filtlong-minlength-input"),
                dbc.Input(
                    id="filtlong-minlength-input",
                    type="number",
                    min=0,
                    max=50000,
                    step=50,
                    value=1000,
                ),
                dbc.FormText("Only used when QC tool is filtlong (above)"),
                dbc.Tooltip(
                    "Filtlong's --min_length filter. Same "
                    "amplicon guidance as chopper_minlength: "
                    "100 for V3-V4, 250-500 for ITS/16S.",
                    target="filtlong-minlength-info",
                ),
            ], md=4),
        ], className="mb-3"),

        # Row 2: kraken2 confidence + minimum hit groups
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Kraken2 confidence (0.0-1.0) ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="kraken2-confidence-info"),
                ], html_for="kraken2-confidence-input"),
                dbc.Input(
                    id="kraken2-confidence-input",
                    type="number",
                    min=0,
                    max=1,
                    step=0.05,
                    value=0.0,
                ),
                dbc.FormText("Per-read classification confidence (0 disables)"),
                dbc.Tooltip(
                    "Kraken2 --confidence flag. 0 means accept "
                    "every classification; raise (0.05-0.2) if "
                    "you see noise in low-abundance taxa. "
                    "Database-dependent.",
                    target="kraken2-confidence-info",
                ),
            ], md=6),
            dbc.Col([
                dbc.Label([
                    "Kraken2 minimum hit groups ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="kraken2-hitgroups-info"),
                ], html_for="kraken2-hitgroups-input"),
                dbc.Input(
                    id="kraken2-hitgroups-input",
                    type="number",
                    min=0,
                    max=10,
                    step=1,
                    value=0,
                ),
                dbc.FormText("Hit groups required (0 disables)"),
                dbc.Tooltip(
                    "Kraken2 --minimum-hit-groups. Requires at "
                    "least N distinct k-mer regions to support "
                    "a classification. Lowers false positives "
                    "but loses sensitivity on short reads.",
                    target="kraken2-hitgroups-info",
                ),
            ], md=6),
        ]),
    ], title="Read Filtering")


def _analysis_options_item():
    """Advanced: optional pipeline outputs."""
    return dbc.AccordionItem([
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Quality Filter ",
                    html.I(className="bi bi-info-circle text-muted ms-1",
                           id="qc-tool-info"),
                ], html_for="qc-tool-input"),
                dbc.Select(
                    id="qc-tool-input",
                    options=[
                        {"label": "chopper (recommended)", "value": "chopper"},
                        {"label": "fastp", "value": "fastp"},
                    ],
                    # Operator preference + matches
                    # nextflow_schema.json default; closes
                    # P1 #4 from
                    # docs/audit-2026-04-30-config-tab.md.
                    value="chopper"
                ),
                dbc.FormText("Tool used to filter out low-quality DNA sequences"),
                dbc.Tooltip(
                    "Filters low-quality DNA sequences before species "
                    "identification. fastp is recommended for most users.",
                    target="qc-tool-info"
                )
            ], md=4),
            dbc.Col([
                dbc.Switch(
                    id="skip-nanoplot-input",
                    label="Skip detailed QC report",
                    value=False,
                    className="mt-3"
                ),
                dbc.FormText("Makes analysis faster but produces fewer quality details")
            ], md=4),
            dbc.Col([
                dbc.Switch(
                    id="kraken2-incremental-input",
                    label="Running totals in live mode",
                    value=True,
                    className="mt-3"
                ),
                dbc.FormText("Show cumulative species counts during live sequencing"),
                dbc.Badge("Recommended", color="success",
                          style={"fontSize": "0.6rem", "verticalAlign": "middle"}),
            ], md=4),
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Switch(
                    id="enable-krona-input",
                    label="Generate interactive taxonomy charts",
                    value=False,
                    className="mt-1"
                ),
                dbc.FormText("Creates browsable species classification charts (slower)")
            ], md=4),
            dbc.Col([
                dbc.Switch(
                    id="enable-nanopore-stats-input",
                    label="Include sequencing quality summary",
                    value=False,
                    className="mt-1"
                ),
                dbc.FormText("Adds sequencer-specific metrics to the combined report")
            ], md=4),
        ]),
    ], title="Analysis Options")


def _display_settings_item():
    """Advanced: dashboard refresh + alert threshold."""
    return dbc.AccordionItem([
        dbc.Row([
            dbc.Col([
                dbc.Label([
                    "Update Interval (seconds) ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="update-interval-info")
                ], html_for="update-interval-input"),
                dbc.Input(
                    id="update-interval-input",
                    type="number",
                    min=5,
                    max=300,
                    step=5,
                    value=10
                ),
                dbc.FormText("How often the dashboard refreshes (5-300 seconds)"),
                dbc.Tooltip(
                    "Controls how frequently the dashboard charts and tables update. "
                    "Lower values show results faster but increase CPU usage. "
                    "Different from Check Interval which controls pipeline file scanning.",
                    target="update-interval-info"
                )
            ], md=6),
            dbc.Col([
                dbc.Label([
                    "Alert Threshold (reads) ",
                    html.I(className="bi bi-info-circle text-muted ms-1", id="alert-threshold-info")
                ], html_for="danger-threshold-input"),
                dbc.Input(
                    id="danger-threshold-input",
                    type="number",
                    min=1,
                    step=10,
                    value=100
                ),
                dbc.FormText("Minimum reads before an organism triggers a dashboard alert"),
                dbc.Tooltip(
                    "When an organism reaches this many classified reads, "
                    "it will appear in the dashboard alerts panel. "
                    "Lower values are more sensitive but may produce false alerts.",
                    target="alert-threshold-info"
                )
            ], md=6)
        ])
    ], title="Display Settings")


def _performance_item():
    """Advanced: CPU cores, dashboard port, temp cleanup."""
    return dbc.AccordionItem([
        dbc.Row([
            dbc.Col([
                dbc.Label("CPU Cores", html_for="cores-input"),
                dbc.Input(
                    id="cores-input",
                    type="number",
                    min=1,
                    step=1,
                    value=4
                ),
                dbc.FormText("Number of processing threads")
            ], md=4),
            dbc.Col([
                dbc.Label("Dashboard Port", html_for="gui-port-input"),
                dbc.Input(
                    id="gui-port-input",
                    type="number",
                    min=1024,
                    max=65535,
                    step=1,
                    value=8050
                ),
                dbc.FormText(
                    "Network port for this web interface (default: 8050). "
                    "Takes effect on the next application launch -- the "
                    "running server keeps the port it started on."
                )
            ], md=4),
            dbc.Col([
                dbc.Switch(
                    id="clean-temp-input",
                    label="Clean temp files",
                    value=True,
                    className="mt-4"
                ),
                dbc.FormText("Remove after processing")
            ], md=4)
        ])
    ], title="Performance")
