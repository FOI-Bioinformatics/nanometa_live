"""Version detection must not turn garbage into a passing version.

`nanometa-prepare doctor` exists to tell a field operator whether the laptop
in front of them can run an analysis. The most likely reason it cannot is a
missing Java Runtime -- Nextflow is a JVM application, and installing it from
a tarball or a bare conda package does not necessarily bring a JRE.

In that state `nextflow -version` prints an ANSI-coloured error rather than a
banner. The version parser's unanchored ``(\\d+)`` regex matched the **colour
code** in ``\\x1b[31m``, yielding "version 31.0.0", which cleared the 26.4.0
floor. doctor printed `PASS Nextflow` and `Install looks sane`, exit 0, on a
machine that could not run a single task.

These tests pin the two halves of that fix: the parser must reject anything
that is not a version, and version detection must not pass prose off as one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    _NEXTFLOW_MIN_VERSION,
    _get_nextflow_version,
    _parse_semver,
)

pytestmark = pytest.mark.unit

#: What `nextflow -version` actually prints with no JRE installed.
JAVA_MISSING_OUTPUT = (
    "\x1b[31mThe operation couldn’t be completed. "
    "Unable to locate a Java Runtime.\x1b[0m\n"
    "Please visit http://www.java.com for information on installing Java.\n"
)


class TestParserRejectsNonVersions:
    def test_ansi_colour_code_is_not_a_version(self):
        """The exact regression: \\x1b[31m must not parse as 31.0.0."""
        assert _parse_semver(JAVA_MISSING_OUTPUT) is None

    @pytest.mark.parametrize("garbage", [
        "The operation couldn't be completed. Unable to locate a Java Runtime.",
        "command not found",
        "Error: exit status 127",
        "Please visit http://www.java.com for information",
        "not found",
        "unknown",
        "error",
        "",
    ])
    def test_prose_is_not_a_version(self, garbage):
        assert _parse_semver(garbage) is None

    def test_java_error_does_not_clear_the_floor(self):
        """The consequence, asserted end to end.

        Even if some future parser change made the error parse to *something*,
        it must never compare as satisfying the minimum supported Nextflow.
        """
        parsed = _parse_semver(JAVA_MISSING_OUTPUT)
        floor = _parse_semver(_NEXTFLOW_MIN_VERSION)
        assert floor is not None
        assert not (parsed and parsed >= floor)


class TestParserAcceptsRealVersions:
    @pytest.mark.parametrize("text,expected", [
        ("26.04.0", (26, 4, 0)),
        ("26.04.0 build 12031", (26, 4, 0)),
        ("v2.1.0", (2, 1, 0)),
        ("0.12.0b", (0, 12, 0)),
        ("25.10", (25, 10, 0)),
        ("  26.04.0  ", (26, 4, 0)),
    ])
    def test_real_version_strings_still_parse(self, text, expected):
        """Tightening must not reject the forms actually in use."""
        assert _parse_semver(text) == expected

    def test_floor_constant_parses(self):
        assert _parse_semver(_NEXTFLOW_MIN_VERSION) == (26, 4, 0)


class TestVersionDetectionDoesNotInventVersions:
    def _run(self, stdout="", stderr=""):
        result = MagicMock(stdout=stdout, stderr=stderr, returncode=0)
        with patch("shutil.which", return_value="/usr/bin/nextflow"), \
             patch("subprocess.run", return_value=result):
            return _get_nextflow_version()

    def test_java_missing_is_not_reported_as_a_version(self):
        """The fallback used to return the first non-empty line verbatim."""
        reported = self._run(stderr=JAVA_MISSING_OUTPUT)
        assert _parse_semver(reported) is None

    def test_real_banner_still_parses(self):
        banner = (
            "      N E X T F L O W\n"
            "      version 26.04.0 build 12031\n"
            "      created 01-04-2026 06:00 UTC\n"
        )
        assert _parse_semver(self._run(stdout=banner)) == (26, 4, 0)

    def test_missing_binary_is_reported_plainly(self):
        with patch("shutil.which", return_value=None):
            assert _get_nextflow_version() == "not found"


class TestDoctorFailsWithoutJava:
    """doctor must not bless a machine that cannot run Nextflow."""

    def test_java_probe_exists(self):
        """A JRE check must be present at all -- there was none."""
        from nanometa_live.cli import prepare

        assert hasattr(prepare, "_java_runtime_available"), (
            "no Java detection: Nextflow is a JVM application and a missing "
            "JRE is the most likely reason a field laptop cannot run it"
        )

    def test_missing_java_is_reported_as_a_failure(self, capsys):
        from nanometa_live.cli import prepare

        reported = []

        def fake_report(name, ok, message, hint=None, fatal=True):
            reported.append((name, ok, fatal))

        with patch.object(prepare, "_java_runtime_available",
                          return_value=(False, "not found")), \
             patch("shutil.which", return_value="/usr/bin/nextflow"), \
             patch("nanometa_live.core.workflow.bundle_manager."
                   "_get_nextflow_version", return_value="unknown"):
            prepare._doctor_check_toolchain(fake_report)

        java_rows = [r for r in reported if "Java" in r[0]]
        assert java_rows, f"no Java row reported; got {[r[0] for r in reported]}"
        assert java_rows[0][1] is False, "missing Java reported as passing"
        assert java_rows[0][2] is True, "missing Java must be fatal, not a warning"

    def test_unparseable_nextflow_version_is_a_failure(self):
        """A version we cannot read is not a version we can accept."""
        from nanometa_live.cli import prepare

        reported = []

        def fake_report(name, ok, message, hint=None, fatal=True):
            reported.append((name, ok, fatal))

        with patch.object(prepare, "_java_runtime_available",
                          return_value=(True, "openjdk 17.0.9")), \
             patch("shutil.which", return_value="/usr/bin/nextflow"), \
             patch("nanometa_live.core.workflow.bundle_manager."
                   "_get_nextflow_version",
                   return_value=JAVA_MISSING_OUTPUT.strip()):
            prepare._doctor_check_toolchain(fake_report)

        nf_rows = [r for r in reported if r[0] == "Nextflow"]
        assert nf_rows and nf_rows[0][1] is False, (
            "unreadable Nextflow version reported as passing"
        )
