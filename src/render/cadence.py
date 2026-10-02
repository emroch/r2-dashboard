"""Build cadence: how fast VINs are being issued, and where the build front is heading.

Delivery date stands in for build date. The build-to-delivery lag changes WHEN a
VIN shows up but barely changes the slope, and the slope is the rate. Inputs are
orders with a VIN and a FIRM delivery date that passes the order-date contradiction
check (parsing.implausible_latency): a range or window would put a guessed midpoint
on the time axis.

Three ideas carry the design:

  * The FRONT, not the middle. Low VINs keep being delivered weeks later (cars held
    back, slower shipping), so the median VIN delivered in a week tracks lag as much
    as production. A high percentile tracks the newest cars reaching people.
  * A RECENT robust rate. Production is ramping (the median VIN delivered went from
    ~1,300 in June to ~8,300 in September), so one line through everything averages
    the launch pace into today's. The rate is a Theil-Sen slope over the last few
    weeks of front, which a typo'd VIN can't drag.
  * A SELF-CALIBRATING, ASYMMETRIC band. The band is not a chosen number: the same
    fit is re-run as of earlier weeks on every build, its projections compared with
    what was then delivered, and each side of the band is the projection's typical
    (mean) miss in that direction. Production is still ramping,
    and the ramp has come in steps (cadence more than doubled in two weeks in mid-
    August) rather than smoothly, so the misses are lopsided — the real front has
    run AHEAD far more than behind. A symmetric band would understate the upside and
    overstate the downside.

    The line itself stays a constant recent rate on purpose. Models that extrapolate
    the ramp (a curved front, or a trend in the rate) were back-tested on this data
    and did worse: they learn the August jump and carry it into the September
    plateau, overshooting by thousands of VINs. Nothing in the data says WHEN the
    next step comes, but the back-test does say how big past ones were — so the
    ramp is represented in the band, where it is measured, not in the line, where
    it would be guessed.

With too little history to measure, there is no projection at all.

The projection is published in aggregate only — where the front is heading — never
as a per-order delivery date.
"""
import numpy as np
import pandas as pd

from config import (AS_OF, CADENCE_BACKTEST_CUTS, CADENCE_FRONT_Q,
                    CADENCE_HORIZON_WEEKS, CADENCE_MIN_WEEK_N, CADENCE_WINDOW_WEEKS)
from ingest.parsing import implausible_latency

# Origin for the day-number axis the fits run on. Any Monday works; only
# differences matter.
_EPOCH = pd.Timestamp("2026-01-05")


def cadence_frame(df):
    """Orders usable for cadence: a VIN, a firm delivery date, no contradiction.

    Adds `vin` (float) and `week` (Monday the delivery week starts on).
    """
    d = df[df["vin_present"].astype(bool) & (df["delivery_type"] == "explicit")
           & df["delivery_est"].notna()].copy()
    ok = [implausible_latency(o, mn, mx) is None for o, mn, mx in
          zip(d["order_date"], d["delivery_min"], d["delivery_max"])]
    d = d[ok]
    d["vin"] = d["vin_seq"].astype(float)
    d["week"] = d["delivery_est"].dt.to_period("W-SUN").dt.start_time
    return d


def _mid_day(weeks):
    """Mid-week day number (Thursday) for an index/array of week starts."""
    return ((pd.DatetimeIndex(weeks) - _EPOCH).days + 3).astype(float)


def theil_sen(x, y):
    """Median of pairwise slopes, and the matching intercept; None below 2 points.

    Exact over all pairs — front series are a few dozen points at most.
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


def build_front(d, q=CADENCE_FRONT_Q, min_n=CADENCE_MIN_WEEK_N, as_of=AS_OF):
    """The weekly build front: the q-quantile VIN delivered each week, for weeks
    with at least `min_n` firm dates. Indexed by week start, ascending.

    Only weeks that have FINISHED by `as_of`. A firm date in a week still to come is
    a scheduled delivery, and a future week holds only the few people who already
    have one — so its high percentile sits low, and a single such week dragged the
    current rate from ~140 to ~97 VINs/day.
    """
    if d.empty:
        return pd.Series(dtype=float)
    d = d[d["week"] + pd.Timedelta(days=7) <= as_of]
    if d.empty:
        return pd.Series(dtype=float)
    g = d.groupby("week")["vin"]
    front = g.quantile(q)[g.size() >= min_n]
    return front.sort_index()


def fit_rate(front, window_weeks=CADENCE_WINDOW_WEEKS, end=None):
    """Robust slope (VINs/day) over the last `window_weeks` of front up to `end`.

    Returns (slope, intercept, n_points) on the mid-week day axis, or None if fewer
    than 3 front points fall in the window — two points can't show a rate is stable.
    """
    f = front if end is None else front[front.index <= end]
    if f.empty:
        return None
    f = f[f.index > f.index.max() - pd.Timedelta(weeks=window_weeks)]
    if len(f) < 3:
        return None
    fit = theil_sen(_mid_day(f.index), f.values)
    if fit is None or fit[0] <= 0:
        return None
    return fit[0], fit[1], len(f)


def backtest(d, horizon_weeks=CADENCE_HORIZON_WEEKS, cuts=CADENCE_BACKTEST_CUTS,
             **kw):
    """Projection error, in days, measured on this data's own history.

    For each week with enough history behind it, fit on deliveries BEFORE that week
    and project the front forward; compare with the front actually observed in the
    following weeks. Error is converted from VINs to days at the fitted rate, signed
    so positive means the real front ran AHEAD of the projection. Only the `cuts`
    most recent cut weeks are used, so the error describes the current regime rather
    than the launch ramp. Returns rows of (cut, horizon, err_days).
    """
    front_kw = {k: v for k, v in kw.items() if k in ("q", "min_n", "as_of")}
    full = build_front(d, **front_kw)
    window = kw.get("window_weeks", CADENCE_WINDOW_WEEKS)
    rows = []
    # A cut needs at least one later observed week to be compared against.
    for cut in list(full.index[:-1])[-cuts:]:
        train = d[d["delivery_est"] < cut]
        fit = fit_rate(build_front(train, **front_kw), window)
        if fit is None:
            continue
        slope, icept, _ = fit
        later = full[(full.index >= cut)
                     & (full.index < cut + pd.Timedelta(weeks=horizon_weeks))]
        for week, actual in later.items():
            h = int((week - cut).days // 7) + 1
            pred = slope * _mid_day([week])[0] + icept
            rows.append((cut, h, (actual - pred) / slope))
    return pd.DataFrame(rows, columns=["cut", "horizon", "err_days"])


def rate_history(df, window_weeks=CADENCE_WINDOW_WEEKS):
    """The rolling rate as of each front week: Series of VINs/day by week start."""
    front = build_front(cadence_frame(df))
    out = {}
    for week in front.index:
        fit = fit_rate(front, window_weeks, end=week)
        if fit is not None:
            out[week] = fit[0]
    return pd.Series(out, dtype=float)


def projection(df, horizon_weeks=CADENCE_HORIZON_WEEKS):
    """Observed front, current rate, and the projected front with its error band.

    Returns None when there isn't enough history to fit a rate AND measure its error
    — an unmeasured band would be a guess presented as a forecast. Otherwise a dict:

      front        observed weekly front (Series by week start)
      rate         current VINs/day; fit_points: front weeks it rests on
      weeks        projected week starts, the last observed week first (zero width)
      center, lo, hi   projected front VIN and band, per projected week
      ahead_days   per horizon: mean miss when the real front ran AHEAD of the
                   projection (the band's upper side), non-decreasing
      behind_days  per horizon: mean miss when it fell BEHIND (the lower side)
      bias_days    mean signed back-test error (+ = reality ran ahead)
      n_backtest   how many projected-vs-actual comparisons the band rests on
    """
    d = cadence_frame(df)
    front = build_front(d)
    fit = fit_rate(front)
    if fit is None:
        return None
    slope, icept, n_fit = fit
    bt = backtest(d, horizon_weeks=horizon_weeks)
    if bt.empty:
        return None
    by_h = bt.groupby("horizon")["err_days"]
    # Only horizons the back-test actually measured, and never narrower further
    # out than nearer in — fewer samples at long horizons can't mean more certainty.
    horizons = [h for h in range(1, horizon_weeks + 1) if h in by_h.groups]
    if not horizons:
        return None
    # Mean miss on each side, rather than the worst: with one step change in the
    # history so far, the worst-case envelope reads as "expect another tripling", and
    # with 6-8 comparisons per horizon a percentile is too coarse to mean much. A side
    # with no misses at all has zero width — the projection hasn't erred that way.
    def side(h, sign):
        e = sign * by_h.get_group(h)
        return float(e[e > 0].mean()) if (e > 0).any() else 0.0
    ahead = np.maximum.accumulate([side(h, +1) for h in horizons])
    behind = np.maximum.accumulate([side(h, -1) for h in horizons])

    last = front.index.max()
    weeks = [last] + [last + pd.Timedelta(weeks=h) for h in horizons]
    days = _mid_day(weeks)
    center = slope * days + icept
    up = np.concatenate([[0.0], ahead]) * slope
    down = np.concatenate([[0.0], behind]) * slope
    return dict(front=front, rate=slope, fit_points=n_fit, weeks=weeks,
                center=center, lo=center - down, hi=center + up,
                ahead_days=list(ahead), behind_days=list(behind),
                bias_days=float(bt["err_days"].mean()), n_backtest=len(bt))
