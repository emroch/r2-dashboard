"""Color transforms and the display palettes derived from the measured paints.

The palette in config (loaded from palette.yaml) is the source of truth for the
on-screen colors; here we expose the marker/legend palette (COLOR_DISPLAY) and
derive the tinted window whiskers (WHISKER_HEX).
"""
import colorsys

from .config import COLOR_HEX


def _hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _rgb_to_hex(r, g, b):
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _whisker_color(h, light=0.52, sat=0.20):
    """Medium grey with a slight tint of the paint, so window whiskers stay
    visible on white while still keying to their color."""
    r, g, b = _hex_to_rgb(h)
    hue, _, s = colorsys.rgb_to_hls(r, g, b)
    return _rgb_to_hex(*colorsys.hls_to_rgb(hue, light, sat if s > 0.06 else 0.0))


# COLOR_DISPLAY is the palette used for markers/legend (the palette.yaml hex
# values are already tuned for on-screen legibility); WHISKER_HEX tints the
# delivery-window whiskers per paint.
COLOR_DISPLAY = {n: h for n, h in COLOR_HEX.items()}
WHISKER_HEX = {n: _whisker_color(h) for n, h in COLOR_HEX.items()}
