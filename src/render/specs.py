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

from typing import Any

import numpy as np
import pandas as pd

from config import AS_OF, COLOR_ORDER, DIMENSIONS

from .aggregates import Aggregate
from .cadence import projection as cadence_projection

# wheels value -> its marker shape (dimensions.yaml `symbol`; the Plotly names,
# which each library's adapter maps to its own).
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
    """Most-ordered paint first, the palette breaking ties (#58), as everywhere."""
    counts = d["color"].value_counts()
    rank = {c: i for i, c in enumerate(COLOR_ORDER)}
    return sorted(counts.index, key=lambda c: (-counts[c], rank.get(c, len(rank)), c))


def delivery_vs_vin(df: pd.DataFrame) -> tuple[dict[str, Any], Aggregate]:
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
                    "tip": [str(r["user"]),
                            "%s · %s" % (color, wheel),
                            "%s · %s" % (r["interior"], r["buylease"]),
                            "State: %s" % r["state"],
                            "VIN seq: %s" % r["vin_display"],
                            "Ordered: %s" % r["order_display"],
                            "Est. delivery: %s (%s)" % (r["est_display"],
                                                        r["delivery_type"])]})
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
    return spec, Aggregate("delivery-vs-vin points", "orders", cells, excluded)
