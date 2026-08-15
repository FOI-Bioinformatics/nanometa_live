"""Tests for the pathogen-alert RENDERING path.

Detection and rendering are separate failure modes. The detection side is
covered (watchlist matching, attribution, verdict selection); the code that
turns a detection dict into the card an operator actually reads was not
covered at all. A select agent can be detected correctly and then rendered
without its taxid, without its required action, in the wrong severity colour,
or not at all -- and nothing in the suite would fail.

The path under test:

    _generate_alerts()             -- dashboard alert list (AlertEngine)
    _create_pathogen_alert_panel() -- detection dicts -> alert cards
      -> CriticalPathogenAlert / HighRiskPathogenAlert / WatchedSpeciesAlert
    PathogenAlertPanel()           -- standalone panel used by components

Detections are built from a real run (nmcampaign R1, 2026-07-28), whose
measured Kraken2 numbers are recorded in ``_R1`` below, and from the shipped
``cdc_bioterrorism.yaml`` watchlist entry -- parsed here rather than
transcribed, so a change to the shipped threat level or action string is
caught rather than mirrored.

The assertions are on rendered text and semantic properties (severity colour,
contrast, routing, component identity), never on the nested component tree:
a layout change must not break these tests, but a card that loses the taxid,
the action string, or its severity must.
"""

import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
import yaml
from dash import html

from nanometa_live.app.components.pathogen_alert import (
    THREAT_LEVELS,
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
    PathogenAlertPanel,
    WatchedSpeciesAlert,
)
from nanometa_live.app.tabs import dashboard_helpers
from nanometa_live.app.tabs.dashboard_helpers import (
    _create_pathogen_alert_panel,
    _generate_alerts,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Real measurements from run R1 (/Volumes/.../nmcampaign/results/R1)
# ---------------------------------------------------------------------------
# barcode11: 34,120 classified reads, 34,096 of them Francisella tularensis.
# barcode14: 20,676 classified; Limosilactobacillus fermentum 4,229 reads;
#            1 read of taxid 263.
# barcode16: negative control, 11 classified reads, 6 of taxid 263.
_R1 = {
    "tularensis_taxid": 263,
    "fermentum_taxid": 1613,
    "samples": [
        {"sample": "barcode11", "reads": 34096, "abundance": 99.87,
         "is_negative_control": False},
        {"sample": "barcode16", "reads": 6, "abundance": 54.55,
         "is_negative_control": True},
        {"sample": "barcode14", "reads": 1, "abundance": 0.00,
         "is_negative_control": False},
    ],
    # 34,096 + 6 + 1 of 34,120 + 11 + 20,676 classified reads.
    "tularensis_total_reads": 34103,
    "tularensis_total_abundance": 62.22,
}

_WATCHLIST_YAML = (
    "nanometa_live/core/config/data/watchlists/cdc_bioterrorism.yaml"
)


@pytest.fixture(scope="module")
def tularensis_entry() -> Dict[str, Any]:
    """The shipped F. tularensis watchlist entry, parsed from the YAML."""
    import nanometa_live

    root = os.path.dirname(os.path.dirname(nanometa_live.__file__))
    with open(os.path.join(root, _WATCHLIST_YAML)) as fh:
        data = yaml.safe_load(fh)
    entries = data.get("pathogens") or data.get("organisms") or []
    match = [e for e in entries if e.get("taxid_ncbi") == _R1["tularensis_taxid"]]
    assert match, (
        "cdc_bioterrorism.yaml no longer carries taxid 263; the rendering "
        "tests below assert against the shipped select-agent entry"
    )
    return match[0]


@pytest.fixture
def tularensis_detection(tularensis_entry) -> Dict[str, Any]:
    """A detection dict shaped exactly as check_organisms_with_mapping emits."""
    return {
        "taxid": tularensis_entry["taxid_ncbi"],
        "detected_taxid": _R1["tularensis_taxid"],
        "name": tularensis_entry["name"],
        "common_name": tularensis_entry.get("common_name"),
        "reads": _R1["tularensis_total_reads"],
        "abundance": _R1["tularensis_total_abundance"],
        "threat_level": tularensis_entry["threat_level"],
        "bsl": tularensis_entry.get("bsl_level"),
        "category": tularensis_entry.get("category"),
        "notes": tularensis_entry.get("notes"),
        "action_required": tularensis_entry["action_required"],
        "threshold": tularensis_entry["alert_threshold"],
        "match_score": 1.0,
        "match_method": "direct_ncbi",
        "detected_name": tularensis_entry["name"],
        "ambiguous_with": [],
    }


@pytest.fixture
def taxid_to_samples() -> Dict[int, List[Dict[str, Any]]]:
    """Per-taxid attribution keyed by the Kraken2 report taxid, as built by
    _load_per_sample_organisms."""
    return {_R1["tularensis_taxid"]: [dict(s) for s in _R1["samples"]]}


# ---------------------------------------------------------------------------
# Tree helpers -- text and property extraction only, never structure
# ---------------------------------------------------------------------------


def _walk(node):
    """Yield every node in a Dash component tree, depth first."""
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)


def _text(node) -> str:
    """Flatten a component tree to the text an operator would read."""
    parts = []
    for n in _walk(node):
        if isinstance(n, (str, int, float)):
            parts.append(str(n))
    return " ".join(parts)


def _styles(node) -> List[Dict[str, Any]]:
    """Every inline style dict in the tree."""
    return [
        s for s in (getattr(n, "style", None) for n in _walk(node))
        if isinstance(s, dict)
    ]


def _colors(node) -> set:
    """Every colour value used anywhere in the tree's inline styles."""
    keys = ("color", "backgroundColor", "borderColor", "borderLeft", "border")
    out = set()
    for style in _styles(node):
        for key in keys:
            value = style.get(key)
            if isinstance(value, str):
                out.add(value)
    return out


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(fg: str, bg: str) -> float:
    lum = sorted((_relative_luminance(fg), _relative_luminance(bg)))
    return (lum[1] + 0.05) / (lum[0] + 0.05)


def _panel(detections, **kwargs):
    """Render _create_pathogen_alert_panel with detection matching stubbed.

    The panel's own job starts once detections exist; stubbing the watchlist
    match keeps these tests off the WatchlistManager singleton (shared state
    across a worker) and off the taxid-mapping cache.
    """
    with patch.object(
        dashboard_helpers, "_check_pathogens_with_mapping",
        return_value=detections,
    ):
        return _create_pathogen_alert_panel(
            detected_organisms=detections or [{"taxid": 1, "name": "x"}],
            **kwargs,
        )


class TestCriticalDetectionContent:
    """A critical select-agent card must carry everything the operator needs
    to act: the organism, its identity, and the required action."""

    def test_names_organism_taxid_and_required_action(
        self, tularensis_detection, taxid_to_samples, tularensis_entry
    ):
        panel, style = _panel(
            [tularensis_detection], taxid_to_samples=taxid_to_samples
        )
        text = _text(panel)

        assert style == {"display": "block"}, (
            "critical select-agent panel rendered hidden; the operator would "
            f"see no alert at all (style={style})"
        )
        assert "Francisella tularensis" in text, (
            "organism name absent from the critical alert card"
        )
        assert str(_R1["tularensis_taxid"]) in text, (
            "taxid missing; the operator cannot cross-check the identity"
        )
        assert tularensis_entry["action_required"] in text, (
            "action_required string missing; the card states a select-agent "
            "detection without saying what to do about it"
        )

    def test_reports_read_count_and_abundance(self, tularensis_detection):
        panel, _ = _panel([tularensis_detection])
        text = _text(panel)
        assert "34,103" in text, (
            "read count missing or unformatted; evidence strength is the "
            "operator's main sanity check on a detection"
        )
        assert "62.22" in text, "abundance percentage missing from the card"

    def test_common_name_shown_alongside_scientific_name(
        self, tularensis_detection, tularensis_entry
    ):
        panel, _ = _panel([tularensis_detection])
        assert tularensis_entry["common_name"] in _text(panel), (
            "common name omitted; non-expert operators read 'Tularemia', "
            "not 'Francisella tularensis'"
        )

    def test_names_the_samples_it_was_detected_in(
        self, tularensis_detection, taxid_to_samples
    ):
        panel, _ = _panel(
            [tularensis_detection], taxid_to_samples=taxid_to_samples
        )
        text = _text(panel)
        assert "barcode11" in text, (
            "the triggering barcode is not named; the operator cannot tell "
            "which sample to quarantine"
        )
        assert "barcode16 (NC)" in text, (
            "the negative control is not flagged (NC); an operator would read "
            "a control contamination as a real positive"
        )

    def test_attribution_resolves_via_detected_taxid_on_a_gtdb_style_db(
        self, tularensis_detection
    ):
        """On a GTDB/custom database the report taxid differs from the NCBI
        taxid on the watchlist entry. Attribution must follow the report."""
        detection = {**tularensis_detection, "detected_taxid": 4005020}
        panel, _ = _panel(
            [detection],
            taxid_to_samples={4005020: [dict(s) for s in _R1["samples"]]},
        )
        assert "barcode11" in _text(panel), (
            "attribution lost when the database taxid differs from the NCBI "
            "taxid -- the failure is silent, the card just names no sample"
        )

    def test_critical_card_is_an_assertive_live_region(
        self, tularensis_detection
    ):
        panel, _ = _panel([tularensis_detection])
        live = [
            getattr(n, "aria-live", None) for n in _walk(panel)
            if getattr(n, "aria-live", None)
        ]
        assert "assertive" in live, (
            "critical alert is not an assertive live region; screen-reader "
            "users get no announcement of a select-agent detection"
        )


class TestThreatLevelSeverity:
    """Every threat level the code supports must render a visually distinct,
    readable severity treatment. Two tiers that look alike is a real defect:
    the colour is the whole 30-second-scan signal."""

    def test_all_watchlist_threat_levels_are_defined(self):
        """The YAML validator's level set and THREAT_LEVELS must agree."""
        from nanometa_live.core.config.pathogen_loader import ThreatLevel

        for level in ThreatLevel:
            if level is ThreatLevel.UNKNOWN:
                continue
            assert level.value in THREAT_LEVELS, (
                f"threat level {level.value!r} exists in the watchlist schema "
                "but has no visual definition; it would render untagged"
            )

    @pytest.mark.parametrize("level", ["critical", "high", "moderate", "low"])
    def test_severity_label_and_readable_colour(self, level):
        spec = THREAT_LEVELS[level]
        ratio = _contrast_ratio(spec["color"], spec["bg_color"])
        assert ratio >= 4.5, (
            f"{level} severity text {spec['color']} on {spec['bg_color']} is "
            f"{ratio:.1f}:1, below WCAG AA 4.5:1 -- unreadable in field "
            "conditions"
        )

    def test_the_four_severities_are_visually_distinguishable(self):
        pairs = {
            level: (spec["color"], spec["border_color"])
            for level, spec in THREAT_LEVELS.items()
        }
        assert len(set(pairs.values())) == len(pairs), (
            "two threat levels share a colour pair; an operator cannot tell "
            f"a critical hit from a lesser one ({pairs})"
        )

    @pytest.mark.parametrize(
        "level,expected_label",
        [
            ("critical", "CRITICAL"),
            ("high", "HIGH RISK"),
            ("high_risk", "HIGH RISK"),
            ("moderate", "WATCH"),
            ("low", "WATCH"),
            ("unknown", "WATCH"),
        ],
    )
    def test_threat_level_routes_to_the_right_card(
        self, tularensis_detection, level, expected_label
    ):
        """Including the ``high_risk`` alias and the unmapped levels, which
        must degrade to the watched tier rather than vanish."""
        panel, style = _panel([{**tularensis_detection, "threat_level": level}])
        text = _text(panel)
        assert style == {"display": "block"}, (
            f"threat level {level!r} produced no visible card"
        )
        assert expected_label in text, (
            f"threat level {level!r} did not render the {expected_label!r} "
            f"severity label; operator sees the wrong urgency. Text: {text[:200]}"
        )

    def test_critical_card_uses_the_critical_palette(self, tularensis_detection):
        panel, _ = _panel([tularensis_detection])
        assert THREAT_LEVELS["critical"]["color"] in _colors(panel), (
            "critical card does not use the critical severity colour"
        )

    def test_moderate_hit_does_not_use_the_critical_palette(
        self, tularensis_detection
    ):
        panel, _ = _panel(
            [{**tularensis_detection, "threat_level": "moderate"}]
        )
        assert THREAT_LEVELS["critical"]["color"] not in _colors(panel), (
            "a moderate watched-species hit renders in the critical colour; "
            "over-alerting trains operators to ignore real critical hits"
        )

    def test_mixed_severities_summarised_and_ordered_critical_first(
        self, tularensis_detection
    ):
        watched = {
            **tularensis_detection,
            "taxid": _R1["fermentum_taxid"],
            "name": "Limosilactobacillus fermentum",
            "common_name": None,
            "reads": 4229,
            "abundance": 20.43,
            "threat_level": "moderate",
        }
        panel, _ = _panel([tularensis_detection, watched])
        text = _text(panel)
        assert "2 WATCHED ORGANISMS DETECTED" in text, (
            "multi-hit panel lost its summary header"
        )
        assert text.index("Francisella tularensis") < text.index(
            "Limosilactobacillus fermentum"
        ), (
            "the critical hit is not rendered first; the most urgent card "
            "must be the one at the top of the panel"
        )
        assert "Watched Species (1)" in text, (
            "watched-species section header missing or miscounted"
        )


class TestDegradedInput:
    """Field data is ragged. Each of these has produced, or could produce, a
    card the operator cannot use -- none may raise."""

    def test_missing_common_name(self, tularensis_detection):
        detection = dict(tularensis_detection)
        detection.pop("common_name")
        panel, style = _panel([detection])
        text = _text(panel)
        assert style == {"display": "block"} and "Francisella tularensis" in text
        assert "()" not in text.replace(" ", ""), (
            "an empty parenthetical is rendered where the common name would "
            f"be: {text[:200]}"
        )

    def test_null_common_name(self, tularensis_detection):
        panel, style = _panel([{**tularensis_detection, "common_name": None}])
        assert style == {"display": "block"}, (
            "a null common_name suppressed the whole critical card"
        )

    def test_zero_reads_still_renders(self, tularensis_detection):
        panel, style = _panel(
            [{**tularensis_detection, "reads": 0, "abundance": 0.0}]
        )
        text = _text(panel)
        assert style == {"display": "block"}, (
            "a zero-read detection vanished instead of rendering; a caller "
            "that passes an unfiltered hit would show nothing"
        )
        assert "0 DNA matches" in text, f"read count not rendered: {text[:200]}"

    def test_unicode_organism_name_is_preserved(self, tularensis_detection):
        name = "Nörgaard's bacterium ☃ (β-strain)"
        panel, _ = _panel([{**tularensis_detection, "name": name}])
        assert name in _text(panel), (
            "a non-ASCII organism name was mangled or dropped"
        )

    def test_empty_detection_list_renders_nothing_visible(self):
        panel, style = _create_pathogen_alert_panel([])
        assert style == {"display": "none"}, (
            "the panel container is shown with no detections in it"
        )
        assert _text(panel).strip() == "", "empty panel rendered stray text"

    def test_no_matching_detections_hides_the_panel(self, tularensis_detection):
        panel, style = _panel([])
        assert style == {"display": "none"}, (
            "organisms present but no watchlist match must leave the panel "
            "hidden, not render an empty alert box"
        )

    def test_taxid_none(self, tularensis_detection):
        detection = {**tularensis_detection, "taxid": None,
                     "detected_taxid": None}
        panel, style = _panel([detection])
        assert style == {"display": "block"}, (
            "a detection with no taxid produced no card; an unidentifiable "
            "hit is still a hit the operator must see"
        )
        assert "Francisella tularensis" in _text(panel)

    def test_taxid_none_gives_buttons_a_usable_id(self, tularensis_detection):
        """The report/acknowledge buttons are pattern-matching ids; a None
        taxid must not produce a duplicate or malformed id."""
        panel, _ = _panel(
            [{**tularensis_detection, "taxid": None, "detected_taxid": None}]
        )
        ids = [
            getattr(n, "id", None) for n in _walk(panel)
            if isinstance(getattr(n, "id", None), dict)
        ]
        assert ids, "no pattern-matching button ids rendered"
        assert all(i.get("taxid") is not None for i in ids), (
            f"a button id carries taxid=None and will not match a callback: {ids}"
        )

    @pytest.mark.parametrize(
        "name",
        [
            "<script>alert('xss')</script>",
            'Bacillus "anthracis" & <b>friends</b>',
        ],
    )
    def test_html_special_characters_are_inert_text(
        self, tularensis_detection, name
    ):
        """Names reach the card from an operator-uploaded watchlist YAML.
        They must be React text children (escaped on render), never markup."""
        panel, _ = _panel([{**tularensis_detection, "name": name}])
        assert name in _text(panel), (
            "the organism name was altered or dropped instead of being "
            "rendered as literal text"
        )
        unsafe = [
            n for n in _walk(panel)
            if getattr(n, "dangerously_allow_html", False)
        ]
        assert not unsafe, (
            "a component in the alert tree enables dangerously_allow_html, so "
            f"a watchlist-supplied name would be interpreted as markup: {unsafe}"
        )

    def test_missing_action_required_falls_back_to_a_default(
        self, tularensis_detection
    ):
        detection = dict(tularensis_detection)
        detection.pop("action_required")
        panel, _ = _panel([detection])
        text = _text(panel)
        assert "Recommended Action" in text, (
            "an entry with no action_required renders a critical card with no "
            "recommendation section at all"
        )
        assert len(text.split("Recommended Action:")[-1].strip()) > 0, (
            "the recommendation section is present but empty"
        )

    def test_a_broken_detection_does_not_take_down_the_dashboard(self):
        """The panel swallows its own errors by design -- assert it does,
        rather than propagating into the dashboard callback."""
        panel, style = _panel([{"threat_level": "critical", "reads": "many"}])
        assert style == {"display": "none"}, (
            "a malformed detection must degrade to a hidden panel, not raise "
            "into the callback and blank the dashboard"
        )


class TestCardComponentsDirectly:
    """The three card builders are also called from PathogenAlertPanel and
    from the components package, so their contracts are asserted directly."""

    def test_high_risk_card_carries_name_taxid_and_action(self):
        card = HighRiskPathogenAlert(
            pathogen_name="Brucella melitensis",
            common_name="Brucellosis",
            read_count=1500,
            abundance_pct=4.2,
            taxid=29459,
            recommendation="Notify the biosafety officer.",
        )
        text = _text(card)
        for expected in ("Brucella melitensis", "Brucellosis", "1,500",
                         "4.20", "HIGH RISK"):
            assert expected in text, f"{expected!r} missing from high-risk card"

    def test_watched_species_card_names_organism_and_reads(self):
        card = WatchedSpeciesAlert(
            pathogen_name="Limosilactobacillus fermentum",
            read_count=_R1["fermentum_taxid"] and 4229,
            abundance_pct=20.43,
            taxid=_R1["fermentum_taxid"],
        )
        text = _text(card)
        assert "Limosilactobacillus fermentum" in text
        assert "4,229" in text, "watched-species card lost its read count"
        assert "WATCH" in text, "watched-species card lost its severity label"

    def test_critical_card_without_optional_arguments(self):
        """Only pathogen_name is required; the rest must have safe defaults."""
        card = CriticalPathogenAlert(pathogen_name="Yersinia pestis")
        text = _text(card)
        assert "Yersinia pestis" in text
        assert THREAT_LEVELS["critical"]["action"] in text, (
            "no recommendation rendered when the caller supplies none"
        )

    def test_confidence_label_is_rendered(self):
        low = _text(CriticalPathogenAlert("X", read_count=5,
                                          confidence="MODERATE"))
        high = _text(CriticalPathogenAlert("X", read_count=5000,
                                           confidence="HIGH"))
        assert "MODERATE" in low and "HIGH" in high, (
            "confidence label not rendered; the operator loses the only "
            "on-card signal of evidence strength"
        )


class TestPathogenAlertPanelComponent:
    """PathogenAlertPanel matches raw Kraken2 organisms against a watched-
    species config itself, so it has its own matching contract."""

    def _watchlist(self):
        return [{
            "taxid": _R1["tularensis_taxid"],
            "name": "Francisella tularensis",
            "common_name": "Tularemia",
            "threat_level": "critical",
        }]

    def test_matches_by_taxid_and_renders_a_critical_card(self):
        panel = PathogenAlertPanel(
            [{"taxid": _R1["tularensis_taxid"],
              "name": "Francisella tularensis", "reads": 34096,
              "abundance": 99.87}],
            self._watchlist(),
        )
        text = _text(panel)
        assert "CRITICAL" in text and "Francisella tularensis" in text, (
            "a taxid-matched select agent did not render a critical card"
        )
        assert "Tularemia" in text, "common name from the watchlist not used"

    def test_matches_by_name_when_taxid_differs(self):
        """On a GTDB database the report taxid will not be the NCBI one."""
        panel = PathogenAlertPanel(
            [{"taxid": 4005020, "name": "Francisella tularensis",
              "reads": 34096, "abundance": 99.87}],
            self._watchlist(),
        )
        assert "CRITICAL" in _text(panel), (
            "name fallback failed; on a custom database the panel would show "
            "ALL CLEAR for a detected select agent"
        )

    def test_unwatched_organism_yields_an_explicit_all_clear(self):
        panel = PathogenAlertPanel(
            [{"taxid": _R1["fermentum_taxid"],
              "name": "Limosilactobacillus fermentum", "reads": 4229}],
            self._watchlist(),
        )
        assert "All Clear" in _text(panel), (
            "no watched organism detected must state ALL CLEAR explicitly, "
            "not render an empty panel indistinguishable from a broken one"
        )

    def test_empty_inputs_still_state_all_clear(self):
        assert "All Clear" in _text(PathogenAlertPanel([], []))

    def test_organism_missing_name_does_not_raise(self):
        panel = PathogenAlertPanel(
            [{"taxid": _R1["tularensis_taxid"], "reads": 100}],
            self._watchlist(),
        )
        assert "CRITICAL" in _text(panel), (
            "a nameless organism row broke taxid matching for a select agent"
        )


# ---------------------------------------------------------------------------
# _generate_alerts -- the dashboard's alert list, over a real-derived results
# tree
# ---------------------------------------------------------------------------


def _write_report(path: str, rows: List[str]) -> None:
    """Write a Kraken2 report and back-date it past the loader stability check."""
    with open(path, "w") as fh:
        fh.write("\n".join(rows) + "\n")
    old = os.path.getmtime(path) - 60
    os.utime(path, (old, old))


@pytest.fixture
def r1_results_dir(tmp_path) -> str:
    """A minimal results tree carrying R1's measured Kraken2 rows."""
    kraken = tmp_path / "kraken2"
    kraken.mkdir()
    _write_report(str(kraken / "barcode11.kraken2.report.txt"), [
        "  0.06\t21\t21\tU\t0\tunclassified",
        " 99.94\t34120\t0\tR\t1\troot",
        " 99.92\t34115\t0\tD\t2\t  Bacteria",
        " 99.87\t34096\t29721\tS\t263\t    Francisella tularensis",
    ])
    _write_report(str(kraken / "barcode14.kraken2.report.txt"), [
        "  0.10\t21\t21\tU\t0\tunclassified",
        " 99.90\t20676\t0\tR\t1\troot",
        " 99.00\t20500\t0\tD\t2\t  Bacteria",
        " 20.43\t4229\t4228\tS\t1613\t    Limosilactobacillus fermentum",
        "  0.00\t1\t1\tS\t263\t    Francisella tularensis",
    ])
    _write_report(str(kraken / "barcode16.kraken2.report.txt"), [
        "  0.00\t0\t0\tU\t0\tunclassified",
        "100.00\t11\t0\tR\t1\troot",
        " 81.82\t9\t0\tD\t2\t  Bacteria",
        " 54.55\t6\t4\tS\t263\t    Francisella tularensis",
    ])
    return str(tmp_path)


class TestGenerateAlerts:
    """_generate_alerts turns run state into the dashboard's alert list. It
    must surface a select-agent detection as a critical alert, and must not
    raise on a results directory that has produced nothing yet."""

    def _samples_data(self):
        return [
            {"sample": "barcode11", "status": "Complete", "quality": "Good",
             "organisms": 12, "reads": "34,120"},
            {"sample": "barcode14", "status": "Complete", "quality": "Good",
             "organisms": 40, "reads": "20,676"},
            {"sample": "barcode16", "status": "Complete", "quality": "Poor",
             "organisms": 3, "reads": "11"},
        ]

    def _run(self, main_dir, watchlist, **status):
        from nanometa_live.core.utils.alert_engine import AlertEngine

        overall = {"running": False, "completed": True, "error_count": 0,
                   "total_reads": 54807, "quality_score": 70,
                   "organisms_detected": 55, **status}
        # A fresh engine per call: the module singleton carries alert history
        # and dedup state, which would make these tests order dependent.
        with patch.object(dashboard_helpers, "get_alert_engine",
                          return_value=AlertEngine()), \
             patch.object(dashboard_helpers, "_get_active_watchlist_entries",
                          return_value=watchlist):
            return _generate_alerts(
                overall, main_dir, {"results_output_directory": main_dir},
                self._samples_data(),
            )

    def test_select_agent_detection_becomes_a_critical_alert(
        self, r1_results_dir, tularensis_entry
    ):
        watchlist = [{
            "name": tularensis_entry["name"],
            "taxid": tularensis_entry["taxid_ncbi"],
            "db_taxid": None,
            "common_name": tularensis_entry.get("common_name"),
            "threat_level": tularensis_entry["threat_level"],
            "alert_threshold": tularensis_entry["alert_threshold"],
            "enabled": True,
        }]
        alerts = self._run(r1_results_dir, watchlist)
        blob = " ".join(
            f"{a.get('message', '')} {a.get('recommendation', '')} "
            f"{a.get('technical_details', '')}"
            for a in alerts
        )
        assert "tularensis" in blob.lower(), (
            "34,096 reads of a Tier 1 select agent produced no alert naming "
            f"it. Alerts: {[a.get('message') for a in alerts]}"
        )
        severities = {a.get("severity") for a in alerts}
        assert "critical" in severities, (
            f"select-agent detection did not raise a critical alert: {severities}"
        )

    def test_alert_dicts_have_the_fields_the_ui_reads(self, r1_results_dir):
        alerts = self._run(r1_results_dir, [])
        assert isinstance(alerts, list)
        for alert in alerts:
            assert "severity" in alert and "message" in alert, (
                f"alert dict missing the keys the alert list renders: {alert}"
            )

    def test_empty_results_directory_does_not_raise(self, tmp_path):
        alerts = self._run(str(tmp_path), [])
        assert isinstance(alerts, list), (
            "a run with no results yet must yield a list, not raise into the "
            "dashboard callback"
        )

    def test_missing_results_directory_does_not_raise(self, tmp_path):
        alerts = self._run(str(tmp_path / "does-not-exist"), [])
        assert isinstance(alerts, list), (
            "a stale/absent results path must degrade to an empty-ish alert "
            "list rather than crashing the dashboard"
        )
