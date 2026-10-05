"""Color transforms and the display palettes derived from the measured paints.

The palette in config (loaded from dimensions.yaml) is the source of truth for the
on-screen colors. Two kinds of derived color live here:

  * for the Plotly charts: the marker/legend palette (COLOR_DISPLAY) and the
    tinted window whiskers (WHISKER_HEX), in HLS. They go with Plotly (#111).
  * for the presentation layer's CSS (docs/presentation.md, "Theming"): OKLCH,
    the perceptual space the page's mark rule works in. A category keeps its
    true color for its swatch; its MARK is the same hue and chroma with the
    lightness clamped to a per-theme range, so it can't sit too close to the
    surface. Browsers do that clamp themselves with relative color syntax; the
    functions here compute the same result for the fallback CSS and for the
    contrast tests.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import colorsys
import math

from config import COLOR_HEX, REGION_COLOR


def _hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _rgb_to_hex(r, g, b):
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _whisker_color(h, light=0.56, sat=0.14):
    """Light-medium grey with just a hint of the source hue, so window whiskers
    stay subtle (a tinted grey) yet still key to their series on white or dark."""
    r, g, b = _hex_to_rgb(h)
    hue, _, s = colorsys.rgb_to_hls(r, g, b)
    return _rgb_to_hex(*colorsys.hls_to_rgb(hue, light, sat if s > 0.06 else 0.0))


# COLOR_DISPLAY is the palette used for markers/legend (the dimensions.yaml hex
# values are already tuned for on-screen legibility); WHISKER_HEX / REGION_WHISKER
# tint the delivery-window whiskers per paint and per region (subtle tinted grey).
COLOR_DISPLAY = dict(COLOR_HEX)
WHISKER_HEX = {n: _whisker_color(h) for n, h in COLOR_HEX.items()}
REGION_WHISKER = {n: _whisker_color(h) for n, h in REGION_COLOR.items()}


# --- OKLCH (Björn Ottosson's OKLab, in polar form) ------------------------------

Rgb = tuple[float, float, float]


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_oklch(h: str) -> tuple[float, float, float]:
    """#rrggbb -> (L, C, H): lightness 0-1, chroma, hue in degrees."""
    r, g, b = (_linear(c) for c in _hex_to_rgb(h))
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lum = 0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc
    a = 1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc
    bb = 0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc
    return lum, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _oklch_to_linear(lum: float, c: float, hue: float) -> Rgb:
    a, b = c * math.cos(math.radians(hue)), c * math.sin(math.radians(hue))
    lc = (lum + 0.3963377774 * a + 0.2158037573 * b) ** 3
    mc = (lum - 0.1055613458 * a - 0.0638541728 * b) ** 3
    sc = (lum - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
            -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
            -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc)


def _in_gamut(rgb: Rgb) -> bool:
    return all(-1e-7 <= c <= 1 + 1e-7 for c in rgb)


def oklch_to_hex(lum: float, c: float, hue: float) -> str:
    """(L, C, H) -> #rrggbb. A color outside sRGB keeps its lightness and hue and
    loses chroma until it fits, which is how CSS maps a relative color that the
    clamp pushed out of gamut (a dark saturated paint lifted to L 0.70)."""
    rgb = _oklch_to_linear(lum, c, hue)
    if not _in_gamut(rgb):
        lo, hi = 0.0, c
        for _ in range(40):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_linear(lum, mid, hue)):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_to_linear(lum, lo, hue)
    r, g, b = (_gamma(min(max(x, 0.0), 1.0)) for x in rgb)
    return _rgb_to_hex(r, g, b)


def mark_hex(h: str, lmin: float, lmax: float) -> str:
    """The mark color for a category color: the CSS rule
    oklch(from <h> clamp(lmin, l, lmax) c h), computed."""
    lum, c, hue = hex_to_oklch(h)
    return oklch_to_hex(min(max(lum, lmin), lmax), c, hue)


def contrast_ratio(h1: str, h2: str) -> float:
    """WCAG 2 contrast ratio between two #rrggbb colors (1 to 21). Non-text
    marks are held to 3:1 (WCAG 1.4.11)."""
    def y(h: str) -> float:
        r, g, b = (_linear(c) for c in _hex_to_rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((y(h1), y(h2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
