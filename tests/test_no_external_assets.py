"""The dashboard must not fetch anything from the internet to render.

Every other offline guarantee in this project is enforced in the Python
process -- ``offline_mode`` guards, ``NXF_OFFLINE``, cached taxonomy. None of
them apply here, because a stylesheet in ``external_stylesheets`` is fetched by
the *browser*, not by us. Socket patching cannot see it and ``--network none``
on the app container cannot see it either.

The app declared ``dbc.themes.BOOTSTRAP`` and ``dbc.icons.BOOTSTRAP``, both
``https://cdn.jsdelivr.net/...`` URLs. On an air-gapped field machine that
means the operator gets an unstyled page with every ``bi-*`` glyph missing --
including the icons in the offline-mode banner itself. The app "works": it
serves, callbacks fire, tests pass. It is just unreadable.

Note ``serve_locally`` does not help: it governs Dash's own component bundles,
not ``external_stylesheets``.

Two assertions, because they fail differently:
 * no external URL is declared or rendered (catches the regression), and
 * the vendored files are actually present and complete, fonts included
   (catches "we dropped the CDN but shipped a stylesheet that renders no
   icons").
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import nanometa_live.app.app as app_module

ASSETS = Path(app_module.__file__).parent / "assets"

_EXTERNAL = re.compile(r"https?://", re.I)


class TestNoExternalStylesheets:
    def test_external_stylesheets_are_not_remote(self, tmp_path):
        """Nothing the real app declares may be an http(s) URL.

        Built through ``create_app`` rather than read off a module constant, so
        the assertion cannot go vacuous if the wiring moves.
        """
        from unittest.mock import MagicMock

        app = app_module.create_app(
            {"data_dir": str(tmp_path), "project_dir": str(tmp_path)},
            str(tmp_path),
            MagicMock(),
        )
        declared = list(app.config.external_stylesheets or [])
        remote = [s for s in declared if isinstance(s, str) and _EXTERNAL.match(s)]
        assert not remote, (
            "The dashboard declares remote stylesheets, which the browser "
            f"fetches over the internet: {remote}. Air-gapped, the page renders "
            "unstyled with no icons -- including the offline banner's own icons."
        )
        # Guard the guard: if the app somehow declares nothing at all, the
        # assertion above is trivially true and proves nothing.
        assert declared or list(ASSETS.rglob("*bootstrap*.css")), (
            "No stylesheets declared and none vendored -- the check above "
            "would pass on a dashboard with no styling at all."
        )

    def test_no_remote_url_in_served_assets(self):
        """No asset the browser loads may reference a remote host.

        Covers the second-order case: a vendored CSS file whose @font-face or
        @import still points at a CDN is no better than the CDN itself.
        """
        offenders = {}
        for css in sorted(ASSETS.rglob("*.css")):
            text = css.read_text(encoding="utf-8", errors="replace")
            hits = sorted(set(re.findall(r"https?://[^\s\"')]+", text)))
            # A bare comment/credit URL is harmless; a url() or @import is not.
            fetched = [
                h
                for h in hits
                if re.search(
                    r"(url\(\s*['\"]?|@import\s+['\"]?)" + re.escape(h), text
                )
            ]
            if fetched:
                offenders[css.name] = fetched
        assert not offenders, (
            f"Vendored CSS still fetches from remote hosts: {offenders}. "
            "Fonts referenced by URL must be vendored too."
        )


class TestVendoredAssetsAreComplete:
    def test_bootstrap_css_is_vendored(self):
        candidates = list(ASSETS.rglob("*bootstrap*.css"))
        assert candidates, (
            "No vendored Bootstrap CSS found under app/assets/. Dropping the "
            "CDN without vendoring leaves the dashboard unstyled."
        )
        biggest = max(candidates, key=lambda p: p.stat().st_size)
        assert biggest.stat().st_size > 50_000, (
            f"{biggest.name} is only {biggest.stat().st_size} bytes; that is "
            "not a complete Bootstrap stylesheet."
        )

    def test_icon_font_files_are_vendored(self):
        """The icons are a font, not just a stylesheet.

        Vendoring bootstrap-icons.css alone still renders every bi-* glyph as
        a blank box, which is the failure this test exists to prevent.
        """
        fonts = [
            p
            for p in ASSETS.rglob("*")
            if p.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf"}
        ]
        assert fonts, (
            "No icon font files found under app/assets/. bootstrap-icons.css "
            "declares @font-face against .woff2 files; without them every "
            "bi-* icon renders as an empty box."
        )
        assert max(f.stat().st_size for f in fonts) > 10_000, (
            "The vendored font files are implausibly small; check the download."
        )
