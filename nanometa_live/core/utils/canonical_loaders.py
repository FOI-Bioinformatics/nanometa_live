"""
Canonical format loaders for Nanometa Live.

Functions for loading data from the canonical intermediate JSON format
produced by nanometanf canonical writer modules. Each loader returns
data in a structure compatible with the existing raw-format loaders,
or None if the canonical file is not available (triggering fallback
to raw parsing).
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd


def load_manifest(results_dir: str) -> Optional[Dict[str, Any]]:
    """
    Load the canonical run manifest.

    The manifest provides run-level metadata including sample list,
    tool identity, and output availability, eliminating the need for
    glob-based detection.

    Args:
        results_dir: Path to the pipeline results directory.

    Returns:
        Parsed manifest dictionary, or None if not found or invalid.
    """
    path = os.path.join(results_dir, "canonical", "_manifest.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning("Failed to load canonical manifest %s: %s", path, exc)
        return None


def load_canonical_classification(
    results_dir: str, sample_id: str
) -> Optional[pd.DataFrame]:
    """
    Load classification data from canonical JSON format.

    Returns a DataFrame with columns matching KRAKEN2_EXPECTED_COLUMNS
    (%, cumul_reads, reads, rank, taxid, name, parent_taxid) so that
    existing visualization code works without modification.

    Args:
        results_dir: Path to the pipeline results directory.
        sample_id: Sample identifier (e.g. "barcode01").

    Returns:
        DataFrame with classification data, or None if canonical file
        is not available.
    """
    path = os.path.join(
        results_dir, "canonical", "classification",
        f"{sample_id}.classification.json",
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)

        taxa = data.get("taxa")
        if not taxa:
            logging.debug("Canonical classification for %s has no taxa", sample_id)
            return pd.DataFrame(
                columns=["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]
            )

        df = pd.DataFrame(taxa)
        # Map canonical column names to existing column names for compatibility
        df = df.rename(columns={
            "percent": "%",
            "reads_clade": "cumul_reads",
            "reads_direct": "reads",
        })

        # Ensure expected columns exist
        for col in ["%", "cumul_reads", "reads", "rank", "taxid", "name"]:
            if col not in df.columns:
                logging.warning(
                    "Canonical classification for %s missing column '%s'",
                    sample_id, col,
                )
                return None

        # Ensure numeric types
        df["taxid"] = pd.to_numeric(df["taxid"], errors="coerce").fillna(0).astype(int)
        df["reads"] = pd.to_numeric(df["reads"], errors="coerce").fillna(0).astype(int)
        df["cumul_reads"] = pd.to_numeric(df["cumul_reads"], errors="coerce").fillna(0).astype(int)
        df["%"] = pd.to_numeric(df["%"], errors="coerce").fillna(0.0)

        # parent_taxid defaults to 0 if absent
        if "parent_taxid" not in df.columns:
            df["parent_taxid"] = 0
        else:
            df["parent_taxid"] = (
                pd.to_numeric(df["parent_taxid"], errors="coerce").fillna(0).astype(int)
            )

        return df

    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logging.warning(
            "Failed to load canonical classification for %s: %s", sample_id, exc
        )
        return None


def load_canonical_qc_stats(
    results_dir: str, sample_id: str
) -> Optional[Dict[str, Any]]:
    """
    Load QC statistics from canonical JSON format.

    Returns a dictionary compatible with the structure expected by
    qc_tab.py, mapping canonical keys to the existing fastp-style keys.

    Args:
        results_dir: Path to the pipeline results directory.
        sample_id: Sample identifier (e.g. "barcode01").

    Returns:
        Dictionary with QC statistics, or None if canonical file
        is not available.
    """
    path = os.path.join(
        results_dir, "canonical", "qc",
        f"{sample_id}.qc_stats.json",
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)

        after = data.get("after_filtering", {})
        before = data.get("before_filtering") or {}
        filtering = data.get("filtering_result") or {}

        # Map to the fastp-compatible dict structure used by qc_tab.py
        stats = {
            "total_reads_before": before.get("total_reads", 0),
            "total_reads_after": after.get("total_reads", 0),
            "total_bases_before": before.get("total_bases", 0),
            "total_bases_after": after.get("total_bases", 0),
            "passed_filter": filtering.get("passed_filter_reads", 0),
            "low_quality": filtering.get("low_quality_reads", 0),
            "too_short": filtering.get("too_short_reads", 0),
            "too_many_N": filtering.get("too_many_n_reads", 0),
            "q30_rate_after": after.get("q30_rate", 0.0),
        }
        return stats

    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logging.warning(
            "Failed to load canonical QC stats for %s: %s", sample_id, exc
        )
        return None


def load_canonical_validation(
    results_dir: str, sample_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Load canonical validation aggregate results.

    Returns the parsed validation_results.json from the canonical
    directory, or None if the file is not available.

    Args:
        results_dir: Path to the pipeline results directory.
        sample_id: Unused (aggregate file covers all samples), kept
            for interface consistency.

    Returns:
        Dictionary with aggregate validation data, or None if not available.
    """
    path = os.path.join(
        results_dir, "canonical", "validation", "validation_results.json"
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning(
            "Failed to load canonical validation results: %s", exc
        )
        return None


def load_canonical_assembly(
    results_dir: str, sample_id: str
) -> Optional[Dict[str, Any]]:
    """
    Load assembly statistics from canonical JSON format.

    Args:
        results_dir: Path to the pipeline results directory.
        sample_id: Sample identifier (e.g. "barcode01").

    Returns:
        Dictionary with assembly statistics, or None if not available.
    """
    path = os.path.join(
        results_dir, "canonical", "assembly",
        f"{sample_id}.assembly_stats.json",
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning(
            "Failed to load canonical assembly stats for %s: %s",
            sample_id, exc,
        )
        return None
