"""Aggregates for the presentation layer: counts that add back up to their cohort.

Every number a component shows is computed here, in Python, never in the browser
(docs/presentation.md, ground rules). An aggregate says which COHORT it counts,
and returns both what it counted and what it left out:

    Aggregate(cohort="orders", cells=[...], excluded={"not reported": 3})

so that `cells + excluded == cohort` holds for every one of them. reconcile()
checks exactly that for every aggregate a build makes, and the pipeline stops on a
mismatch. A denominator that silently loses rows (an "answered-only" share that
drops an unanswered order without saying so) then fails the build instead of
shipping.

counts() is the building block the static components share (take-rates, mixes,
heatmap margins): one dimension's categories, ordered and labelled as
dimensions.yaml says, with its blank handling applied.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import DIMENSIONS, PRICE_TRIMS

# The cohorts an aggregate can declare, each a mask over the cleaned orders.
COHORTS: dict[str, Callable[[pd.DataFrame], Any]] = {
    "orders": lambda df: pd.Series(True, index=df.index),
    "vin_assigned": lambda df: df["vin_present"].astype(bool),
    "priced": lambda df: df["price"].notna(),
    "located": lambda df: df["lat"].notna(),
}

# dimensions.yaml names the column as published in r2_orders_clean.csv; the frame
# the renderers get still uses the loader's name for these.
_FRAME_COLUMN = {"r1_owner": "r1_owner_effective"}

NOT_REPORTED = "not reported"


@dataclass
class Aggregate:
    """What one component counts.

    cells     [{value, label, n, ref, known}], in display order. `ref` is the
              "<dimension>:<value>" category reference when the category has a
              color (render/categories.py), else None. `known` is False for a
              value dimensions.yaml doesn't list (a new paint, say): still
              counted, but with no color or label of its own yet.
    excluded  {reason: n}: cohort members deliberately left out.
    dim       the dimension counted, when it is one dimension's counts.
    meta      anything else a template needs (a crosstab's row and column
              order and totals, a summary's statistics).
    basis     for an aggregate whose cells aren't counts that add up (averages
              over the cohort), how many cohort members it is computed over;
              that is what reconciles.
    """
    name: str
    cohort: str
    cells: list[dict[str, Any]]
    excluded: dict[str, int] = field(default_factory=dict)
    dim: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    basis: int | None = None

    @property
    def counted(self) -> int:
        if self.basis is not None:
            return self.basis
        return sum(int(c["n"]) for c in self.cells)


class ReconcileError(Exception):
    pass


def cohort_sizes(df: pd.DataFrame) -> dict[str, int]:
    return {name: int(mask(df).sum()) for name, mask in COHORTS.items()}


def reconcile(aggregates: list[Aggregate], sizes: dict[str, int]) -> None:
    """Raise ReconcileError listing every aggregate whose cells and exclusions
    don't add back up to its declared cohort."""
    bad = []
    for a in aggregates:
        if a.cohort not in sizes:
            bad.append("%s: unknown cohort %r" % (a.name, a.cohort))
            continue
        total = a.counted + sum(a.excluded.values())
        if total != sizes[a.cohort]:
            bad.append("%s: %d counted + %d excluded = %d, but the %s cohort is %d"
                       % (a.name, a.counted, sum(a.excluded.values()), total,
                          a.cohort, sizes[a.cohort]))
    if bad:
        raise ReconcileError("aggregates don't add up:\n  " + "\n  ".join(bad))


def _blank(v: Any) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v)) or \
        (isinstance(v, str) and not v.strip())


# Delivery stages, in reading order: how far an order has got. The split the
# take-rate bars show (theme.yaml's --a-* opacities, one per stage).
#   delivered  its delivery is inferred (the estimated window has passed)
#   scheduled  a firm delivery date, not yet passed. Rivian schedules delivery
#              only after a VIN is assigned, so a scheduled order with no VIN
#              reported is incomplete data, not a contradiction: it counts here.
#   vin        a VIN, no firm date yet
#   wait       neither
STAGES = ("delivered", "scheduled", "vin", "wait")
STAGE_LABELS = {"delivered": "delivered", "scheduled": "delivery scheduled",
                "vin": "with a VIN", "wait": "waiting for a VIN"}


def stages(df: pd.DataFrame) -> pd.Series:
    """Each order's delivery stage (see STAGES)."""
    def yes(v: Any) -> bool:
        return not _blank(v) and bool(v)
    firm = df["delivery_type"] if "delivery_type" in df else pd.Series(
        None, index=df.index)
    return pd.Series(["delivered" if yes(d) else "scheduled" if f == "explicit"
                      else "vin" if yes(v) else "wait"
                      for d, f, v in zip(df["delivered_inferred"], firm,
                                         df["vin_present"])],
                     index=df.index)


def stage_counts(df: pd.DataFrame) -> Aggregate:
    """Every order by delivery stage (STAGES): the summary's Delivery progress
    readouts, split exactly as the take-rate bars are."""
    st = stages(df)
    cells = [{"value": s, "label": STAGE_LABELS[s], "n": int((st == s).sum()),
              "known": True, "ref": None} for s in STAGES]
    return Aggregate("orders by delivery stage", "orders", cells)


def counts(df: pd.DataFrame, dim: str, cohort: str = "orders",
           by_stage: bool = False) -> Aggregate:
    """One dimension's category counts over a cohort.

    Blanks follow the dimension's `missing` policy: `omit` (and no policy)
    excludes them as "not reported"; `bucket` counts them as their own cell,
    labelled; `category` counts them as the named category. Order follows
    `order`: "fixed" is the listed order; "count" is most orders first, the
    listed order breaking ties. Unlisted values come last, most orders first.
    A dimension with no listed categories (state) has an open vocabulary.

    by_stage adds each cell's split by delivery stage, `stages` {stage: n},
    which always sums to the cell's n.
    """
    spec = DIMENSIONS[dim]
    col = _FRAME_COLUMN.get(spec["column"], spec["column"])
    rows = df[COHORTS[cohort](df)]
    return _count(rows[col], stages(rows) if by_stage else None, dim, cohort,
                  spec.get("missing") or {"policy": "omit"})


def r1_models(df: pd.DataFrame, by_stage: bool = False) -> Aggregate:
    """R1 ownership as one list: each model an owner named, owners who didn't
    name one ("Unspecified"), and non-owners ("No R1").

    A blank r1_model means different things depending on the owner question, so
    it can't be one dimension's blank policy: an owner who skipped the follow-up
    is still an owner, and a non-owner was never asked. Uses the reconciled owner
    flag (r1_owner_effective), so a row that named a model counts as an owner.
    Orders that didn't answer the owner question are excluded as not reported.
    """
    owner = df[_FRAME_COLUMN["r1_owner"]]
    model = df["r1_model"]
    unspecified = DIMENSIONS["r1_model"]["missing"]["value"]
    values = pd.Series(
        [None if _blank(o) else
         (unspecified if _blank(m) else m) if o == "Yes" else "No R1"
         for o, m in zip(owner, model)], index=df.index, dtype=object)
    agg = _count(values, stages(df) if by_stage else None, "r1_model", "orders",
                 {"policy": "omit"})
    agg.name = "orders by R1 ownership"
    return agg


def _count(values: pd.Series, stage: pd.Series | None, dim: str, cohort: str,
           missing: dict[str, Any]) -> Aggregate:
    spec = DIMENSIONS[dim]
    listed = spec.get("categories") or []
    by_value = {c["value"]: c for c in listed}
    rank = {c["value"]: i for i, c in enumerate(listed)}
    stage_of = stage if stage is not None else pd.Series(None, index=values.index)

    tally: dict[Any, dict[str, int]] = {}
    blank_stages: dict[str, int] = {}
    for v, st in zip(values, stage_of):
        bucket = blank_stages if _blank(v) else tally.setdefault(v, {})
        bucket[st] = bucket.get(st, 0) + 1
    blanks = sum(blank_stages.values())
    excluded = {}
    if blanks and missing["policy"] == "category":
        into = tally.setdefault(missing["value"], {})
        for st, n in blank_stages.items():
            into[st] = into.get(st, 0) + n
    elif blanks and missing["policy"] != "bucket":
        excluded[NOT_REPORTED] = blanks

    def total(v: Any) -> int:
        return sum(tally[v].values())

    def cell(v: Any, split: dict[str, int], label: str | None = None,
             known: bool = True) -> dict[str, Any]:
        c = by_value.get(v)
        out = {"value": v, "n": sum(split.values()), "known": known,
               "label": label or (c or {}).get("label") or (c or {}).get("short")
               or str(v),
               "ref": "%s:%s" % (dim, v) if c and "color" in c else None}
        if stage is not None:
            out["stages"] = {st: split.get(st, 0) for st in STAGES}
        return out

    known_vals = [v for v in tally if v in by_value or not listed]
    unknown = sorted((v for v in tally if v not in known_vals),
                     key=lambda v: (-total(v), str(v)))
    if spec.get("order") == "fixed":
        known_vals.sort(key=lambda v: rank.get(v, 0))
    else:
        known_vals.sort(key=lambda v: (-total(v), rank.get(v, 0), str(v)))
    cells = ([cell(v, tally[v]) for v in known_vals]
             + [cell(v, tally[v], known=False) for v in unknown])
    if blanks and missing["policy"] == "bucket":
        cells.append(cell(None, blank_stages, label=missing["label"]))
    return Aggregate("%s by %s" % (cohort, dim), cohort, cells, excluded, dim)


def _resolved(values: pd.Series, dim: str) -> pd.Series:
    """Each value as the category it counts as under the dimension's blank
    policy: a blank becomes the named category (`category`), its bucket's label
    (`bucket`: a row of its own, "No state data"), or None, meaning "not
    reported" (`omit`, or no policy)."""
    missing = DIMENSIONS[dim].get("missing") or {"policy": "omit"}
    fill = {"category": missing.get("value"),
            "bucket": missing.get("label")}.get(missing["policy"])
    return pd.Series([fill if _blank(v) else v for v in values], index=values.index,
                     dtype=object)


def binned(values: pd.Series, edges: Sequence[float], unit: str,
           missing: str = "No state data") -> tuple[pd.Series, list[str]]:
    """A numeric column as ordered bin labels ("< 500 ft", "500–1,000 ft",
    "≥ 3,000 ft"); a missing value gets `missing`. `unit` carries its own leading
    space where one is wanted. Returns (labels, keys): keys in NUMERIC order,
    never by volume, since a binned panel asks whether the mix shifts as the
    value rises; empty bins are dropped, so widening an edge leaves no gap."""
    def fmt(v: float) -> str:
        # int(): round() of a numpy float can stay a float on older numpy.
        return format(int(round(v)), ",")  # noqa: RUF046
    names = ["< %s%s" % (fmt(edges[0]), unit)]
    names += ["%s–%s%s" % (fmt(lo), fmt(hi), unit) for lo, hi in zip(edges, edges[1:])]
    names.append("\u2265 %s%s" % (fmt(edges[-1]), unit))

    def label(v: Any) -> str:
        if pd.isna(v):
            return missing
        return next((n for n, e in zip(names, edges) if v < e), names[-1])
    out = pd.Series([label(v) for v in values], index=values.index, dtype=object)
    keys = [n for n in names if (out == n).any()]
    return out, keys + ([missing] if (out == missing).any() else [])


def crosstab(df: pd.DataFrame, row_dim: str | None, col_dim: str,
             cohort: str = "orders", rows: tuple[pd.Series, list[str]] | None = None,
             small_n: bool = False) -> Aggregate:
    """Counts of every (row, column) pairing of two dimensions.

    An order that hasn't reported either dimension (after its blank policy)
    is excluded as not reported, so the grid covers the orders that reported
    both. Rows and columns are each dimension's categories present among those
    orders, in its own order (counts()). Every row × column cell is listed,
    zeros included, row by row. meta["rows"] and meta["cols"] are the ordered
    categories with their totals (the grid's margins), and meta["baseline"] the
    column categories over every cohort order that reported the column, the
    row a panel's rows are read against.

    `rows` groups by something that isn't a dimension instead: (a label per
    order, the labels in display order), from binned(). `small_n` applies the
    row dimension's small_n rule: a row category under its min_orders is
    excluded with that reason (dimensions.yaml says where it is summarized).
    """
    d = df[COHORTS[cohort](df)]
    cspec = DIMENSIONS[col_dim]
    c = _resolved(d[_FRAME_COLUMN.get(cspec["column"], cspec["column"])], col_dim)
    bin_keys: list[str] = []
    if rows is None:
        assert row_dim is not None
        rspec = DIMENSIONS[row_dim]
        r = _resolved(d[_FRAME_COLUMN.get(rspec["column"], rspec["column"])], row_dim)
    else:
        r, bin_keys = rows[0].reindex(d.index), rows[1]
    both = r.notna() & c.notna()
    excluded = {NOT_REPORTED: int((~both).sum())} if (~both).any() else {}
    # Blanks are already resolved above, so nothing is left for _count to drop.
    baseline = _count(c[c.notna()], None, col_dim, cohort, {"policy": "omit"}).cells
    if row_dim is not None:
        row_cells = _count(r[both], None, row_dim, cohort, {"policy": "omit"}).cells
    else:
        sizes = r[both].value_counts()
        row_cells = [{"value": k, "label": k, "n": int(sizes[k]), "known": True,
                      "ref": None} for k in bin_keys if k in sizes.index]
    if small_n:
        assert row_dim is not None
        least = int(DIMENSIONS[row_dim]["small_n"]["min_orders"])
        thin = [rc for rc in row_cells if rc["n"] < least]
        if thin:
            excluded["fewer than %d orders" % least] = sum(rc["n"] for rc in thin)
            row_cells = [rc for rc in row_cells if rc["n"] >= least]
            both &= r.isin([rc["value"] for rc in row_cells])
    col_cells = _count(c[both], None, col_dim, cohort, {"policy": "omit"}).cells
    # Columns (and the baseline) keep the whole cohort's order of the column
    # dimension, so a paint sits in the same place here as in every other paint
    # component (#58), whatever subset this grid counts.
    rank = {cc["value"]: i for i, cc in enumerate(counts(df, col_dim).cells)}
    for lst in (col_cells, baseline):
        lst.sort(key=lambda cc: rank.get(cc["value"], len(rank)))
    pairs = Counter(zip(r[both], c[both]))
    cells = []
    for rc in row_cells:
        for cc in col_cells:
            n = pairs.get((rc["value"], cc["value"]), 0)
            cells.append({"row": rc["value"], "col": cc["value"], "n": n,
                          "label": "%s · %s" % (rc["label"], cc["label"]),
                          "row_label": rc["label"], "col_label": cc["label"],
                          "row_ref": rc["ref"], "col_ref": cc["ref"],
                          "ref": rc["ref"], "known": rc["known"] and cc["known"]})
    return Aggregate("%s by %s × %s" % (cohort, row_dim or "bin", col_dim), cohort,
                     cells, excluded,
                     meta={"rows": row_cells, "cols": col_cells, "baseline": baseline,
                           "row_dim": row_dim, "col_dim": col_dim,
                           "lean": lean(row_cells, cells, baseline)})


# A row needs this many orders before its share can headline a summary: below
# it, one order moves a share by 5+ points.
LEAN_MIN_ORDERS = 20


def lean(rows: list[dict], cells: list[dict], baseline: list[dict]) -> str:
    """The biggest departure from the baseline in a crosstab, as a sentence
    fragment ("Launch Green at 31% of Midwest orders (24% across all orders)"),
    among rows with LEAN_MIN_ORDERS or more."""
    total = sum(int(b["n"]) for b in baseline)
    base = {b["value"]: int(b["n"]) / total for b in baseline} if total else {}
    size = {r["value"]: int(r["n"]) for r in rows}
    best = None
    for c in cells:
        n = size[c["row"]]
        if n < LEAN_MIN_ORDERS or c["col"] not in base:
            continue
        gap = int(c["n"]) / n - base[c["col"]]
        if best is None or abs(gap) > abs(best[0]):
            best = (gap, c)
    if best is None:
        return "no group has %d orders yet" % LEAN_MIN_ORDERS
    gap, c = best
    return "%s at %s of %s orders (%s across all orders)" % (
        c["col_label"], "%.0f%%" % (100.0 * int(c["n"]) / size[c["row"]]),
        c["row_label"],
        "%.0f%%" % (100.0 * base[c["col"]]))


# --- Configured price (§4) --------------------------------------------------------
# Over the "priced" cohort: orders whose whole configuration has a published
# price. An unpriced order is counted in the report and the data-quality panel,
# never here as zero.

def _money(v: float) -> str:
    return "$%s" % format(round(v), ",")


def price_distribution(df: pd.DataFrame) -> Aggregate:
    """Orders per exact configured price, highest first. The cohort lands on a few
    exact totals (options are fixed amounts), so these are exact prices, not
    bins. The cell nearest the median is marked: an even count can put the
    median between two prices."""
    d = df[COHORTS["priced"](df)]
    counts = d["price"].value_counts().sort_index()
    meta: dict[str, Any] = {}
    cells = []
    if len(d):
        prices = [float(p) for p in counts.index]
        med = float(d["price"].median())
        mi = min(range(len(prices)), key=lambda i: abs(prices[i] - med))
        cells = [{"value": p, "label": _money(p), "n": int(k), "known": True,
                  "ref": None, "highlight": i == mi,
                  "note": "median" if i == mi else ""}
                 for i, (p, k) in enumerate(zip(prices, counts.values))][::-1]
        meta = {"median": _money(med), "mean": _money(float(d["price"].mean())),
                "min": _money(float(d["price"].min())),
                "max": _money(float(d["price"].max()))}
    return Aggregate("priced by exact price", "priced", cells, meta=meta)


# The option categories priced, in reading order, and the note a $0 row carries:
# "nobody bought the upgrade" and "everybody gets it free" both show $0 and mean
# opposite things, so a zero row is kept only with a note saying which.
_OPTIONS = (("price_drive", "Drive system", None), ("price_paint", "Paint", None),
            ("price_wheels", "Wheels", None),
            ("price_interior", "Interior", "none paid yet"),
            ("price_spare", "Compact spare", None),
            ("price_autonomy_tow", "Autonomy+ / Tow", "bundled"))


def price_options(df: pd.DataFrame) -> Aggregate:
    """Average spend per option category across every priced order, with the
    share that paid for it, biggest first. The trim base is left out: a constant
    per trim, ~140x the largest option, it would flatten every other row.
    Reconciles by basis (every priced order is in every average)."""
    d = df[COHORTS["priced"](df)]
    n = len(d)
    held = (int((d["opted_autonomy"].astype(bool) | d["opted_tow"].astype(bool)).sum())
            if n and {"opted_autonomy", "opted_tow"} <= set(d.columns) else 0)
    cells: list[dict[str, Any]] = []
    for col, label, zero_note in _OPTIONS if n else ():
        v = d[col].fillna(0)
        avg, paid = float(v.mean()), v[v > 0]
        if not avg and zero_note is None:
            continue                     # doesn't apply to anyone: no row at all
        if len(paid):
            pct = 100.0 * len(paid) / n
            # Under a percent rounds to "0% chose", which reads as nobody.
            note = ("%d of %d paid · %s" % (len(paid), n, _money(float(paid.mean())))
                    if pct < 1 else
                    "%.0f%% chose · %s avg" % (pct, _money(float(paid.mean()))))
        elif zero_note == "bundled":
            note = "included free for %d of %d" % (held, n)
        else:
            note = zero_note or ""
        cells.append({"value": label, "label": label, "amount": avg,
                      "display": _money(avg), "note": note, "n": len(paid),
                      "known": True, "ref": None})
    cells.sort(key=lambda c: -float(c["amount"]))
    meta: dict[str, Any] = {}
    if n:
        extra = float((d["price"] - d["price_base"].fillna(0)).mean())
        meta = {"options_mean": _money(extra),
                "options_share": "%.1f%%" % (100.0 * extra / float(d["price"].mean()))}
    return Aggregate("priced option spend", "priced", cells, meta=meta, basis=n)


def price_by_trim(df: pd.DataFrame) -> Aggregate:
    """The configured-price spread per trim, every trim in pricing.yaml's order
    whether it has orders or not: min, quartiles, median, max and mean. The axis
    (meta lo..hi) is shared, padded by 8% of the range or $500."""
    d = df[COHORTS["priced"](df)]
    cells = []
    for trim in PRICE_TRIMS:
        p = d.loc[d["price_trim"] == trim, "price"].astype(float)
        stats = ({k: float(p.quantile(q)) for k, q in
                  (("min", 0), ("q1", .25), ("median", .5), ("q3", .75), ("max", 1))}
                 if len(p) else {})
        if len(p):
            stats["mean"] = float(p.mean())
        cells.append({"value": trim, "label": trim, "n": len(p), "stats": stats,
                      "known": True, "ref": None})
    meta: dict[str, Any] = {}
    if len(d):
        lo, hi = float(d["price"].min()), float(d["price"].max())
        pad = max((hi - lo) * 0.08, 500.0)
        meta = {"lo": lo - pad, "hi": hi + pad,
                "medians": "; ".join(
                    "%s %s" % (c["label"], _money(c["stats"]["median"]))
                    for c in cells if c["n"])}
    return Aggregate("priced by trim", "priced", cells, meta=meta)
