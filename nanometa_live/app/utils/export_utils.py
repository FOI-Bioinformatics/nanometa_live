"""
Export utilities for Nanometa Live.

This module provides functions to export classification data in various formats
commonly used in metagenomics analysis.

Supported formats:
- CSV/TSV: Standard tabular format
- BIOM: Biological Observation Matrix (for QIIME, etc.)
- Krona: Interactive HTML visualization
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from io import StringIO

import pandas as pd


def export_to_csv(
    kraken_df: pd.DataFrame,
    output_path: Optional[str] = None,
    include_hierarchy: bool = True,
    sep: str = ","
) -> str:
    """
    Export Kraken2 classification data to CSV/TSV format.

    Args:
        kraken_df: DataFrame with Kraken2 report data
        output_path: Path to save file (None returns string)
        include_hierarchy: Whether to include taxonomic hierarchy columns
        sep: Field separator ("," for CSV, "\t" for TSV)

    Returns:
        CSV string if output_path is None, else the output path
    """
    if kraken_df.empty:
        raise ValueError("Cannot export empty DataFrame")

    # Select columns to export
    export_cols = ['taxid', 'rank', 'name', 'reads', 'cumul_reads']
    if 'percentage' in kraken_df.columns:
        export_cols.insert(0, 'percentage')

    # Filter to available columns
    available_cols = [col for col in export_cols if col in kraken_df.columns]
    export_df = kraken_df[available_cols].copy()

    # Rename columns for clarity
    rename_map = {
        'taxid': 'Tax_ID',
        'rank': 'Rank',
        'name': 'Scientific_Name',
        'reads': 'Direct_Reads',
        'cumul_reads': 'Total_Reads',
        'percentage': 'Percentage'
    }
    export_df = export_df.rename(columns=rename_map)

    # Add metadata
    export_df['Export_Date'] = datetime.now().isoformat()

    if output_path:
        export_df.to_csv(output_path, index=False, sep=sep)
        logging.info(f"Exported classification data to {output_path}")
        return output_path
    else:
        return export_df.to_csv(index=False, sep=sep)


def export_to_tsv(
    kraken_df: pd.DataFrame,
    output_path: Optional[str] = None,
    include_hierarchy: bool = True
) -> str:
    """
    Export Kraken2 classification data to TSV format.

    Args:
        kraken_df: DataFrame with Kraken2 report data
        output_path: Path to save file (None returns string)
        include_hierarchy: Whether to include taxonomic hierarchy columns

    Returns:
        TSV string if output_path is None, else the output path
    """
    return export_to_csv(kraken_df, output_path, include_hierarchy, sep="\t")


def export_to_biom(
    kraken_df: pd.DataFrame,
    sample_name: str = "sample1",
    output_path: Optional[str] = None
) -> str:
    """
    Export Kraken2 classification data to BIOM format (JSON).

    BIOM (Biological Observation Matrix) is a standard format for
    metagenomics data that can be imported into QIIME2, MetaPhlAn, etc.

    Args:
        kraken_df: DataFrame with Kraken2 report data
        sample_name: Name of the sample
        output_path: Path to save file (None returns string)

    Returns:
        BIOM JSON string if output_path is None, else the output path
    """
    if kraken_df.empty:
        raise ValueError("Cannot export empty DataFrame")

    # Filter to species level for BIOM (most common use case)
    species_df = kraken_df[kraken_df['rank'] == 'S'].copy()

    if species_df.empty:
        # Fall back to all classified taxa
        species_df = kraken_df[~kraken_df['name'].str.contains('unclassified', case=False, na=False)].copy()

    # Build BIOM structure (version 1.0 JSON format)
    biom_data = {
        "id": f"nanometa_live_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "format": "Biological Observation Matrix 1.0.0",
        "format_url": "http://biom-format.org",
        "type": "OTU table",
        "generated_by": "Nanometa Live",
        "date": datetime.now().isoformat(),
        "rows": [],
        "columns": [
            {
                "id": sample_name,
                "metadata": {
                    "sample_name": sample_name,
                    "source": "Kraken2 classification"
                }
            }
        ],
        "matrix_type": "sparse",
        "matrix_element_type": "int",
        "shape": [len(species_df), 1],
        "data": []
    }

    # Add rows (taxa) and data - vectorized approach
    # Prepare data columns with proper types
    taxids = species_df['taxid'].fillna(0).astype(int).tolist()
    names = species_df['name'].fillna('').str.strip().tolist()
    ranks = species_df['rank'].fillna('S').astype(str).tolist() if 'rank' in species_df.columns else ['S'] * len(species_df)
    reads_vals = species_df['reads'].fillna(0).astype(int).tolist()

    # Build rows and data using list comprehension (faster than iterrows)
    biom_data["rows"] = [
        {
            "id": str(taxid),
            "metadata": {
                "taxonomy": [name],
                "rank": rank,
                "scientific_name": name
            }
        }
        for taxid, name, rank in zip(taxids, names, ranks)
    ]

    # Sparse format: [row_idx, col_idx, value] for non-zero reads
    biom_data["data"] = [
        [idx, 0, reads]
        for idx, reads in enumerate(reads_vals) if reads > 0
    ]

    biom_json = json.dumps(biom_data, indent=2)

    if output_path:
        with open(output_path, 'w') as f:
            f.write(biom_json)
        logging.info(f"Exported BIOM data to {output_path}")
        return output_path
    else:
        return biom_json


def export_to_krona_xml(
    kraken_df: pd.DataFrame,
    sample_name: str = "sample1",
    output_path: Optional[str] = None
) -> str:
    """
    Export Kraken2 classification data to Krona XML format.

    This creates an XML file that can be converted to an interactive
    HTML visualization using the Krona ktImportXML tool.

    Args:
        kraken_df: DataFrame with Kraken2 report data
        sample_name: Name of the sample
        output_path: Path to save file (None returns string)

    Returns:
        Krona XML string if output_path is None, else the output path
    """
    if kraken_df.empty:
        raise ValueError("Cannot export empty DataFrame")

    # Build Krona XML
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<krona>',
        f'  <attributes magnitude="reads">',
        '    <attribute display="Read Count">reads</attribute>',
        '  </attributes>',
        f'  <datasets>',
        f'    <dataset>{sample_name}</dataset>',
        '  </datasets>',
        '  <node name="root">'
    ]

    # Build taxonomy hierarchy
    # Group by rank and build tree structure
    rank_order = ['D', 'K', 'P', 'C', 'O', 'F', 'G', 'S']

    # Simple flat export for now (hierarchical would require more complex tree building)
    # Vectorized approach: filter and prepare data first
    valid_df = kraken_df[
        (kraken_df['reads'].fillna(0) > 0) &
        (kraken_df['name'].fillna('').str.strip() != '') &
        (~kraken_df['name'].fillna('').str.lower().str.contains('unclassified'))
    ].copy()

    if not valid_df.empty:
        # Extract data as lists for fast iteration
        names = valid_df['name'].str.strip().tolist()
        reads_vals = valid_df['reads'].fillna(0).astype(int).tolist()

        # Build XML nodes using list comprehension
        for name, reads in zip(names, reads_vals):
            # Escape XML special characters
            name_escaped = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            xml_lines.append(f'    <node name="{name_escaped}">')
            xml_lines.append(f'      <reads><val>{reads}</val></reads>')
            xml_lines.append(f'    </node>')

    xml_lines.extend([
        '  </node>',
        '</krona>'
    ])

    xml_content = '\n'.join(xml_lines)

    if output_path:
        with open(output_path, 'w') as f:
            f.write(xml_content)
        logging.info(f"Exported Krona XML to {output_path}")
        return output_path
    else:
        return xml_content


def export_species_summary(
    kraken_df: pd.DataFrame,
    top_n: int = 50,
    output_path: Optional[str] = None
) -> str:
    """
    Export a summary of top species by read count.

    Args:
        kraken_df: DataFrame with Kraken2 report data
        top_n: Number of top species to include
        output_path: Path to save file (None returns string)

    Returns:
        Summary CSV string if output_path is None, else the output path
    """
    if kraken_df.empty:
        raise ValueError("Cannot export empty DataFrame")

    # Filter to species level
    species_df = kraken_df[kraken_df['rank'] == 'S'].copy()

    if species_df.empty:
        raise ValueError("No species-level classifications found")

    # Sort by reads and take top N
    top_species = species_df.nlargest(top_n, 'reads')

    # Calculate percentages
    total_reads = species_df['reads'].sum()
    top_species['percentage'] = (top_species['reads'] / total_reads * 100).round(2)

    # Select and rename columns
    export_df = top_species[['taxid', 'name', 'reads', 'percentage']].copy()
    export_df.columns = ['Tax_ID', 'Species', 'Read_Count', 'Percentage']

    # Add rank column
    export_df.insert(0, 'Rank', range(1, len(export_df) + 1))

    if output_path:
        export_df.to_csv(output_path, index=False)
        logging.info(f"Exported species summary to {output_path}")
        return output_path
    else:
        return export_df.to_csv(index=False)


def get_export_filename(
    base_name: str,
    format_type: str,
    sample_name: Optional[str] = None
) -> str:
    """
    Generate a standardized export filename.

    Args:
        base_name: Base name for the file (e.g., "classification")
        format_type: Export format ("csv", "tsv", "biom", "krona")
        sample_name: Sample name to include (optional)

    Returns:
        Formatted filename with timestamp
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    ext_map = {
        "csv": ".csv",
        "tsv": ".tsv",
        "biom": ".biom",
        "krona": ".xml",
        "json": ".json"
    }

    ext = ext_map.get(format_type.lower(), ".txt")

    if sample_name and sample_name != "All Samples":
        return f"{base_name}_{sample_name}_{timestamp}{ext}"
    else:
        return f"{base_name}_{timestamp}{ext}"
