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


class TestExportWarnsAboutItsOwnDatabase:
    """Symmetric with the import-side check above.

    Export records a db_hash so import can verify compatibility, but never
    checked that kraken_db pointed at a real database. A bundle built from a
    config whose database path was wrong -- moved, unmounted, mistyped --
    exported cleanly and carried a hash derived from nothing, which import
    then compared against. The operator learns at first run, air-gapped.
    """

    @staticmethod
    def _export_warnings(bundle_path):
        """export_warnings recorded in the produced bundle's manifest.

        export_bundle returns a Path, not a result dict; the warnings ride in
        manifest.json, which is also where import and verify_bundle read them.
        """
        import json
        import tarfile

        with tarfile.open(str(bundle_path)) as tar:
            member = tar.extractfile("manifest.json")
            manifest = json.load(member)
        return manifest.get("export_warnings", [])

    def test_a_bad_kraken_db_is_warned_about_at_export(self, tmp_path):
        home = tmp_path / "home"
        (home / "genomes").mkdir(parents=True)
        out = tmp_path / "bundle.tar.gz"

        BundleManager().export_bundle(
            str(out),
            config={"kraken_db": str(tmp_path / "gone")},
            nanometa_home=str(home),
        )

        warnings = self._export_warnings(out)
        assert any("gone" in w for w in warnings), (
            "a bundle was exported against a Kraken2 database path that does "
            f"not exist, with no warning ({warnings}); the operator finds out "
            "on the air-gapped machine"
        )

    def test_a_valid_database_produces_no_such_warning(self, tmp_path):
        home = tmp_path / "home"
        (home / "genomes").mkdir(parents=True)
        db = tmp_path / "real_db"
        db.mkdir()
        for name in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (db / name).write_bytes(b"x")
        out = tmp_path / "bundle_ok.tar.gz"

        BundleManager().export_bundle(
            str(out), config={"kraken_db": str(db)}, nanometa_home=str(home),
        )

        assert not any(
            "not a usable" in w for w in self._export_warnings(out)
        )


class TestBlockerWordingIsAccurate:
    """A dry run aborts nothing, and a forced import completes.

    The architecture and conda blockers opened with "Import aborted:". That
    text reaches two callers where it is simply false: verify_bundle, which is
    a read-only dry run, and a forced import, which carries on and succeeds.
    Observed in the air-gapped rig -- verify_bundle refused an amd64 bundle on
    an arm64 host with "Import aborted", and the forced import then reported
    success while carrying the same sentence in its warnings.

    Whether a blocker stops the import is the caller's decision (force), so
    the message states the condition and leaves the consequence alone.
    """

    def test_no_blocker_claims_the_import_was_aborted(self):
        import pathlib

        source = pathlib.Path(
            __import__(
                "nanometa_live.core.workflow.bundle_manager",
                fromlist=["bundle_manager"],
            ).__file__
        ).read_text()

        assert "Import aborted" not in source, (
            "a blocker message still says 'Import aborted'; it is emitted by "
            "verify_bundle (a dry run) and by forced imports that complete, "
            "so in both cases it describes something that did not happen"
        )
