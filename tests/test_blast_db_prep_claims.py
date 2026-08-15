"""Preparing BLAST databases must not report success over nothing.

Two defects, both the campaign's recurring shape -- a reassuring conclusion
that was not earned. Found 2026-07-29.

1. `build_missing_blast_dbs` computed `missing_blast` as the genomes that
   lack a database. With no genomes downloaded at all that list is empty, so
   the vacuous "every genome has a database" rendered as

       All BLAST databases already built    [Complete]

   in green -- identical to a fully prepared system. An operator preparing a
   deployment in the documented order (download genomes, then build BLAST
   databases) who clicked Build first would be told the step was done.

2. `download_missing_genomes` builds BLAST databases for what it downloaded,
   then decided its badge on `failed`, which counted download failures only.
   Every download succeeding while every BLAST build failed reported
   "Complete" in green.

Both matter for the same reason: a genome with no BLAST database cannot be
validated against, and confirmatory validation is what turns a Kraken2 hit
into a reportable detection. The failure would surface as a validation that
could not run, on a field machine, after the green badge.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dash
import pytest

pytestmark = pytest.mark.unit


def _fn(output_id, input_contains):
    from nanometa_live.app.tabs import preparation_tab
    from tests.dash_test_utils import get_callback_fn

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    preparation_tab.register_preparation_callbacks(app)
    return get_callback_fn(app, output_id, input_contains=input_contains)


def _badge(progress_tuple):
    badge = progress_tuple[4]
    return str(getattr(badge, "children", badge))


def _log(progress_tuple):
    return " ".join(str(e) for e in progress_tuple[3])


def _genome(taxid):
    m = MagicMock()
    m.taxid = taxid
    m.name = f"organism {taxid}"
    return m


class TestBuildingOverNoGenomes:
    """Defect 1: vacuous completeness."""

    def _run(self, genomes, has_db):
        fn = _fn("blast-build-complete", "genome-build-blast-btn")
        mgr = MagicMock()
        mgr.get_all_genomes.return_value = genomes
        mgr.has_blast_db.side_effect = has_db
        seen = []
        # The callback refuses to start without makeblastdb on PATH. That is
        # correct behaviour and has its own test below, but leaving it to the
        # environment made these three assertions pass on a developer machine
        # with BLAST+ installed and fail on CI, which has none -- they never
        # reached the branch they were written for. Pin the tool as present.
        with patch(
            "shutil.which",
            return_value="/usr/bin/makeblastdb",
        ), patch(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            return_value=mgr,
        ):
            fn(lambda v: seen.append(v), 1, {})
        return seen[-1]

    def test_a_missing_makeblastdb_is_reported_as_an_error(self):
        """The environment dependence the other tests patch away.

        Asserted here rather than left implicit, so patching `shutil.which`
        above cannot quietly disable a real guard.
        """
        fn = _fn("blast-build-complete", "genome-build-blast-btn")
        seen = []
        with patch(
            "shutil.which",
            return_value=None,
        ):
            fn(lambda v: seen.append(v), 1, {})
        assert _badge(seen[-1]) == "Error"
        assert "BLAST+" in _log(seen[-1])

    def test_no_genomes_is_not_complete(self):
        last = self._run([], lambda t: True)
        assert "Complete" not in _badge(last), (
            "with no reference genomes present the system cannot validate "
            "anything; reporting the BLAST step complete tells the operator "
            "the opposite"
        )
        assert _badge(last) == "No genomes"

    def test_no_genomes_says_what_to_do(self):
        assert "download genomes first" in _log(self._run([], lambda t: True)).lower()

    def test_genomes_all_having_databases_is_genuinely_complete(self):
        """Control: the real all-clear must survive."""
        last = self._run([_genome(263), _genome(1392)], lambda t: True)
        assert "Complete" in _badge(last)
        assert "All 2 genome(s)" in _log(last)


class TestDownloadDoesNotHideBlastFailures:
    """Defect 2: the Complete badge counted downloads only."""

    def _run(self, built):
        """One genome missing; it downloads fine; `built` databases result."""
        fn = _fn("genome-download-complete", "genome-download-all-btn")
        mgr = MagicMock()
        mgr.download_genome.return_value = (True, "/tmp/263.fasta")
        mgr.build_blast_dbs_batch.return_value = built
        seen = []
        with patch(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            return_value=mgr,
        ):
            fn(lambda v: seen.append(v), 1, {},
               [{"taxid": 263, "name": "Francisella tularensis"}])
        return seen[-1]

    def test_a_failed_blast_build_is_not_complete(self):
        last = self._run(built=0)
        assert "Complete" not in _badge(last), (
            "the download succeeded but produced no BLAST database, so the "
            "genome still cannot be validated against"
        )
        assert "BLAST failed" in _badge(last)

    def test_a_successful_build_is_complete(self):
        """Control."""
        assert "Complete" in _badge(self._run(built=1))
