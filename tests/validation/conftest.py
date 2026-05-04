"""
Pytest configuration for validation tests.

Adds the project root to sys.path so that the 'tests' package
is importable (required by tests that use absolute imports like
'from tests.validation.generate_synthetic_data import ...').
"""

import sys
from pathlib import Path

# Add the project root (two levels up from this file) to sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
