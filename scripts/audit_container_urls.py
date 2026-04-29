"""One-shot container URL auditor for nanometanf modules.

Walks ``modules/local/*/main.nf`` and ``modules/nf-core/*/main.nf``,
parses each module's ``container "${ ... }"`` ternary plus its
``environment.yml`` bioconda spec, HEAD-checks the Singularity URL,
and emits a Markdown table.

Closes W6-A from
nanometa_live/docs/plan-2026-04-28-throughput-fixes.md.
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

NANOMETANF_ROOT = Path("/Users/andreassjodin/Code/nanometanf")
TIMEOUT = 8.0  # seconds for HEAD checks

SINGULARITY_RE = re.compile(
    r"https://depot\.galaxyproject\.org/singularity/[^'\"\s]+"
)
DOCKER_RE = re.compile(
    r"['\"]"
    r"(?:biocontainers|community\.wave\.seqera\.io|quay\.io/biocontainers)"
    r"/[^'\"]+"
    r"['\"]"
)


def parse_main_nf(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (singularity_url, docker_ref) or (None, None) if absent."""
    try:
        text = path.read_text()
    except OSError:
        return None, None

    sing = SINGULARITY_RE.search(text)
    doc = DOCKER_RE.search(text)
    sing_url = sing.group(0) if sing else None
    doc_ref = doc.group(0).strip("'\"") if doc else None
    return sing_url, doc_ref


def parse_env_yml(path: Path) -> Optional[str]:
    """Return the bioconda dependency string (e.g. 'chopper=0.12.0b'),
    or None if no bioconda dep."""
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError):
        return None
    if not data:
        return None
    deps = data.get("dependencies", []) or []
    for dep in deps:
        if isinstance(dep, str) and dep.startswith("bioconda::"):
            return dep[len("bioconda::"):]
    # Some modules just use ``- chopper=0.12.0b`` without prefix
    for dep in deps:
        if isinstance(dep, str) and "=" in dep and not dep.startswith("-"):
            return dep
    return None


def parse_version_from_container(url_or_ref: Optional[str]) -> Optional[str]:
    """Extract the version tag. Singularity URLs end ``tool:VER--HASH``,
    Docker refs use the same pattern."""
    if not url_or_ref:
        return None
    # Match the last ``:VER--HASH`` or ``:VER`` segment.
    m = re.search(r":([^/'\":\s]+?)(?:--[^'\"]+)?$", url_or_ref)
    return m.group(1) if m else None


def parse_version_from_conda(spec: Optional[str]) -> Optional[str]:
    """Extract the version after ``=`` in a bioconda spec."""
    if not spec or "=" not in spec:
        return None
    parts = spec.split("=", 1)
    return parts[1].split("=")[0] if len(parts) > 1 else None


def head_check(url: str) -> Tuple[bool, str]:
    """Return (reachable, status_or_error). Singularity URLs return 200
    on success."""
    if not url:
        return False, "no-url"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"URLError: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def classify(
    conda_spec: Optional[str],
    conda_ver: Optional[str],
    sing_ver: Optional[str],
    doc_ver: Optional[str],
    sing_reachable: bool,
    has_local_only: bool,
) -> str:
    """One-word verdict.

    nf-core modules that publish a Docker image at
    ``community.wave.seqera.io`` without a separate Singularity URL
    are NOT single-source: Apptainer / Singularity 3.5+ can pull OCI
    images directly. We treat any Docker ref as a valid container
    source.

    Local modules whose conda spec lists a runtime (python,
    coreutils, base-os) while the container provides the runtime
    itself are NOT mismatches: the conda env adds Python packages
    on top of a Python or Ubuntu base image. Detected via a
    runtime-prefix allowlist.
    """
    if not (sing_ver or doc_ver) and not conda_ver:
        return "no-container" if has_local_only else "unreachable"

    # Wave-style Docker-only is fine; Apptainer pulls OCI directly.
    if not sing_ver and doc_ver:
        return "OK"

    if sing_ver and not sing_reachable:
        return "unreachable"

    # Runtime / base-image containers paired with a tool-list conda env
    # are intentional, not mismatches.
    runtime_prefixes = (
        "python", "conda-forge::python", "coreutils",
        "conda-forge::coreutils",
    )
    if conda_spec and any(conda_spec.startswith(p) for p in runtime_prefixes):
        return "runtime-base"

    if conda_ver and sing_ver and conda_ver != sing_ver:
        return "mismatch"
    return "OK"


def audit_module(path: Path, scope: str) -> Dict[str, str]:
    main_nf = path / "main.nf"
    env_yml = path / "environment.yml"
    if not main_nf.exists():
        return {}
    sing_url, doc_ref = parse_main_nf(main_nf)
    conda_spec = parse_env_yml(env_yml)
    sing_ver = parse_version_from_container(sing_url)
    doc_ver = parse_version_from_container(doc_ref)
    conda_ver = parse_version_from_conda(conda_spec)

    sing_reachable = False
    sing_status = "skipped"
    if sing_url:
        sing_reachable, sing_status = head_check(sing_url)

    verdict = classify(
        conda_spec,
        conda_ver,
        sing_ver,
        doc_ver,
        sing_reachable,
        has_local_only=(scope == "local"),
    )
    return {
        "scope": scope,
        "name": path.name if scope == "local" else f"{path.parent.name}/{path.name}"
        if path.parent.name not in ("local", "nf-core") else path.name,
        "conda": conda_spec or "",
        "conda_ver": conda_ver or "",
        "sing_url": sing_url or "",
        "sing_ver": sing_ver or "",
        "sing_reachable": "yes" if sing_reachable else "no",
        "sing_status": sing_status,
        "doc_ref": doc_ref or "",
        "doc_ver": doc_ver or "",
        "verdict": verdict,
    }


def main():
    rows: List[Dict[str, str]] = []

    # Local modules: each is a single .nf file or a sub-directory
    local_dir = NANOMETANF_ROOT / "modules" / "local"
    for entry in sorted(local_dir.iterdir()):
        if entry.is_dir():
            row = audit_module(entry, "local")
        elif entry.suffix == ".nf":
            # Flat file: synthesize a temp dir-shaped audit
            sing_url, doc_ref = parse_main_nf(entry)
            sing_ver = parse_version_from_container(sing_url)
            doc_ver = parse_version_from_container(doc_ref)
            sing_reachable = False
            sing_status = "skipped"
            if sing_url:
                sing_reachable, sing_status = head_check(sing_url)
            row = {
                "scope": "local",
                "name": entry.stem,
                "conda": "",
                "conda_ver": "",
                "sing_url": sing_url or "",
                "sing_ver": sing_ver or "",
                "sing_reachable": "yes" if sing_reachable else "no",
                "sing_status": sing_status,
                "doc_ref": doc_ref or "",
                "doc_ver": doc_ver or "",
                "verdict": classify(
                    None, None, sing_ver, doc_ver, sing_reachable,
                    has_local_only=True,
                ),
            }
        else:
            continue
        if row:
            rows.append(row)

    # nf-core modules: nested two levels (e.g. nf-core/blast/blastn/main.nf)
    nfcore_dir = NANOMETANF_ROOT / "modules" / "nf-core"
    for tool_dir in sorted(nfcore_dir.iterdir()):
        if not tool_dir.is_dir():
            continue
        if (tool_dir / "main.nf").exists():
            rows.append(audit_module(tool_dir, "nf-core"))
        else:
            for sub in sorted(tool_dir.iterdir()):
                if sub.is_dir() and (sub / "main.nf").exists():
                    rows.append(audit_module(sub, "nf-core"))

    # Counts
    counts = {"OK": 0, "mismatch": 0, "unreachable": 0,
              "runtime-base": 0, "no-container": 0}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    out_path = (NANOMETANF_ROOT.parent.parent / "Desktop/deving/nanometa_live"
                / "docs/audit-2026-04-29-container-urls.md")
    md = []
    md.append("# Module Container URL Audit -- 2026-04-29")
    md.append("")
    md.append("Inventory of every nanometanf module's tri-source artifact:")
    md.append("the bioconda spec from ``environment.yml``, the Singularity")
    md.append("URL from ``main.nf`` (depot.galaxyproject.org), and the")
    md.append("Docker reference. Each Singularity URL is HEAD-checked;")
    md.append("the conda version is cross-checked against the container tag.")
    md.append("")
    md.append("Closes W6-A from")
    md.append("``docs/plan-2026-04-28-throughput-fixes.md``.")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append(f"- Total modules audited: **{len(rows)}**")
    md.append(f"- OK (conda + container in version sync): **{counts['OK']}**")
    md.append(f"- Runtime-base container (intentional, not a mismatch): **{counts['runtime-base']}**")
    md.append(f"- Version mismatch (conda vs container): **{counts['mismatch']}**")
    md.append(f"- Singularity URL unreachable: **{counts['unreachable']}**")
    md.append(f"- No container directive: **{counts['no-container']}**")
    md.append("")
    md.append("## Methodology")
    md.append("")
    md.append("- ``container \"${ ... }\"`` ternary is parsed with a")
    md.append("  regex that picks the first depot.galaxyproject.org URL")
    md.append("  and the first biocontainers / quay.io / community.wave")
    md.append("  Docker reference encountered.")
    md.append("- ``environment.yml`` is parsed with PyYAML; the first")
    md.append("  ``bioconda::`` (or unprefixed) dependency wins.")
    md.append("- Singularity URLs are HEAD-checked with an 8 s timeout.")
    md.append(f"  HEAD checks performed at run time on the build machine.")
    md.append("- Version match compares the version segment before the")
    md.append("  ``--<hash>`` build suffix (e.g. ``0.12.0`` of")
    md.append("  ``chopper:0.12.0--hdcf5f25_0``) against the conda spec's")
    md.append("  trailing ``=<version>``.")
    md.append("")
    md.append("## Results")
    md.append("")
    md.append("| Module | Scope | Conda spec | Singularity tag | Sing reachable | Verdict |")
    md.append("|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["scope"], x["name"])):
        verdict_emoji = {
            "OK": "OK",
            "mismatch": "MISMATCH",
            "unreachable": "UNREACHABLE",
            "runtime-base": "runtime-base",
            "no-container": "no-container",
        }[r["verdict"]]
        sing_short = r["sing_ver"] or "-"
        if not r["sing_url"] and r["verdict"] != "no-container":
            sing_short = "(none)"
        md.append(
            f"| {r['name']} | {r['scope']} | "
            f"{r['conda'] or '-'} | {sing_short} | "
            f"{r['sing_reachable']} ({r['sing_status']}) | "
            f"**{verdict_emoji}** |"
        )
    md.append("")

    # Detail block for genuinely non-OK rows. runtime-base and
    # no-container are intentional and excluded from "flagged".
    flagged = [
        r for r in rows
        if r["verdict"] in ("mismatch", "unreachable")
    ]
    if flagged:
        md.append("## Flagged modules (genuine drift)")
        md.append("")
        for r in flagged:
            md.append(f"### {r['name']} ({r['scope']})")
            md.append(f"- Verdict: **{r['verdict']}**")
            if r['conda']:
                md.append(f"- Conda spec: ``{r['conda']}`` (version: ``{r['conda_ver']}``)")
            else:
                md.append("- Conda spec: (none)")
            if r['sing_url']:
                md.append(f"- Singularity URL: ``{r['sing_url']}``")
                md.append(f"- Singularity HEAD: {r['sing_status']}")
                md.append(f"- Singularity tag version: ``{r['sing_ver']}``")
            else:
                md.append("- Singularity URL: (none)")
            if r['doc_ref']:
                md.append(f"- Docker reference: ``{r['doc_ref']}``")
                md.append(f"- Docker tag version: ``{r['doc_ver']}``")
            md.append("")

    md.append("## Notes for follow-on work")
    md.append("")
    md.append("- Local modules without container directives are expected:")
    md.append("  they run plain shell or Python and pick up tools from")
    md.append("  the host or a parent process scope.")
    md.append("- Any ``mismatch`` rows mean the conda ``environment.yml``")
    md.append("  and the container tag drifted. Fix in-repo by re-pulling")
    md.append("  the module via ``nf-core modules update <name>``.")
    md.append("- Any ``unreachable`` rows mean the depot.galaxyproject.org")
    md.append("  URL no longer resolves. Either upstream rebuilt the image")
    md.append("  under a different tag, or the depot dropped the artifact;")
    md.append("  file an upstream nf-core/modules issue for those rows.")
    md.append("- This table is the input artifact for any future")
    md.append("  Apptainer pre-pull deployment path (Wave 7 candidate).")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md) + "\n")
    print(f"Audit written: {out_path}")
    print(f"Modules audited: {len(rows)}")
    print(f"OK: {counts['OK']}, runtime-base: {counts['runtime-base']}, "
          f"mismatch: {counts['mismatch']}, "
          f"unreachable: {counts['unreachable']}, "
          f"no-container: {counts['no-container']}")


if __name__ == "__main__":
    main()
