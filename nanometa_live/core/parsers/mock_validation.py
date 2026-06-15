"""Mock validation-data generator for UI testing.

Extracted from ``blast_validation_parser`` to keep the production parser under
the file-size cap and out of the demo/test scaffolding. Generates realistic
per-(sample, taxid) validation JSON files without an actual pipeline run.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from nanometa_live.core.parsers.blast_validation_parser import ValidationResult

logger = logging.getLogger(__name__)


def generate_mock_validation_data(
    samples: List[str],
    pathogens: List[Dict[str, Any]],
    output_dir: str,
) -> None:
    """
    Generate mock validation data for UI testing.

    Creates realistic validation JSON files without requiring an actual pipeline
    run. Useful for development and testing of the validation UI.

    Args:
        samples: List of sample names
        pathogens: List of pathogen dicts with 'taxid' and 'name' keys
        output_dir: Directory to write mock files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for sample in samples:
        for pathogen in pathogens:
            taxid = pathogen.get('taxid', 0)
            name = pathogen.get('name', f'Species {taxid}')

            # Generate realistic mock data
            total_reads = random.randint(100, 5000)
            validation_rate = random.uniform(0.3, 0.99)
            validated_reads = int(total_reads * validation_rate)

            # Identity varies with validation rate
            base_identity = 85 + (validation_rate * 12)
            identity_mean = min(100, base_identity + random.uniform(-2, 2))
            identity_min = max(70, identity_mean - random.uniform(5, 15))
            identity_max = min(100, identity_mean + random.uniform(2, 5))

            result = ValidationResult(
                sample_id=sample,
                taxid=taxid,
                species=name,
                total_reads=total_reads,
                validated_reads=validated_reads,
                percent_validated=round(validation_rate * 100, 2),
                percent_identity_mean=round(identity_mean, 1),
                percent_identity_min=round(identity_min, 1),
                percent_identity_max=round(identity_max, 1),
                alignment_length_mean=round(random.uniform(200, 800), 0),
                coverage_breadth=round(random.uniform(0.4, 0.95), 2),
                coverage_depth_mean=round(random.uniform(5, 50), 1),
                validation_method='blast',
                reference_accession=f'GCF_{random.randint(100000, 999999)}.1',
                timestamp=datetime.now().isoformat(),
            )
            result.status = result.determine_status()

            # Write individual file
            filename = f"{sample}_{taxid}_validation.json"
            with open(output_path / filename, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)

    logger.info(
        f"Generated mock validation data for {len(samples)} samples, "
        f"{len(pathogens)} pathogens"
    )
