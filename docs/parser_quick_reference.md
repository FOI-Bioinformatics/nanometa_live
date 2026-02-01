# NanometanfOutputParser Quick Reference

One-page reference for the most commonly used parser methods.

## Initialization

```python
from nanometa_live.core.parsers import NanometanfOutputParser, RealtimeMonitor

parser = NanometanfOutputParser("/path/to/nanometanf/results")
```

## Most Common Operations

### Get Top Species (Classification Results)

```python
# Get top 10 species by read count
top_species = parser.get_top_species(n=10)
# Returns: DataFrame with columns [taxid, name, total_reads, samples, num_samples]
```

### Get Overall Classification Summary

```python
# Get comprehensive summary across all data sources
summary = parser.get_classification_summary()
# Returns: Dict with keys [kraken2, fastp, realtime, overall]

# Access classification rate
rate = summary['overall']['classification_rate']
total_reads = summary['overall']['total_reads']
```

### Get Quality Control Summary

```python
# Get FASTP summary statistics
qc_summary = parser.get_fastp_summary()
# Returns: Dict with total_reads_before, total_reads_after, avg_q30_rate_after, etc.

print(f"Q30 rate: {qc_summary['avg_q30_rate_after']:.2%}")
```

### Monitor Real-time Processing

```python
# Get cumulative statistics across all batches
cumulative = parser.get_cumulative_stats()
# Returns: Dict with total_batches, total_reads, classification_rate, etc.

print(f"Processed {cumulative['total_batches']} batches")
print(f"Classification rate: {cumulative['classification_rate']:.2%}")
```

### Get Latest Batch Information

```python
# Get latest batch number
latest_batch = parser.get_latest_batch_number()

# Get batch data
batch_data = parser.parse_batch_stats(latest_batch)
print(f"Batch {batch_data['batch_number']}: {batch_data['reads_in_batch']} reads")
```

## Advanced Operations

### Parse Individual Sample Data

```python
# Kraken2 report for specific sample
kraken_df = parser.parse_kraken_report("sample1")
species = kraken_df[kraken_df['rank'] == 'S']  # Filter for species

# FASTP report for specific sample
fastp_data = parser.parse_fastp_report("sample1")
q30_rate = fastp_data['summary']['after_filtering']['q30_rate']

# BLAST results for specific sample
blast_df = parser.parse_blast_results("sample1", taxid="1350")
high_identity = blast_df[blast_df['pident'] > 95]
```

### Aggregate Across All Samples

```python
# Combine all Kraken2 reports
all_kraken = parser.combine_kraken_reports()
total_species = all_kraken[all_kraken['rank'] == 'S']['taxid'].nunique()

# Combine all FASTP reports
all_fastp = parser.combine_fastp_reports()
avg_q30 = all_fastp['q30_rate_after'].mean()
```

### Search for Specific Species

```python
# Get read counts for specific taxonomy IDs
target_species = ['562', '1280', '1350']  # E. coli, S. aureus, E. faecalis
counts = parser.get_species_read_counts(target_species)

for taxid, count in counts.items():
    print(f"Taxid {taxid}: {count:,} reads")
```

## Real-time Monitoring

### Set Up Live Monitoring

```python
from nanometa_live.core.parsers import RealtimeMonitor

def on_new_batch(batch_data):
    """Called when new batch detected."""
    print(f"New batch: {batch_data['reads_in_batch']} reads")
    # Update your dashboard here

monitor = RealtimeMonitor(
    outdir="/path/to/results",
    update_callback=on_new_batch
)

# Start monitoring (runs in background)
monitor.start_monitoring(interval=10)  # Check every 10 seconds

# Stop monitoring
monitor.stop_monitoring()
```

## Return Types Reference

| Method | Returns | Empty Case |
|--------|---------|------------|
| `parse_kraken_report(sample)` | `pd.DataFrame` | Empty DataFrame with schema |
| `get_top_species(n)` | `pd.DataFrame` | Empty DataFrame |
| `parse_fastp_report(sample)` | `Dict` | Empty dict `{}` |
| `get_fastp_summary()` | `Dict` | Dict with zeros |
| `parse_batch_stats(batch_num)` | `Dict` | Empty dict `{}` |
| `get_cumulative_stats()` | `Dict` | Dict with zeros |
| `get_classification_summary()` | `Dict` | Nested dict with zeros |
| `get_latest_batch_number()` | `int` | `0` |

## Common Patterns

### Dashboard Update Pattern

```python
def update_dashboard():
    """Update all dashboard metrics."""
    # Get overall summary
    summary = parser.get_classification_summary()

    # Get top species
    top_species = parser.get_top_species(n=10)

    # Get quality metrics
    qc_summary = parser.get_fastp_summary()

    # Get real-time progress
    cumulative = parser.get_cumulative_stats()

    return {
        'classification_rate': summary['overall']['classification_rate'],
        'total_reads': summary['overall']['total_reads'],
        'top_species': top_species.to_dict('records'),
        'q30_rate': qc_summary['avg_q30_rate_after'],
        'batches_processed': cumulative['total_batches']
    }
```

### Error-Safe Parsing Pattern

```python
def safe_parse_sample(sample_name):
    """Parse sample data with error handling."""
    try:
        kraken_data = parser.parse_kraken_report(sample_name)
        if kraken_data.empty:
            return None

        # Process data
        species = kraken_data[kraken_data['rank'] == 'S']
        return species

    except Exception as e:
        print(f"Error parsing {sample_name}: {e}")
        return None
```

### Polling Pattern

```python
import time

def poll_for_updates(interval=10):
    """Poll for new batches."""
    last_batch = parser.get_latest_batch_number()

    while True:
        current_batch = parser.get_latest_batch_number()

        if current_batch > last_batch:
            # New batches available
            for batch_num in range(last_batch + 1, current_batch + 1):
                batch_data = parser.parse_batch_stats(batch_num)
                process_batch(batch_data)

            last_batch = current_batch

        time.sleep(interval)
```

## File Format Cheat Sheet

### Kraken2 Report (.kreport2)
```
percent  reads_clade  reads_taxon  rank  taxid  name
0.15     300          300          U     0      unclassified
99.85    19970        0            R     1      root
50.00    10000        100          S     1350   Enterococcus faecalis
```

### FASTP JSON
```json
{
  "summary": {
    "before_filtering": {"total_reads": 10000, "q30_rate": 0.90},
    "after_filtering": {"total_reads": 9500, "q30_rate": 0.92}
  }
}
```

### Batch Stats JSON
```json
{
  "batch_number": 1,
  "timestamp": "2025-10-06T12:34:56",
  "reads_in_batch": 50000,
  "classified_in_batch": 45000
}
```

### BLAST Output (outfmt 6)
```
qseqid  sseqid  pident  length  mismatch  gapopen  qstart  qend  sstart  send  evalue  bitscore
read1   ref1    98.5    500     2         1        1       500   1       500   1e-100  900
```

## Logging

```python
import logging

# Enable detailed logging
logging.basicConfig(level=logging.INFO)

# Parser will log operations
parser = NanometanfOutputParser("/path/to/results")
# INFO - Initialized NanometanfOutputParser with outdir: /path/to/results
```

## Directory Structure

```
results/
├── multiqc/multiqc_data/
│   ├── multiqc_general_stats.txt
│   ├── multiqc_data.json
│   ├── multiqc_fastp.txt
│   └── multiqc_kraken.txt
├── fastp/
│   └── *.fastp.json
├── kraken2/
│   ├── *.kreport2
│   └── *.kraken2
├── blast/
│   └── *.blast.txt
└── realtime_batch_stats/
    └── batch_*.json
```

## Dash Integration

```python
from dash import Input, Output
import plotly.express as px

parser = NanometanfOutputParser("/path/to/results")

@app.callback(
    Output('species-chart', 'figure'),
    Input('interval-component', 'n_intervals')
)
def update_species_chart(n):
    df = parser.get_top_species(n=10)
    fig = px.bar(df, x='name', y='total_reads',
                 title='Top 10 Species by Read Count')
    return fig
```

## Tips

1. **Empty results are normal** - Parser returns empty DataFrames/dicts when files don't exist
2. **Enable logging** - Use `logging.basicConfig(level=logging.INFO)` for debugging
3. **Cache expensive operations** - Store results in `dcc.Store` or application state
4. **Use real-time monitor** - Don't poll manually; use `RealtimeMonitor` class
5. **Check file naming** - Parser supports multiple naming conventions (see guide)

## See Full Documentation

[Complete NanometanfOutputParser Guide](nanometanf_parser_guide.md)
