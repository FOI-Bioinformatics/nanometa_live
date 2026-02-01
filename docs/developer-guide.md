# Developer Guide

Architecture, extension points, and contribution guidelines for Nanometa Live.

## Architecture Overview

### Technology Stack

- **Frontend**: Dash 2.x + Plotly + Dash Bootstrap Components
- **Data Processing**: Pandas, NumPy
- **Backend**: nanometanf (Nextflow pipeline)
- **Configuration**: YAML files

### Directory Structure

```
nanometa_live/
├── app/
│   ├── app.py              # Main Dash application
│   ├── callbacks.py        # Core callbacks
│   ├── components/         # Reusable UI components
│   │   ├── header.py       # Header with status/timer
│   │   ├── sample_selector.py
│   │   └── ...
│   ├── layouts/            # Tab layouts
│   │   ├── main_layout.py
│   │   ├── qc_layout.py
│   │   ├── classification_layout.py
│   │   └── config_layout.py
│   ├── tabs/               # Tab callbacks
│   │   ├── main_tab.py
│   │   ├── qc_tab.py
│   │   ├── classification_tab.py
│   │   └── config_tab.py
│   └── assets/
│       └── styles.css
├── core/
│   ├── config/
│   │   ├── config_loader.py
│   │   ├── config_validator.py
│   │   └── parameter_mapping.py
│   ├── parsers/
│   │   └── ...
│   ├── utils/
│   │   ├── sample_detector.py
│   │   ├── data_loaders.py
│   │   └── ...
│   └── workflow/
│       ├── backend_manager.py
│       └── nextflow_manager.py
└── docs/
```

### Data Flow

```
User Input (GUI)
       ↓
Configuration (app-config store)
       ↓
Backend Manager → Nextflow Manager → Pipeline Execution
       ↓
Output Files (kraken2/, fastp/, etc.)
       ↓
Sample Detector → Data Loaders
       ↓
Dash Callbacks → Visualizations
```

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

Load and aggregate output data:
- `load_kraken_data()` - Parse Kraken2 reports
- `load_fastp_data()` - Parse FASTP JSON
- Sample-aware with aggregation support

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

```python
# core/utils/data_loaders.py

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
        # Aggregate all samples
        files = glob.glob(os.path.join(data_dir, "*.txt"))
        dfs = [pd.read_csv(f, sep="\t") for f in files]
        if not dfs:
            return pd.DataFrame()
        combined = pd.concat(dfs, ignore_index=True)
        return combined.groupby("key").agg({"value": "sum"})
    else:
        # Single sample
        sample_file = os.path.join(data_dir, f"{sample}.txt")
        if os.path.exists(sample_file):
            return pd.read_csv(sample_file, sep="\t")
        return pd.DataFrame()
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
- Keep callbacks focused and small

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

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run formatting and tests
5. Submit pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed guidelines.
