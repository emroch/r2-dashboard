"""House-schema specs for the browser-drawn components (docs/presentation.md).

Each builder turns the cleaned orders into one component's spec: what the chart
library draws, already counted and laid out in Python, so the browser only
draws. Specs never carry a color: a series names its category
("color:Launch Green") and an accent names a CSS variable ("var:cadence-front"),
and the page's CSS resolves both, per theme. Each builder also returns the
Aggregate behind it, so the points it publishes reconcile against their cohort
like every static component's counts.

    scatter   series of points (x, y, optional window lo..hi, tooltip lines),
              plus layers: line, band and a rule (the "today" line), and fixed
              axis domains, so hiding a series never rescales the chart. Layers
              sharing a `group` are one legend entry, shown and hidden together.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from config import (AS_OF, COLOR_ORDER, DIMENSIONS, FACTORY, INTERIOR_ORDER,
                    INTERIOR_SHORT, STATE_INFO, WHEEL_ABBR)

from .aggregates import STAGE_LABELS, STAGES, Aggregate, stages
from .cadence import projection as cadence_projection

# wheels value -> its marker shape (dimensions.yaml `symbol`: circle, square,
# diamond, triangle-up, which charts/scatter.js maps to d3's symbols).
_WHEEL_SYMBOL = {c["value"]: c["symbol"] for c in DIMENSIONS["wheels"]["categories"]}


def _iso(ts: Any) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == ""


def _day(ts: Any) -> str:
    return pd.Timestamp(ts).strftime("%b %d")


def _vins(v: Any, to: int = 1) -> str:
    return format(int(round(float(v) / to) * to), ",")


def _date_domain(xs: list[pd.Timestamp], pad: float = 0.03,
                 min_days: int = 3) -> list[str | None] | None:
    if not xs:
        return None
    lo, hi = min(xs), max(xs)
    p = max((hi - lo) * pad, pd.Timedelta(days=min_days))
    return [_iso(lo - p), _iso(hi + p)]


def _num_domain(ys: list[float], pad: float = 0.03) -> list[float] | None:
    if not ys:
        return None
    lo, hi = min(ys), max(ys)
    p = max((hi - lo) * pad, 1.0)
    return [lo - p, hi + p]


def _paint_order(d: pd.DataFrame) -> list[str]:
    """Most-ordered paint first, the palette breaking ties (#58), as everywhere.
    A blank (an unreported build) is not a paint."""
    counts = d.loc[~d["color"].map(_blank), "color"].value_counts()
    rank = {c: i for i, c in enumerate(COLOR_ORDER)}
    return sorted(counts.index, key=lambda c: (-counts[c], rank.get(c, len(rank)), c))


def _config_tip(r: pd.Series) -> list[str]:
    """An order's tooltip in the configuration scatters (§9, §10, §11)."""
    return [str(r["user"]),
            "%s · %s" % (r["color"], r["wheels_short"]),
            "%s · %s" % (r["interior"], r["buylease"]),
            "State: %s" % r["state"],
            "VIN seq: %s" % r["vin_display"],
            "Ordered: %s" % r["order_display"],
            "Est. delivery: %s (%s)" % (r["est_display"], r["delivery_type"])]


def _reported(d: pd.DataFrame, *cols: str) -> pd.Series:
    """Rows that report every one of `cols`. A curated addition can leave the
    configuration blank (overrides.yaml); it counts in the cohort but has no
    choice to plot, so the configuration charts leave it out, as excluded."""
    ok = pd.Series(True, index=d.index)
    for c in cols:
        ok &= ~d[c].map(_blank)
    return ok


def _config_series(d: pd.DataFrame, paints: list[str], x: Callable[[pd.Series], Any],
                   y: Callable[[pd.Series], Any]) -> tuple[list[dict], list[dict]]:
    """One series per paint × wheel, paints in `paints` order, then the wheels in
    dimensions.yaml's: fill = paint, shape = wheels, the house config language.
    Returns (series, cells)."""
    series, cells = [], []
    for color in paints:
        for wheel in _WHEEL_SYMBOL:
            s = d[(d["color"] == color) & (d["wheels_short"] == wheel)]
            if s.empty:
                continue
            name = "%s · %s" % (color, wheel.split()[0])
            series.append({"name": name, "color": "color:%s" % color,
                           "shape": "wheels:%s" % wheel, "symbol": _WHEEL_SYMBOL[wheel],
                           "points": [{"x": x(r), "y": y(r), "tip": _config_tip(r)}
                                      for _, r in s.iterrows()]})
            cells.append({"value": name, "label": name, "n": len(s),
                          "ref": "color:%s" % color, "known": True})
    return series, cells


def vin_vs_order(df: pd.DataFrame) -> tuple:
    """§9: each order with a VIN at (order date, VIN), one series per paint ×
    wheel, as §10."""
    vin = df["vin_present"].astype(bool)
    has = vin & df["order_date"].notna()
    d = df[has & _reported(df, "color", "wheels_short")]
    excluded = {"no VIN": int((~vin).sum()),
                "no order date": int((vin & df["order_date"].isna()).sum()),
                "paint or wheels not reported": int(has.sum()) - len(d)}
    series, cells = _config_series(d, _paint_order(d),
                                   lambda r: _iso(r["order_date"]),
                                   lambda r: int(r["vin_seq"]))
    xs = list(d["order_date"]) + [AS_OF]
    spec = {"template": "scatter", "title": "VIN sequence vs. order date",
            "x": {"label": "R2 order date", "type": "date", "domain": _date_domain(xs)},
            "y": {"label": "VIN sequence number", "type": "linear",
                  "domain": _num_domain([float(v) for v in d["vin_seq"]])},
            "legend": "Paint · wheels", "series": series, "layers": []}
    rows = [[s_["name"], p["tip"][0], p["x"], format(p["y"], ",")]
            for s_ in series for p in s_["points"]]
    table = (["Paint · wheels", "Order", "Ordered", "VIN"], rows)
    return spec, Aggregate("vin-vs-order points", "orders", cells, excluded), table


def vin_by_config(df: pd.DataFrame) -> tuple:
    """§11: each order with a VIN at its sequence (x), in a row per full
    configuration (trim · paint · wheels · interior). Interior joins the row key
    rather than becoming a third marker channel: fill and shape are taken."""
    vin = df["vin_present"].astype(bool)
    d = df[vin & _reported(df, "color", "wheels_short", "interior")]
    excluded = {"no VIN": int((~vin).sum()),
                "configuration not reported": int(vin.sum()) - len(d)}
    # The cohort's paint order, not the VIN-assigned rows', so rows group the way
    # every other paint chart on the page does.
    paints = _paint_order(df)
    paint_rank = {c: i for i, c in enumerate(paints)}
    interior_rank = {v: i for i, v in enumerate(INTERIOR_ORDER)}
    keys = {}
    for _, r in d.iterrows():
        label = " · ".join([str(r["trim"]), r["color"],
                            WHEEL_ABBR.get(r["wheels_short"], r["wheels_short"]),
                            INTERIOR_SHORT.get(r["interior"], r["interior"])])
        keys[label] = (str(r["trim"]), paint_rank.get(r["color"], len(paint_rank)),
                       WHEEL_ABBR.get(r["wheels_short"], r["wheels_short"]),
                       interior_rank.get(r["interior"], len(interior_rank)))
    rows = sorted(keys, key=keys.__getitem__)
    row_of = {k: i for i, k in enumerate(rows)}
    # A fixed jitter within the row, so stacked points separate, and the same on
    # every build.
    rng = np.random.RandomState(11)
    jitter = dict(zip(d.index, (rng.rand(len(d)) - 0.5) * 0.36))

    def _row(r: pd.Series) -> float:
        label = " · ".join([str(r["trim"]), r["color"],
                            WHEEL_ABBR.get(r["wheels_short"], r["wheels_short"]),
                            INTERIOR_SHORT.get(r["interior"], r["interior"])])
        return round(row_of[label] + float(jitter[r.name]), 3)

    series, cells = _config_series(d, [p for p in paints if p in set(d["color"])],
                                   lambda r: int(r["vin_seq"]), _row)
    spec = {"template": "scatter", "title": "VIN sequence by configuration",
            "x": {"label": "VIN sequence number (production order →)", "type": "linear",
                  "domain": _num_domain([float(v) for v in d["vin_seq"]])},
            "y": {"label": "Configuration", "type": "rows", "rows": rows,
                  "domain": [-0.6, len(rows) - 0.4]},
            "legend": "Paint · wheels", "series": series, "layers": []}
    table_rows = [[rows[round(p["y"])], p["tip"][0], format(p["x"], ",")]
                  for s_ in series for p in s_["points"]]
    table = (["Configuration", "Order", "VIN"], table_rows)
    agg = Aggregate("vin-by-config points", "orders", cells, excluded,
                    meta={"rows": len(rows)})
    return spec, agg, table


# Regions in dimensions.yaml's order, for the destination chart's legend.
_REGIONS = [c["value"] for c in DIMENSIONS["region"]["categories"]]


def dest_vs_delivery(df: pd.DataFrame) -> tuple:
    """§17: each order with a delivery estimate and a known destination, in a row
    per state, ordered by distance from the factory (nearest at the bottom), one
    series per region, with the quoted window as a whisker; and today."""
    est = df["delivery_est"].notna()
    d = df[est & df["dist_mi"].notna()]
    excluded = {"no delivery estimate": int((~est).sum()),
                "no known destination": int((est & df["dist_mi"].isna()).sum())}
    dist = (d.groupby("state")["dist_mi"].first()
            .sort_values(ascending=False, kind="mergesort"))
    rows = ["%s (%.0f mi)" % (st, mi) for st, mi in dist.items()]
    row_of = {st: i for i, st in enumerate(dist.index)}
    rng = np.random.RandomState(7)
    jitter = dict(zip(d.index, (rng.rand(len(d)) - 0.5) * 0.55))
    series, cells = [], []
    for region in [r for r in _REGIONS if (d["region"] == r).any()]:
        pts = []
        for i, r in d[d["region"] == region].iterrows():
            lo, hi = _iso(r["delivery_min"]), _iso(r["delivery_max"])
            window = bool(lo and hi and hi > lo)
            pts.append({"x": _iso(r["delivery_est"]),
                        "y": round(row_of[r["state"]] + float(jitter[i]), 3),
                        "lo": lo if window else None, "hi": hi if window else None,
                        "tip": ["%s — %s" % (r["user"], r["state"]),
                                "%.0f mi from Normal, IL" % r["dist_mi"],
                                str(r["color"]),
                                "Est. delivery: %s (%s)" % (r["est_display"],
                                                            r["delivery_type"])]})
        series.append({"name": region, "color": "region:%s" % region,
                       "symbol": "circle", "points": pts})
        cells.append({"value": region, "label": region, "n": len(pts),
                      "ref": "region:%s" % region, "known": True})
    xs = [pd.Timestamp(v) for c in ("delivery_est", "delivery_min", "delivery_max")
          for v in d[c].dropna()] + [AS_OF]
    spec = {"template": "scatter", "title": "Destination vs. delivery date",
            "x": {"label": "Estimated delivery date (whiskers = quoted window)",
                  "type": "date", "domain": _date_domain(xs)},
            "y": {"label": "Destination — nearest to the factory at the bottom",
                  "type": "rows", "rows": rows, "domain": [-0.7, len(rows) - 0.3]},
            "legend": "Region", "series": series,
            "layers": [{"type": "rule", "axis": "x", "value": _iso(AS_OF),
                        "label": "Today"}],
            "toggles": {"whiskers": True}}
    table_rows = [[rows[round(p["y"])], s_["name"], p["tip"][0].split(" — ")[0],
                   p["x"], "%s – %s" % (p["lo"], p["hi"]) if p["lo"] else ""]
                  for s_ in series for p in s_["points"]]
    table = (["Destination", "Region", "Order", "Est. delivery", "Quoted window"],
             table_rows)
    return spec, Aggregate("dest-vs-delivery points", "orders", cells, excluded), table


# --- geo: the US states map ----------------------------------------------------
#
#   geo   states: {postal code: {region, orders, vin, demand, tip}}, keyed as the
#         map's paths are; measures: the counts the reader
#         can map ({key, label}), and `default`; factory: [lat, lon]. The map is
#         the US only, for now (docs/presentation.md): Canada isn't on sale yet,
#         so its orders and reservations are left out, counted in `excluded`.

# The map's measures, most inclusive first: each is a subset of the one before
# (the delivery stages count cumulatively, so "with a VIN" includes scheduled and
# delivered orders, as an order past a stage has passed the ones before it).
_MEASURES = (("demand", "Orders + reservations"), ("orders", "Orders"),
             ("vin", "With a VIN"), ("scheduled", "Scheduled"),
             ("delivered", "Delivered"))
_PAST = {"vin": ("vin", "scheduled", "delivered"),
         "scheduled": ("scheduled", "delivered"), "delivered": ("delivered",)}


def _count(n: int, noun: str) -> str:
    return "%s %s%s" % (format(n, ","), noun, "" if n == 1 else "s")


def _us(frame: pd.DataFrame) -> pd.Series:
    known = frame["state"].isin(STATE_INFO)
    return known & frame["state"].map(lambda s: STATE_INFO.get(s, ("",))[0] != "Canada")


def geo_demand(df: pd.DataFrame, resv: pd.DataFrame | None) -> tuple:
    """§12: per US state, total demand (orders + outstanding reservations), orders,
    and the orders that have reached each delivery stage, cumulatively: with a
    VIN (or further), scheduled (or delivered), delivered."""
    if resv is None or "state" not in resv:
        resv = pd.DataFrame({"state": pd.Series([], dtype=object)})
    us, rus = _us(df), _us(resv)
    known = df["state"].isin(STATE_INFO)
    excluded = {"outside the US (not mapped)": int((known & ~us).sum()),
                "no known state": int((~known).sum())}
    d = df[us]
    st = stages(d)
    resv_n = resv[rus].groupby("state").size()
    states, cells = {}, []

    def _state(code: str, n: int, r: int, past: dict[str, int]) -> dict[str, Any]:
        tip = ["%s + %s" % (_count(n, "order"), _count(r, "reservation"))]
        if n:
            tip += ["%s: %s (%.0f%%)" % (label, format(past[k], ","), 100 * past[k] / n)
                    for k, label in _MEASURES[2:]]
        return {"region": STATE_INFO[code][0], "demand": n + r, "orders": n, **past,
                "tip": tip}

    for code, g in sorted(d.groupby("state"), key=lambda kv: (-len(kv[1]), kv[0])):
        n, at = len(g), st[g.index]
        past = {k: int(at.isin(v).sum()) for k, v in _PAST.items()}
        states[str(code)] = _state(str(code), n, int(resv_n.get(code, 0)), past)
        cells.append({"value": code, "label": code, "n": n,
                      "ref": None, "known": True})
    # A state with reservations but no orders yet is still demand on the map.
    for where, r in resv_n.items():
        key = str(where)
        if key not in states:
            states[key] = _state(key, 0, int(r), dict.fromkeys(_PAST, 0))
    left = {"orders": int((known & ~us).sum()), "resv": int((~rus).sum())}
    spec = {"template": "geo", "title": "Geographic demand",
            "measures": [{"key": k, "label": lbl} for k, lbl in _MEASURES],
            "default": "orders",
            "factory": list(FACTORY), "states": states}
    table = (["State", "Region"] + [lbl for _, lbl in _MEASURES],
             [[c, v["region"]] + [v[k] for k, _ in _MEASURES]
              for c, v in states.items()])
    agg = Aggregate("orders by US state", "orders", cells, excluded, "state",
                    meta={"states": sum(1 for v in states.values() if v["orders"]),
                          "left": "%s and %s" % (_count(left["orders"], "order"),
                                                 _count(left["resv"], "reservation"))})
    return spec, agg, table


def delivery_vs_vin(df: pd.DataFrame) -> tuple:
    """§10: each order with a VIN and a delivery estimate, at (estimated
    delivery date, VIN), one series per paint × wheel, with the quoted window
    as a whisker; the build front, its projection and band; and today."""
    has = df["vin_present"].astype(bool) & df["delivery_est"].notna()
    d = df[has & ~df["color"].map(_blank) & ~df["wheels_short"].map(_blank)]
    excluded = {"no VIN": int((~df["vin_present"].astype(bool)).sum())}
    excluded["no delivery estimate"] = int(
        (df["vin_present"].astype(bool) & df["delivery_est"].isna()).sum())
    excluded["paint or wheels not reported"] = int(has.sum()) - len(d)

    series, cells = [], []
    for color in _paint_order(d):
        for wheel in _WHEEL_SYMBOL:
            s = d[(d["color"] == color) & (d["wheels_short"] == wheel)]
            if s.empty:
                continue
            pts = []
            for _, r in s.iterrows():
                lo, hi = _iso(r["delivery_min"]), _iso(r["delivery_max"])
                pts.append({
                    "x": _iso(r["delivery_est"]), "y": int(r["vin_seq"]),
                    "lo": lo if lo and hi and hi > lo else None,
                    "hi": hi if lo and hi and hi > lo else None,
                    "firm": r["delivery_type"] == "explicit",
                    "tip": _config_tip(r)})
            name = "%s · %s" % (color, wheel.split()[0])
            series.append({"name": name, "color": "color:%s" % color,
                           "shape": "wheels:%s" % wheel,
                           "symbol": _WHEEL_SYMBOL[wheel], "points": pts})
            cells.append({"value": name, "label": name, "n": len(pts),
                          "ref": "color:%s" % color, "known": True})

    layers: list[dict[str, Any]] = []
    proj = cadence_projection(df)
    if proj and proj["front"] is not None and not proj["front"].empty:
        # Each week's point sits at its midpoint, like the points it summarizes.
        front = proj["front"]
        week = [w + pd.Timedelta(days=3) for w in front.index]
        layers.append({
            "type": "line", "name": "Build front (observed)", "group": "Build front",
            "color": "var:cadence-front",
            "points": [[_iso(w), float(v)] for w, v in zip(week, front.values)],
            "tips": [["Build front", "Week of %s: ≈ VIN %s" % (_day(w), _vins(v))]
                     for w, v in zip(front.index, front.values)]})
        mids = [_iso(w + pd.Timedelta(days=3)) for w in proj["weeks"]]
        layers.append({"type": "band", "name": "Likely range", "group": "Build front",
                       "color": "var:cadence-band",
                       "points": [[m, float(lo), float(hi)]
                                  for m, lo, hi in zip(mids, proj["lo"], proj["hi"])]})
        # The projection quotes VINs, its own axis, to the nearest hundred: the
        # back-test supports no more precision than that.
        layers.append({
            "type": "line", "name": "Projected · ≈ %.0f VINs/day" % proj["rate"],
            "group": "Build front", "color": "var:cadence-front", "dash": True,
            "points": [[m, float(c)] for m, c in zip(mids, proj["center"])],
            "tips": [["Projected front",
                      "Week of %s: ≈ VIN %s" % (_day(w), _vins(c, 100)),
                      "Likely VIN %s–%s" % (_vins(lo, 100), _vins(hi, 100))]
                     for w, c, lo, hi in zip(proj["weeks"], proj["center"],
                                             proj["lo"], proj["hi"])]})
    layers.append({"type": "rule", "axis": "x", "value": _iso(AS_OF),
                   "label": "Today"})

    # Fixed domains over every point, window, layer and today, padded a little,
    # so neither hiding a series nor zooming out past the data rescales anything.
    xs = [pd.Timestamp(v) for p in (q for s_ in series for q in s_["points"])
          for v in (p["x"], p["lo"], p["hi"]) if v]
    ys = [float(p["y"]) for s_ in series for p in s_["points"]]
    for layer in layers:
        if layer["type"] == "rule":
            xs.append(pd.Timestamp(layer["value"]))
        else:
            xs += [pd.Timestamp(pt[0]) for pt in layer["points"]]
            ys += [float(v) for pt in layer["points"] for v in pt[1:]]

    spec = {"template": "scatter",
            "title": "Delivery date vs. VIN sequence",
            "x": {"label": "Estimated delivery date (whiskers = quoted window)",
                  "type": "date", "domain": _date_domain(xs)},
            "y": {"label": "VIN sequence number (production order →)",
                  "type": "linear", "domain": _num_domain(ys)},
            "legend": "Paint · wheels",
            "series": series, "layers": layers,
            "toggles": {"whiskers": True}}
    rows = [[s_["name"], p["tip"][0], format(p["y"], ","), p["x"],
             "%s – %s" % (p["lo"], p["hi"]) if p.get("lo") else "",
             "firm" if p.get("firm") else ""]
            for s_ in series for p in s_["points"]]
    table = (["Paint · wheels", "Order", "VIN", "Est. delivery", "Quoted window",
              "Date"], rows)
    return spec, Aggregate("delivery-vs-vin points", "orders", cells, excluded), table


# --- timeseries: weekly columns (stacked) and lines over dates ---------------------
#
#   timeseries  x: Monday weeks; `series`: stacked columns, each
#               {name, color, values: [[week, n], ...]}; `lines`: {name, color,
#               points: [[iso, y]], tips}; `rules` (today); y may carry `clip`
#               (the domain stops there, and a taller column is marked with its
#               total) and `format` ("pct": values are percentages). With
#               `toggles.cumulative`, the reader can switch the columns to running
#               totals; y.cumulative is that view's fixed domain.
# Every week is Monday-to-Sunday, the same weeks the latency median and the
# cadence use.

def _week(s: pd.Series) -> pd.Series:
    return s.dt.to_period("W-SUN").dt.start_time


def _weekly(dates: pd.Series) -> dict[pd.Timestamp, int]:
    counts: Any = _week(dates.dropna()).value_counts()
    return {pd.Timestamp(k): int(v) for k, v in counts.items()}


def _partial(weeks: Sequence[pd.Timestamp]) -> str | None:
    """The last week, when it's the current one and so still under way (the
    chart marks it as so far)."""
    if not weeks:
        return None
    last, now = pd.Timestamp(weeks[-1]), pd.Timestamp(AS_OF)
    return _iso(last) if last <= now < last + pd.Timedelta(days=7) else None


def _week_label(w: pd.Timestamp) -> str:
    return "Week of %s" % pd.Timestamp(w).strftime("%b %d, %Y")


def _columns(stack: list[tuple[str, str, dict[pd.Timestamp, int]]],
             clip_over: float = 3.0, cumulative: bool = False) -> dict[str, Any]:
    """The weeks, series and y axis of a stacked weekly column chart. When the
    tallest week is more than `clip_over` times the next, the axis clips just
    above the rest (a nice round number) and that week is marked with its total,
    so one spike doesn't flatten every other week. `cumulative` lists every
    week from the first to the last (a running total has no gaps) and adds the
    running-total view's domain."""
    weeks = sorted({w for _, _, by in stack for w in by})
    if cumulative and weeks:
        weeks = list(pd.date_range(weeks[0], weeks[-1], freq="7D"))
    totals = [sum(by.get(w, 0) for _, _, by in stack) for w in weeks]
    series = [{"name": name, "color": color,
               "values": [[_iso(w), by.get(w, 0)] for w in weeks]}
              for name, color, by in stack]
    y: dict[str, Any] = {"type": "linear", "domain": [0, max(totals or [1]) * 1.05]}
    if cumulative:
        y["cumulative"] = {"domain": [0, max(sum(totals), 1) * 1.05]}
    ranked = sorted(totals, reverse=True)
    if len(ranked) > 1 and ranked[0] > clip_over * max(ranked[1], 1):
        top = ranked[1] * 1.15
        step = 10 ** max(int(np.floor(np.log10(top))), 0)
        y["clip"] = y["domain"][1] = float(np.ceil(top / step) * step)
    return {"weeks": weeks, "totals": totals, "series": series, "y": y}


def _weeks_domain(weeks: list[pd.Timestamp],
                  extra: Sequence[pd.Timestamp] = ()) -> list:
    """Monday of the first week to the Monday after the last (each column spans
    its week), widened to `extra` dates (today)."""
    lo = min(list(weeks) + list(extra))
    hi = max([w + pd.Timedelta(days=7) for w in weeks] + list(extra))
    return [_iso(lo), _iso(hi)]


def _column_table(first: str, cols: dict[str, Any]) -> tuple[list[str], list[list]]:
    names = [s["name"] for s in cols["series"]]
    run = np.cumsum(cols["totals"]).tolist() if "cumulative" in cols["y"] else None
    rows = [[_iso(w)] + [s["values"][i][1] for s in cols["series"]]
            + ([cols["totals"][i]] if len(names) > 1 else [])
            + ([int(run[i])] if run else [])
            for i, w in enumerate(cols["weeks"])]
    return ([first] + names + (["Total"] if len(names) > 1 else [])
            + (["Running total"] if run else [])), rows


def reservations_by_week(df: pd.DataFrame, resv: pd.DataFrame) -> tuple:
    """§5, top: reservations by the week they were made, stacked: outstanding
    (holders still waiting to order, from the reservations sheet) on top of
    converted (every order with a reservation date)."""
    ordered, only = _weekly(df["resv_date"]), _weekly(resv["resv_date"])
    cols = _columns([("Converted", "acc:timeline-ordered", ordered),
                     ("Outstanding", "acc:timeline-reserved", only)],
                    cumulative=True)
    x = {"label": "Week reserved", "type": "date",
         "domain": _weeks_domain(cols["weeks"]) if cols["weeks"] else None,
         "partial": _partial(cols["weeks"])}
    spec = {"template": "timeseries", "title": "Reservations by week",
            "x": x, "y": {**cols["y"], "label": "Reservations"},
            "legend": "Reservation", "series": cols["series"], "lines": [],
            "rules": [], "toggles": {"cumulative": True}}
    heads, rows = _column_table("Week of", cols)
    cells = [{"value": s["name"], "label": s["name"],
              "n": sum(v for _, v in s["values"]), "known": True, "ref": None}
             for s in cols["series"]]
    excluded = {"order without a reservation date": int(df["resv_date"].isna().sum()),
                "reservation without a date": int(resv["resv_date"].isna().sum())}
    # The summary's count is every outstanding reservation, dated or not, so it
    # matches the summary readout; the chart can only place the dated ones.
    agg = Aggregate("reservations by week", "orders+reservations", cells,
                    {k: v for k, v in excluded.items() if v},
                    meta={"outstanding": format(len(resv), ",")})
    return spec, agg, (heads, rows)


def _stage_names() -> list[tuple[str, str]]:
    """(stage, label) bottom to top, labelled as the take-rate stage key."""
    return [(st, STAGE_LABELS[st][:1].upper() + STAGE_LABELS[st][1:]) for st in STAGES]


def orders_by_week(df: pd.DataFrame) -> tuple:
    """§5, bottom: orders by the week the configuration was finalized, each
    split by how far it has got today (the four delivery stages, delivered at
    the bottom): how each week's cohort is doing. The neutral grey at the
    stages' opacities (`stage`), as the take-rate stage key draws them."""
    st = stages(df)
    cols = _columns([(label, "neutral",
                      _weekly(df.loc[st == stage, "order_date"]))
                     for stage, label in _stage_names()], cumulative=True)
    for s_, (stage, _) in zip(cols["series"], _stage_names()):
        s_["stage"] = stage
    spec = {"template": "timeseries", "title": "Orders by week",
            "x": {"label": "Week ordered", "type": "date",
                  "domain": _weeks_domain(cols["weeks"]) if cols["weeks"] else None,
                  "partial": _partial(cols["weeks"])},
            "y": {**cols["y"], "label": "Orders"}, "legend": "Status today",
            "series": cols["series"], "lines": [], "rules": [],
            "toggles": {"cumulative": True}}
    heads, rows = _column_table("Week of", cols)
    n = int(df["order_date"].notna().sum())
    cells = [{"value": s_["name"], "label": s_["name"],
              "n": sum(v for _, v in s_["values"]), "known": True, "ref": None}
             for s_ in cols["series"]]
    agg = Aggregate("orders by week", "orders", cells,
                    {"no order date": len(df) - n} if len(df) - n else {})
    if cols["weeks"]:
        i = int(np.argmax(cols["totals"]))
        agg.meta["peak"] = "%s (%d orders)" % (
            pd.Timestamp(cols["weeks"][i]).strftime("%b %d, %Y"), cols["totals"][i])
    return spec, agg, (heads, rows)


def deliveries_by_week(df: pd.DataFrame) -> tuple:
    """§6: estimated deliveries by week, stacked by how firm the estimate is
    (dimensions.yaml delivery_type, firm first), with today."""
    unknown = DIMENSIONS["delivery_type"]["missing"]["value"]
    types = [c for c in DIMENSIONS["delivery_type"]["categories"]
             if c["value"] != unknown]
    d = df[df["delivery_est"].notna() & df["delivery_type"].isin(
        [c["value"] for c in types])]
    stack = [(c.get("label") or c["value"], "delivery_type:%s" % c["value"],
              _weekly(d.loc[d["delivery_type"] == c["value"], "delivery_est"]))
             for c in types]
    cols = _columns([s for s in stack if s[2]])
    today = pd.Timestamp(AS_OF).normalize()
    spec = {"template": "timeseries", "title": "Estimated deliveries by week",
            "x": {"label": "Estimated delivery week", "type": "date",
                  "domain": _weeks_domain(cols["weeks"], [today])
                  if cols["weeks"] else None},
            "y": {**cols["y"], "label": "Orders"}, "legend": "Estimate",
            "series": cols["series"], "lines": [],
            "rules": [{"axis": "x", "value": _iso(today), "label": "Today"}]}
    heads, rows = _column_table("Week of", cols)
    cells = [{"value": s["name"], "label": s["name"],
              "n": sum(v for _, v in s["values"]), "known": True, "ref": None}
             for s in cols["series"]]
    agg = Aggregate("deliveries by week", "orders", cells,
                    {"no delivery estimate": len(df) - len(d)} if len(df) - len(d)
                    else {})
    return spec, agg, (heads, rows)


# The pipeline's events, in reading order: (key, label, line accent). Each is an
# order's own date (ingest/milestones.py), the dates r2_series.json counts.
_EVENTS = (("placed", "Orders placed", "fulfil-placed"),
           ("vin", "VINs assigned", "fulfil-vin"),
           ("scheduled", "Deliveries scheduled", "fulfil-scheduled"),
           ("delivered", "Deliveries made", "fulfil-delivered"))


def _event_dates(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Each order's date for each pipeline event, NaT where it hasn't happened
    (or happened with no date we know; see fulfilment_by_week)."""
    nat = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    def col(name: str) -> pd.Series:
        return pd.to_datetime(df[name]) if name in df else nat
    vin = df["vin_present"].fillna(False).astype(bool)
    firm = df["delivery_type"] == "explicit"
    done = df["delivered_inferred"].fillna(False).astype(bool)
    return {"placed": pd.to_datetime(df["order_date"]),
            "vin": col("vin_assigned").where(vin),
            "scheduled": col("delivery_scheduled").where(firm),
            "delivered": pd.to_datetime(df["delivery_est"]).where(done)}


def fulfilment_by_week(df: pd.DataFrame) -> tuple:
    """§6: the whole pipeline over time, from each order's event dates.

    Cumulative (the default view): each week's column is every order placed by
    the week's end, split by the stage it had reached by then, stacked
    (delivered at the bottom), so the last column is today's Delivery progress.
    Weekly: what happened that week, as lines: orders placed, VINs assigned,
    deliveries scheduled, deliveries made. The last week is each order's stage
    today (aggregates.stages(), as the readouts count it), so an event with no
    known date (a VIN with no recorded date) shows from then on."""
    d = df[df["order_date"].notna()]
    ev = _event_dates(d)
    now = pd.Timestamp(AS_OF)
    first = _week(pd.Series([ev["placed"].min()])).iloc[0] if len(d) else None
    weeks = (list(pd.date_range(first, _week(pd.Series([now])).iloc[0], freq="7D"))
             if first is not None else [])
    levels: dict[str, list[int]] = {st: [] for st in STAGES}
    for i, w in enumerate(weeks):
        if i == len(weeks) - 1:
            now_stage = stages(d)
            for st in STAGES:
                levels[st].append(int((now_stage == st).sum()))
            continue
        end = w + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
        placed = ev["placed"] <= end
        dl = placed & (ev["delivered"] <= end)
        sc = placed & ~dl & (ev["scheduled"] <= end)
        vn = placed & ~dl & ~sc & (ev["vin"] <= end)
        for st, mask in (("delivered", dl), ("scheduled", sc), ("vin", vn),
                         ("wait", placed & ~dl & ~sc & ~vn)):
            levels[st].append(int(mask.sum()))
    events = {key: _weekly(ev[key]) for key, _, _ in _EVENTS}
    iso = [_iso(w) for w in weeks]
    series = [{"name": label, "color": "neutral", "stage": st,
               "view": "cumulative",
               "values": [[x, v] for x, v in zip(iso, levels[st])]}
              for st, label in _stage_names()]
    lines = [{"name": label, "color": "var:" + accent, "view": "weekly",
              "points": [[_iso(w + pd.Timedelta(days=3)), events[key].get(w, 0)]
                         for w in weeks]}
             for key, label, accent in _EVENTS]
    totals = [sum(levels[st][i] for st in STAGES) for i in range(len(weeks))]
    peak = max([int(c) for by in events.values() for c in by.values()] or [1])
    today = now.normalize()
    spec = {"template": "timeseries", "title": "Fulfilment over time",
            "x": {"label": "Week", "type": "date",
                  "domain": _weeks_domain(weeks, [today]) if weeks else None,
                  "partial": _partial(weeks)},
            "y": {"type": "linear", "label": "Orders",
                  "domain": [0, peak * 1.1],
                  "cumulative": {"domain": [0, max(totals or [1]) * 1.05]}},
            "legend": "Orders", "series": series, "lines": lines, "rules": [],
            "toggles": {"cumulative": True, "default": "cumulative"}}
    heads = (["Week of"] + [label for _, label in _stage_names()]
             + ["Orders placed by then"] + [label for _, label, _ in _EVENTS])
    rows = [[iso[i]] + [levels[st][i] for st in STAGES] + [totals[i]]
            + [events[key].get(w, 0) for key, _, _ in _EVENTS]
            for i, w in enumerate(weeks)]
    cells = [{"value": st, "label": label, "n": levels[st][-1] if weeks else 0,
              "known": True, "ref": None} for st, label in _stage_names()]
    agg = Aggregate("fulfilment over time", "orders", cells,
                    {"no order date": len(df) - len(d)} if len(df) - len(d) else {})
    return spec, agg, (heads, rows)


# §7: a weekly median is only drawn for weeks with at least this many firm
# dates; below it, one fast or slow delivery swings the line by weeks.
LATENCY_MIN_WEEK_N = 3


def latency_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Orders whose wait from order to delivery can be measured, with `days`.

    Firm ("explicit") delivery dates only: a range or window is a guess at when
    the car will come, so its midpoint would plot a precision the data doesn't
    have. An estimate that contradicts the order date never gets here: cleaning
    sets it aside as unknown and lists it (ingest/outliers.py)."""
    d = df[(df["delivery_type"] == "explicit") & df["order_date"].notna()
           & df["delivery_est"].notna()].copy()
    d["days"] = (d["delivery_est"] - d["order_date"]).dt.days
    # The Monday-start week the order was placed in, for the median and coverage.
    d["order_week"] = _week(d["order_date"])
    return d


def delivery_latency(df: pd.DataFrame) -> tuple:
    """§7: each order with a firm delivery date at (order date, days to
    delivery), filled once the date has passed and open while it's still
    scheduled, with the weekly median for weeks of LATENCY_MIN_WEEK_N or more."""
    d = latency_frame(df)
    passed = d["delivery_est"] <= pd.Timestamp(AS_OF)
    series: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for name, mask, open_ in (("Delivery date passed", passed, False),
                              ("Scheduled (future date)", ~passed, True)):
        s = d[mask].sort_values("order_date")
        if s.empty:
            continue
        series.append({"name": name, "color": "acc:latency-order", "open": open_,
                       "points": [{"x": _iso(o), "y": int(n),
                                   "tip": [str(u), "Ordered %s" % _day(o),
                                           "Delivery %s" % _day(e), "%d days" % n]}
                                  for u, o, e, n in zip(s["user"], s["order_date"],
                                                        s["delivery_est"], s["days"])]})
        cells.append({"value": name, "label": name, "n": len(s), "known": True,
                      "ref": None})
    g: Any = d.groupby("order_week")["days"]
    med: Any = g.median()[g.size() >= LATENCY_MIN_WEEK_N]
    layers: list[dict[str, Any]] = []
    if len(med):
        layers.append({
            "type": "line", "name": "Weekly median (%d+ orders)" % LATENCY_MIN_WEEK_N,
            "color": "var:latency-median",
            "points": [[_iso(w + pd.Timedelta(days=3)), float(v)]
                       for w, v in med.items()],
            "tips": [["Weekly median", "%s: %.0f days" % (_week_label(w), v),
                      "%d orders" % g.size()[w]] for w, v in med.items()]})
    xs = [pd.Timestamp(p["x"]) for s_ in series for p in s_["points"]]
    ys = [0.0] + [float(p["y"]) for s_ in series for p in s_["points"]]
    spec = {"template": "scatter", "title": "Order-to-delivery time",
            "x": {"label": "Order date", "type": "date", "domain": _date_domain(xs)},
            "y": {"label": "Days from order to delivery", "type": "linear",
                  "domain": [0.0, (_num_domain(ys) or [0, 1])[1]]},
            "legend": "Orders", "series": series, "layers": layers, "toggles": {}}
    rows = [[s_["name"], p["tip"][0], p["x"], p["tip"][2][len("Delivery "):], p["y"]]
            for s_ in series for p in s_["points"]]
    excluded = {"no order date": int(df["order_date"].isna().sum())}
    rest = len(df) - excluded["no order date"] - len(d)
    excluded["no firm delivery date"] = rest
    agg = Aggregate("order-to-delivery points", "orders", cells,
                    {k: v for k, v in excluded.items() if v},
                    meta={"median": "%.0f" % d["days"].median()} if len(d) else {})
    return spec, agg, (["Status", "Order", "Ordered", "Delivery", "Days"], rows)


def latency_coverage(df: pd.DataFrame) -> tuple:
    """§7, beneath: what share of each order week's orders have a firm delivery
    date, i.e. how much of the week the points above cover. Every order with an
    order date counts in its week's denominator, whatever its estimate."""
    have = df[df["order_date"].notna()]
    den = _week(have["order_date"]).value_counts().sort_index()
    num = latency_frame(df)["order_week"].value_counts()
    weeks = [pd.Timestamp(w) for w in den.index]
    pct = [100.0 * int(num.get(w, 0)) / int(den[w]) for w in den.index]
    spec = {"template": "timeseries", "title": "Firm-date coverage by order week",
            "x": {"label": "Week ordered", "type": "date",
                  "domain": _weeks_domain(weeks) if weeks else None},
            "y": {"label": "Orders with a firm date", "type": "linear",
                  "domain": [0, 100], "format": "pct"},
            "legend": None, "lines": [], "rules": [],
            "series": [{"name": "Coverage", "color": "acc:latency-coverage",
                        "values": [[_iso(w), round(p, 1)] for w, p in zip(weeks, pct)],
                        "tips": ["%d of %d orders have a firm date"
                                 % (int(num.get(w, 0)), int(den[w]))
                                 for w in den.index]}]}
    rows = [[_iso(w), int(num.get(w, 0)), int(den[w]), "%.0f%%" % p]
            for w, p in zip(weeks, pct)]
    agg = Aggregate("firm-date coverage", "orders",
                    [{"value": "with an order date", "label": "Orders", "n": len(have),
                      "known": True, "ref": None}],
                    {"no order date": len(df) - len(have)} if len(df) - len(have)
                    else {})
    return spec, agg, (["Week of", "Firm dates", "Orders", "Coverage"], rows)


def build_cadence(df: pd.DataFrame) -> tuple:
    """§10, beneath: the build front's rate over time, VINs per day, as of each
    front week (render/cadence.py rate_history), at the week's middle."""
    from config import CADENCE_WINDOW_WEEKS
    from .cadence import cadence_frame, rate_history
    hist = rate_history(df)
    pts = [[_iso(w + pd.Timedelta(days=3)), float(r)] for w, r in hist.items()]
    weeks = [pd.Timestamp(w) for w in hist.index]
    spec = {"template": "timeseries",
            "title": "Build cadence (rate over the previous %d weeks of front)"
                     % CADENCE_WINDOW_WEEKS,
            "x": {"label": "Delivery week", "type": "date",
                  "domain": _weeks_domain(weeks) if weeks else None},
            "y": {"label": "VINs per day", "type": "linear",
                  "domain": [0, max([float(r) for r in hist] or [1.0]) * 1.1]},
            "legend": None, "series": [], "rules": [],
            "lines": [{"name": "Build cadence", "color": "var:cadence-front",
                       "points": pts,
                       "tips": [["%s: ≈ %.0f VINs/day" % (_week_label(w), r)]
                                for w, r in hist.items()]}]}
    used = len(cadence_frame(df))
    vins = int(df["vin_present"].astype(bool).sum())
    agg = Aggregate("build cadence", "vin_assigned", [], basis=used,
                    excluded={"no firm delivery date": vins - used},
                    meta={"rate": "%.0f" % hist.iloc[-1],
                          "window": str(CADENCE_WINDOW_WEEKS)} if len(hist) else {})
    rows = [[_iso(w), "%.1f" % r] for w, r in hist.items()]
    return spec, agg, (["Week of", "VINs per day"], rows)
