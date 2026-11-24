"""Display names for samples.

MinKNOW writes reads it could not assign to a barcode into a folder named
``unclassified`` beside ``barcode01`` ... ``barcodeNN``. Nanometa Live and
nanometanf treat it as a sample, which is correct: its reads are real and a
detection in them is worth seeing. On screen, though, it was listed among a
detection's samples as plain "unclassified" (Barcelona exercise feedback,
2026-11-24), a word Kraken2 uses for reads it could not classify.

``display_sample_name`` is for text an operator reads. Never apply it to a
value used as a key, a path or a Store entry.
"""

UNASSIGNED_SAMPLE = "unclassified"


def display_sample_name(sample: str) -> str:
    """``unclassified (no barcode)`` for MinKNOW's unassigned folder."""
    if sample == UNASSIGNED_SAMPLE:
        return f"{UNASSIGNED_SAMPLE} (no barcode)"
    return sample
