"""Milestone dates: when each order's FINAL VIN and final delivery date took hold.

Issue #99 (docs/data-layer.md). Two milestones per order:

  vin_assigned        when the order's final VIN was assigned
  delivery_scheduled  when its final firm delivery date was set

Each comes from one of three places, best first:

  curated   a date in overrides.yaml (`dates:` on an override or addition), from a
            post that says when it happened. It must fit the snapshot history (see
            below); a date that doesn't is reported and not used
  sheet     the first snapshot that showed the final value, i.e. the sheet's own
            record. An upper bound: it happened by then, perhaps earlier
  curation  the as_of of the override or addition that supplied the value, when
            the final value never appeared in the sheet at all

Only the FINAL value matters. A VIN that was entered, removed, and replaced a week
later dates from the replacement: a year on, what matters is how long the final
assignment took, not the transient values, which can't be told apart from typo
fixes anyway (#99). "The final value" is compared by meaning: a VIN by its
sequence number (so "X1435" and "01435" are one VIN), a delivery date by the date
it parses to.

These dates stay internal. They feed the event-dated series (ingest/contract.py)
and later analysis (#34), but are not exported per order: per-order history is not
published.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from config import ADDITIONS, AS_OF, OVERRIDES

from . import curation
from .history import History
from .parsing import clean_vin, parse_delivery

Record = tuple[str, str, str]   # (sheet "#", username, detail) for the QA panel


def _final_run_start(runs: list[tuple], same) -> tuple | None:
    """(first_seen, after) of the trailing block of runs that all mean the final
    value, or None when the latest run doesn't mean it (it came from curation).

    `runs` is [(value, first_seen, after), ...] in time order; `same(value)` says
    whether a raw value means the final one.
    """
    start = None
    for v, first, after in reversed(runs):
        if not same(v):
            break
        start = (first, after)
    return start


def _same_vin(seq):
    """Whether a raw VIN means sequence `seq` ("X1435" and "01435" both do)."""
    def same(v):
        s, present, _ = clean_vin(v)
        return present and s == seq
    return same


def _same_firm_date(est, order_date):
    """Whether a raw delivery estimate is the firm date `est`."""
    def same(v):
        p = parse_delivery(v, order_date)
        return p["type"] == "explicit" and p["est"] == est
    return same


def _runs(h: History, field: str) -> dict[str, list[list[tuple]]]:
    """Lowercased username -> one run list per order key of that user.

    By user, not by key: de-duplication merges a user's repeat submissions of
    one build into the earliest row, filling its fields from the later ones, so
    the final value can live in a sibling key's history (dingular's VIN is on
    dingular#2's row). A repeat submission is the same order, so any of them
    showing the final value dates it.
    """
    e = h.events[h.events["field"] == field].sort_values(["key", "first_seen"])
    per_key: dict[str, list[tuple]] = {}
    for k, v, f, a in zip(e["key"], e["value"], e["first_seen"], e["after"]):
        per_key.setdefault(k, []).append((v, f, None if pd.isna(a) else a))
    out: dict[str, list[list[tuple]]] = {}
    for k, runs in per_key.items():
        out.setdefault(k.split("#")[0], []).append(runs)
    return out


def _curated(df: pd.DataFrame) -> dict[int, list[curation.Entry]]:
    """df row -> the curation entries (overrides, additions) that target it, by
    order key for `user#n`, else the user's latest row, as overrides apply."""
    by_key = dict(zip(df["key"], df.index))
    by_user: dict[str, int] = {}
    for i, u in zip(df.index, df["user"]):
        by_user[str(u).lower()] = i            # last row wins: the latest order
    out: dict[int, list[curation.Entry]] = {}
    for e in curation.entries(OVERRIDES) + curation.entries(ADDITIONS):
        t = e.target.lower()
        i = by_key.get(t) if "#" in t else by_user.get(t)
        if i is not None:
            out.setdefault(i, []).append(e)
    return out


def milestones(df: pd.DataFrame, h: History) -> tuple[pd.DataFrame, list[Record]]:
    """Add vin_assigned / delivery_scheduled (Timestamps, NaT when the order has
    no such final value) to a cleaned orders frame. Returns (df, qa_records)."""
    vin_runs, deliv_runs = _runs(h, "vin_raw"), _runs(h, "delivery_raw")
    entries = _curated(df)
    issues: list[Record] = []
    out: dict[str, list[Any]] = {m: [pd.NaT] * len(df)
                                 for m in curation.MILESTONES}
    for n, i in enumerate(df.index):
        r = df.loc[i]
        mine = entries.get(i, [])
        order = r["order_date"]
        user = str(r["user"]).lower()
        firm = r["delivery_type"] == "explicit" and pd.notna(r["delivery_est"])
        finals = {
            "vin_assigned": (bool(r["vin_present"]), _same_vin(r["vin_seq"]),
                             vin_runs.get(user, []), "vin_raw"),
            "delivery_scheduled": (firm, _same_firm_date(r["delivery_est"], order),
                                   deliv_runs.get(user, []), "delivery_raw"),
        }
        for m, (has_final, same, runs, field) in finals.items():
            curated = next((e.dates[m] for e in mine if e.dates.get(m)), None)
            if not has_final:
                if curated:
                    issues.append((r["orig_num"], r["user"],
                                   "%s %s given, but the order has no final %s"
                                   % (m, curated,
                                      "VIN" if field == "vin_raw"
                                      else "firm delivery date")))
                continue
            starts = [s for s in (_final_run_start(rs, same) for rs in runs) if s]
            start = min(starts, key=lambda s: s[0]) if starts else None
            bound = start[0] if start else None        # first snapshot showing it
            if start is None:
                # The final value never appeared in the sheet: it came from
                # curation, which is when we learned it.
                src = next((e.as_of for e in mine if field in (e.body or {})
                            and e.as_of), None)
                bound = pd.Timestamp(src) if src else None
            date_ = bound
            if start and pd.notna(order) and bound is not None and bound < order:
                issues.append((r["orig_num"], r["user"],
                               "the sheet showed the final %s on %s, before the "
                               "order date (%s) — one of the two is wrong"
                               % ("VIN" if field == "vin_raw" else "delivery date",
                                  pd.Timestamp(bound).date(), order.date())))
            if curated:
                why = _misfit(curated, order, bound if start else None,
                              r["delivery_est"] if m == "delivery_scheduled"
                              else None)
                if why:
                    issues.append((r["orig_num"], r["user"],
                                   "%s %s not used: %s" % (m, curated, why)))
                else:
                    date_ = pd.Timestamp(curated)
            out[m][n] = (pd.Timestamp(date_).normalize() if date_ is not None
                         else pd.NaT)
    for m, vals in out.items():
        df[m] = pd.to_datetime(pd.Series(vals, index=df.index), errors="coerce")
    return df, issues


def _misfit(d: date, order, shown, delivery) -> str | None:
    """Why a curated milestone date can't be right, or None."""
    t = pd.Timestamp(d)
    if t > AS_OF:
        return "it is in the future"
    if pd.notna(order) and t < order:
        return "it is before the order date (%s)" % order.date()
    if shown is not None and t.normalize() > pd.Timestamp(shown).normalize():
        return ("the sheet already showed the final value on %s"
                % pd.Timestamp(shown).date())
    if delivery is not None and pd.notna(delivery) and t > delivery:
        return "it is after the delivery date (%s)" % delivery.date()
    return None
