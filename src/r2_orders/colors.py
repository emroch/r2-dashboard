"""Color transforms and the display palettes derived from the measured paints.

The palette in config (loaded from palette.yaml) is the source of truth for the
on-screen colors; here we expose the marker/legend palette (COLOR_DISPLAY) and
derive the tinted window whiskers (WHISKER_HEX).
"""
import colorsys

from .config import COLOR_HEX, REGION_COLOR


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


# COLOR_DISPLAY is the palette used for markers/legend (the palette.yaml hex
# values are already tuned for on-screen legibility); WHISKER_HEX / REGION_WHISKER
# tint the delivery-window whiskers per paint and per region (subtle tinted grey).
COLOR_DISPLAY = {n: h for n, h in COLOR_HEX.items()}
WHISKER_HEX = {n: _whisker_color(h) for n, h in COLOR_HEX.items()}
REGION_WHISKER = {n: _whisker_color(h) for n, h in REGION_COLOR.items()}
