"""Likely data-entry errors: values that parse cleanly but disagree with the data.

A typo'd VIN or delivery date is a perfectly good number on its own. It only shows
up against the other orders, which is why this runs after parsing. Two facts make
the test possible:

  * VINs climb with ORDER DATE. People who ordered in the same week got VINs from
    the same part of the sequence.
  * DELIVERY DATES climb with VIN. Cars with neighbouring VINs reach people at
    about the same time.

Neither has a fixed scale (both keep climbing as production runs), so there is no
cap to set. Each value is compared with its COHORT instead: the running median of
the orders nearest to it along the trend, scaled by a robust spread (MAD) of
everyone's distance from their own cohort. That is a robust z-score against a local
trend line. It follows the trend as numbers climb, and one bad value can't move
the median it is judged by.

Only some disagreements are errors. These two have innocent explanations, so they
are never flagged on direction alone:

  * a LOW VIN on a late order. Cars are held back for repairs and later sold, and
    cancelled orders free up built cars. There are several of these per week.
  * a LATE delivery for its VIN. This is the same held-back car, seen from the
    other side.

So the checks are one-sided where physics makes them so:

  vin       the VIN is extremely far from its order-date cohort, in either
            direction. The threshold sits well past any held-back car seen so far,
            so this catches digit-level typos (an extra or missing digit) rather
            than unusual cars.
  delivery  a firm delivery date falls well BEFORE cars with neighbouring VINs.
            A car can't be delivered before it is built. "8-12" (meant weeks) read
            as 12 August, and "7-10 days" read as 10 July before the parser
            learned days, were both caught this way.

Plus the cross-check against the order's own date, parsing.implausible_latency,
which needs no cohort: an estimate that ends before the order was placed, or
starts a year after it.

A flagged value is SET ASIDE (made unknown) by the caller, not corrected. The data
can't say what the right value is, and the person can fix the sheet or overrides.yaml
can. `verified` in overrides.yaml marks a value that looks wrong but has been
confirmed, so a genuine outlier isn't removed every build.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from config import OUTLIER_COHORT, OUTLIER_EARLY_DELIVERY_Z, OUTLIER_VIN_Z

from .parsing import implausible_latency

# Day-number origin for the date axes. Only differences matter.
_EPOCH = pd.Timestamp("2026-01-01")


def theil_sen(x: Any, y: Any) -> tuple[float, float] | None:
    """Median of pairwise slopes, and the matching intercept; None below 2 points
    or when every x is the same.

    Exact over all pairs — the series it is used on are a few dozen points.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2:
        return None
    i, j = np.triu_indices(len(x), 1)
    keep = x[i] != x[j]
    if not keep.any():
        return None
    slope = float(np.median((y[j][keep] - y[i][keep]) / (x[j][keep] - x[i][keep])))
    return slope, float(np.median(y - slope * x))


def trend_z(x: Any, y: Any,
            cohort: int = OUTLIER_COHORT) -> tuple[np.ndarray, np.ndarray]:
    """Robust z-score of each y against the local trend of its cohort along x.

    The cohort is the `cohort` points nearest in x-order, centred where possible
    and shifted inward at the ends so it is always full. It never includes the
    point being judged. The expected value is a robust line (Theil-Sen) through
    the cohort, read at the point's own x. A plain cohort median would be biased
    at the ends of a climbing trend, where every neighbour lies on one side; a
    line isn't. z is the distance from that expectation, divided by 1.4826 × the
    median absolute deviation of every point's distance from its own expectation
    (≈ one standard deviation for normal noise).

    Returns (z, expected), arrays aligned with the inputs. Both are all NaN when
    there are not enough points to form a cohort or the spread is zero, since then
    there is nothing to compare against.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    z, expect = np.full(n, np.nan), np.full(n, np.nan)
    if n <= cohort:
        return z, expect
    order = np.argsort(x, kind="stable")
    xs, ys = x[order], y[order]
    fit = np.empty(n)
    for k in range(n):
        lo = min(max(k - cohort // 2, 0), n - cohort - 1)
        wx = np.concatenate([xs[lo:k], xs[k + 1:lo + cohort + 1]])
        wy = np.concatenate([ys[lo:k], ys[k + 1:lo + cohort + 1]])
        line = theil_sen(wx, wy)
        # Every neighbour on the same x (one busy order day): the median is the
        # local trend.
        fit[k] = line[0] * xs[k] + line[1] if line else np.median(wy)
    resid = ys - fit
    mad = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    if not mad > 0:
        return z, expect
    z[order], expect[order] = resid / mad, fit
    return z, expect


def _days(ts: Any) -> np.ndarray:
    return (pd.DatetimeIndex(ts) - _EPOCH).days.values.astype(float)


def _date(day: float) -> str:
    return (_EPOCH + pd.Timedelta(days=float(day))).strftime("%b %d")


def find_suspects(df: pd.DataFrame, verified: dict[str, list[str]] | None = None,
                  ) -> tuple[dict[Any, str], dict[Any, str]]:
    """Which VINs and delivery estimates look like entry errors, and why.

    Reads the parsed columns (vin_seq, vin_present, order_date, delivery_min/max/
    est/type). Returns (vin, delivery): dicts of row index -> reason. `verified`
    maps a lower-cased username to the raw fields ("vin_raw", "delivery_raw")
    confirmed correct, which skips every check on that field.
    """
    verified = verified or {}
    checked = {f: {i for i, u in zip(df.index, df["user"])
                   if f not in verified.get(str(u).lower(), ())}
               for f in ("vin_raw", "delivery_raw")}
    vin: dict[Any, str] = {}
    delivery: dict[Any, str] = {}

    # VIN against orders placed around the same date.
    d = df[df["vin_present"].astype(bool) & df["order_date"].notna()]
    z, med = trend_z(_days(d["order_date"]), d["vin_seq"].astype(float))
    for i, v, o, zi, mi in zip(d.index, d["vin_seq"], d["order_date"], z, med):
        if abs(zi) > OUTLIER_VIN_Z and i in checked["vin_raw"]:
            vin[i] = ("VIN %d is far from orders placed around %s (typical ≈ %d) "
                      "— a missing or extra digit?"
                      % (v, o.strftime("%b %d"), round(mi, -2)))

    # The estimate against the order's own date.
    for i, o, mn, mx in zip(df.index, df["order_date"], df["delivery_min"],
                            df["delivery_max"]):
        why = implausible_latency(o, mn, mx)
        if why and i in checked["delivery_raw"]:
            delivery[i] = why

    # A firm delivery date against cars with neighbouring VINs. Only rows whose VIN
    # and date both survived the checks above, so neither side of the comparison is
    # already known to be wrong.
    d = df[df["vin_present"].astype(bool) & (df["delivery_type"] == "explicit")
           & df["delivery_est"].notna()]
    d = d[[i not in vin and i not in delivery for i in d.index]]
    z, med = trend_z(d["vin_seq"].astype(float), _days(d["delivery_est"]))
    for i, est, zi, mi in zip(d.index, d["delivery_est"], z, med):
        if zi < -OUTLIER_EARLY_DELIVERY_Z and i in checked["delivery_raw"]:
            delivery[i] = ("delivery %s is well before cars with nearby VINs "
                           "(typical ≈ %s)" % (est.strftime("%b %d"), _date(mi)))
    return vin, delivery
