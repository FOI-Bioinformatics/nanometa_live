"""Dark-mode legibility guards (operator feedback #8).

Black text authored for the light theme stayed dark on the dark background.
These tests pin the two halves of the fix so it cannot silently regress:

1. The stylesheet defines theme-aware inline-text colour variables (light in
   ``:root``, lightened under ``[data-theme="dark"]``) and per-class dark
   overrides for the text classes that were dark-on-dark.
2. The audited Python modules reference those variables instead of hardcoding a
   dark-on-light hex for text that sits on a (themed) card surface.

Note: Plotly figure text is generated server-side and several charts pin a light
paper background, so chart theming is a separate, larger change and is out of
scope here -- these guards cover the HTML/text layer the operator reported.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent / "nanometa_live" / "app"
_CSS = (_ROOT / "assets" / "styles.css").read_text(encoding="utf-8")


_THEME_VARS = [
    "--text-label",
    "--text-strong",
    "--text-muted-inline",
    "--text-success-inline",
    "--text-warning-inline",
    "--text-danger-inline",
    "--text-info-inline",
]


class TestThemeVariables:
    @pytest.mark.parametrize("var", _THEME_VARS)
    def test_var_defined_for_both_themes(self, var):
        # Defined once for light (:root) and again under the dark block.
        assert _CSS.count(f"{var}:") >= 2, f"{var} needs light + dark definitions"

    def test_dark_block_lightens_label_text(self):
        # The dark override must not repeat the light near-black value.
        dark_idx = _CSS.index('[data-theme="dark"] {')
        dark_section = _CSS[dark_idx:dark_idx + 1200]
        assert "--text-strong: #eaeaea" in dark_section
        assert "--text-label: #c7ccd4" in dark_section


class TestDarkClassOverrides:
    @pytest.mark.parametrize("selector", [
        '[data-theme="dark"] .config-section-title',
        '[data-theme="dark"] .stage-strip-count',
        '[data-theme="dark"] .text-info',
        '[data-theme="dark"] .text-success',
        '[data-theme="dark"] .text-danger',
    ])
    def test_selector_present(self, selector):
        assert selector in _CSS


class TestNoHardcodedDarkInlineText:
    """The audited modules must use the theme vars, not raw dark hexes, for
    text that sits on a themed surface (no paired light background)."""

    def test_organism_components_uses_vars(self):
        src = (_ROOT / "components" / "organism_components.py").read_text()
        for dead in ('"color": "#495057"', '"color": "#212529"', '"color": "#6c757d"'):
            assert dead not in src, f"{dead} should be a theme var"
        assert "var(--text-label)" in src
        assert "var(--text-strong)" in src

    def test_qc_grid_rate_text_uses_vars(self):
        src = (_ROOT / "layouts" / "qc_layout.py").read_text()
        # The classified-rate cell text (no background) is theme-aware now.
        assert '"style": {"color": "#155724", "fontWeight": "600"}' not in src
        assert '"style": {"color": "#721c24"}' not in src
        assert "var(--text-success-inline)" in src
        assert "var(--text-danger-inline)" in src
