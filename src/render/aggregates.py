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


def counts(df: pd.DataFrame, dim: str, cohort: str = "orders") -> Aggregate:
    """One dimension's category counts over a cohort.

    Blanks follow the dimension's `missing` policy: `omit` (and no policy)
    excludes them as "not reported"; `bucket` counts them as their own cell,
    labelled; `category` counts them as the named category. Order follows
    `order`: "fixed" is the listed order; "count" is most orders first, the
    listed order breaking ties. Unlisted values come last, most orders first.
    A dimension with no listed categories (state) has an open vocabulary.
    """
    spec = DIMENSIONS[dim]
    col = _FRAME_COLUMN.get(spec["column"], spec["column"])
    rows = df[COHORTS[cohort](df)]
    missing = spec.get("missing") or {"policy": "omit"}
    listed = spec.get("categories") or []
    by_value = {c["value"]: c for c in listed}
    rank = {c["value"]: i for i, c in enumerate(listed)}

    tally: dict[Any, int] = {}
    blanks = 0
    for v in rows[col]:
        if _blank(v):
            blanks += 1
        else:
            tally[v] = tally.get(v, 0) + 1
    excluded = {}
    if blanks and missing["policy"] == "category":
        tally[missing["value"]] = tally.get(missing["value"], 0) + blanks
    elif blanks and missing["policy"] != "bucket":
        excluded[NOT_REPORTED] = blanks

    def cell(v: Any, n: int) -> dict[str, Any]:
        c = by_value.get(v)
        known = c is not None or not listed
        label = (c or {}).get("label") or (c or {}).get("short") or str(v)
        return {"value": v, "label": label, "n": n, "known": known,
                "ref": "%s:%s" % (dim, v) if c and "color" in c else None}

    known_vals = [v for v in tally if v in by_value or not listed]
    unknown = sorted((v for v in tally if v not in known_vals),
                     key=lambda v: (-tally[v], str(v)))
    if spec.get("order") == "fixed":
        known_vals.sort(key=lambda v: rank.get(v, 0))
    else:
        known_vals.sort(key=lambda v: (-tally[v], rank.get(v, 0), str(v)))
    cells = [cell(v, tally[v]) for v in known_vals + unknown]
    if blanks and missing["policy"] == "bucket":
        cells.append({"value": None, "label": missing["label"], "n": blanks,
                      "known": True, "ref": None})
    return Aggregate("%s by %s" % (cohort, dim), cohort, cells, excluded, dim)
