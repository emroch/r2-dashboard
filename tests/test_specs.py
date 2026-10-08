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
                delivered_inferred=[False] * n,
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
    spec, _, _ = delivery_vs_vin(df)
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
    spec, _, _ = delivery_vs_vin(df)
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
    _, agg, _ = delivery_vs_vin(df)
    assert agg.counted == 2
    assert agg.excluded == {"no VIN": 1, "no delivery estimate": 1,
                            "paint or wheels not reported": 1}
    reconcile([agg], cohort_sizes(df))


def test_build_front_layers_follow_the_series_and_quote_vins_to_the_hundred():
    from render.specs import delivery_vs_vin
    spec, _, _ = delivery_vs_vin(_ramp())
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
    spec, _, _ = delivery_vs_vin(_ramp())
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
    spec, _, _ = delivery_vs_vin(_ramp())
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
    spec, agg, table = delivery_vs_vin(df)
    html = mount("c-delivery-vs-vin", "delivery-vs-vin",
                 COMPONENTS["delivery-vs-vin"], spec, table, agg)
    assert 'data-chart="delivery-vs-vin" data-template="scatter"' in html
    assert html.startswith('<figure class="r2c r2c-wide"'), "a chart spans the grid"
    assert html.count("<tr>") == 1 + 3, "a header row and one row per point"
    assert "3 orders with both a VIN and a delivery estimate." in html


# --- timeseries specs (§5, §6, §7's coverage, §10's cadence) ------------------------

def _sizes(df, resv):
    from render.aggregates import cohort_sizes
    sizes = cohort_sizes(df.assign(price=None, lat=None))
    sizes["orders+reservations"] = len(df) + len(resv)
    return sizes


def test_reservations_by_week_stack_on_monday_weeks_and_clip_the_spike():
    from render.aggregates import reconcile
    from render.specs import reservations_by_week
    # A reveal week far taller than the rest, then a trickle; one order and one
    # reservation without a date.
    spike = [pd.Timestamp("2024-03-07")] * 400
    df = _orders(len(spike) + 3, resv_date=spike + [pd.Timestamp("2024-04-10"),
                                                    pd.Timestamp("2024-04-12"), pd.NaT])
    resv = pd.DataFrame({"resv_date": [pd.Timestamp("2024-03-08")] * 100
                         + [pd.Timestamp("2024-04-11")] * 9 + [pd.NaT]})
    spec, agg, (heads, rows) = reservations_by_week(df, resv)
    assert spec["template"] == "timeseries"
    assert [s["name"] for s in spec["series"]] == ["Converted", "Outstanding"]
    weeks = [v[0] for v in spec["series"][0]["values"]]
    assert weeks == ["2024-03-04", "2024-03-11", "2024-03-18", "2024-03-25",
                     "2024-04-01", "2024-04-08"], "every Monday week (running totals)"
    assert [v[1] for v in spec["series"][1]["values"]] == [100, 0, 0, 0, 0, 9]
    # The cumulative view has its own fixed domain: every dated reservation.
    assert spec["toggles"] == {"cumulative": True}
    assert spec["y"]["cumulative"]["domain"][1] == 511 * 1.05
    # 500 in the spike week against 11 in the next: the axis clips just above it.
    assert spec["y"]["clip"] == spec["y"]["domain"][1] == 20
    assert heads == ["Week of", "Converted", "Outstanding", "Total", "Running total"]
    assert rows[0] == ["2024-03-04", 400, 100, 500, 500]
    assert rows[-1] == ["2024-04-08", 2, 9, 11, 511]
    reconcile([agg], _sizes(df, resv))
    assert agg.excluded == {"order without a reservation date": 1,
                            "reservation without a date": 1}


def test_orders_by_week_split_each_cohort_by_its_stage_today():
    from render.aggregates import reconcile
    from render.specs import orders_by_week
    df = _orders(4, order_date=[pd.Timestamp("2026-06-15")] * 3 + [pd.NaT],
                 delivered_inferred=[True, False, None, True],
                 delivery_type=["explicit", "explicit", "window", "window"],
                 vin_present=[True, True, False, True])
    spec, agg, (heads, _) = orders_by_week(df)
    assert [(s["name"], s["stage"]) for s in spec["series"]] == [
        ("Delivered", "delivered"), ("Delivery scheduled", "scheduled"),
        ("With a VIN", "vin"), ("Waiting for a VIN", "wait")], "one color, by stage"
    assert [v[1] for s in spec["series"] for v in s["values"]] == [1, 1, 0, 1]
    assert heads[:5] == ["Week of", "Delivered", "Delivery scheduled", "With a VIN",
                         "Waiting for a VIN"]
    reconcile([agg], _sizes(df, pd.DataFrame({"resv_date": []})))
    assert agg.excluded == {"no order date": 1}


def test_fulfilment_over_time_ends_at_the_readouts_and_counts_dated_events():
    from render.aggregates import reconcile, stage_counts
    from render.specs import fulfilment_by_week
    d = pd.Timestamp
    # a: ordered wk1, VIN wk2, scheduled wk3, delivered wk4. b: ordered wk2, VIN
    # with no recorded date. c: ordered wk3, nothing yet. z: no order date.
    df = _orders(4, user=["a", "b", "c", "z"],
                 order_date=[d("2026-06-01"), d("2026-06-08"), d("2026-06-15"), pd.NaT],
                 vin_present=[True, True, False, True],
                 vin_assigned=[d("2026-06-09"), pd.NaT, pd.NaT, d("2026-06-10")],
                 delivery_type=["explicit", "window", "unknown", "explicit"],
                 delivery_scheduled=[d("2026-06-16"), pd.NaT, pd.NaT, pd.NaT],
                 delivery_est=[d("2026-06-23"), d("2026-12-01"), pd.NaT,
                               d("2026-06-25")],
                 delivered_inferred=[True, False, False, True])
    spec, agg, _ = fulfilment_by_week(df)
    level = {s["stage"]: [v[1] for v in s["values"]] for s in spec["series"]}
    assert all(s["view"] == "cumulative" for s in spec["series"])
    assert all(line["view"] == "weekly" for line in spec["lines"])
    assert spec["toggles"] == {"cumulative": True, "default": "cumulative"}
    # Week by week, a moves up the stages; b's undated VIN shows on the last week.
    assert level["wait"][:4] == [1, 1, 2, 2] and level["vin"][:4] == [0, 1, 0, 0]
    assert level["scheduled"][:4] == [0, 0, 1, 0]
    assert level["delivered"][:4] == [0, 0, 0, 1]
    dated = df[df["order_date"].notna()]
    today = {c["value"]: c["n"] for c in stage_counts(dated).cells}
    assert {st: v[-1] for st, v in level.items()} == today, "the last column is today"
    events = {line["name"]: sum(p[1] for p in line["points"]) for line in spec["lines"]}
    assert events == {"Orders placed": 3, "VINs assigned": 1, "Deliveries scheduled": 1,
                      "Deliveries made": 1}, "dated events of dated orders only"
    reconcile([agg], _sizes(df, pd.DataFrame({"resv_date": []})))
    assert agg.excluded == {"no order date": 1}


def test_deliveries_by_week_stack_firm_first_and_leave_out_no_estimate():
    from render.aggregates import reconcile
    from render.specs import deliveries_by_week
    df = _orders(4, delivery_type=["window", "explicit", "explicit", "unknown"],
                 delivery_est=[pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-02"),
                               pd.Timestamp("2026-07-09"), pd.NaT])
    spec, agg, _ = deliveries_by_week(df)
    assert [s["color"] for s in spec["series"]] == ["delivery_type:explicit",
                                                     "delivery_type:window"]
    assert [v[1] for v in spec["series"][0]["values"]] == [1, 1]
    assert spec["rules"][0]["label"] == "Today"
    assert "clip" not in spec["y"], "no spike, no clip"
    reconcile([agg], _sizes(df, pd.DataFrame({"resv_date": []})))
    assert agg.excluded == {"no delivery estimate": 1}


def test_build_cadence_is_a_line_over_the_firm_dated_vins():
    from render.aggregates import reconcile
    from render.specs import build_cadence
    df = _ramp()
    spec, agg, (_, rows) = build_cadence(df)
    line = spec["lines"][0]
    assert spec["series"] == [] and line["color"] == "var:cadence-front"
    assert len(line["points"]) == len(rows) > 3
    assert 100 < line["points"][-1][1] < 200, "about the 150 VINs/day ramp"
    assert spec["y"]["domain"][0] == 0
    reconcile([agg], _sizes(df, pd.DataFrame({"resv_date": []})))
    assert agg.meta["rate"].isdigit()


def test_every_mounted_spec_names_colors_never_hex():
    import json
    import re
    from render.specs import (build_cadence, deliveries_by_week, delivery_latency,
                              dest_vs_delivery, latency_coverage, orders_by_week,
                              geo_demand, reservations_by_week, vin_by_config,
                              vin_vs_order)
    df = _orders(5, order_date=[pd.Timestamp("2026-06-15")] * 5,
                 resv_date=[pd.Timestamp("2024-03-07")] * 5, trim=["Performance"] * 5,
                 region=["Midwest"] * 5, dist_mi=[11.0] * 5)
    resv = pd.DataFrame({"resv_date": [pd.Timestamp("2024-03-08")]})
    for spec in (reservations_by_week(df, resv)[0], orders_by_week(df)[0],
                 deliveries_by_week(df)[0], delivery_latency(df)[0],
                 latency_coverage(df)[0], build_cadence(_ramp())[0],
                 vin_vs_order(df)[0], vin_by_config(df)[0], dest_vs_delivery(df)[0],
                 geo_demand(df, resv.assign(state="IL"))[0]):
        assert not re.search(r"#[0-9a-fA-F]{6}\b", json.dumps(spec)), spec["title"]


def test_vin_vs_order_plots_order_date_against_vin_and_reconciles():
    from render.aggregates import cohort_sizes, reconcile
    from render.specs import vin_vs_order
    df = _orders(4, order_date=[pd.Timestamp("2026-06-15")] * 4,
                 trim=["Performance"] * 4,
                 price=[None] * 4, lat=[None] * 4)
    df.loc[1, "vin_present"] = False
    df.loc[2, "order_date"] = pd.NaT
    spec, agg, (_, rows) = vin_vs_order(df)
    assert agg.excluded == {"no VIN": 1, "no order date": 1,
                            "paint or wheels not reported": 0}
    reconcile([agg], cohort_sizes(df))
    p = spec["series"][0]["points"][0]
    assert (p["x"], p["y"]) == ("2026-06-15", 1000) and len(rows) == 2
    x0, x1 = (pd.Timestamp(v) for v in spec["x"]["domain"])
    assert x0 <= AS_OF <= x1


def test_vin_by_config_rows_group_by_trim_then_paint_order():
    from render.aggregates import cohort_sizes, reconcile
    from render.specs import vin_by_config
    paints = [COLOR_ORDER[1]] * 3 + [COLOR_ORDER[0]] * 2 + [COLOR_ORDER[2]]
    df = _orders(6, color=paints, trim=["Performance"] * 6, price=[None] * 6,
                 lat=[None] * 6)
    df.loc[5, "interior"] = ""            # its configuration isn't fully reported
    spec, agg, _ = vin_by_config(df)
    reconcile([agg], cohort_sizes(df))
    assert agg.excluded == {"no VIN": 0, "configuration not reported": 1}
    rows = spec["y"]["rows"]
    # The most-ordered paint's row first, then the next.
    assert [r.split(" · ")[1] for r in rows] == [COLOR_ORDER[1], COLOR_ORDER[0]], rows
    assert spec["y"]["type"] == "rows" and spec["x"]["type"] == "linear"
    assert agg.meta["rows"] == 2
    for s in spec["series"]:
        for p in s["points"]:
            row = rows.index(" · ".join(["Performance", s["color"].split(":", 1)[1],
                                         '21" AS', "Black Crater Sig"]))
            assert abs(p["y"] - row) < 0.2, (p["y"], row)


def test_dest_vs_delivery_rows_run_farthest_first_with_today():
    from render.aggregates import cohort_sizes, reconcile
    from render.specs import dest_vs_delivery
    df = _orders(4, state=["IL", "CA", "CA", "TX"],
                 region=["Midwest", "West", "West", "South"],
                 dist_mi=[11.0, 1800.0, 1800.0, None], price=[None] * 4, lat=[None] * 4)
    df.loc[1, "delivery_est"] = pd.NaT
    spec, agg, _ = dest_vs_delivery(df)
    reconcile([agg], cohort_sizes(df))
    assert agg.excluded == {"no delivery estimate": 1, "no known destination": 1}
    assert spec["y"]["rows"] == ["CA (1800 mi)", "IL (11 mi)"]
    assert [s["color"] for s in spec["series"]] == ["region:West", "region:Midwest"]
    assert spec["layers"][-1]["type"] == "rule" and spec["toggles"]["whiskers"]


def test_geo_demand_maps_us_states_and_counts_what_it_leaves_out():
    from render.aggregates import cohort_sizes, reconcile
    from render.specs import geo_demand
    df = _orders(4, state=["CA", "CA", "BC", "ZZ"], price=[None] * 4, lat=[None] * 4,
                 delivered_inferred=[True, False, False, False])
    resv = pd.DataFrame({"state": ["CA", "WA", "BC"]})
    spec, agg, _ = geo_demand(df, resv)
    reconcile([agg], cohort_sizes(df))
    assert agg.excluded == {"outside the US (not mapped)": 1, "no known state": 1}
    assert agg.meta["left"] == "1 order and 1 reservation"
    ca = spec["states"]["CA"]
    assert (ca["orders"], ca["vin"], ca["demand"], ca["delivered"]) == (2, 2, 3, 0.5)
    # Reservations alone still put a state on the demand map, with no orders.
    assert spec["states"]["WA"]["orders"] == 0 and spec["states"]["WA"]["demand"] == 1
    assert "BC" not in spec["states"] and ca["small"]


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
