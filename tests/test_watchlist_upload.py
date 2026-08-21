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


@pytest.fixture(autouse=True)
def _reset_manager_loader_cache():
    """watchlist_manager keeps its own module-level loader cache
    (``_get_watchlist_loader``). A test that runs a real manager method
    while ``get_watchlist_loader`` is patched (the parse-count test)
    freezes the patched, tmp-dir loader into that cache and every later
    test in the process silently reads the wrong watchlist directory."""
    from nanometa_live.core.watchlist import watchlist_manager as wm_mod
    wm_mod._watchlist_loader = None
    yield
    wm_mod._watchlist_loader = None


@pytest.fixture
def user_wl_dir(tmp_path, monkeypatch):
    """Point the whole watchlist stack at a throwaway directory."""
    d = tmp_path / "data_home" / "watchlists"
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "data_home"))
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)
    return d


@pytest.fixture
def upload_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_watchlist_callbacks(app)
    return app


@pytest.fixture
def upload_fn(upload_app):
    return get_callback_fn(
        upload_app, "watchlist-upload-feedback.children",
        input_contains="watchlist-upload")


@pytest.fixture
def worker_fn(upload_app):
    return get_callback_fn(
        upload_app, "watchlist-import-result.data",
        input_contains="watchlist-import-request")


@pytest.fixture
def finalize_fn(upload_app):
    return get_callback_fn(
        upload_app, "watchlist-tab-state.data",
        input_contains="watchlist-import-result")


@pytest.fixture
def import_chain(upload_fn, worker_fn, finalize_fn):
    """Drive the full upload -> worker -> finalize chain like the app does.

    Returns (state, final_feedback, upload_feedback, pending, result).
    When the upload stops early (invalid name, collision, builtin shadow)
    the worker and finalize never run and state/result are None.
    """
    from dash import no_update

    def run(contents, filename):
        feedback, pending, request = upload_fn(contents, filename)
        if request is no_update or not request:
            return None, None, feedback, pending, None
        result = worker_fn(lambda *_a: None, request)
        state, final_feedback = finalize_fn(result)
        return state, final_feedback, feedback, pending, result

    return run


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
        self, import_chain, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            state, alert, _fb, _p, _r = import_chain(
                _contents(VALID_YAML), "field.yaml")

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
        self, import_chain, fresh_loader, user_wl_dir
    ):
        from dash import no_update

        state, alert, _fb, _p, _r = import_chain(
            _contents(INVALID_YAML), "bad.yaml")
        assert state is no_update
        assert not (user_wl_dir / "bad.yaml").exists()
        assert "Invalid watchlist file" in _alert_text(alert)
        # The decoded pending file is cleaned up on failure too.
        assert not (user_wl_dir / ".pending" / "bad.yaml").exists()

    def test_entries_without_taxid_are_flagged(
        self, import_chain, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _s, alert, _fb, _p, _r = import_chain(
                _contents(NO_TAXID_YAML), "names.yaml")

        text = _alert_text(alert)
        assert "no taxonomy ID" in text
        assert "Bacillus mysteriosus" in text
        assert "Escherichia coli" not in text
        assert alert.color == "warning"

    def test_all_entries_with_taxid_gives_clean_success(
        self, import_chain, fresh_loader
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _s, alert, _fb, _p, _r = import_chain(
                _contents(VALID_YAML), "field.yaml")
        assert alert.color == "success"
        assert "no taxonomy ID" not in _alert_text(alert)

    def test_duplicate_upload_refused(
        self, import_chain, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            import_chain(_contents(VALID_YAML), "field.yaml")
            first = (user_wl_dir / "field.yaml").read_text()
            other = VALID_YAML.replace("Field List", "Different content")
            state, _fa, alert, pending, _r = import_chain(
                _contents(other), "field.yaml")

        assert state is None, "a collision must not reach the import worker"
        assert "already exists" in _alert_text(alert)
        assert (user_wl_dir / "field.yaml").read_text() == first, (
            "a second upload of the same name must not silently overwrite")

    def test_no_pending_file_leak_when_collision_check_raises(
        self, upload_fn, fresh_loader, user_wl_dir
    ):
        """An exception after the decoded upload lands in .pending/ must
        not strand the file there for the life of the session."""
        with patch.object(
            fresh_loader, "classify_upload_collision",
            side_effect=RuntimeError("boom"),
        ):
            alert, _p, _req = upload_fn(_contents(VALID_YAML), "field.yaml")
        assert "Upload failed" in _alert_text(alert)
        pending_dir = user_wl_dir / ".pending"
        assert not pending_dir.is_dir() or not list(pending_dir.iterdir())

    def test_no_contents_prevents_update(self, upload_fn):
        with pytest.raises(PreventUpdate):
            upload_fn(None, None)


class TestImportWorkerIsolation:
    """The background worker is file I/O only; session side effects belong
    to the finalize callback (DiskcacheManager runs the worker in another
    OS process, where singleton mutations are invisible to the app)."""

    def test_worker_never_touches_the_manager_and_reports_progress(
        self, upload_fn, worker_fn, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        progress_calls = []
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _fb, _p, request = upload_fn(_contents(VALID_YAML), "field.yaml")
            result = worker_fn(
                lambda payload: progress_calls.append(payload), request)

        assert result["success"] is True
        assert result["count"] == 2
        assert result["dest_name"] == "field.yaml"
        manager._load_custom_yaml_file.assert_not_called()
        assert len(progress_calls) >= 2, "the worker must report progress"

    def test_worker_result_for_missing_pending_file(
        self, worker_fn, fresh_loader, user_wl_dir
    ):
        result = worker_fn(
            lambda *_a: None,
            {"path": str(user_wl_dir / ".pending" / "gone.yaml"),
             "filename": "gone.yaml", "overwrite": False, "nonce": "x"},
        )
        assert result["success"] is False
        assert "no longer available" in result["message"]


class TestImportParseCount:
    def test_full_import_parses_the_yaml_at_most_twice(
        self, import_chain, fresh_loader, user_wl_dir, monkeypatch
    ):
        """One upload used to be parsed 5-6 times (validate, taxid audit,
        import re-validate, session validate + load, cache-refill load).
        The budget: once in the worker (validate_and_parse), once for the
        destination file in the finalize path."""
        from nanometa_live.core.watchlist import watchlist_loader as wl_mod

        counts = {"n": 0}
        real_safe_load = yaml.safe_load

        def counting(stream):
            counts["n"] += 1
            return real_safe_load(stream)

        monkeypatch.setattr(wl_mod.yaml, "safe_load", counting)
        from nanometa_live.core.watchlist import watchlist_manager as wm_mod
        monkeypatch.setattr(wm_mod.yaml, "safe_load", counting)

        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: None):
            manager = WatchlistManager()
            manager._entries.clear()
            manager._name_index.clear()
            with patch.object(wt, "get_watchlist_manager",
                              return_value=manager):
                state, _a, _fb, _p, _r = import_chain(
                    _contents(VALID_YAML), "field.yaml")

        assert state is not None
        assert counts["n"] <= 2, (
            f"import parsed the watchlist YAML {counts['n']} times"
        )


@pytest.fixture
def replace_fn(upload_app):
    return get_callback_fn(
        upload_app, "watchlist-upload-feedback.children",
        input_contains="watchlist-upload-replace-btn")


@pytest.fixture
def cancel_fn(upload_app):
    return get_callback_fn(
        upload_app, "watchlist-upload-feedback.children",
        input_contains="watchlist-upload-cancel-btn")


class TestReplaceFlow:
    """W2: a collision with the operator's own file offers a confirmed
    replacement; the confirm actually replaces; builtin stems stay refused."""

    def test_collision_returns_pending_payload_without_the_blob(
        self, import_chain, upload_fn, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            import_chain(_contents(VALID_YAML), "field.yaml")
            other = VALID_YAML.replace("Field List", "Corrected List")
            alert, pending, _req = upload_fn(_contents(other), "field.yaml")
        assert pending is not None
        assert pending["filename"] == "field.yaml"
        assert Path(pending["path"]).exists()
        assert "contents" not in pending, (
            "the decoded upload must wait on disk, not round-trip through "
            "the browser as a base64 blob"
        )
        assert "Replace existing" in _alert_text(alert)

    def test_confirmed_replace_overwrites_and_activates(
        self, import_chain, upload_fn, replace_fn, worker_fn, finalize_fn,
        fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            import_chain(_contents(VALID_YAML), "field.yaml")
            other = VALID_YAML.replace("Field List", "Corrected List")
            _a, pending, _req = upload_fn(_contents(other), "field.yaml")
            _alert2, cleared, request = replace_fn(1, pending)
            assert request["overwrite"] is True
            result = worker_fn(lambda *_a: None, request)
            state, alert = finalize_fn(result)

        saved = user_wl_dir / "field.yaml"
        assert yaml.safe_load(saved.read_text())["metadata"]["name"] == "Corrected List"
        assert state["last_update"] == "upload-field.yaml"
        assert "Replaced: field.yaml" in _alert_text(alert)
        assert cleared is None
        # Activation runs for the replacement too (snapshot rehydration
        # depends on the tab-state write; the manager reload on this call).
        assert manager._load_custom_yaml_file.call_count == 2
        # The consumed pending file is gone.
        assert not (user_wl_dir / ".pending" / "field.yaml").exists()

    def test_cancel_discards_the_pending_file(
        self, import_chain, upload_fn, cancel_fn, fresh_loader, user_wl_dir
    ):
        manager = MagicMock()
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            import_chain(_contents(VALID_YAML), "field.yaml")
            other = VALID_YAML.replace("Field List", "Corrected List")
            _a, pending, _req = upload_fn(_contents(other), "field.yaml")
            alert, cleared = cancel_fn(1, pending)
        assert cleared is None
        assert "cancelled" in _alert_text(alert)
        assert not Path(pending["path"]).exists()
        # The original file was kept.
        assert yaml.safe_load(
            (user_wl_dir / "field.yaml").read_text()
        )["metadata"]["name"] == "Field List"

    def test_builtin_stem_is_not_offered_replacement(
        self, upload_fn, user_wl_dir, tmp_path
    ):
        app_root = tmp_path / "app"
        builtin = app_root / "core" / "config" / "data" / "watchlists"
        builtin.mkdir(parents=True)
        (builtin / "biothreat.yaml").write_text(VALID_YAML)
        loader = WatchlistLoader(app_root=app_root, user_dir=user_wl_dir)
        with patch(
            "nanometa_live.core.watchlist.watchlist_loader.get_watchlist_loader",
            return_value=loader,
        ):
            alert, pending, _req = upload_fn(
                _contents(VALID_YAML), "biothreat.yaml"
            )
        assert pending is None
        assert "built-in watchlist" in _alert_text(alert)
        assert "Replace existing" not in _alert_text(alert)
        # The refused upload's pending file is not left behind.
        pending_dir = user_wl_dir / ".pending"
        assert not pending_dir.is_dir() or not list(pending_dir.iterdir())


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
