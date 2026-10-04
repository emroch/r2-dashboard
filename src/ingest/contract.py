"""The published data contract: dimension metadata and an aggregate time series.

Data layer stage 4 (docs/data-layer.md, issue #84), the hand-off to the
presentation rewrite (#66) and reconfigurable charts (#51). Two JSON files are
published next to the cleaned CSV:

  r2_dimensions.json  what each column of r2_orders_clean.csv MEANS for display:
                      src/conf/dimensions.yaml, published verbatim as JSON
                      (labels, category order, blank handling, small-n rule,
                      caveat and note text, per-category colors and markers).
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
from datetime import datetime
from typing import Any

import pandas as pd

from config import AS_OF, DIMENSIONS, ORDERS_LABEL, ORDERS_SLUG, RESV_SLUG

from .history import snapshot_files
from .loaders import load_and_clean, load_reservations

CONTRACT_VERSION = 1


def dimensions() -> dict[str, Any]:
    """dimensions.yaml, as published: the file's data, unchanged.

    Nothing is assembled here on purpose. The YAML is the single, human-edited
    source for the category vocabulary and its display text, and config.py reads
    the same file for the charts, so the published metadata can't drift from
    what the dashboard draws.
    """
    return {"version": CONTRACT_VERSION, "dimensions": DIMENSIONS}


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
