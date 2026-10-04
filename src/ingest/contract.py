"""The published data contract: dimension metadata and an aggregate time series.

Data layer stage 4 (docs/data-layer.md, issue #84), the hand-off to the
presentation rewrite (#66) and reconfigurable charts (#51). Two JSON files are
published next to the cleaned CSV:

  r2_dimensions.json  what each column of r2_orders_clean.csv MEANS for display:
                      its label, category order, how blanks are handled, the
                      small-n rule, a caveat, and a color TOKEN per category.
                      The token names a color; a `palette` block maps tokens
                      to today's hex values, and CSS is meant to own them. A
                      category is named, its color is styled.
  r2_series.json      the dashboard's headline counts as they stood each Monday
                      since the first snapshot, plus today. Aggregates only,
                      never a per-order history.

Each point of the series is the REAL cleaning (loaders.load_and_clean) run on the
snapshot that was current at the end of that day, with `as_of` set to that day.
So a point is exactly what the dashboard would have counted then, under today's
cleaning rules and with only the curation that was in effect by that date. The
last point is today, and the pipeline checks it against the live report.

Weekly, not daily (decided on #84): a cleaning pass takes about 0.5 s, so daily
points would add about 40 s to every build now and minutes within a year.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import contextlib
import io
import re
from datetime import datetime
from typing import Any

import pandas as pd

from config import (AS_OF, COLOR_HEX, COLOR_ORDER, INTERIOR_COLOR, INTERIOR_ORDER,
                    INTERIOR_SHORT, ORDERS_LABEL, ORDERS_SLUG, REGION_COLOR,
                    RESV_SLUG, TRIM_COLORS, TYPE_COLOR, TYPE_ORDER, WHEEL_ABBR,
                    WHEEL_COLOR, WHEEL_ORDER, WHEEL_SYMBOL)

from .history import snapshot_files
from .loaders import load_and_clean, load_reservations

CONTRACT_VERSION = 1

# The small-n rule the location charts use (fig_paint_by_location): a state is
# only drawn on its own with at least this many orders.
STATE_MIN_ORDERS = 5


def _token(kind: str, value: str) -> str:
    """A CSS-safe color token: "paint", "Catalina Cove" -> "paint-catalina-cove"."""
    return "%s-%s" % (kind, re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"))


def _cats(kind: str, values, colors: dict[str, str], labels=None, extra=None):
    """Category list for one dimension, plus the palette entries it uses."""
    cats, palette = [], {}
    for v in values:
        c: dict[str, Any] = {"value": v, "label": (labels or {}).get(v, v)}
        if v in colors:
            c["color"] = _token(kind, v)
            palette[c["color"]] = colors[v]
        c.update((extra or {}).get(v, {}))
        cats.append(c)
    return cats, palette


_OMIT = {"policy": "omit",
         "note": "Blank values are left out of the chart but stay in the cohort; "
                 "the data-quality panel lists them."}
_INFERRED = ("Inferred, not reported: an estimate whose whole window has passed "
             "counts as delivered. It can be wrong both ways.")
_SELF = "Self-reported in a forum-run sheet; treat as indicative."


def dimensions() -> dict[str, Any]:
    """Metadata for every categorical column of r2_orders_clean.csv."""
    palette: dict[str, str] = {}

    def add(cats_palette):
        cats, pal = cats_palette
        palette.update(pal)
        return cats

    wheel_extra = {w: {"abbr": WHEEL_ABBR[w], "symbol": WHEEL_SYMBOL[w]}
                   for w in WHEEL_ORDER}
    dims = [
        {"name": "color", "column": "color", "label": "Paint",
         "order": "count", "order_note": "Most ordered first; ties keep the "
                                         "listed (showroom) order.",
         "categories": add(_cats("paint", COLOR_ORDER, COLOR_HEX)),
         "missing": _OMIT, "caveat": None},
        {"name": "wheels", "column": "wheels_short", "label": "Wheels",
         "order": "fixed", "order_note": "Ascending size.",
         "categories": add(_cats("wheel", WHEEL_ORDER, WHEEL_COLOR,
                                 extra=wheel_extra)),
         "missing": _OMIT, "caveat": None},
        {"name": "interior", "column": "interior", "label": "Interior",
         "order": "fixed", "order_note": "Plainest first.",
         "categories": add(_cats("interior", INTERIOR_ORDER, INTERIOR_COLOR,
                                 labels=INTERIOR_SHORT)),
         "missing": _OMIT, "caveat": None},
        {"name": "trim", "column": "trim", "label": "Trim", "order": "fixed",
         "categories": add(_cats("trim", list(TRIM_COLORS), TRIM_COLORS)),
         "missing": _OMIT, "caveat": None},
        {"name": "buylease", "column": "buylease", "label": "Purchase or lease",
         "order": "fixed",
         "categories": add(_cats("buylease", ["Purchase", "Lease"], {})),
         "missing": _OMIT, "caveat": None},
        {"name": "r1_owner", "column": "r1_owner", "label": "Current R1 owner",
         "order": "fixed", "categories": add(_cats("r1", ["Yes", "No"], {})),
         "missing": _OMIT,
         "caveat": "A named R1 model counts as ownership even when the yes/no "
                   "answer says No."},
        {"name": "region", "column": "region", "label": "Region", "order": "count",
         "categories": add(_cats("region", list(REGION_COLOR), REGION_COLOR)),
         "missing": {"policy": "bucket", "label": "Unknown"}, "caveat": _SELF},
        {"name": "state", "column": "state", "label": "State / province",
         "order": "count", "categories": None,
         "small_n": {"min_orders": STATE_MIN_ORDERS,
                     "note": "States with fewer orders are summarized by region "
                             "only."},
         "missing": {"policy": "bucket", "label": "No state data"},
         "caveat": _SELF},
        {"name": "delivery_type", "column": "delivery_type",
         "label": "Delivery estimate", "order": "fixed",
         "categories": add(_cats("estimate", [*TYPE_ORDER, "unknown"], TYPE_COLOR,
                                 labels={"explicit": "Firm date",
                                         "window": "Relative window",
                                         "range": "Date range",
                                         "month": "Month",
                                         "unknown": "No date given"})),
         "missing": {"policy": "category", "value": "unknown"},
         "caveat": "Normalized from free text; a window is measured from the "
                   "order date."},
        {"name": "delivered", "column": "delivered_inferred",
         "label": "Delivered (est.)", "order": "fixed",
         "categories": add(_cats("delivered", [True, False], {},
                                 labels={True: "Delivered (est.)",
                                         False: "Awaiting delivery"})),
         "missing": None, "caveat": _INFERRED},
    ]
    for col, label in (("opted_autonomy", "Autonomy+"), ("opted_tow", "Tow package"),
                       ("opted_spare", "Compact spare")):
        dims.append({"name": col, "column": col, "label": label, "order": "fixed",
                     "categories": add(_cats(col, [True, False], {},
                                             labels={True: "Yes", False: "No"})),
                     "missing": None,
                     "caveat": "\"Included\" with the Launch Package counts as yes."
                     if col != "opted_spare" else None})
    return {"version": CONTRACT_VERSION, "palette": palette, "dimensions": dims}


# --- Time series ---------------------------------------------------------------

SERIES_METRICS = {
    "orders": "Unique orders (the dashboard's cohort)",
    "vin_assigned": "Orders with a VIN",
    "estimate_firm": "Orders with a firm delivery date",
    "estimate_vague": "Orders with a window, range or month",
    "estimate_unknown": "Orders with no usable estimate",
    "delivered_inferred": "Orders inferred delivered (estimate passed)",
    "reservations_incomplete": "Reservations not yet ordered",
    "reservations_converted": "Reservation holders found in the orders sheet",
}


def counts(df: pd.DataFrame, report: dict, resv_report: dict | None) -> dict:
    """The series metrics from one cleaning run."""
    dc = report["delivery_counts"]
    return {
        "orders": int(report["n_dedup"]),
        "vin_assigned": int(report["vin_present"]),
        "estimate_firm": int(dc.get("explicit", 0)),
        "estimate_vague": int(sum(dc.get(t, 0) for t in ("window", "range", "month"))),
        "estimate_unknown": int(dc.get("unknown", 0)),
        "delivered_inferred": int(df["delivered_inferred"].astype(bool).sum()),
        "reservations_incomplete": (None if resv_report is None
                                    else int(resv_report["n_incomplete"])),
        "reservations_converted": (None if resv_report is None
                                   else int(resv_report["n_matched"])),
    }


def _latest_by(files: list[tuple[datetime, str]], end: pd.Timestamp) -> str | None:
    """The newest snapshot written before `end`."""
    paths = [p for ts, p in files if pd.Timestamp(ts) < end]
    return paths[-1] if paths else None


def point(day: pd.Timestamp, orders_path: str, resv_path: str | None,
          today: bool = False) -> dict:
    """Clean the snapshots current at `day` as of `day`, and count."""
    as_of = None if today else day
    with open(orders_path) as fh:
        text = fh.read()
    # The cleaning prints nothing itself, but keep a stray warning from
    # interleaving with the pipeline's report.
    with contextlib.redirect_stdout(io.StringIO()):
        df, report, _ = load_and_clean(text, {"label": ORDERS_LABEL}, as_of=as_of)
        resv_report = None
        if resv_path:
            with open(resv_path) as fh:
                _, resv_report = load_reservations(
                    fh.read(), set(df["user"]), report["cancelled_users"],
                    as_of=as_of)
    return {"date": day.date().isoformat(), **counts(df, report, resv_report)}


def series(raw_dir: str | None = None, as_of: pd.Timestamp = AS_OF) -> dict:
    """Every Monday since the first orders snapshot, plus `as_of` (today)."""
    ofiles = snapshot_files(ORDERS_SLUG, raw_dir)
    rfiles = snapshot_files(RESV_SLUG, raw_dir)
    points = []
    if ofiles:
        first = pd.Timestamp(ofiles[0][0]).normalize()
        mondays = pd.date_range(first, as_of, freq="W-MON")
        for day in [d for d in mondays if d < as_of]:
            end = day + pd.Timedelta(days=1)        # end of that day
            path = _latest_by(ofiles, end)
            if path:
                points.append(point(day, path, _latest_by(rfiles, end)))
        points.append(point(as_of, ofiles[-1][1],
                            rfiles[-1][1] if rfiles else None, today=True))
    return {"version": CONTRACT_VERSION, "grain": "weekly (Mondays) + today",
            "metrics": SERIES_METRICS, "points": points}
