"""The default project directory must not be the current working directory.

``project_dir`` decided where run outputs, taxid mappings, the toggle state and
the operator watchlist directory live, and it defaulted to ``os.getcwd()``. So
launching from a clone wrote all of that INTO the checkout: 2.3 GB of results
and a ``.nanometa/`` tree appeared inside the repository. They are gitignored,
so nothing was committed -- but a ``git add -f``, a ``git clean -x`` or an edit
to ``.gitignore`` each turn that into data loss or a polluted commit, and the
project-local watchlist directory inside the repo is what made four copies of
the same watchlist accumulate.

The default is now ``~/nanometa-projects/<name>``, outside any checkout. An
explicit ``--project`` still wins, and the name is derived from what the
operator already told us: the analysis name, else the config file's stem.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils.paths import resolve_project_dir

HOME_DEFAULT = Path.home() / "nanometa-projects"


@pytest.fixture(autouse=True)
def _clear_sandbox_project_dir(monkeypatch):
    # The suite-wide home sandbox (tests/conftest.py) exports
    # NANOMETA_PROJECT_DIR, which outranks the data dir these tests set up
    # themselves. Clear it so the resolution under test is the one asserted.
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)


class TestExplicitWins:
    def test_explicit_project_is_used_verbatim(self, tmp_path):
        assert resolve_project_dir(str(tmp_path)) == str(tmp_path.resolve())

    def test_explicit_project_expands_user(self):
        got = resolve_project_dir("~/somewhere")
        assert got == str((Path.home() / "somewhere").resolve())


class TestDefaultIsOutsideTheCheckout:
    def test_default_is_not_the_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(None)
        assert got != str(tmp_path), (
            "the project still defaults to the working directory, so running "
            "from a clone writes results and .nanometa into the repository"
        )

    def test_default_lives_under_nanometa_projects(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert str(HOME_DEFAULT) in resolve_project_dir(None)

    def test_name_comes_from_the_analysis_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(None, config={"analysis_name": "Bioshield Run 3"})
        assert got == str(HOME_DEFAULT / "bioshield-run-3"), (
            "the analysis name is the operator's own label for the run and "
            "should name the folder"
        )

    def test_name_falls_back_to_the_config_stem(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(None, config_path="/tmp/exercises/mp02.yaml")
        assert got == str(HOME_DEFAULT / "mp02")

    def test_analysis_name_outranks_the_config_stem(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(
            None, config={"analysis_name": "Chosen"}, config_path="/tmp/other.yaml")
        assert got == str(HOME_DEFAULT / "chosen")

    def test_bare_launch_gets_a_stable_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_project_dir(None) == str(HOME_DEFAULT / "default")


class TestEnvOverride:
    def test_env_is_honoured_when_no_flag_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(tmp_path))
        assert resolve_project_dir(None) == str(tmp_path.resolve())

    def test_flag_outranks_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", "/tmp/from-env")
        assert resolve_project_dir(str(tmp_path)) == str(tmp_path.resolve())


class TestNameSanitising:
    @pytest.mark.parametrize("raw,expected", [
        ("Simple", "simple"),
        ("With Spaces", "with-spaces"),
        ("slash/and:colon", "slash-and-colon"),
        ("  padded  ", "padded"),
        ("", "default"),
        ("...", "default"),
    ])
    def test_names_become_safe_folder_names(self, raw, expected, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(None, config={"analysis_name": raw})
        assert Path(got).name == expected

    def test_a_name_cannot_escape_the_projects_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        got = resolve_project_dir(None, config={"analysis_name": "../../etc"})
        assert Path(got).parent == HOME_DEFAULT, (
            "a crafted analysis name escaped the projects directory"
        )
