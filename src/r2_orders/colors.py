"""Color transforms and the display palettes derived from the measured paints.

The measured COLOR_HEX values in config remain the source of truth; here we
brighten them for on-screen legibility (COLOR_DISPLAY) and tint the window
whiskers (WHISKER_HEX).
"""
import colorsys

from .config import COLOR_BOOST_PARAMS, COLOR_HEX


def _hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _rgb_to_hex(r, g, b):
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _boost_color(h, sat_mul=1.6, sat_add=0.15, l_gamma=0.6, l_max=0.95):
    """On-screen enhancement of a measured paint (hue preserved). Lifts dark
    colors and boosts saturation so the muted, near-dark paints separate; the
    additive term is skipped for true greys so they stay neutral."""
    r, g, b = _hex_to_rgb(h)
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = min(l_max, light ** l_gamma)
    sat = min(0.9, sat * sat_mul + (sat_add if sat > 0.08 else 0.0))
    return _rgb_to_hex(*colorsys.hls_to_rgb(hue, light, sat))


def _whisker_color(h, light=0.52, sat=0.20):
    """Medium grey with a slight tint of the paint, so window whiskers stay
    visible on white while still keying to their color."""
    r, g, b = _hex_to_rgb(h)
    hue, _, s = colorsys.rgb_to_hls(r, g, b)
    return _rgb_to_hex(*colorsys.hls_to_rgb(hue, light, sat if s > 0.06 else 0.0))


# Display palettes derived from (and honoring) the measured colors above:
# COLOR_DISPLAY brightens markers/legend for legibility; WHISKER_HEX tints the
# window whiskers. The measured COLOR_HEX values remain the source of truth.
# COLOR_DISPLAY = {n: _boost_color(h, **COLOR_BOOST_PARAMS.get(n, {}))
#                  for n, h in COLOR_HEX.items()}
COLOR_DISPLAY = {n: h for n, h in COLOR_HEX.items()}
WHISKER_HEX = {n: _whisker_color(h) for n, h in COLOR_HEX.items()}
