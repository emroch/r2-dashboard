"""House-schema specs for the browser-drawn components (docs/presentation.md).

Each builder turns the cleaned orders into one component's spec: what the chart
library draws, already counted and laid out in Python, so the browser only
draws. Specs never carry a color: a series names its category
("color:Launch Green") and an accent names a CSS variable ("var:cadence-front"),
and the page's CSS resolves both, per theme. Each builder also returns the
Aggregate behind it, so the points it publishes reconcile against their cohort
like every static component's counts.

    scatter   series of points (x, y, optional window lo..hi, tooltip lines),
              plus layers: line, band and a rule (the "today" line)
    geo       bubbles at coordinates, sized by count, plus marker points
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from config import AS_OF, COLOR_ORDER, DIMENSIONS, FACTORY

from .aggregates import Aggregate
from .cadence import projection as cadence_projection

# wheels value -> its marker shape (dimensions.yaml `symbol`; the Plotly names,
# which each library's adapter maps to its own).
_WHEEL_SYMBOL = {c["value"]: c["symbol"] for c in DIMENSIONS["wheels"]["categories"]}


def _iso(ts: Any) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == ""


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
        front = proj["front"]
        layers.append({"type": "line", "name": "Build front (observed)",
                       "color": "var:cadence-front",
                       "points": [[_iso(w + pd.Timedelta(days=3)), float(v)]
                                  for w, v in front.items()]})
        mids = [_iso(w + pd.Timedelta(days=3)) for w in proj["weeks"]]
        layers.append({"type": "band", "name": "Likely range",
                       "color": "var:cadence-band",
                       "points": [[m, float(lo), float(hi)]
                                  for m, lo, hi in zip(mids, proj["lo"], proj["hi"])]})
        layers.append({"type": "line", "name": "Projected · ≈ %.0f VINs/day"
                       % proj["rate"], "color": "var:cadence-front", "dash": True,
                       "points": [[m, float(c)] for m, c in zip(mids, proj["center"])]})
    layers.append({"type": "rule", "axis": "x", "value": _iso(AS_OF),
                   "label": "Today"})

    spec = {"template": "scatter",
            "title": "Delivery date vs. VIN sequence",
            "x": {"label": "Estimated delivery date (whiskers = quoted window)",
                  "type": "date"},
            "y": {"label": "VIN sequence number (production order →)",
                  "type": "linear"},
            "legend": "Paint · wheels",
            "series": series, "layers": layers,
            "toggles": {"whiskers": True}}
    return spec, Aggregate("delivery-vs-vin points", "orders", cells, excluded)


def geo_orders(df: pd.DataFrame) -> tuple[dict[str, Any], Aggregate]:
    """§12 (all orders): a bubble per state or province at its coordinates,
    area = orders, colored by region; and the plant."""
    located = df[df["lat"].notna()]
    g = (located.groupby("state")
         .agg(n=("user", "size"), lat=("lat", "first"), lon=("lon", "first"),
              region=("region", "first"))
         .reset_index().sort_values(["n", "state"], ascending=[False, True]))
    bubbles = [{"name": str(st), "lat": float(la), "lon": float(lo), "n": int(n),
                "color": "region:%s" % rg, "tip": ["%s: %d orders" % (st, n)]}
               for st, n, la, lo, rg in zip(g["state"], g["n"], g["lat"], g["lon"],
                                            g["region"])]
    cells = [{"value": b["name"], "label": b["name"], "n": b["n"],
              "ref": b["color"], "known": True} for b in bubbles]
    spec = {"template": "geo", "title": "All orders by state / province",
            "scope": "north-america", "legend": "Region",
            "bubbles": bubbles,
            "markers": [{"name": "Rivian plant — Normal, IL", "lat": FACTORY[0],
                         "lon": FACTORY[1], "symbol": "star"}]}
    return spec, Aggregate("geo-orders bubbles", "orders", cells,
                           {"location unknown": len(df) - len(located)})
