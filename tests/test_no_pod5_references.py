"""Regression test: verify POD5/Dorado/basecalling code paths are fully removed.

Nanometa Live v2 and the nanometanf pipeline accept only basecalled FASTQ input.
This test guards against regressions that reintroduce POD5 signal-level paths,
Dorado basecaller invocations, or related configuration hooks in production code.

Documentation strings may legitimately reference these terms for historical
context or migration notes, so documentation directories are excluded from the
scan. Tests and fixtures are also excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "nanometa_live"

# Files/directories whose contents are exempt from the scan.
EXEMPT_SUFFIX_DIRS = {"__pycache__", ".pyc"}
EXEMPT_DIR_NAMES = {
    "__pycache__",
    "docs",
    "tests",
    "examples",
    "screenshots",
    ".git",
    "Nanometa_Live.egg-info",
}

# Patterns that indicate POD5/Dorado/basecalling references in production code.
FORBIDDEN_PATTERNS = [
    re.compile(r"\bpod5\b", re.IGNORECASE),
    re.compile(r"\bdorado\b", re.IGNORECASE),
    re.compile(r"\bbasecall(ing|er|ed)?\b", re.IGNORECASE),
]

# Narrow allowlist for comments that explicitly document the removal.
ALLOWED_PHRASES = [
    "pipeline no longer accepts POD5 input",
    "basecalled fastq",  # config.yaml description of post-basecalling FASTQ input
]


def _should_skip(path: Path) -> bool:
    if path.suffix in {".pyc", ".pyo", ".so"}:
        return True
    for part in path.parts:
        if part in EXEMPT_DIR_NAMES:
            return True
        if part in EXEMPT_SUFFIX_DIRS:
            return True
    return False


def _iter_source_files():
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path):
            continue
        # Only scan text-like source and config files.
        if path.suffix not in {".py", ".yaml", ".yml", ".json", ".md", ".cfg", ".toml", ".ini"}:
            continue
        yield path


def _line_is_allowed(line: str) -> bool:
    lowered = line.lower()
    return any(phrase.lower() in lowered for phrase in ALLOWED_PHRASES)


def test_no_pod5_or_dorado_in_production_code():
    offenders = []
    for source_file in _iter_source_files():
        try:
            text = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if _line_is_allowed(line):
                continue
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    offenders.append(
                        f"{source_file.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                    )
                    break

    assert not offenders, (
        "Found POD5/Dorado/basecalling references in production code:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "core/utils/auto_detect.py",
        "core/utils/language_utils.py",
        "config.yaml",
    ],
)
def test_known_entry_points_have_no_forbidden_tokens(relative_path):
    """Pin specific files that previously contained POD5/Dorado logic."""
    target = PACKAGE_ROOT / relative_path
    assert target.exists(), f"Expected file missing: {relative_path}"

    text = target.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _line_is_allowed(line):
            continue
        for pattern in FORBIDDEN_PATTERNS:
            assert not pattern.search(line), (
                f"Forbidden token found in {relative_path}:{lineno}: {line.strip()}"
            )
