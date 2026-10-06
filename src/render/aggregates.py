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

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import DIMENSIONS

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
    """
    name: str
    cohort: str
    cells: list[dict[str, Any]]
    excluded: dict[str, int] = field(default_factory=dict)
    dim: str | None = None

    @property
    def counted(self) -> int:
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
