"""The destination filename of an imported watchlist is not trusted input.

``import_watchlist`` joined its ``file_name`` argument straight onto the
destination directory. That argument carries the browser-supplied
``dcc.Upload`` filename, so a name containing ``..`` wrote outside the
watchlists directory entirely.

The operator uploads their own file, so this is not a remote-attacker path.
But the filename travels with the file: a watchlist YAML shared between labs,
or handed to an operator by someone else, chooses where it lands. A component
that writes outside its own directory because of a string in its input is
worth closing regardless of who supplied the string.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader

pytestmark = pytest.mark.unit


MINIMAL = {
    "metadata": {"name": "test", "version": "2.0"},
    "pathogens": [
        {"name": "Bacillus anthracis", "taxid_ncbi": 1392, "threat_level": "high"}
    ],
}


@pytest.fixture
def loader(tmp_path, monkeypatch):
    """A loader whose user watchlist dir is an isolated temp directory."""
    user_dir = tmp_path / "home" / "watchlists"
    user_dir.mkdir(parents=True)
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "home"))
    loader = WatchlistLoader()
    monkeypatch.setattr(
        type(loader), "user_watchlist_dir",
        property(lambda self: user_dir),
    )
    return loader


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "upload.yaml"
    path.write_text(yaml.safe_dump(MINIMAL))
    return path


class TestTheFilenameCannotEscapeTheWatchlistDirectory:
    @pytest.mark.parametrize("hostile", [
        "../escaped.yaml",
        "../../escaped.yaml",
        "subdir/../../escaped.yaml",
    ])
    def test_a_traversing_name_does_not_write_outside(
        self, loader, source, tmp_path, hostile
    ):
        loader.import_watchlist(source, destination="user", file_name=hostile)

        escaped = list(
            p for p in tmp_path.rglob("escaped.yaml")
            if p.parent != loader.user_watchlist_dir
        )
        assert not escaped, (
            f"'{hostile}' wrote outside the watchlists directory: {escaped}"
        )

    def test_a_traversing_name_is_reduced_to_its_basename(
        self, loader, source
    ):
        """Landing in the right place is what matters, not being refused.

        Reducing to the basename keeps a well-meaning upload working; the
        operator's file is still imported, just not where the string asked.
        """
        ok, message = loader.import_watchlist(
            source, destination="user", file_name="../escaped.yaml"
        )

        assert ok, f"the import was refused outright: {message}"
        assert (loader.user_watchlist_dir / "escaped.yaml").is_file()

    def test_an_absolute_name_does_not_write_outside(
        self, loader, source, tmp_path
    ):
        target = tmp_path / "absolute_escape.yaml"
        loader.import_watchlist(
            source, destination="user", file_name=str(target)
        )

        assert not target.exists(), (
            "an absolute destination filename wrote outside the watchlists "
            "directory"
        )

    def test_an_ordinary_name_is_unaffected(self, loader, source):
        ok, _ = loader.import_watchlist(
            source, destination="user", file_name="operator_list.yaml"
        )

        assert ok
        assert (loader.user_watchlist_dir / "operator_list.yaml").is_file()
