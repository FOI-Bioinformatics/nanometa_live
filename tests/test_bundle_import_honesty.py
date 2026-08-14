"""An import must not report success over a problem it detected.

Two ways it did:

- A ``--db`` path that does not exist was accepted in silence. The
  ``kraken_db_unset`` guard fires only when the path is EMPTY, so an operator
  who supplied a wrong path -- a typo, a drive that did not mount, a directory
  that moved -- got the same clean result as one who supplied a correct one.
  The unset case is warned about precisely because the run will fail later;
  a wrong path fails the same way and said nothing.

- When writing the rebased config raised, the exception became a warning and
  ``success`` stayed True. The config on disk then still carries the export
  placeholders (``${KRAKEN_DB}``, ``./pipeline_source``), so the installation
  is unusable -- reported as a successful import. Three lines above, the
  missing-main.nf branch already sets ``success = False`` for the same class
  of problem; this branch just did not.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.workflow.bundle_manager import BundleManager

from tests.test_bundle_manager import _make_minimal_bundle

pytestmark = pytest.mark.unit


#: A bundle-shaped config, carrying the export-time placeholders that the
#: import is supposed to rebase.
_EXPORTED_CONFIG = (
    "kraken_db: ${KRAKEN_DB}\n"
    "pipeline_source: ./pipeline_source\n"
    "offline_mode: false\n"
)


@pytest.fixture
def bundle(tmp_path):
    """A bundle that carries a config.yaml.

    Import skips its whole config-rebase block when config.yaml is absent, so
    the default minimal bundle never reaches the code under test here.
    """
    bundle_path, _ = _make_minimal_bundle(
        tmp_path, extra_files={"config.yaml": _EXPORTED_CONFIG}
    )
    home = tmp_path / "import_home"
    home.mkdir()
    return str(bundle_path), str(home)


class TestABadDatabasePathIsReported:
    def test_a_nonexistent_db_path_is_not_accepted_in_silence(self, bundle, tmp_path):
        bundle_path, home = bundle

        result = BundleManager().import_bundle(
            bundle_path,
            kraken_db_path=str(tmp_path / "no_such_database"),
            nanometa_home=home,
        )

        assert result.get("kraken_db_invalid"), (
            "an import given a Kraken2 database path that does not exist "
            "reported no problem; the run will fail later with nothing having "
            "warned about it"
        )
        assert any(
            "no_such_database" in w for w in result.get("warnings", [])
        ), "the warning must name the path that was wrong"

    def test_a_path_that_is_not_a_kraken_database_is_reported(
        self, bundle, tmp_path
    ):
        """Exists, but has none of the required .k2d files."""
        bundle_path, home = bundle
        empty_dir = tmp_path / "not_a_db"
        empty_dir.mkdir()

        result = BundleManager().import_bundle(
            bundle_path, kraken_db_path=str(empty_dir), nanometa_home=home,
        )

        assert result.get("kraken_db_invalid")
        joined = " ".join(result.get("warnings", []))
        assert "hash.k2d" in joined or "missing" in joined.lower(), (
            "the warning should name what is missing, so the operator can "
            "tell a wrong path from an incomplete copy"
        )

    def test_a_valid_database_path_raises_nothing(self, bundle, tmp_path):
        bundle_path, home = bundle
        db = tmp_path / "real_db"
        db.mkdir()
        for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (db / name).write_bytes(b"x")

        result = BundleManager().import_bundle(
            bundle_path, kraken_db_path=str(db), nanometa_home=home,
        )

        assert not result.get("kraken_db_invalid")
        assert not result.get("kraken_db_unset")

    def test_an_omitted_path_still_reports_unset_not_invalid(self, bundle):
        """The two are different situations and keep different flags.

        Importing first and pointing the database later is a supported flow;
        it must not start reporting an invalid path.
        """
        bundle_path, home = bundle

        result = BundleManager().import_bundle(
            bundle_path, kraken_db_path="", nanometa_home=home,
        )

        assert result.get("kraken_db_unset")
        assert not result.get("kraken_db_invalid")


class TestAnUnwritableConfigFailsTheImport:
    def test_success_is_false_when_the_config_cannot_be_written(
        self, bundle, monkeypatch
    ):
        """Without this the operator gets an unusable install marked OK.

        The config still holds the export-time placeholders, so every path in
        it points nowhere -- and the import said it worked.
        """
        bundle_path, home = bundle

        from nanometa_live.core.config.config_loader import ConfigLoader

        def boom(self, *a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(ConfigLoader, "save_config", boom)

        result = BundleManager().import_bundle(
            bundle_path, kraken_db_path="", nanometa_home=home,
        )

        assert result["success"] is False, (
            "the rebased config could not be written, so the installation "
            "carries unresolved ${KRAKEN_DB} / ./pipeline_source placeholders "
            "-- yet the import reported success"
        )
        assert result.get("config_write_failed")
        assert any(
            "disk full" in w for w in result.get("warnings", [])
        ), "the underlying error must survive into the warnings"
