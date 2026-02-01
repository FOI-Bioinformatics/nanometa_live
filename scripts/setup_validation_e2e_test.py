#!/usr/bin/env python3
"""
End-to-end test setup for validation functionality.

This script:
1. Creates mock validation data in the results directory
2. Updates test_config.yaml to enable blast_validation
3. Provides instructions for running the app
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import random

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def generate_validation_data(results_dir: str, samples: list[str]) -> Path:
    """
    Generate mock validation data files.

    Args:
        results_dir: Path to results directory
        samples: List of sample names

    Returns:
        Path to validation directory
    """
    validation_dir = Path(results_dir) / "blast_validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    # Common pathogens for testing
    pathogens = [
        {"taxid": 562, "name": "Escherichia coli", "accession": "GCF_000005845.2"},
        {"taxid": 1280, "name": "Staphylococcus aureus", "accession": "GCF_000013425.1"},
        {"taxid": 573, "name": "Klebsiella pneumoniae", "accession": "GCF_000016305.1"},
        {"taxid": 287, "name": "Pseudomonas aeruginosa", "accession": "GCF_000006765.1"},
        {"taxid": 1313, "name": "Streptococcus pneumoniae", "accession": "GCF_000007045.1"},
        {"taxid": 90371, "name": "Salmonella enterica", "accession": "GCF_000006945.2"},
    ]

    all_validations = []

    for sample in samples:
        for pathogen in pathogens:
            # Generate realistic mock data with some variation
            total_reads = random.randint(200, 3000)

            # Create varied validation rates for different statuses
            if pathogen["taxid"] in [562, 1280]:  # E. coli and S. aureus - confirmed
                validation_rate = random.uniform(0.85, 0.98)
                identity_base = 95
            elif pathogen["taxid"] in [573, 287]:  # K. pneumoniae, P. aeruginosa - partial
                validation_rate = random.uniform(0.55, 0.75)
                identity_base = 88
            elif pathogen["taxid"] == 1313:  # S. pneumoniae - low confidence
                validation_rate = random.uniform(0.2, 0.45)
                identity_base = 82
            else:  # S. enterica - very few reads
                validation_rate = random.uniform(0.05, 0.15)
                identity_base = 78

            validated_reads = int(total_reads * validation_rate)
            percent_validated = round(validation_rate * 100, 2)

            # Identity varies around base
            identity_mean = min(100, identity_base + random.uniform(-3, 4))
            identity_min = max(70, identity_mean - random.uniform(8, 18))
            identity_max = min(100, identity_mean + random.uniform(1, 6))

            # Determine status
            if percent_validated >= 80 and identity_mean >= 90:
                status = "confirmed"
            elif percent_validated >= 50:
                status = "partial"
            elif percent_validated > 0:
                status = "low"
            else:
                status = "no_data"

            result = {
                "sample_id": sample,
                "taxid": pathogen["taxid"],
                "species": pathogen["name"],
                "total_reads": total_reads,
                "validated_reads": validated_reads,
                "percent_validated": percent_validated,
                "percent_identity_mean": round(identity_mean, 1),
                "percent_identity_min": round(identity_min, 1),
                "percent_identity_max": round(identity_max, 1),
                "alignment_length_mean": round(random.uniform(300, 700), 0),
                "coverage_breadth": round(random.uniform(0.3, 0.9), 2),
                "coverage_depth_mean": round(random.uniform(5, 40), 1),
                "validation_method": "blast",
                "reference_accession": pathogen["accession"],
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }

            # Write individual file
            filename = f"{sample}_{pathogen['taxid']}_validation.json"
            with open(validation_dir / filename, 'w') as f:
                json.dump(result, f, indent=2)

            all_validations.append(result)
            print(f"  Created: {filename} ({status})")

    # Write summary file
    summary = {
        "generated_at": datetime.now().isoformat(),
        "samples": samples,
        "pathogens": len(pathogens),
        "validations": all_validations
    }

    with open(validation_dir / "validation_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\nCreated validation_summary.json with {len(all_validations)} entries")

    return validation_dir


def update_config(config_path: str) -> None:
    """Enable blast_validation in the config file."""
    import yaml

    with open(config_path, 'r') as f:
        content = f.read()

    # Simple replacement to enable blast_validation
    if "blast_validation: false" in content:
        content = content.replace("blast_validation: false", "blast_validation: true")
        with open(config_path, 'w') as f:
            f.write(content)
        print(f"Updated {config_path}: blast_validation = true")
    elif "blast_validation: true" in content:
        print(f"Config already has blast_validation = true")
    else:
        print(f"Warning: Could not find blast_validation setting in {config_path}")


def main():
    """Set up end-to-end validation test."""
    print("=" * 60)
    print("Validation End-to-End Test Setup")
    print("=" * 60)

    # Configuration
    results_dir = "/Users/andreassjodin/Desktop/deving/new/kraken2_tests/incremental/outputs/inc01_final"
    config_path = "/Users/andreassjodin/Desktop/deving/nanometa_live/test_config.yaml"
    samples = ["inc01_sample1"]

    # Check results directory exists
    if not Path(results_dir).exists():
        print(f"Error: Results directory not found: {results_dir}")
        sys.exit(1)

    print(f"\n1. Generating mock validation data...")
    print(f"   Results dir: {results_dir}")
    print(f"   Samples: {samples}")
    validation_dir = generate_validation_data(results_dir, samples)

    print(f"\n2. Updating configuration...")
    update_config(config_path)

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"\nValidation data created in: {validation_dir}")
    print(f"\nTo run the app and test validation:")
    print(f"  cd {project_root}")
    print(f"  python -m nanometa_live.app --config test_config.yaml")
    print(f"\nThen open: http://localhost:8050")
    print(f"Navigate to the 'Validation' tab to see results.")
    print("=" * 60)


if __name__ == "__main__":
    main()
