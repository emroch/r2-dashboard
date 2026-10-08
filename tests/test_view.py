"""Tests for the presentation layer (#105): the section and component registries,
category CSS and mark contrast, the component frame, and the view build.
Aggregates and the take-rate component are in test_aggregates.py.

Run with `python3 tests/test_view.py` (no pytest needed) or `pytest tests/`.
"""
import os
import re
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from config import DIMENSIONS, SECTIONS_CONF, THEME_CSS

with open(os.path.join(_SRC, "templates", "styles.css")) as _fh:
    CSS_TEXT = _fh.read()

# --- The section registry (src/conf/sections.yaml) -----------------------------


def test_every_section_names_known_charts_and_renders_in_order():
    from render.page import _BUILDERS, SECTIONS
    assert len(SECTIONS) == len(SECTIONS_CONF) > 0
    titles = [e["title"] for e in SECTIONS_CONF]
    assert len(set(titles)) == len(titles), "duplicate section titles"
    for entry, (title, desc, builders) in zip(SECTIONS_CONF, SECTIONS):
        assert title == entry["title"] and desc.strip(), title
        names = [b.__name__ for b in
                 (builders if isinstance(builders, tuple) else (builders,))]
        assert names == entry.get("charts", []), title
        assert names or entry.get("components"), "%s draws nothing" % title
        assert all(n in _BUILDERS for n in names), title


def test_a_section_naming_an_unknown_chart_fails_loudly():
    from render.page import _section
    try:
        _section({"title": "X", "desc": "d", "charts": ["fig_nope"]})
    except LookupError as exc:
        assert "fig_nope" in str(exc)
    else:
        raise AssertionError("an unknown chart name was accepted")


# --- Category CSS and marks (render/categories.py) -----------------------------

def _colored_refs():
    return ["%s:%s" % (d, c["value"]) for d, spec in DIMENSIONS.items()
            for c in spec.get("categories") or [] if "color" in c]


def test_every_colored_category_has_a_class_with_its_true_paint():
    from render.categories import category_class, category_css, true_color
    css = category_css()
    refs = _colored_refs()
    true = {"%s:%s" % k for k in true_color()}
    assert "color:Midnight" in true and "wheels:20\" Black Sand" not in true
    # Every category keeps a clamped mark (take-rate stages fade it); a mix bar
    # draws a true-color one from --paint (.mark-true).
    assert ".mark.mark-true{background:var(--paint);}" in CSS_TEXT
    assert len(refs) > 20
    for ref in refs:
        dim, _, value = ref.partition(":")
        hexv = next(c["color"] for c in DIMENSIONS[dim]["categories"]
                    if str(c["value"]) == value)
        cls = category_class(ref)
        assert re.fullmatch(r"cat-[a-z0-9_]+-[a-z0-9-]+", cls), cls
        assert ".%s{--paint:%s;}" % (cls, hexv) in css, ref
        # The fallback mark exists for both themes.
        assert re.search(r"\n\.%s\{--mark:#[0-9A-F]{6};\}" % cls, css), ref
        assert 'html[data-theme="dark"] .%s{--mark:#' % cls in css, ref


def test_class_names_are_unique_and_bad_references_fail():
    from render.categories import category_class
    classes = [category_class(r) for r in _colored_refs()]
    assert len(set(classes)) == len(classes), "two categories share a class"
    for bad in ("color:Not A Paint", "nodim:Launch Green", "Launch Green",
                "buylease:Purchase"):    # a category without a color
        try:
            category_class(bad)
        except KeyError:
            continue
        raise AssertionError("%r resolved" % bad)


def test_oklch_round_trips_every_palette_color():
    from render.colors import hex_to_oklch, oklch_to_hex
    for spec in DIMENSIONS.values():
        for c in spec.get("categories") or []:
            if "color" in c:
                assert oklch_to_hex(*hex_to_oklch(c["color"])) == c["color"].upper(), c


def test_every_mark_holds_3_to_1_against_the_card_in_both_themes():
    # WCAG 1.4.11: a non-text mark needs 3:1 against what it sits on. The mark
    # bounds in theme.yaml are set so that every category color clears it; a
    # true-color mix segment (paints, cabins) sits in a bar outlined in
    # mark-edge, which must.
    from render.categories import bounds, marked
    from render.colors import contrast_ratio, mark_hex
    worst = {}
    for theme in ("light", "dark"):
        card = THEME_CSS[theme]["card-bg"]
        edge = contrast_ratio(THEME_CSS[theme]["mark-edge"], card)
        assert edge >= 3.0, "%s mark-edge is %.2f:1 on %s" % (theme, edge, card)
        for (dim, value), hexv in marked().items():   # categories and accents
            ratio = contrast_ratio(mark_hex(hexv, *bounds(theme)), card)
            assert ratio >= 3.0, "%s %s:%s mark is %.2f:1 on %s" % (
                theme, dim, value, ratio, card)
            worst[theme] = min(worst.get(theme, 99), ratio)
    assert worst["dark"] > 5, worst


def test_glacier_white_and_midnight_stay_visible_and_true_as_swatches():
    from render.categories import bounds, colored
    from render.colors import contrast_ratio, hex_to_oklch, mark_hex
    paints = colored()
    white, black = paints[("color", "Glacier White")], paints[("color", "Midnight")]
    light, dark = THEME_CSS["light"]["card-bg"], THEME_CSS["dark"]["card-bg"]
    # As swatches (the true color), each nearly vanishes on its own card...
    assert contrast_ratio(white, light) < 1.2
    assert contrast_ratio(black, dark) < 1.5
    # ...and in a mix bar they stay true too (paint is true_color), so what
    # keeps them visible there is the bar's mark-edge border, 3:1 on both cards.
    for theme, card in (("light", light), ("dark", dark)):
        assert contrast_ratio(THEME_CSS[theme]["mark-edge"], card) >= 3
    # Clamped, silver, grey and white would land within a hair of each other on
    # the dark card, and Midnight would lift to a blue-grey: why a mix bar draws
    # paints true.
    silver = paints[("color", "Esker Silver")]
    grey = paints[("color", "Half Moon Grey")]
    lifted = [hex_to_oklch(mark_hex(h, *bounds("dark")))[0]
              for h in (silver, grey, white)]
    assert max(lifted) - min(lifted) < 0.25
    assert hex_to_oklch(mark_hex(black, *bounds("dark")))[0] >= 0.7


# --- The component frame (render/components.py) --------------------------------

def test_frame_carries_title_summary_n_caveats_and_table():
    from render.components import Table, frame
    html = frame("c-test", "Paint <mix>", "<div class='body'></div>",
                 summary="Launch Green & co.", n=1234, dims=["region", "state"],
                 notes=["Extra note."], small_n=["state"],
                 table=Table(["Paint", "Orders"], [["Midnight", 18]]))
    assert html.startswith('<figure class="r2c" id="c-test" role="group" '
                           'aria-labelledby="c-test-t">')
    assert '<figcaption id="c-test-t">Paint &lt;mix&gt;</figcaption>' in html
    assert "Launch Green &amp; co." in html and "<div class='body'></div>" in html
    assert "n = 1,234" in html
    # region and state share a caveat: shown once, then state's small-n note
    # (the frame applies that rule; one that doesn't leaves the note out).
    assert html.count("Location is self-reported.") == 1
    assert DIMENSIONS["state"]["small_n"]["note"] in html and "Extra note." in html
    assert DIMENSIONS["state"]["small_n"]["note"] not in frame(
        "c-x", "All states", "", dims=["state"]), "§13 lists every state"
    assert '<table id="c-test-data">' in html and "<td>Midnight</td>" in html
    assert 'data-table="c-test-data" data-file="c-test.csv" hidden' in html


def test_frame_leaves_out_what_it_was_not_given():
    from render.components import frame
    html = frame("c-x", "T", "")
    assert "r2c-summary" not in html and "r2c-meta" not in html
    assert "<details" not in html


def test_view_build_reconciles_and_renders_every_component():
    import pandas as pd

    from config import COMPONENTS
    from render.view import build, view_json
    from test_aggregates import _orders
    cols = {spec["column"]: [None, None] for spec in DIMENSIONS.values()}
    cols["r1_owner_effective"] = cols.pop("r1_owner")
    cols.update(color=["Midnight", "Midnight"], state=["IL", "WA"],
                r1_model=["", ""], user=["a", "b"], vin_present=[True, False],
                vin_seq=[1200, None], lat=[40.0, None], lon=[-89.0, None],
                region=["Midwest", None], delivery_est=[pd.Timestamp("2026-09-01"),
                                                        pd.NaT],
                delivery_min=[pd.NaT, pd.NaT], delivery_max=[pd.NaT, pd.NaT],
                wheels_short=['21" Liquid Tungsten', None],
                vin_display=["1200", "—"], order_display=["—", "—"],
                est_display=["Sep 01, 2026", "—"], elev_ft=[600.0, None],
                temp_f=[51.0, None], urban_pct=[88.0, None], dist_mi=[11.0, None],
                resv_date=[pd.Timestamp("2024-03-08"), pd.NaT],
                order_date=[pd.Timestamp("2026-06-15"), pd.NaT])
    from test_aggregates import _priced
    cols.update({k: v[:1] + [None] for k, v in _priced([60990.0]).items()})
    view = build(_orders(**cols))
    assert {a.dim for a in view.aggregates} >= set(DIMENSIONS)
    # The summary's Delivery progress readouts are reconciled with the rest.
    assert view.readouts["progress"] in view.aggregates
    assert view.readouts["progress"].counted == 2
    # Everything but the browser-drawn templates is rendered to HTML in Python.
    drawn = ("scatter", "timeseries")
    static = {c for c, sp in COMPONENTS.items() if sp["template"] not in drawn}
    assert set(view.static) == static
    for cid in view.static:
        assert view.render(cid).startswith('<figure class="r2c" id="c-%s"' % cid), cid
    # Browser-drawn components are published as specs, with no colors in them.
    out = view_json(view)
    assert set(out["components"]) == set(COMPONENTS) - static
    import json
    assert not re.search(r"#[0-9a-fA-F]{6}\b", json.dumps(out)), \
        "a spec carries a hex color; it should name a category or a CSS variable"
    scatter = out["components"]["delivery-vs-vin"]
    assert [s["name"] for s in scatter["series"]] == ['Midnight · 21"']
    assert scatter["series"][0]["points"][0]["y"] == 1200


def test_a_section_layout_sets_the_grid_class():
    from render.page import SECTION_LAYOUTS, _LAYOUTS
    assert set(SECTION_LAYOUTS) <= set(_LAYOUTS)
    assert SECTION_LAYOUTS[[e["title"] for e in SECTIONS_CONF].index(
        "Configured price")] == "single"


def test_every_section_component_is_registered():
    from config import COMPONENTS
    named = [c for e in SECTIONS_CONF for c in e.get("components", [])]
    assert named and all(c in COMPONENTS for c in named), named
    assert len(set(named)) == len(named), "a component placed twice"


def _run_all():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        else:
            print("PASS %s" % name)
    print("-" * 40)
    print("%d passed, %d failed (of %d)" % (len(tests) - failed, failed, len(tests)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
