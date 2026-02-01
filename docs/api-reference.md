# API Reference

Reference documentation for Nanometa Live's Python APIs.

## Data Loaders

### `nanometa_live.core.utils.data_loaders`

#### `load_kraken_data(main_dir, sample=None)`

Load Kraken2 classification results.

```python
from nanometa_live.core.utils.data_loaders import load_kraken_data

# Load all samples aggregated
df = load_kraken_data("/path/to/results", sample="All Samples")

# Load specific sample
df = load_kraken_data("/path/to/results", sample="barcode01")
```

**Parameters:**
- `main_dir` (str): Path to pipeline output directory
- `sample` (str, optional): Sample name or "All Samples" for aggregation

**Returns:**
- `pd.DataFrame`: DataFrame with columns `[%, cumul_reads, reads, rank, taxid, name]`

**File Priority:**
1. `*.cumulative.kraken2.report.txt` (real-time mode)
2. `*.kraken2.report.txt` (standard)
3. `*.kreport2.txt` (legacy)

---

#### `load_fastp_data(main_dir, sample=None)`

Load FASTP quality filtering statistics.

```python
from nanometa_live.core.utils.data_loaders import load_fastp_data

stats = load_fastp_data("/path/to/results", sample="barcode01")
```

**Parameters:**
- `main_dir` (str): Path to pipeline output directory
- `sample` (str, optional): Sample name or None for all

**Returns:**
- `dict`: FASTP statistics including reads, bases, quality scores

---

## Sample Detection

### `nanometa_live.core.utils.sample_detector`

#### `get_available_samples(main_dir)`

Detect available samples from output files.

```python
from nanometa_live.core.utils.sample_detector import get_available_samples

samples = get_available_samples("/path/to/results")
# Returns: ["All Samples", "barcode01", "barcode02", ...]
```

**Parameters:**
- `main_dir` (str): Path to pipeline output directory

**Returns:**
- `list[str]`: List of sample names, always starts with "All Samples"

---

#### `get_sample_file_mapping(main_dir)`

Get mapping of samples to their output files.

```python
from nanometa_live.core.utils.sample_detector import get_sample_file_mapping

mapping = get_sample_file_mapping("/path/to/results")
# Returns: {
#     "barcode01": {
#         "kraken2": ["/path/to/kraken2/barcode01.kraken2.report.txt"],
#         "fastp": ["/path/to/fastp/barcode01.fastp.json"]
#     },
#     ...
# }
```

---

#### `resolve_analysis_directory(main_dir)`

Resolve the actual analysis directory (handles timestamped subdirs).

```python
from nanometa_live.core.utils.sample_detector import resolve_analysis_directory

resolved = resolve_analysis_directory("/path/to/results")
# If results/analysis_20251212_123456/ exists, returns that path
# Otherwise returns the original path
```

---

## Parameter Mapping

### `nanometa_live.core.config.parameter_mapping`

#### `detect_input_mode(input_dir)`

Detect the type of input directory structure.

```python
from nanometa_live.core.config.parameter_mapping import detect_input_mode

mode = detect_input_mode("/path/to/fastq")
# Returns: "barcode" or "batch"
```

---

#### `generate_samplesheet(input_dir, output_path, sample_handling, sample_name=None)`

Generate a samplesheet CSV for the pipeline.

```python
from nanometa_live.core.config.parameter_mapping import generate_samplesheet

generate_samplesheet(
    input_dir="/path/to/fastq",
    output_path="/path/to/samplesheet.csv",
    sample_handling="by_barcode"
)
```

**Parameters:**
- `input_dir` (str): Directory containing FASTQ files
- `output_path` (str): Where to write the samplesheet
- `sample_handling` (str): "by_barcode", "single_sample", or "per_file"
- `sample_name` (str, optional): Name for single_sample mode

**Generated CSV format:**
```csv
sample,fastq
barcode01,/path/to/barcode01/reads.fastq.gz
barcode02,/path/to/barcode02/reads.fastq.gz
```

---

#### `create_nextflow_params(config)`

Convert configuration dict to Nextflow parameters.

```python
from nanometa_live.core.config.parameter_mapping import create_nextflow_params

params = create_nextflow_params({
    "nanopore_output_directory": "/path/to/fastq",
    "kraken_db": "/path/to/kraken2_db",
    "processing_mode": "batch",
    "sample_handling": "by_barcode"
})
# Returns dict with --input, --outdir, --kraken2_db, etc.
```

---

## Backend Management

### `nanometa_live.core.workflow.backend_manager`

#### `BackendManager`

Manages pipeline lifecycle.

```python
from nanometa_live.core.workflow.backend_manager import BackendManager

manager = BackendManager(data_dir="/path/to/data")

# Configure
manager.update_config({
    "nanopore_output_directory": "/path/to/fastq",
    "kraken_db": "/path/to/db"
})

# Start pipeline
success, message = manager.start(profile="docker")

# Check status
status = manager.get_status()
# Returns: {
#     "running": True,
#     "pipeline_status": "running",
#     "processes_complete": 5,
#     "processes_running": 2,
#     "current_stage": "KRAKEN2",
#     "start_time": "2025-12-12T10:30:00",
#     ...
# }

# Stop pipeline
success, message = manager.stop()
```

**Methods:**
- `update_config(config)`: Update configuration
- `setup_project()`: Prepare directories
- `start(profile=None)`: Start pipeline
- `stop()`: Stop pipeline
- `get_status()`: Get current status dict

---

## Configuration

### `nanometa_live.core.config.config_loader`

#### `ConfigLoader`

Load and validate configuration files.

```python
from nanometa_live.core.config.config_loader import ConfigLoader

loader = ConfigLoader()
config = loader.load("/path/to/config.yaml")

# Save configuration
loader.save(config, "/path/to/new_config.yaml")
```

---

## Parsers

### `nanometa_live.core.parsers`

#### `NanometanfOutputParser`

Unified parser for all pipeline outputs.

```python
from nanometa_live.core.parsers import NanometanfOutputParser

parser = NanometanfOutputParser("/path/to/results")

# Get top species
top = parser.get_top_species(n=10)

# Get QC summary
qc = parser.get_qc_summary()

# Get sample list
samples = parser.get_samples()
```

See [Parser Guide](nanometanf_parser_guide.md) for detailed documentation.

---

## Dash Stores

Data stores available in callbacks:

| Store ID | Type | Description |
|----------|------|-------------|
| `app-config` | dict | Current configuration |
| `backend-status` | dict | Pipeline status |
| `selected-sample` | str | Current sample selection |
| `available-samples` | list | Detected sample names |
| `last-update-time` | str | Timestamp of last data refresh |

### Accessing in Callbacks

```python
@app.callback(
    Output("my-output", "children"),
    Input("update-interval", "n_intervals"),
    [State("app-config", "data"),
     State("selected-sample", "data"),
     State("backend-status", "data")]
)
def my_callback(n, config, sample, status):
    main_dir = config.get("main_dir", "")
    is_running = status and status.get("running", False)
    # ...
```

---

## Intervals

| Interval ID | Default | Purpose |
|-------------|---------|---------|
| `update-interval` | 30000ms | Data refresh |
| `countdown-tick` | 1000ms | Timer display |

### Accessing Interval

```python
@app.callback(
    Output("countdown", "children"),
    Input("countdown-tick", "n_intervals"),
    Input("update-interval", "interval")
)
def update_countdown(tick, interval_ms):
    interval_sec = interval_ms / 1000
    # ...
```
