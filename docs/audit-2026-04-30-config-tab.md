# Configuration tab UX audit -- 2026-04-30

Cross-references the GUI Configuration tab
(`app/components/config_form.py`,
`app/layouts/config_layout.py`,
`app/tabs/config_tab.py`,
`core/config/parameter_mapping.py`,
`core/config/config_validator.py`)
against `nextflow_schema.json` and
`nextflow.config` in nanometanf.

## P0 -- Defaults that contradict the project convention

### 1. Pipeline profile default was ``docker`` -- FIXED

Per `CLAUDE.md` ("`pipeline_profile: conda` -- always conda for
nanometanf; docker/singularity exist but aren't used") and the
operator's persistent memory entry on the same point. The form
default at `config_form.py:224` was ``docker`` with a
"(Recommended)" badge, and `parameter_mapping.py:848` defaulted
to ``docker`` when ``pipeline_profile`` was missing. Every actual
deployment uses Conda.

Fix: option order reordered (Conda first, marked Recommended) and
both defaults changed to ``conda``. Form FormText reads "Conda is
the canonical setup; switch only if Conda is unavailable". Tooltip
documents the rationale.

### 2. Validation disabled by default -- FIXED

The Validate-organism button on the Main tab routes through
`OnDemandValidator.validate_via_nanometanf` (the 2026-04-30
refactor) and uses `nextflow run -resume` so previously-validated
(sample, taxid) pairs hit the work cache. With this design,
keeping ``Enable confirmation testing`` off by default forces every
new operator to flip it on before they get the dashboard's
strongest signal. Default flipped to True.

### 3. Validation method default ``both`` -- FIXED

Default was ``both`` (BLAST + minimap2). Running both doubles per-
pair compute. minimap2 alone is fast, ONT-optimised, and produces
the coverage-depth plots that are the dashboard's headline
visualisation; BLAST adds 5-10x runtime per pair for marginal
extra confidence. Default flipped to ``minimap2``; ``both`` is
relabelled "Both (highest confidence, 2x compute)" so the trade-off
is explicit.

## P1 -- Form/schema misalignment (documented, not fixed)

### 4. qc_tool default mismatch

`nextflow_schema.json: quality_control_options.qc_tool.default =
"chopper"`. Form default at `config_form.py:706` is ``fastp``, with
a "(recommended)" label. They disagree. Either:
  - Change schema default to ``fastp`` (changes nanometanf behaviour
    when called without ``--qc_tool``, riskier)
  - Change form default to ``chopper`` (safer, but contradicts the
    form's "(recommended)" label)
  - Pick a side and propagate

Recommended: keep form/operator-facing default ``fastp`` and update
the schema to match. Defer because this requires nanometanf change
+ test snapshot refresh.

### 5. Two identity-threshold inputs are easy to mis-set

`config_form.py:568` (`min-identity-input`, BLAST e-value pair,
default 90) and `config_form.py:869`
(`validation-identity-input`, "Validation identity threshold",
default 90) are both validation thresholds. They are in different
cards (Confirmation Testing vs Read Filtering and Validation),
which means an operator who tunes one for short-amplicon data
(e.g. drops it to 80) without realising the other exists ends up
with a half-applied change.

Recommended: collapse to one input wired to both downstream params,
or render the read-filtering one as read-only mirroring the
canonical value. Defer because the wiring change is non-trivial.

### 6. Card ordering does not match operator workflow

Order today (Advanced Settings accordion):
  Display Settings -> Database Settings -> Pipeline Source ->
  Processing Settings -> Confirmation Testing -> Analysis Options
  -> Read Filtering and Validation -> Performance

The operator workflow is: define inputs (Pipeline Source, Database)
-> set processing knobs -> set QC / Read Filtering -> set
Validation -> set Display + Performance. Reordering improves
discoverability, especially for amplicon protocols where the Read
Filtering card is what the operator must touch FIRST (length
filter) but it sits 6 sections down.

Recommended order:
  Pipeline Source -> Database Settings -> Processing Settings ->
  Read Filtering and Validation -> Confirmation Testing ->
  Analysis Options -> Display Settings -> Performance

Defer because it touches a lot of vertical lines and benefits from
operator review.

## P2 -- Smaller polish items

### 7. Stale pipeline-branch options

`config_form.py:357-363` offers ``master (Stable)`` and
``dev (Development)``. The repo's actual branches at
`github.com/FOI-Bioinformatics/nanometanf` should be verified; if
``master`` no longer exists or has been renamed to ``main``, the
default value will be wrong.

Recommended: replace the dropdown with a free-text branch input
(or fetch the live branch list from the GitHub API at GUI startup).

### 8. Section headers use ``html.Strong`` instead of ``html.H6``

`config_form.py` card headers like ``html.Strong("Display
Settings")`` (lines 250, 303, 327, 399, 517, 690, 769, 957) are
visually correct but semantically wrong -- screen readers do not
treat them as section headings. Switching to ``html.H6`` with
appropriate Bootstrap classes preserves the look while improving
accessibility.

### 9. ``~/.nanometa`` placeholder + value never expanded

`config_form.py:664` sets the genome cache directory's default
value to literal string ``~/.nanometa``. Python's ``Path`` won't
expand this unless `os.path.expanduser` is called by the consumer.
Verify the consumer expands tildes; if not, either expand at form
load or change the default to ``str(Path.home() / ".nanometa")``.

### 10. ``save_reads_assignment`` invisible but required

The validation flow requires ``save_reads_assignment: true`` on the
Kraken2 side -- without it, ``EXTRACT_READS_BY_TAXID`` has nothing
to extract. Today this is **auto-set** by
`parameter_mapping.py:611` based on the ``run_validation_enabled``
flag, so the operator does not need to manage it. Verified
correctly wired during the 2026-04-30 e2e: the test data without
this flag had empty ``*.kraken2.output.txt`` files, and the new
GUI flow flips it on whenever validation is enabled. No fix
needed; documenting the dependency for future reference.

## Verified working

- The ``Sample Name`` column has a callback (`config_tab.py:829`,
  `toggle_sample_name_field`) that hides the field when
  ``sample_handling != "single_sample"``. Earlier audit suspicion
  about wasted screen space is invalid.
- The Read Filtering and Validation card exposes all six amplicon-
  tunable params (chopper_minlength, chopper_quality,
  filtlong_min_length, validation_identity_threshold,
  kraken2_confidence, kraken2_minimum_hit_groups) with operator-
  friendly tooltips and amplicon-specific guidance.
- Help icons use `bi bi-info-circle text-muted` which clears the
  WCAG AA contrast floor after the 2026-04-29 muted-text override
  to ``#5a6370``.
