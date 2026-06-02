#!/usr/bin/env python3
"""Code-size ratchet: flag NEW oversized files and functions.

The repository already contains some large modules and functions (god files
accrued before the 2026-06 tech-debt pass). Rewriting all of them at once is
not the goal; *preventing new ones* is. This script reports every file over
``FILE_MAX_LINES`` and every function over ``FUNC_MAX_LINES``, then compares
the set against a committed baseline so CI fails only when a NEW violation
appears (a brand-new oversized file, or an existing item crossing the
threshold for the first time).

Function length is measured with the ``ast`` module (``end_lineno`` -
``lineno``), not a line-counting heuristic, so a closure nested in a large
function is measured as its own function rather than inflating an outer one
(the mismeasurement that made ``add_cache_headers`` look like 513 lines in the
original audit).

Usage:
    python scripts/check_code_size.py            # check; exit 1 on NEW violations
    python scripts/check_code_size.py --update   # rewrite the baseline to current
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "nanometa_live"
BASELINE_PATH = REPO_ROOT / "scripts" / "code_size_baseline.json"

FILE_MAX_LINES = 800
FUNC_MAX_LINES = 80


def _iter_source_files():
    for path in sorted(SOURCE_DIR.rglob("*.py")):
        yield path


def _function_violations(path: Path, rel: str):
    """Yield (key, length) for every function in *path* longer than the cap."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return

    stack: list[str] = []

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = ".".join(scope + [child.name])
                end = getattr(child, "end_lineno", child.lineno)
                length = end - child.lineno + 1
                if length > FUNC_MAX_LINES:
                    yield f"{rel}::{qualname}", length
                yield from visit(child, scope + [child.name])
            elif isinstance(child, ast.ClassDef):
                yield from visit(child, scope + [child.name])
            else:
                yield from visit(child, scope)

    yield from visit(tree, stack)


def collect_violations() -> dict[str, int]:
    """Return {key: size} for all current file and function violations."""
    violations: dict[str, int] = {}
    for path in _iter_source_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        line_count = path.read_text(encoding="utf-8").count("\n") + 1
        if line_count > FILE_MAX_LINES:
            violations[rel] = line_count
        for key, length in _function_violations(path, rel):
            violations[key] = length
    return violations


def load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return set(data.get("allowed", []))


def write_baseline(violations: dict[str, int]) -> None:
    payload = {
        "_comment": (
            "Code-size ratchet baseline. Keys are existing files >"
            f"{FILE_MAX_LINES} LOC and functions >{FUNC_MAX_LINES} LOC that "
            "predate the ratchet. CI fails only on keys NOT listed here. "
            "Regenerate with: python scripts/check_code_size.py --update "
            "(only ever to REMOVE entries you have just shrunk -- adding "
            "entries means you are admitting new debt)."
        ),
        "file_max_lines": FILE_MAX_LINES,
        "func_max_lines": FUNC_MAX_LINES,
        "allowed": sorted(violations),
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the baseline to the current set of violations.",
    )
    args = parser.parse_args()

    violations = collect_violations()

    if args.update:
        write_baseline(violations)
        print(f"Baseline updated: {len(violations)} allowed entries written to "
              f"{BASELINE_PATH.relative_to(REPO_ROOT)}")
        return 0

    baseline = load_baseline()
    current = set(violations)
    new = sorted(current - baseline)
    resolved = sorted(baseline - current)

    if resolved:
        print(f"note: {len(resolved)} baselined item(s) no longer exceed the cap. "
              "Run --update to shrink the baseline:")
        for key in resolved:
            print(f"  - {key}")

    if new:
        print()
        print(f"FAIL: {len(new)} new code-size violation(s) "
              f"(files >{FILE_MAX_LINES} LOC, functions >{FUNC_MAX_LINES} LOC):")
        for key in new:
            print(f"  - {key} ({violations[key]} lines)")
        print()
        print("Split the file/function, or -- if genuinely unavoidable -- run "
              "`python scripts/check_code_size.py --update` to accept it.")
        return 1

    print(f"OK: no new code-size violations "
          f"({len(baseline)} pre-existing item(s) baselined).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
