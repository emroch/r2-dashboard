"""The published data contract: dimension metadata and an event-dated series.

The hand-off to the presentation rewrite (#66) and reconfigurable charts (#51).
Two JSON files are published next to the cleaned CSV:

  r2_dimensions.json  what each column of r2_orders_clean.csv MEANS for display:
                      src/conf/dimensions.yaml, published verbatim as JSON
                      (labels, category order, blank handling, small-n rule,
                      caveat and note text, per-category colors and markers).
  r2_series.json      daily counts of what was TRUE by each date (#99): orders
                      by order date, VINs by when the final VIN was assigned,
                      deliveries by when they were scheduled and when they
                      happened. Aggregates only, never a per-order history.

"True by date", not "reported by date": the series is built once, from TODAY's
cleaned data, by each order's own event dates, so an order reported on Tuesday
for a Monday order counts on Monday. Early points therefore keep rising as late
reports and better dates arrive. That is true to the data, since the series is
recomputed every build and nothing is cached. How far the sheet lagged behind
events is forum participation, which isn't a goal (#99), so it isn't published.

Milestone dates come from ingest/milestones.py. Anything the sheet already
showed in its first snapshot can only be dated "on or before" that day, so it is
counted on it; `history_start` and `on_history_start` say how much that covers.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from typing import Any

import pandas as pd

from config import AS_OF, DIMENSIONS

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

SERIES_VERSION = 2

SERIES_METRICS = {
    "orders": "Orders placed, by order date",
    "vin_assigned": "Orders whose final VIN had been assigned",
    "delivery_scheduled": "Orders whose final delivery date had been set",
    "delivered": "Orders delivered (inferred: the estimate has passed), by "
                 "delivery date",
    "reservations_outstanding": "Reservations still outstanding today, by "
                                "reservation date",
    "reservations_converted": "Reservation holders who have since ordered, by "
                              "order date",
}


def _event_dates(df: pd.DataFrame, resv: pd.DataFrame,
                 converted: set[str]) -> dict[str, pd.Series]:
    """Each metric's event date per counted order (NaT = no date to count by)."""
    delivered = df[df["delivered_inferred"].astype(bool)]
    vin = df[df["vin_present"].astype(bool)]
    firm = df[df["delivery_type"] == "explicit"]
    conv = df[df["user"].str.lower().isin(converted)]
    return {
        "orders": df["order_date"],
        "vin_assigned": vin["vin_assigned"],
        "delivery_scheduled": firm["delivery_scheduled"],
        "delivered": delivered["delivery_est"],
        "reservations_outstanding": resv["resv_date"],
        "reservations_converted": conv["order_date"],
    }


def series(df: pd.DataFrame, resv: pd.DataFrame, converted: set[str],
           history_start: pd.Timestamp | None, start: pd.Timestamp,
           end: pd.Timestamp = AS_OF) -> dict[str, Any]:
    """Daily cumulative counts from `start` to `end`, from today's cleaned data.

    df         cleaned orders, with milestones (ingest/milestones.py)
    resv       outstanding reservations (load_reservations)
    converted  lowercased usernames of reservation holders who have ordered
    Reservations dated before `start` count from the first point.
    """
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    if history_start is not None:
        history_start = pd.Timestamp(history_start).normalize()
    values, undated, on_start = {}, {}, {}
    for name, dates in _event_dates(df, resv, converted).items():
        d = pd.to_datetime(dates, errors="coerce").dt.normalize()
        undated[name] = int(d.isna().sum())
        # Before the first day (a 2024 reservation): count from the first point.
        d = d.dropna().where(lambda x: x >= days[0], days[0])
        counts = d.value_counts().reindex(days, fill_value=0).cumsum()
        values[name] = [int(v) for v in counts]
        if history_start is not None:
            on_start[name] = int((d == history_start).sum())
    return {
        "version": SERIES_VERSION,
        "basis": "true by date: each order counted on its own event dates, from "
                 "today's data; recent points are provisional and early points "
                 "rise as late reports arrive",
        "history_start": (history_start.date().isoformat()
                          if history_start is not None else None),
        "on_history_start": on_start,
        "metrics": SERIES_METRICS,
        "dates": [x.date().isoformat() for x in days],
        "values": values,
        "undated": undated,
    }
