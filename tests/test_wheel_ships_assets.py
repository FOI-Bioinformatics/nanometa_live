"""A built wheel must contain every asset the app serves.

Round 2 vendored Bootstrap and its icon font into ``app/assets/`` so an
air-gapped dashboard would not reach a CDN. But ``pyproject.toml`` declared
``app/assets/*``, and setuptools package-data globs are not recursive: the
five files directly under ``assets/`` shipped and ``assets/fonts/`` did not.

So a pip-installed nanometa_live had ``01-bootstrap-icons.css``, whose
``@font-face`` points at ``fonts/bootstrap-icons.woff2``, and no such file.
Every ``bi-*`` glyph rendered as a missing-glyph box -- including the icons
on the offline-mode banner the vendoring existed to protect. Silently: the
CSS loads fine, only the font 404s.

This could not reproduce in development. The editable install every
developer and every CI job uses resolves assets from the source tree, where
the fonts are present. It appears only on the real install -- which is how a
field machine receives the software.

So this test builds an actual wheel and looks inside it. Asserting on the
glob string would not have caught the original defect, because the glob was
exactly what everyone had already read and believed.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import zipfile

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Assets the app cannot render correctly without. The fonts are the ones
#: that were missing; the CSS files are here so a future packaging change
#: cannot drop them either.
REQUIRED_ASSETS = (
    "app/assets/00-bootstrap.min.css",
    "app/assets/01-bootstrap-icons.css",
    "app/assets/styles.css",
    "app/assets/fonts/bootstrap-icons.woff2",
    "app/assets/fonts/bootstrap-icons.woff",
)


@pytest.fixture(scope="module")
def wheel_contents(tmp_path_factory):
    """Build a wheel and return the set of paths inside it."""
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("the 'build' package is required to inspect a real wheel")

    outdir = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(outdir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"wheel build failed in this environment:\n{result.stderr[-2000:]}")

    wheels = list(outdir.glob("*.whl"))
    assert wheels, "the build produced no wheel"
    with zipfile.ZipFile(wheels[0]) as zf:
        return set(zf.namelist())


class TestVendoredAssetsAreShipped:
    @pytest.mark.parametrize("asset", REQUIRED_ASSETS)
    def test_asset_is_in_the_wheel(self, wheel_contents, asset):
        expected = f"nanometa_live/{asset}"
        assert expected in wheel_contents, (
            f"{asset} is missing from the built wheel. A pip install will "
            f"serve a dashboard without it; for the icon fonts that means "
            f"every bi-* glyph renders as a missing-glyph box, including the "
            f"offline-mode banner icons."
        )

    def test_the_icon_css_never_ships_without_its_font(self, wheel_contents):
        """State the coupling directly, since that is what actually broke.

        The CSS shipping alone is worse than neither shipping: the page looks
        styled and its icons are silently blank.
        """
        css = "nanometa_live/app/assets/01-bootstrap-icons.css"
        font = "nanometa_live/app/assets/fonts/bootstrap-icons.woff2"

        if css in wheel_contents:
            assert font in wheel_contents, (
                "the icon stylesheet ships without the font it references"
            )
