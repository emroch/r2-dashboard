"""Category colors as CSS: one class per colored category, and its mark color.

Data names a category; CSS owns its color (docs/presentation.md, "Theming"). Every
category in dimensions.yaml that has a `color` becomes a class,

    .cat-<dimension>-<slug> { --paint: <its color> }

and every such class also gets

    --mark: oklch(from var(--paint) clamp(var(--mark-lmin), l, var(--mark-lmax)) c h)

A swatch (the chip that identifies a category) draws var(--paint), the true
color. A mark (a bar, a point) draws var(--mark): the same hue and chroma, with
the lightness clamped into the theme's range from theme.yaml, so a pale paint on
the white card or a dark one on the dark card stays visible. Delivery stages are
the same mark at the stage opacities (--a-delivered/-scheduled/-vin/-wait).

Accents that don't name a category (the build front's line and band) are CSS
variables too, --cadence-<name> from palette.yaml; a spec refers to one as
"var:cadence-front".

Browsers without relative color syntax (before Safari 18) get the clamped colors
precomputed here instead, per theme, in an @supports block.

A component refers to a category as "<dimension>:<value>" (e.g. "color:Launch
Green"); category_class() turns that into the class, and fails on a reference to
a category that has no color, so a typo can't render as an uncolored mark.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import re

from config import CADENCE_COLORS, DIMENSIONS, THEME_CSS

from .colors import mark_hex

_SUPPORTS_RELATIVE = "(color: oklch(from red l c h))"
_MARK_RULE = ("oklch(from var(--paint) clamp(var(--mark-lmin), l, "
              "var(--mark-lmax)) c h)")


def slug(value: object) -> str:
    """'Launch Green' -> 'launch-green', '20" Black Sand' -> '20-black-sand'."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def colored() -> dict[tuple[str, str], str]:
    """(dimension, value) -> color, for every category that has one."""
    return {(dim, str(c["value"])): c["color"]
            for dim, spec in DIMENSIONS.items()
            for c in spec.get("categories") or [] if "color" in c}


def category_class(ref: str) -> str:
    """'color:Launch Green' -> 'cat-color-launch-green'."""
    dim, sep, value = ref.partition(":")
    if not sep or (dim, value) not in colored():
        raise KeyError("no colored category %r in dimensions.yaml" % ref)
    return "cat-%s-%s" % (dim, slug(value))


def bounds(theme: str) -> tuple[float, float]:
    """(lmin, lmax) of the mark lightness range for 'light' or 'dark'."""
    css = THEME_CSS[theme]
    return float(css["mark-lmin"]), float(css["mark-lmax"])


def category_css() -> str:
    """The page's category stylesheet: paints, the mark rule, and the fallback."""
    cats = colored()
    sel = {k: "." + category_class("%s:%s" % k) for k in cats}
    paints = "\n".join("%s{--paint:%s;}" % (sel[k], h) for k, h in cats.items())
    marks = "%s{--mark:%s;}" % (",".join(sel.values()), _MARK_RULE)
    light, dark = bounds("light"), bounds("dark")
    fallback = "\n".join(
        ["%s{--mark:%s;}" % (sel[k], mark_hex(h, *light)) for k, h in cats.items()]
        + ['html[data-theme="dark"] %s{--mark:%s;}' % (sel[k], mark_hex(h, *dark))
           for k, h in cats.items()])
    accents = ":root{%s}" % "".join("--cadence-%s:%s;" % kv
                                    for kv in CADENCE_COLORS.items())
    return "\n%s\n%s\n%s\n@supports not %s{\n%s\n}\n" % (
        accents, paints, marks, _SUPPORTS_RELATIVE, fallback)
