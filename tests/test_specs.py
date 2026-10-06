"""Tests for the browser-drawn components' specs (render/specs.py, #107): what
Python hands the page's d3 templates.

§10's delivery-vs-VIN scatter carries over what its Plotly figure's tests
checked (test_parsing.py, before #107): one series per paint × wheel in the
page-wide paint order; whiskers only for quoted windows; the build front, its
projection and band as their own layers after the series, with the projection
quoted in VINs to the hundred; date on x, VIN on y.

Run with `python3 tests/test_specs.py` (no pytest needed) or `pytest tests/`.
"""
import json
import os
import re
import sys

import pandas as pd

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from config import AS_OF, COLOR_ORDER


def _orders(n=0, **cols):
    """A cleaned-orders frame with every column the §10 spec reads."""
    base = dict(user=["u%d" % i for i in range(n)], color=["Esker Silver"] * n,
                wheels_short=['21" Liquid Tungsten'] * n,
                interior=["Black Crater Signature"] * n, buylease=["Purchase"] * n,
                state=["IL"] * n, vin_present=[True] * n,
                vin_seq=[1000.0 + 100 * i for i in range(n)],
                delivery_type=["explicit"] * n,
                delivery_est=[pd.Timestamp("2026-07-01") + pd.Timedelta(days=7 * i)
                              for i in range(n)],
                vin_display=["%d" % (1000 + 100 * i) for i in range(n)],
                order_display=["—"] * n, est_display=["—"] * n)
    base["delivery_min"] = list(base["delivery_est"])
    base["delivery_max"] = list(base["delivery_est"])
    base.update(cols)
    return pd.DataFrame(base)


def _ramp(weeks=13, per_week=8, rate=150.0):
    """Firm-dated deliveries whose build front rises steadily, so the cadence
    model has a front and a projection to draw."""
    from test_parsing import _cadence_input
    d = _cadence_input(rate=rate, weeks=weeks, per_week=per_week)
    n = len(d)
    extra = _orders(n)
    for c in ("user", "color", "wheels_short", "interior", "buylease", "state",
              "vin_display", "order_display", "est_display"):
        d[c] = extra[c].values
    return d


def test_series_follow_the_paint_order_then_the_wheels():
    from render.specs import delivery_vs_vin
    plan = [(COLOR_ORDER[2], 5), (COLOR_ORDER[1], 3), (COLOR_ORDER[0], 1)]
    colors = [p for p, k in plan for _ in range(k)]
    wheels = ['21" Liquid Tungsten', '20" Black Sand'] * 5
    df = _orders(len(colors), color=colors, wheels_short=wheels[:len(colors)])
    spec, _ = delivery_vs_vin(df)
    paints = []
    for s in spec["series"]:
        paint = s["color"].split(":", 1)[1]
        if paint not in paints:
            paints.append(paint)
    assert paints == [COLOR_ORDER[2], COLOR_ORDER[1], COLOR_ORDER[0]], paints
    # Within a paint, the wheels keep dimensions.yaml's order (ascending size).
    first = [s["shape"] for s in spec["series"] if s["color"].endswith(COLOR_ORDER[2])]
    assert first == ['wheels:20" Black Sand', 'wheels:21" Liquid Tungsten'], first


def test_whiskers_only_for_a_quoted_window():
    from render.specs import delivery_vs_vin
    df = _orders(2)
    df.loc[1, "delivery_type"] = "window"
    df.loc[1, "delivery_min"] = df.loc[1, "delivery_est"] - pd.Timedelta(days=7)
    df.loc[1, "delivery_max"] = df.loc[1, "delivery_est"] + pd.Timedelta(days=7)
    spec, _ = delivery_vs_vin(df)
    pts = spec["series"][0]["points"]
    assert pts[0]["lo"] is None and pts[0]["hi"] is None, "a firm date has no window"
    assert pts[1]["lo"] < pts[1]["x"] < pts[1]["hi"]
    assert pts[0]["firm"] and not pts[1]["firm"]


def test_points_reconcile_with_everything_left_out():
    from render.aggregates import cohort_sizes, reconcile
    from render.specs import delivery_vs_vin
    df = _orders(5, price=[None] * 5, lat=[None] * 5)
    df.loc[1, "vin_present"] = False
    df.loc[2, "delivery_est"] = pd.NaT
    df.loc[3, "color"] = ""
    _, agg = delivery_vs_vin(df)
    assert agg.counted == 2
    assert agg.excluded == {"no VIN": 1, "no delivery estimate": 1,
                            "paint or wheels not reported": 1}
    reconcile([agg], cohort_sizes(df))


def test_build_front_layers_follow_the_series_and_quote_vins_to_the_hundred():
    from render.specs import delivery_vs_vin
    spec, _ = delivery_vs_vin(_ramp())
    kinds = [(layer["type"], (layer.get("name") or layer["label"]).split(" ·")[0])
             for layer in spec["layers"]]
    assert kinds == [("line", "Build front (observed)"), ("band", "Likely range"),
                     ("line", "Projected"), ("rule", "Today")], kinds
    proj = spec["layers"][2]
    assert proj["dash"] and proj["name"].startswith("Projected · ≈ ")
    assert len(proj["tips"]) == len(proj["points"])
    for tip in proj["tips"]:
        found = re.findall(r"\d[\d,]{2,}", " ".join(tip))
        nums = [int(n.replace(",", "")) for n in found]
        assert nums and all(n % 100 == 0 for n in nums), tip
    assert all("day" not in " ".join(t) for t in proj["tips"]), "VINs, not days"
    band = spec["layers"][1]
    assert all(lo <= hi for _, lo, hi in band["points"])
    # The front, its projection and band are one legend entry, toggled together.
    assert {layer.get("group") for layer in spec["layers"][:3]} == {"Build front"}
    assert "group" not in spec["layers"][3]


def test_domains_are_fixed_over_everything_drawn():
    from render.specs import delivery_vs_vin
    spec, _ = delivery_vs_vin(_ramp())
    assert spec["x"]["type"] == "date" and spec["y"]["type"] == "linear"
    x0, x1 = (pd.Timestamp(v) for v in spec["x"]["domain"])
    y0, y1 = spec["y"]["domain"]
    assert x0 <= AS_OF <= x1, "the today line is inside the x domain"
    for s in spec["series"]:
        for p in s["points"]:
            assert x0 <= pd.Timestamp(p["x"]) <= x1 and y0 <= p["y"] <= y1
    for layer in spec["layers"]:
        for pt in layer.get("points", []):
            assert x0 <= pd.Timestamp(pt[0]) <= x1
            assert all(y0 <= v <= y1 for v in pt[1:]), layer.get("name")


def test_specs_name_colors_never_hex():
    from render.specs import delivery_vs_vin
    spec, _ = delivery_vs_vin(_ramp())
    text = json.dumps(spec)
    assert not re.search(r"#[0-9a-fA-F]{6}\b", text)
    refs = {s["color"] for s in spec["series"]} | {
        layer["color"] for layer in spec["layers"] if layer.get("color")}
    assert all(r.startswith(("color:", "var:")) for r in refs), refs


def test_the_mounted_component_has_a_no_js_table_of_every_point():
    from config import COMPONENTS
    from render.components import mount
    from render.specs import delivery_vs_vin
    df = _orders(3)
    spec, agg = delivery_vs_vin(df)
    html = mount("c-delivery-vs-vin", "delivery-vs-vin",
                 COMPONENTS["delivery-vs-vin"], spec, agg)
    assert 'data-chart="delivery-vs-vin" data-template="scatter"' in html
    assert html.startswith('<figure class="r2c r2c-wide"'), "a chart spans the grid"
    assert html.count("<tr>") == 1 + 3, "a header row and one row per point"
    assert "3 orders with both a VIN and a delivery estimate." in html


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
