"""Tests for the watchlist create / upload / delete path.

``handle_upload``, ``handle_delete_watchlist``, ``import_watchlist``,
``create_user_watchlist_dir`` and ``_load_custom_yaml_file`` had no coverage,
so upload, persistence, session reload and delete were all untested. These
tests drive the registered callbacks directly (see CLAUDE.md, "Callback
tests") against a temporary watchlist directory.
"""

import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

pytestmark = pytest.mark.callback

from dash import Dash
from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn
from nanometa_live.app.tabs import watchlist_tab as wt
from nanometa_live.app.tabs.watchlist_tab import register_watchlist_callbacks
from nanometa_live.core.watchlist.watchlist_loader import (
    PSEUDO_TAXID_BASE,
    WatchlistLoader,
    build_watchlist_yaml,
)


VALID_YAML = """\
version: "2.0"
taxonomy_support: ["ncbi", "gtdb"]
metadata:
  name: "Field List"
  description: "Operator supplied"
pathogens:
  - name: "Listeria monocytogenes"
    taxid_ncbi: 1639
    threat_level: "critical"
    bsl_level: 2
    alert_threshold: 5
  - name: "Salmonella enterica"
    taxid_ncbi: 28901
    threat_level: "high"
    alert_threshold: 10
"""

NO_TAXID_YAML = """\
version: "2.0"
metadata:
  name: "Names only"
pathogens:
  - name: "Bacillus mysteriosus"
    threat_level: "high"
  - name: "Escherichia coli"
    taxid_ncbi: 562
"""

INVALID_YAML = """\
version: "2.0"
pathogens:
  - threat_level: "critical"
"""


def _contents(text: str) -> str:
    """Encode a file body the way dcc.Upload delivers it."""
    b64 = base64.b64encode(text.encode()).decode()
    return f"data:application/x-yaml;base64,{b64}"


def _alert_text(component) -> str:
    """Flatten a Dash component tree to its string content."""
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
            return
        if isinstance(node, (list, tuple)):
            for n in node:
                walk(n)
            return
        children = getattr(node, "children", None)
        if children is not None:
            walk(children)

    walk(component)
    return " ".join(out)


@pytest.fixture
def user_wl_dir(tmp_path, monkeypatch):
    """Point the whole watchlist stack at a throwaway directory."""
    d = tmp_path / "data_home" / "watchlists"
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data_home"))
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
    return d


@pytest.fixture
def upload_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_watchlist_callbacks(app)
    return get_callback_fn(
        app, "watchlist-upload-feedback.children",
        input_contains="watchlist-upload")


@pytest.fixture
def delete_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_watchlist_callbacks(app)
    return get_callback_fn(
        app, "watchlist-upload-feedback.children",
        input_contains="watchlist-file-delete")


@pytest.fixture
def download_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_watchlist_callbacks(app)
    return get_callback_fn(app, "watchlist-download.data")


@pytest.fixture
def fresh_loader(user_wl_dir):
    """A loader wired to the temporary user directory, installed as the
    singleton the callbacks fetch."""
    loader = WatchlistLoader(user_dir=user_wl_dir)
    with patch(
        "nanometa_live.core.watchlist.watchlist_loader.get_watchlist_loader",
        return_value=loader,
    ):
        yield loader


class TestUploadCallback:
    def test_valid_upload_persists_and_loads(
        self, upload_fn, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            state, alert = upload_fn(_contents(VALID_YAML), "field.yaml")

        saved = user_wl_dir / "field.yaml"
        assert saved.exists(), "upload must persist to the user watchlist dir"
        assert yaml.safe_load(saved.read_text())["metadata"]["name"] == "Field List"
        assert state["last_update"] == "upload-field.yaml"
        # The session manager is told to load the persisted file, or the
        # organisms would not appear until the next restart.
        manager._load_custom_yaml_file.assert_called_once_with(str(saved))
        text = _alert_text(alert)
        assert "Imported: field.yaml" in text
        assert "2 pathogens" in text

    def test_invalid_upload_is_rejected_and_not_persisted(
        self, upload_fn, fresh_loader, user_wl_dir
    ):
        from dash import no_update

        state, alert = upload_fn(_contents(INVALID_YAML), "bad.yaml")
        assert state is no_update
        assert not (user_wl_dir / "bad.yaml").exists()
        assert "Invalid watchlist file" in _alert_text(alert)

    def test_entries_without_taxid_are_flagged(
        self, upload_fn, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _, alert = upload_fn(_contents(NO_TAXID_YAML), "names.yaml")

        text = _alert_text(alert)
        assert "no taxonomy ID" in text
        assert "Bacillus mysteriosus" in text
        assert "Escherichia coli" not in text
        assert alert.color == "warning"

    def test_all_entries_with_taxid_gives_clean_success(
        self, upload_fn, fresh_loader
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _, alert = upload_fn(_contents(VALID_YAML), "field.yaml")
        assert alert.color == "success"
        assert "no taxonomy ID" not in _alert_text(alert)

    def test_duplicate_upload_refused(self, upload_fn, fresh_loader, user_wl_dir):
        from dash import no_update

        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            upload_fn(_contents(VALID_YAML), "field.yaml")
            first = (user_wl_dir / "field.yaml").read_text()
            other = VALID_YAML.replace("Field List", "Different content")
            state, alert = upload_fn(_contents(other), "field.yaml")

        assert state is no_update
        assert "already exists" in _alert_text(alert)
        assert (user_wl_dir / "field.yaml").read_text() == first, (
            "a second upload of the same name must not silently overwrite")

    def test_no_temp_file_leak_when_validation_raises(
        self, upload_fn, fresh_loader
    ):
        """validate_file raising used to be swallowed by the blanket except,
        leaving the NamedTemporaryFile(delete=False) behind in /tmp."""
        before = set(Path(tempfile.gettempdir()).glob("*.yaml"))
        with patch.object(
            fresh_loader, "validate_file", side_effect=RuntimeError("boom")
        ):
            _, alert = upload_fn(_contents(VALID_YAML), "field.yaml")
        after = set(Path(tempfile.gettempdir()).glob("*.yaml"))
        assert after == before
        assert "Upload failed" in _alert_text(alert)

    def test_no_contents_prevents_update(self, upload_fn):
        with pytest.raises(PreventUpdate):
            upload_fn(None, None)


class TestImportWatchlistCollisions:
    def test_overwrite_flag_allows_replacement(self, tmp_path, user_wl_dir):
        loader = WatchlistLoader(user_dir=user_wl_dir)
        src = tmp_path / "custom.yaml"
        src.write_text(VALID_YAML)

        ok, msg = loader.import_watchlist(src)
        assert ok, msg
        ok, msg = loader.import_watchlist(src)
        assert not ok and "already exists" in msg
        ok, msg = loader.import_watchlist(src, overwrite=True)
        assert ok, msg

    def test_builtin_stem_collision_refused(self, tmp_path, user_wl_dir):
        app_root = tmp_path / "app"
        builtin = app_root / "core" / "config" / "data" / "watchlists"
        builtin.mkdir(parents=True)
        (builtin / "biothreat.yaml").write_text(VALID_YAML)

        loader = WatchlistLoader(app_root=app_root, user_dir=user_wl_dir)
        src = tmp_path / "biothreat.yaml"
        src.write_text(VALID_YAML)

        ok, msg = loader.import_watchlist(src)
        assert not ok
        assert "built-in watchlist" in msg
        assert not (user_wl_dir / "biothreat.yaml").exists()

    def test_file_name_override_used_for_destination(self, tmp_path, user_wl_dir):
        loader = WatchlistLoader(user_dir=user_wl_dir)
        src = tmp_path / "tmp1234.yaml"
        src.write_text(VALID_YAML)
        ok, _ = loader.import_watchlist(src, file_name="operator-name.yaml")
        assert ok
        assert (user_wl_dir / "operator-name.yaml").exists()
        assert not (user_wl_dir / "tmp1234.yaml").exists()


class TestUserWatchlistDirResolution:
    """The loader, the upload callback and the bundle exporter must all agree
    on one directory; hard-coded ``~/.nanometa/watchlists`` in three places
    meant a --data-dir run put uploads where the exporter never looked."""

    def test_follows_data_dir_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "dd"))
        monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
        loader = WatchlistLoader()
        assert loader.user_watchlist_dir == tmp_path / "dd" / "watchlists"

    def test_follows_project_dir_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "dd"))
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(tmp_path / "proj"))
        loader = WatchlistLoader()
        assert loader.user_watchlist_dir == (
            tmp_path / "proj" / ".nanometa" / "watchlists")

    def test_create_user_watchlist_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "dd"))
        monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
        loader = WatchlistLoader()
        created = loader.create_user_watchlist_dir()
        assert created.is_dir()
        assert created == tmp_path / "dd" / "watchlists"

    def test_uploaded_file_is_discovered_as_user_source(
        self, tmp_path, user_wl_dir
    ):
        loader = WatchlistLoader(app_root=tmp_path / "no_builtins",
                                 user_dir=user_wl_dir)
        src = tmp_path / "field.yaml"
        src.write_text(VALID_YAML)
        assert loader.import_watchlist(src)[0]

        found = loader.discover_watchlists()
        assert [w.id for w in found] == ["field"]
        assert found[0].source == "user"


class TestFindEntriesWithoutTaxid:
    def test_reports_only_untyped_entries(self, tmp_path):
        p = tmp_path / "w.yaml"
        p.write_text(NO_TAXID_YAML)
        assert WatchlistLoader.find_entries_without_taxid(p) == [
            "Bacillus mysteriosus"]

    def test_db_taxid_counts_as_matchable(self, tmp_path):
        p = tmp_path / "w.yaml"
        p.write_text(
            'pathogens:\n  - name: "GTDB only"\n    db_taxid: 4242\n')
        assert WatchlistLoader.find_entries_without_taxid(p) == []

    def test_unreadable_file_returns_empty(self, tmp_path):
        assert WatchlistLoader.find_entries_without_taxid(
            tmp_path / "missing.yaml") == []


class TestDeleteCallback:
    def test_delete_removes_file_and_disables_entry(
        self, delete_fn, fresh_loader, user_wl_dir, tmp_path
    ):
        src = tmp_path / "field.yaml"
        src.write_text(VALID_YAML)
        assert fresh_loader.import_watchlist(src)[0]
        target = user_wl_dir / "field.yaml"
        assert target.exists()
        fresh_loader.discover_watchlists()

        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager), \
                patch.object(wt, "ctx", MagicMock(
                    triggered_id={"type": "watchlist-file-delete",
                                  "index": "field"})):
            state, alert = delete_fn([1])

        assert not target.exists()
        manager.disable_watchlist.assert_called_once_with("field")
        assert state["last_update"] == "delete-field"
        assert "Removed" in _alert_text(alert)

    def test_builtin_watchlist_cannot_be_deleted(
        self, delete_fn, fresh_loader, tmp_path
    ):
        from dash import no_update

        with patch.object(fresh_loader, "discover_watchlists", return_value=[]), \
                patch.object(wt, "ctx", MagicMock(
                    triggered_id={"type": "watchlist-file-delete",
                                  "index": "biothreat"})):
            state, alert = delete_fn([1])

        assert state is no_update
        assert "Only custom watchlists can be deleted" in _alert_text(alert)

    def test_no_click_prevents_update(self, delete_fn):
        with pytest.raises(PreventUpdate):
            delete_fn([None, None])


class TestDownloadYaml:
    def test_download_produces_reimportable_yaml(
        self, download_fn, tmp_path, user_wl_dir
    ):
        entries = {
            1639: MagicMock(**{"to_dict.return_value": {
                "taxid": 1639, "name": "Listeria monocytogenes",
                "threat_level": "critical", "bsl_level": 2,
                "alert_threshold": 5, "category": "Foodborne",
            }}),
        }
        manager = MagicMock()
        manager.get_active_entries.return_value = entries
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            payload = download_fn(1)

        assert payload["filename"].startswith("watchlist-")
        assert payload["filename"].endswith(".yaml")
        doc = yaml.safe_load(payload["content"])
        assert doc["version"] == "2.0"
        assert doc["pathogens"][0]["taxid_ncbi"] == 1639

        # The exported file must survive a round trip through the importer.
        out = tmp_path / "roundtrip.yaml"
        out.write_text(payload["content"])
        loader = WatchlistLoader(user_dir=user_wl_dir)
        assert loader.validate_file(out) == (True, [])

    def test_no_click_prevents_update(self, download_fn):
        with pytest.raises(PreventUpdate):
            download_fn(None)


class TestBuildWatchlistYaml:
    def test_synthetic_taxid_not_written_as_ncbi(self):
        doc = build_watchlist_yaml([{
            "taxid": PSEUDO_TAXID_BASE + 17,
            "name": "Name only organism",
            "threat_level": "high",
            "alert_threshold": 10,
        }])
        entry = doc["pathogens"][0]
        assert "taxid_ncbi" not in entry, (
            "an internal synthetic key must not be presented as an NCBI taxid")
        assert entry["name"] == "Name only organism"

    def test_session_only_fields_are_dropped(self):
        doc = build_watchlist_yaml([{
            "taxid": 562, "name": "Escherichia coli",
            "source": "user", "validated": True,
            "ncbi_link": "https://example.invalid",
            "watchlist_ids": ["something"],
        }])
        entry = doc["pathogens"][0]
        for stale in ("source", "validated", "ncbi_link", "watchlist_ids"):
            assert stale not in entry

    def test_optional_fields_preserved(self):
        doc = build_watchlist_yaml([{
            "taxid": 562, "name": "Escherichia coli",
            "names_alt": ["E. coli"], "db_taxid": 99,
            "common_name": "E. coli", "organism_type": "bacteria",
            "annotation": "STEC", "notes": "n", "action_required": "act",
        }])
        entry = doc["pathogens"][0]
        assert entry["names_alt"] == ["E. coli"]
        assert entry["db_taxid"] == 99
        assert entry["organism_type"] == "bacteria"
        assert entry["annotation"] == "STEC"


class TestUploadReachesBundleExport:
    """The point of routing everything through NanometaPaths: a watchlist the
    operator uploads in the GUI must end up in the offline bundle. When the
    loader, the upload callback and the exporter each hard-coded
    ~/.nanometa/watchlists, a run started with --data-dir or --project-dir
    wrote uploads somewhere export_bundle never looked, and the bundle shipped
    without them -- silently, because an empty watchlist dir is a legal bundle.
    """

    @staticmethod
    def _bundle_names(bundle_path):
        import tarfile
        with tarfile.open(str(bundle_path)) as tar:
            return set(tar.getnames())

    @pytest.fixture(autouse=True)
    def _fake_nextflow_home(self, tmp_path, monkeypatch):
        # Keep the exporter's plugin-cache probe off the real ~/.nextflow.
        fake = tmp_path / "fakehome"
        (fake / ".nextflow" / "plugins").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake))

    def test_upload_under_data_dir_is_bundled(self, tmp_path, monkeypatch):
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        data_dir = tmp_path / "dd"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(data_dir))
        monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)

        # Upload exactly as the GUI does: through the loader's resolved dir.
        loader = WatchlistLoader()
        src = tmp_path / "field.yaml"
        src.write_text(VALID_YAML)
        assert loader.import_watchlist(src)[0]
        assert (data_dir / "watchlists" / "field.yaml").exists()

        out = tmp_path / "bundle.tar.gz"
        BundleManager().export_bundle(
            str(out), {"data_dir": str(data_dir), "kraken_db": ""})

        assert "watchlists/field.yaml" in self._bundle_names(out)

    def test_upload_under_project_dir_is_bundled(self, tmp_path, monkeypatch):
        """The case that was broken: the upload lands in
        <project_dir>/.nanometa/watchlists, which is not under the data home
        the exporter walks."""
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        data_dir = tmp_path / "dd"
        project = tmp_path / "proj"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(data_dir))
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(project))

        loader = WatchlistLoader()
        src = tmp_path / "field.yaml"
        src.write_text(VALID_YAML)
        assert loader.import_watchlist(src)[0]
        uploaded = project / ".nanometa" / "watchlists" / "field.yaml"
        assert uploaded.exists(), "upload must follow the project scope"
        assert not (data_dir / "watchlists" / "field.yaml").exists()

        out = tmp_path / "bundle.tar.gz"
        BundleManager().export_bundle(
            str(out),
            {"data_dir": str(data_dir), "project_dir": str(project),
             "kraken_db": ""},
        )

        assert "watchlists/field.yaml" in self._bundle_names(out)

    def test_project_copy_wins_over_data_dir_copy_in_bundle(
        self, tmp_path, monkeypatch
    ):
        """Same file stem in both scopes: the project-scoped copy is the one
        the running app reads, so it is the one that must be bundled."""
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        data_dir = tmp_path / "dd"
        project = tmp_path / "proj"
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(data_dir))
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(project))

        (data_dir / "watchlists").mkdir(parents=True)
        (data_dir / "watchlists" / "field.yaml").write_text(
            VALID_YAML.replace("Field List", "Stale data-dir copy"))
        (project / ".nanometa" / "watchlists").mkdir(parents=True)
        (project / ".nanometa" / "watchlists" / "field.yaml").write_text(
            VALID_YAML.replace("Field List", "Live project copy"))

        out = tmp_path / "bundle.tar.gz"
        BundleManager().export_bundle(
            str(out),
            {"data_dir": str(data_dir), "project_dir": str(project),
             "kraken_db": ""},
        )

        import tarfile
        with tarfile.open(str(out)) as tar:
            body = tar.extractfile("watchlists/field.yaml").read().decode()
        assert "Live project copy" in body
        assert "Stale data-dir copy" not in body


class TestDiscoveryPrecedenceHolds:
    """project > user > built-in, with the user tier now NanometaPaths-scoped.
    The three tiers must stay distinct directories or one silently shadows
    another."""

    def test_three_tiers_are_distinct_directories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "dd"))
        monkeypatch.setenv("NANOMETA_PROJECT_DIR", str(tmp_path / "proj"))
        loader = WatchlistLoader(project_dir=tmp_path / "proj")
        project_dir = tmp_path / "proj" / "watchlists"
        user_dir = loader.user_watchlist_dir
        assert user_dir == tmp_path / "proj" / ".nanometa" / "watchlists"
        assert project_dir != user_dir

    def test_full_precedence_project_over_user_over_builtin(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "dd"))
        monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)

        app_root = tmp_path / "app"
        builtin = app_root / "core" / "config" / "data" / "watchlists"
        builtin.mkdir(parents=True)
        (builtin / "shared.yaml").write_text(
            VALID_YAML.replace("Field List", "BUILTIN"))

        user_dir = tmp_path / "dd" / "watchlists"
        user_dir.mkdir(parents=True)
        (user_dir / "shared.yaml").write_text(
            VALID_YAML.replace("Field List", "USER"))

        project = tmp_path / "proj"
        (project / "watchlists").mkdir(parents=True)
        (project / "watchlists" / "shared.yaml").write_text(
            VALID_YAML.replace("Field List", "PROJECT"))

        # All three tiers present -> project wins.
        loader = WatchlistLoader(project_dir=project, app_root=app_root)
        found = {w.id: w for w in loader.discover_watchlists()}
        assert found["shared"].source == "project"
        assert found["shared"].name == "PROJECT"

        # Drop the project copy -> user wins over built-in.
        (project / "watchlists" / "shared.yaml").unlink()
        loader = WatchlistLoader(project_dir=project, app_root=app_root)
        found = {w.id: w for w in loader.discover_watchlists()}
        assert found["shared"].source == "user"
        assert found["shared"].name == "USER"

        # Drop the user copy -> built-in is the fallback.
        (user_dir / "shared.yaml").unlink()
        loader = WatchlistLoader(project_dir=project, app_root=app_root)
        found = {w.id: w for w in loader.discover_watchlists()}
        assert found["shared"].source == "builtin"
        assert found["shared"].name == "BUILTIN"
