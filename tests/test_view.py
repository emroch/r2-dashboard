"""Tests for the presentation layer's scaffolding (#105): the section registry,
category CSS and mark contrast, the component frame, and reconciled aggregates.

Run with `python3 tests/test_view.py` (no pytest needed) or `pytest tests/`.
"""
import os
import re
import sys

import pandas as pd

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from config import DIMENSIONS, SECTIONS_CONF, THEME_CSS

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
        assert names == entry["charts"], title
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
    from render.categories import category_class, category_css
    css = category_css()
    refs = _colored_refs()
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
    # bounds in theme.yaml are set so that every category color clears it.
    from render.categories import bounds, colored
    from render.colors import contrast_ratio, mark_hex
    worst = {}
    for theme in ("light", "dark"):
        card = THEME_CSS[theme]["card-bg"]
        for (dim, value), hexv in colored().items():
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
    # ...as marks, both clear 3:1 on both cards.
    for hexv in (white, black):
        assert contrast_ratio(mark_hex(hexv, *bounds("light")), light) >= 3
        assert contrast_ratio(mark_hex(hexv, *bounds("dark")), dark) >= 3
    # The clamp only moves lightness: Midnight keeps its hint of blue.
    _, c0, h0 = hex_to_oklch(black)
    _, c1, h1 = hex_to_oklch(mark_hex(black, *bounds("dark")))
    assert abs(h1 - h0) < 3 and c1 > 0.5 * c0


# --- The component frame (render/components.py) --------------------------------

def test_frame_carries_title_summary_n_caveats_and_table():
    from render.components import Table, frame
    html = frame("c-test", "Paint <mix>", "<div class='body'></div>",
                 summary="Launch Green & co.", n=1234, dims=["region", "state"],
                 notes=["Extra note."],
                 table=Table(["Paint", "Orders"], [["Midnight", 18]]))
    assert html.startswith('<figure class="r2c" id="c-test" role="group" '
                           'aria-labelledby="c-test-t">')
    assert '<figcaption id="c-test-t">Paint &lt;mix&gt;</figcaption>' in html
    assert "Launch Green &amp; co." in html and "<div class='body'></div>" in html
    assert "n = 1,234" in html
    # region and state share a caveat: shown once, then state's small-n note.
    assert html.count("Location is self-reported.") == 1
    assert DIMENSIONS["state"]["small_n"]["note"] in html and "Extra note." in html
    assert '<table id="c-test-data">' in html and "<td>Midnight</td>" in html
    assert 'data-table="c-test-data" data-file="c-test.csv" hidden' in html


def test_frame_leaves_out_what_it_was_not_given():
    from render.components import frame
    html = frame("c-x", "T", "")
    assert "r2c-summary" not in html and "r2c-meta" not in html
    assert "<details" not in html


# --- Aggregates (render/aggregates.py) -----------------------------------------

def _orders(**cols):
    n = len(next(iter(cols.values())))
    base = {"vin_present": [False] * n, "price": [None] * n, "lat": [None] * n}
    base.update(cols)
    return pd.DataFrame(base)


def test_counts_omit_excludes_blanks_and_orders_by_count_then_list():
    from render.aggregates import counts
    df = _orders(color=["Midnight", "Launch Green", None, "Midnight", "",
                        "Catalina Cove", "Launch Green"])
    a = counts(df, "color")
    assert [(c["value"], c["n"]) for c in a.cells] == [
        ("Launch Green", 2), ("Midnight", 2), ("Catalina Cove", 1)]
    assert a.excluded == {"not reported": 2} and a.counted == 5
    assert a.cells[0]["ref"] == "color:Launch Green" and a.cells[0]["known"]


def test_counts_bucket_and_category_policies_keep_blanks_as_cells():
    from render.aggregates import counts
    a = counts(_orders(region=["West", None, "West"]), "region")
    assert [(c["label"], c["n"]) for c in a.cells] == [("West", 2), ("Unknown", 1)]
    assert a.excluded == {}
    b = counts(_orders(delivery_type=["window", None, "explicit"]), "delivery_type")
    # fixed order, and the blank became the `unknown` category with its label.
    assert [(c["label"], c["n"]) for c in b.cells] == [
        ("Firm date", 1), ("Relative window", 1), ("No date given", 1)]


def test_counts_keeps_an_unlisted_value_and_marks_it_unknown():
    from render.aggregates import counts
    from render.view import View, unknown_categories
    a = counts(_orders(color=["Launch Green", "Compass Yellow"]), "color")
    new = [c for c in a.cells if not c["known"]]
    assert [(c["value"], c["ref"]) for c in new] == [("Compass Yellow", None)]
    assert unknown_categories(View(aggregates=[a])) == ["color: Compass Yellow"]


def test_counts_over_a_cohort_and_boolean_dimensions():
    from render.aggregates import cohort_sizes, counts
    df = _orders(delivered_inferred=[True, False, True],
                 vin_present=[True, True, False])
    a = counts(df, "delivered", cohort="vin_assigned")
    assert [(c["label"], c["n"]) for c in a.cells] == [
        ("Delivered (est.)", 1), ("Awaiting delivery", 1)]
    assert cohort_sizes(df)["vin_assigned"] == 2


def test_reconcile_passes_when_cells_and_exclusions_add_up():
    from render.aggregates import cohort_sizes, counts, reconcile
    df = _orders(color=["Midnight", None, "Borealis"], region=["West", None, None])
    reconcile([counts(df, "color"), counts(df, "region")], cohort_sizes(df))


def test_reconcile_fails_on_an_aggregate_that_loses_rows():
    from render.aggregates import Aggregate, ReconcileError, reconcile
    lossy = Aggregate("answered only", "orders",
                      [{"value": "a", "label": "a", "n": 2, "ref": None,
                        "known": True}])
    stray = Aggregate("stray", "no such cohort", [])
    try:
        reconcile([lossy, stray], {"orders": 3})
    except ReconcileError as exc:
        msg = str(exc)
        assert "answered only: 2 counted + 0 excluded = 2" in msg and "is 3" in msg
        assert "unknown cohort 'no such cohort'" in msg
    else:
        raise AssertionError("a lossy aggregate reconciled")


def test_view_build_reconciles_every_dimension_and_publishes_no_components_yet():
    from render.view import build, view_json
    cols = {spec["column"]: [None, None] for spec in DIMENSIONS.values()}
    cols["r1_owner_effective"] = cols.pop("r1_owner")
    cols.update(color=["Midnight", "Midnight"], state=["IL", "WA"])
    view = build(_orders(**cols))
    assert {a.dim for a in view.aggregates} == set(DIMENSIONS)
    assert view_json(view) == {"version": 1, "components": {}}


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
