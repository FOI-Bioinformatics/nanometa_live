"""Threat-level to alert-severity mapping in ``AlertEngine._check_dangerous_pathogens``.

This method is the alerting core of a biothreat detection tool: it turns a
pathogen-database match into the severity an operator actually sees. Before
these tests only the ``critical`` branch was exercised, so a mis-wired
``high``/``moderate``/``low`` branch -- or a silently swallowed exception --
would have shipped as an under-stated or missing alert with nothing failing.

Three things are pinned here:

1. Every threat-level string the code branches on maps to the documented
   ``AlertSeverity``, including the ``high_risk`` synonym (reachable only from a
   custom watchlist, since ``ThreatLevel`` itself has no such member) and the
   ``else`` catch-all that absorbs ``low``/``info``/``unknown``.
2. The threshold is inclusive: ``alert_threshold: 5`` fires AT 5 reads, not
   above it. This decides whether a negative control carrying 6 reads of
   *Francisella tularensis* (taxid 263) raises a CRITICAL alert. It does.
3. The exception fallback degrades to a single WARNING rather than propagating
   -- but only for ``KeyError``/``AttributeError``/``ValueError``/``TypeError``.
   Anything else still escapes and takes the whole alert generation with it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nanometa_live.core.utils.alert_engine import (
    AlertCategory,
    AlertEngine,
    AlertSeverity,
)

pytestmark = pytest.mark.unit


PATCH_TARGET = "nanometa_live.core.utils.alert_engine.check_for_dangerous_pathogens"


def _detection(threat_level=None, **overrides):
    """A pathogen-database hit shaped as ``check_for_dangerous_pathogens`` emits."""
    d = {
        "taxid": 263,
        "name": "Francisella tularensis",
        "common_name": "Tularemia",
        "reads": 42,
        "abundance": 1.5,
        "category": "CDC-A",
        "action_required": "Contact biosafety officer.",
    }
    if threat_level is not None:
        d["threat_level"] = threat_level
    d.update(overrides)
    return d


def _alerts_for(detection):
    """Run the branch under test with the database lookup stubbed out."""
    engine = AlertEngine()
    with patch(PATCH_TARGET, return_value=[detection]):
        return engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])


class TestThreatLevelToSeverity:
    """Every threat level the code branches on must reach the right severity."""

    # threat_level, expected severity, expected message prefix.
    # "critical"/"high"/"moderate"/"low" are the four levels that actually occur
    # in nanometa_live/core/config/data/watchlists/*.yaml; "high_risk",
    # "unknown" and "info" are additional strings the branch logic accepts.
    @pytest.mark.parametrize(
        "threat_level, expected_severity, prefix",
        [
            ("critical", AlertSeverity.CRITICAL, "CRITICAL PATHOGEN:"),
            ("high", AlertSeverity.WARNING, "HIGH RISK:"),
            ("high_risk", AlertSeverity.WARNING, "HIGH RISK:"),
            ("moderate", AlertSeverity.WARNING, "Watched species:"),
            ("low", AlertSeverity.INFO, "Species of interest:"),
            ("info", AlertSeverity.INFO, "Species of interest:"),
            ("unknown", AlertSeverity.INFO, "Species of interest:"),
        ],
    )
    def test_threat_level_maps_to_severity(
        self, threat_level, expected_severity, prefix
    ):
        alerts = _alerts_for(_detection(threat_level))

        assert len(alerts) == 1, (
            f"threat_level={threat_level!r} produced {len(alerts)} alerts; a "
            f"detection that reaches the engine must always surface exactly one "
            f"alert or the operator sees nothing"
        )
        alert = alerts[0]
        assert alert.severity is expected_severity, (
            f"threat_level={threat_level!r} rendered as {alert.severity.name}; an "
            f"under-stated severity buries the detection below higher-priority "
            f"noise in the sorted alert list"
        )
        assert alert.category is AlertCategory.PATHOGEN, (
            "a pathogen detection filed under a non-PATHOGEN category is dropped "
            "by any category-filtered view"
        )
        assert alert.message.startswith(prefix), (
            f"threat_level={threat_level!r} produced message {alert.message!r}; the "
            f"prefix is what an operator scanning the alert list reads first"
        )

    def test_missing_threat_level_defaults_to_moderate(self):
        """A detection with no threat_level must not silently vanish."""
        alerts = _alerts_for(_detection(threat_level=None))

        assert len(alerts) == 1, (
            "a detection lacking a threat_level produced no alert; an incomplete "
            "watchlist entry would then hide a real organism"
        )
        assert alerts[0].severity is AlertSeverity.WARNING, (
            "the documented default for an absent threat_level is 'moderate' "
            "(WARNING); anything lower under-states an uncharacterised hit"
        )
        assert alerts[0].message.startswith("Watched species:")

    def test_critical_and_high_carry_technical_details(self):
        """The two actionable levels must name the taxid and abundance."""
        for level in ("critical", "high"):
            alert = _alerts_for(_detection(level))[0]
            assert "TaxID: 263" in (alert.technical_details or ""), (
                f"{level} alert omits the taxid; the operator cannot look the "
                f"organism up or launch on-demand validation from it"
            )
            assert "Abundance: 1.50%" in (alert.technical_details or "")

    def test_low_carries_no_technical_details(self):
        """Pins the asymmetry: the info branch passes no technical_details."""
        alert = _alerts_for(_detection("low"))[0]
        assert alert.technical_details is None

    def test_common_name_is_appended_when_present(self):
        alert = _alerts_for(_detection("critical"))[0]
        assert "Francisella tularensis (Tularemia)" in alert.message

    def test_missing_common_name_leaves_bare_scientific_name(self):
        alert = _alerts_for(_detection("critical", common_name=""))[0]
        assert "Francisella tularensis detected" in alert.message
        assert "()" not in alert.message, (
            "an empty parenthetical reads as a rendering bug on the dashboard"
        )


class TestSampleAttribution:
    """Alerts must name the barcode they came from when attribution is available."""

    def test_samples_named_in_message_and_field(self):
        detection = _detection("critical", detected_taxid=263)
        taxid_to_samples = {
            263: [
                {"sample": "barcode01", "reads": 30},
                {"sample": "barcode04", "reads": 12},
            ]
        }
        engine = AlertEngine()
        with patch(PATCH_TARGET, return_value=[detection]):
            alerts = engine._check_dangerous_pathogens(
                [{"taxid": 263, "reads": 42}], None, taxid_to_samples
            )

        alert = alerts[0]
        assert alert.samples == ["barcode01", "barcode04"], (
            "the samples field is what the dashboard uses to point at a barcode; "
            "empty means the operator cannot act on the alert"
        )
        assert "in barcode01, barcode04" in alert.message

    def test_no_attribution_leaves_message_unsuffixed(self):
        alerts = _alerts_for(_detection("critical"))
        assert alerts[0].samples == []
        assert " in " not in alerts[0].message


class TestAlertThresholdBoundary:
    """``alert_threshold: 5`` fires AT 5 reads -- run against the real database.

    Live consequence: a negative control carrying exactly 6 reads of taxid 263
    raises a CRITICAL alert. That is the intended behaviour of an inclusive
    threshold, not a bug, but it is the boundary the field question turns on.
    """

    @staticmethod
    def _run(reads):
        engine = AlertEngine()
        return engine._check_dangerous_pathogens(
            [{
                "taxid": 263,
                "name": "Francisella tularensis",
                "reads": reads,
                "abundance": 0.5,
            }]
        )

    def test_four_reads_is_below_threshold_and_silent(self):
        assert self._run(4) == [], (
            "4 reads is under the alert_threshold of 5; alerting here would make "
            "every low-level barcode-hopping artefact a CRITICAL call"
        )

    def test_five_reads_fires(self):
        alerts = self._run(5)
        assert len(alerts) == 1, (
            "the threshold is inclusive (reads >= alert_threshold); a detection "
            "exactly at threshold must alert or the documented threshold is a lie"
        )
        assert alerts[0].severity is AlertSeverity.CRITICAL

    def test_six_reads_fires(self):
        """The live case: a negative control with 6 reads of taxid 263."""
        alerts = self._run(6)
        assert len(alerts) == 1, (
            "6 reads of Francisella tularensis in any sample -- including a "
            "negative control -- must raise a CRITICAL alert"
        )
        assert alerts[0].severity is AlertSeverity.CRITICAL
        assert "6 reads" in alerts[0].message


class TestExceptionFallback:
    """A broken pathogen lookup must degrade visibly, not silently."""

    @pytest.mark.parametrize(
        "exc", [KeyError("taxid"), AttributeError("x"), ValueError("bad"), TypeError("bad")]
    )
    def test_handled_exception_yields_a_visible_warning(self, exc):
        engine = AlertEngine()
        with patch(PATCH_TARGET, side_effect=exc):
            alerts = engine._check_dangerous_pathogens([{"taxid": 263, "reads": 9}])

        assert len(alerts) == 1, (
            f"{type(exc).__name__} from the pathogen lookup produced no alert; the "
            f"operator would read an empty alert panel as 'nothing detected'"
        )
        alert = alerts[0]
        assert alert.severity is AlertSeverity.WARNING
        assert alert.category is AlertCategory.SYSTEM
        assert alert.message == "Unable to check pathogen database", (
            "the fallback message must say the CHECK failed, not that the run is "
            "clean -- an all-clear reading of a failed check is the dangerous one"
        )
        assert alert.technical_details, (
            "the fallback must carry the underlying error for support triage"
        )

    def test_malformed_reads_value_degrades_to_the_fallback(self):
        """End-to-end degradation: reads=None trips TypeError inside the lookup."""
        engine = AlertEngine()
        alerts = engine._check_dangerous_pathogens([
            {"taxid": 263, "name": "Francisella tularensis", "reads": None}
        ])
        assert [a.message for a in alerts] == ["Unable to check pathogen database"]

    def test_unhandled_exception_type_still_propagates(self):
        """Pins the limit of the guard: only four exception types are caught.

        A RuntimeError (or OSError) from the pathogen database escapes
        ``_check_dangerous_pathogens`` and aborts ``generate_alerts`` entirely,
        so the operator loses the QC and system alerts too, not just pathogens.
        """
        engine = AlertEngine()
        with patch(PATCH_TARGET, side_effect=RuntimeError("db corrupt")):
            with pytest.raises(RuntimeError):
                engine._check_dangerous_pathogens([{"taxid": 263, "reads": 9}])

    def test_alerts_appended_before_the_failure_are_retained(self):
        """A failure partway through must not discard the criticals already found."""
        engine = AlertEngine()
        good = _detection("critical")
        bad = _detection("critical", reads=None)  # reads=None breaks the f-string

        with patch(PATCH_TARGET, return_value=[good, bad]):
            alerts = engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])

        messages = [a.message for a in alerts]
        assert any("CRITICAL PATHOGEN" in m for m in messages), (
            "the critical alert produced before the malformed detection was "
            "dropped; one bad record must not erase a confirmed select-agent hit"
        )
        assert "Unable to check pathogen database" in messages


class TestPathogenLogDeduplication:
    """The 30 s poll must not re-log the same PATHOGEN ALERT every tick."""

    def test_repeat_identical_detection_logs_once(self, caplog):
        engine = AlertEngine()
        detection = _detection("critical")
        with patch(PATCH_TARGET, return_value=[detection]):
            with caplog.at_level("WARNING", logger="nanometa_live.core.utils.alert_engine"):
                engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])
                engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])

        hits = [r for r in caplog.records if "PATHOGEN ALERT" in r.getMessage()]
        assert len(hits) == 1, (
            "an unguarded log line repeats every poll for the whole run and "
            "buries every other log message"
        )

    def test_changed_counts_log_again(self, caplog):
        engine = AlertEngine()
        with caplog.at_level("WARNING", logger="nanometa_live.core.utils.alert_engine"):
            with patch(PATCH_TARGET, return_value=[_detection("critical")]):
                engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])
            with patch(
                PATCH_TARGET,
                return_value=[_detection("critical"), _detection("critical", taxid=1392)],
            ):
                engine._check_dangerous_pathogens([{"taxid": 263, "reads": 42}])

        hits = [r for r in caplog.records if "PATHOGEN ALERT" in r.getMessage()]
        assert len(hits) == 2, (
            "a second critical organism appearing is a state change the operator "
            "must see in the log, not be deduplicated away"
        )
