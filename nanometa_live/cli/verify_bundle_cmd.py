"""`nanometa-prepare verify` -- dry-run bundle check.

Split out of ``cli/prepare.py`` for the file-size ratchet; the command is
registered from there (``verify_p.set_defaults(func=_verify)``).
"""

import os
import sys


def _verify(args):
    """Verify a bundle without installing anything.

    ``import`` is the only other code path that checks a bundle, and it
    writes as it goes; an operator with a USB copy of a multi-GB bundle
    could not confirm the transfer before committing the field machine to
    it. Shares one implementation with the import path
    (``BundleManager._verify_extracted_bundle``) so the dry run cannot
    disagree with the real thing.
    """
    # Imported lazily: prepare.py imports this module at top level, so a
    # module-level import back into prepare would be circular.
    from nanometa_live.cli.prepare import (
        _BOLD, _DIM, _GREEN, _RED, _RESET, _YELLOW,
    )
    from nanometa_live.core.workflow.bundle_manager import BundleManager

    if not os.path.exists(args.bundle):
        print(f"{_RED}Bundle not found: {args.bundle}{_RESET}", file=sys.stderr)
        sys.exit(1)

    print(f"{_BOLD}Nanometa Live - Verify Bundle{_RESET}")
    print(f"  Bundle: {args.bundle}")
    if args.db:
        print(f"  Kraken2 DB: {args.db}")
    print(f"{_DIM}  Read-only: nothing on this machine is modified.{_RESET}")
    print()

    result = BundleManager().verify_bundle(args.bundle, kraken_db_path=args.db)

    manifest = result.get("manifest", {})
    if manifest:
        print(f"  Created:        {manifest.get('created', 'unknown')}")
        print(f"  Built by:       {manifest.get('creator', 'unknown')}")
        plat = manifest.get("build_platform", {})
        if plat:
            print(
                f"  Build platform: {plat.get('system', '?')}/"
                f"{plat.get('machine', '?')}"
            )
        print(f"  Files:          {len(manifest.get('checksums', {}))}")
        # The manifest records the engine under "engine" (see export_bundle);
        # this line previously read a nonexistent "mode" key and never printed.
        engine = manifest.get("containerization", {}).get("engine")
        if engine:
            print(f"  Containerization: {engine}")
        pwc = manifest.get("pre_warm_conda_envs", {})
        if pwc.get("attempted"):
            print(
                f"  Pre-warmed envs:  {pwc.get('env_count', 0)} "
                f"({'ok' if pwc.get('success') else 'FAILED'})"
            )
        print()

    mismatches = result.get("checksum_mismatches") or []
    if mismatches:
        print(f"{_RED}Checksum failures ({len(mismatches)}):{_RESET}")
        for m in mismatches[:20]:
            print(f"  - {m}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")
        print()

    if result.get("warnings"):
        print(f"{_YELLOW}Warnings:{_RESET}")
        for w in result["warnings"]:
            print(f"  - {w}")
        print()

    if result["success"]:
        print(f"{_GREEN}{_BOLD}Bundle verified. Safe to import.{_RESET}")
    else:
        print(f"{_RED}{_BOLD}Bundle verification FAILED. Do not import "
              f"without --force.{_RESET}")

    sys.exit(0 if result["success"] else 1)
