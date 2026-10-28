"""nanometa_live_env.yml must carry every runtime requirement.

Field audit 2026-10-28, H6: the conda environment file omitted six packages
requirements.txt lists (dash-ag-grid, diskcache, psutil, multiprocess, dill,
openpyxl). An environment built from the file alone failed at import, and
`pip install .` then reached PyPI -- on a field machine, with no network.
The file is the documented offline install route, so the two lists stay in
step here. Floors must agree too, so the conda solve and the pip solve
cannot pick versions the other refuses.
"""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _requirements():
    reqs = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(>=|==)\s*([0-9][^\s,;]*)", line)
        assert m, f"unparsed requirement line: {line!r}"
        reqs[m.group(1).lower()] = m.group(3)
    return reqs


def _env_deps():
    doc = yaml.safe_load((ROOT / "nanometa_live_env.yml").read_text())
    deps = {}
    for item in doc["dependencies"]:
        if not isinstance(item, str):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(?:(>=|==)\s*([0-9][^\s,;]*))?", item)
        assert m, f"unparsed env dependency: {item!r}"
        deps[m.group(1).lower()] = m.group(3)
    return deps


def test_every_requirement_is_in_the_conda_env():
    reqs = _requirements()
    env = _env_deps()
    missing = [n for n in reqs if n not in env]
    assert not missing, (
        "requirements.txt packages absent from nanometa_live_env.yml: "
        f"{missing} -- an environment built from the yml cannot import the app"
    )


def test_floors_agree():
    reqs = _requirements()
    env = _env_deps()
    drift = {n: (reqs[n], env.get(n)) for n in reqs if env.get(n) not in (None, reqs[n])}
    assert not drift, f"version floors differ between requirements.txt and the env yml: {drift}"


def test_nextflow_floor_is_the_pipeline_floor():
    from nanometa_live.core.workflow.bundle_manager import _NEXTFLOW_MIN_VERSION
    env = _env_deps()
    assert env.get("nextflow") == _NEXTFLOW_MIN_VERSION, (
        "the env yml must pin Nextflow at nanometanf's floor so a field "
        "install cannot ship a launcher the pipeline refuses"
    )
