# Developer guide

Extension points, callback patterns, testing, and contribution notes for
Nanometa Live. For the full architectural reference -- directory layout,
data flow, watchlist system, validation pipeline, offline deployment --
see [`CLAUDE.md`](../CLAUDE.md).

## Technology stack

- **Frontend**: Dash 4.x, Plotly 6.x, Dash Bootstrap Components, dash-ag-grid
- **Data processing**: pandas, NumPy
- **Backend**: nanometanf (Nextflow pipeline)
- **Configuration**: YAML files

## Key Components

### App Setup (`app/app.py`)

Creates the Dash application with:
- Layout structure (tabs)
- Intervals (update-interval, countdown-tick)
- Data stores (app-config, backend-status, selected-sample)
- Clientside callbacks (timer)

### Core Callbacks (`app/callbacks.py`)

Central callbacks shared across tabs:
- `update_backend_status()` - Poll pipeline status
- `update_available_samples()` - Detect samples from output
- `update_elapsed_time()` - Display elapsed time
- `update_pipeline_stage_display()` - Show current stage

### Backend Manager (`core/workflow/backend_manager.py`)

Manages pipeline lifecycle:
- `setup_project()` - Prepare directories and config
- `start()` - Launch pipeline
- `stop()` - Terminate pipeline
- `get_status()` - Query current state

### Nextflow Manager (`core/workflow/nextflow_manager.py`)

Wraps Nextflow execution:
- Builds command line from config
- Runs pipeline in background thread
- Parses trace.txt for progress
- Monitors batch statistics

### Parameter Mapping (`core/config/parameter_mapping.py`)

Converts GUI config to Nextflow parameters:
- `detect_input_mode()` - Determine input structure
- `generate_samplesheet()` - Create input CSV
- `create_nextflow_params()` - Build param dict

### Data Loaders (`core/utils/data_loaders.py`)

Re-export hub that provides backward-compatible imports. The actual loading logic
is split across category-specific modules:
- `classification_loaders.py` - Kraken2 report parsing (`load_kraken_data()`)
- `qc_loaders.py` - FASTP/SeqKit/NanoPlot QC loading (`load_fastp_data()`, `load_nanoplot_stats()`)
- `validation_loaders.py` - BLAST/minimap2 validation loading (`load_validation_data()`)
- `canonical_loaders.py` - Waterfall loading: tries canonical JSON first, falls back to raw files
- `loader_utils.py` - Shared cache, file stability checks, and mtime tracking

## Adding a New Tab

### 1. Create Layout

```python
# app/layouts/my_layout.py
from dash import html, dcc
import dash_bootstrap_components as dbc

def create_my_layout():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H4("My New Tab"),
                dcc.Graph(id="my-plot"),
            ])
        ])
    ], fluid=True)
```

### 2. Create Callbacks

```python
# app/tabs/my_tab.py
from dash import Dash, Input, Output, State
from nanometa_live.core.utils.data_loaders import load_kraken_data

def register_my_callbacks(app: Dash):
    @app.callback(
        Output("my-plot", "figure"),
        Input("update-interval", "n_intervals"),
        [State("selected-sample", "data"),
         State("app-config", "data")]
    )
    def update_my_plot(n_intervals, sample, config):
        main_dir = config.get("main_dir", "")
        data = load_kraken_data(main_dir, sample)
        # Create visualization
        fig = create_figure(data)
        return fig
```

### 3. Register in App

```python
# In app/app.py
from nanometa_live.app.layouts.my_layout import create_my_layout
from nanometa_live.app.tabs.my_tab import register_my_callbacks

# Add tab to layout
dbc.Tab(
    label="My Tab",
    tab_id="my-tab",
    children=create_my_layout()
)

# Register callbacks
register_my_callbacks(app)
```

## Callback Patterns

### Standard Data Update

```python
@app.callback(
    Output("plot", "figure"),
    Input("update-interval", "n_intervals"),
    [State("selected-sample", "data"),
     State("app-config", "data")]
)
def update_plot(n_intervals, sample, config):
    if not config:
        return empty_figure()

    data = load_data(config["main_dir"], sample)
    return create_figure(data)
```

### Prevent Update When Not Running

```python
from dash import no_update

@app.callback(
    Output("data-store", "data"),
    Input("update-interval", "n_intervals"),
    State("backend-status", "data")
)
def update_data(n_intervals, status):
    if not status or not status.get("running"):
        return no_update
    return load_latest_data()
```

### Multiple Outputs

```python
@app.callback(
    [Output("plot1", "figure"),
     Output("plot2", "figure"),
     Output("table", "data")],
    Input("update-interval", "n_intervals"),
    State("app-config", "data")
)
def update_all(n_intervals, config):
    data = load_data(config["main_dir"])
    return (
        create_plot1(data),
        create_plot2(data),
        data.to_dict("records")
    )
```

### Clientside Callback (for performance)

```python
app.clientside_callback(
    """
    function(n_intervals, interval_ms) {
        var remaining = Math.ceil(interval_ms/1000 - (Date.now()/1000 % (interval_ms/1000)));
        return "Next: " + remaining + "s";
    }
    """,
    Output("countdown", "children"),
    [Input("countdown-tick", "n_intervals"),
     Input("update-interval", "interval")]
)
```

## Adding a New Data Loader

Place new loaders in the appropriate category-specific module under `core/utils/`,
or create a new module if the data type does not fit an existing category.
Then re-export the function from `data_loaders.py` for backward compatibility.

```python
# core/utils/my_loaders.py

def load_my_data(main_dir: str, sample: str = None) -> pd.DataFrame:
    """
    Load custom data from output directory.

    Args:
        main_dir: Pipeline output directory
        sample: Sample name or "All Samples" for aggregated

    Returns:
        DataFrame with loaded data
    """
    data_dir = os.path.join(main_dir, "my_output")

    if sample is None or sample == "All Samples":
        files = glob.glob(os.path.join(data_dir, "*.txt"))
        dfs = [pd.read_csv(f, sep="\t") for f in files]
        if not dfs:
            return pd.DataFrame()
        combined = pd.concat(dfs, ignore_index=True)
        return combined.groupby("key").agg({"value": "sum"})
    else:
        sample_file = os.path.join(data_dir, f"{sample}.txt")
        if os.path.exists(sample_file):
            return pd.read_csv(sample_file, sep="\t")
        return pd.DataFrame()
```

Then add the re-export in `data_loaders.py`:

```python
from nanometa_live.core.utils.my_loaders import load_my_data  # noqa: F401
```

## Testing

### Unit Tests

```bash
pytest tests/ -v
```

### Manual Testing

```bash
# Generate test data
python -m nanometa_live.core.testing.mock_data_generator \
    --output /tmp/test_data \
    --scenario normal

# Run with test data
python -m nanometa_live.app --main_dir /tmp/test_data --debug
```

### Import Validation

```python
# Quick check that everything imports
python -c "from nanometa_live.app.app import create_app; print('OK')"
```

## Code Style

- Follow PEP 8
- Use type hints
- Document public functions
- Keep callbacks focused and small. Extract pure decision and formatting logic
  into a sibling `app/tabs/<name>_helpers.py` module and keep only the thin
  Dash wiring (Inputs/Outputs, store reads, I/O) in the callback. The helper
  functions take plain arguments and return plain values, so they can be
  unit-tested without a running app. Every tab now follows this split; the
  helper modules are `dashboard_helpers.py` (including `select_verdict`, the
  clinical verdict state machine), `kraken2_helpers.py`, `main_tab_helpers.py`,
  `qc_tab_helpers.py`, `validation_tab_helpers.py`, `config_tab_helpers.py`,
  `preparation_helpers.py`, and `classification_helpers.py` (the Sankey and
  Sunburst figure builders).

### Formatting

```bash
# Format code
black nanometa_live/

# Sort imports
isort nanometa_live/

# Type checking
mypy nanometa_live/
```

## Debugging

### Enable Debug Mode

```bash
DASH_DEBUG=true python -m nanometa_live.app --main_dir /path/to/data
```

### Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# In your code
logging.debug(f"Loaded {len(df)} rows from {file_path}")
```

### Callback Debugging

Add print statements or use Dash Dev Tools in browser (debug mode).

## Performance Tips

### Caching

```python
from functools import lru_cache

@lru_cache(maxsize=10)
def expensive_calculation(param):
    return result
```

### Reduce Data Points

```python
def downsample_for_plot(df, max_points=1000):
    if len(df) <= max_points:
        return df
    step = len(df) // max_points
    return df.iloc[::step]
```

### Lazy Loading

Only load detailed data when needed:

```python
@app.callback(
    Output("detail-view", "children"),
    Input("sample-selector", "value")
)
def load_detail(sample):
    if sample == "All Samples":
        return html.Div("Select a sample for details")
    return create_detailed_view(load_detailed_data(sample))
```

## Operations

### Host binding (F10)

The Dash server binds to `127.0.0.1` (loopback only) by default.
This is intentional: it prevents accidentally exposing an
operator's running analysis to the local network. The CLI
exposes `--host` as a documented escape hatch:

```bash
# Default -- localhost only, browser must be on the same machine
python -m nanometa_live.app --port 8050

# Network-accessible -- bind on all interfaces (use behind a
# trusted firewall or SSH tunnel; the dashboard has no auth)
python -m nanometa_live.app --host 0.0.0.0 --port 8050
```

If the operator is running on a head node and wants to reach
the GUI from a workstation, prefer an SSH tunnel rather than
`--host 0.0.0.0`:

```bash
# From the workstation:
ssh -N -L 8050:localhost:8050 user@head-node
# Then browse to http://localhost:8050 on the workstation
```

The `--host` argument is defined in
`nanometa_live/app/__main__.py:46-49`.

### nanometanf nf-test runner pin (F11)

The repository ships
`nanometanf/bin/run-nf-tests.sh` which pins
`NXF_VER=25.04.7` and sets `NXF_OFFLINE=true`. Reason: Nextflow
25.10.4 does not release the watchPath DirWatcherV2 thread
after the realtime timeout sentinel fires, so any nf-test that
exercises `realtime_mode = true` hangs indefinitely once the
run logically completes (the test runner waits for the JVM to
exit before reporting success).

Use the wrapper rather than `nf-test` directly when running
realtime tests:

```bash
cd ~/Code/nanometanf
bash bin/run-nf-tests.sh test subworkflows/local/realtime_monitoring/tests/main.nf.test
```

Status (2026-05-02): the pin is still required. Track upstream
[Nextflow #26](https://github.com/nextflow-io/nextflow/issues/26)
(or the relevant follow-up) before lifting it.

### Pre-warmed conda envs (F12 / cycle 18)

`BundleManager.export_bundle(..., pre_warm_conda_envs=True)`
runs the nine pipeline scenarios listed in
`core/workflow/bundle_manager.py` to populate
`~/.nanometa/work/conda/`, which the offline-deployment bundle
then carries to the field machine. Adds about 30 minutes and
~5 GB to the build; default off so the existing flow is
unaffected. See `CLAUDE.md` "Pre-warm conda envs" for the
build-platform restriction (Linux x86_64 vs macOS arm64
cannot share envs).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run formatting and tests
5. Submit pull request

See the project's GitHub repository for the contribution workflow.
