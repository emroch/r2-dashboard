"""Snapshot replay: every committed cache of a sheet, read back into order history.

Stage 1 of the data layer (docs/data-layer.md, issue #81). Internal only: nothing
here is charted or published yet. It turns the timestamped caches under data/raw/
into three things:

  snapshots  the cache timestamps, oldest first
  orders     one row per ORDER KEY: who, when it was first and last seen, and
             whether it has dropped out of the sheet
  events     the value history of every raw field, as runs:
             (key, field, value, first_seen, last_seen, after)

ORDER KEYS. The sheet's "#" column is not an identity: one deleted row renumbered
the 124 rows after it. Usernames are stable, but one person can hold several rows
(a second order, or a resubmission). So an order is keyed by its lowercased
username, and a user's second and later orders get "#2", "#3", ... in the order
they first appeared. Rows are matched to known orders by how many fields agree, not
by position, so deleting one of a user's rows can't shift the others' keys.

TIME. A snapshot is written only when the sheet changed, so a value seen first in
the snapshot at `first_seen` took hold some time after the previous snapshot
(`after`) and by `first_seen`. That interval is all that is known. A value already
present in the very first snapshot has `after` = None: it held "on or before" then.

Values are the raw sheet text, before any cleaning or curation. The cleaning in
loaders.py applies on top of them, so the history records what the sheet said.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

import pandas as pd

from config import (CACHE_TS_FMT, ORDERS_HEADERS, ORDERS_IGNORED,
                    ORDERS_LABEL, ORDERS_SLUG, RESERVATIONS_COLUMNS,
                    RESV_IGNORED, RESV_LABEL, RESV_SLUG)

from .fetch import known_caches, read_cache
from .schema_check import read_sheet

# Fields that say which order a row is, weighted by how rarely they change. The
# configuration and dates almost never change (5 of 674 orders ever changed their
# configuration); a delivery estimate or VIN changes all the time, so they only
# break ties. "#" and the username are not compared: rows are only ever matched
# within one username, and "#" can shift.
_MATCH_WEIGHTS: dict[str, dict[str, float]] = {
    "orders": {"order_raw": 3, "resv_raw": 3, "trim": 2, "color": 2, "wheels": 2,
               "interior": 2, "launch": 1, "loc_raw": 1, "buylease": 1,
               "vin_raw": 1, "delivery_raw": 0.5},
    "reservations": {"resv_raw": 3, "loc_raw": 1},
}

# A row must agree with a known order on at least this share of the weights to be
# that order. Below it, the row is a different order that happens to share a
# username — e.g. one of a user's rows deleted while a new one is added.
_MIN_SHARE = 0.4

# Not tracked as field history: "#" is a position, and the username is the key.
_UNTRACKED = ("orig_num", "user")


class History(NamedTuple):
    snapshots: list[datetime]
    orders: pd.DataFrame
    events: pd.DataFrame


def snapshot_files(slug: str, raw_dir: str | None = None) -> list[tuple[datetime, str]]:
    """(timestamp, source) for every cache of a sheet, oldest first.

    By default every cache the fetch knows about (fetch.known_caches): the files
    in data/raw/ plus any committed on origin/main that aren't on disk yet, so
    the newest snapshot replayed is the one being cleaned even on a branch that
    hasn't merged main lately. With an explicit raw_dir, just that directory.
    """
    if raw_dir is None:
        return sorted((datetime.strptime(ts, CACHE_TS_FMT), src)
                      for ts, src in known_caches(slug))
    pat = re.compile(re.escape(slug) + r"_(\d{8}-\d{6})\.csv$")
    out = [(datetime.strptime(m.group(1), CACHE_TS_FMT), os.path.join(raw_dir, fn))
           for fn in os.listdir(raw_dir) for m in [pat.match(fn)] if m]
    return sorted(out)


def _score(a: dict, b: dict, weights: dict) -> float:
    return sum(w for f, w in weights.items() if a.get(f, "") == b.get(f, ""))


def _match(known: list[str], last: dict, rows: list[dict],
           weights: dict) -> list[str | None]:
    """Assign each row (one user's rows in one snapshot, in sheet order) to one of
    that user's known order keys, or None for a new order.

    Greedy over (row, key) pairs by descending agreement, ignoring pairs below
    _MIN_SHARE. Ties go to the earlier row and the earlier key, so a user's rows
    that are all alike map in order.
    """
    floor = _MIN_SHARE * sum(weights.values())
    pairs = sorted((-sc, i, j)
                   for i, r in enumerate(rows) for j, k in enumerate(known)
                   for sc in [_score(r, last[k], weights)] if sc >= floor)
    out: list[str | None] = [None] * len(rows)
    used: set[str] = set()
    for _neg, i, j in pairs:
        if out[i] is None and known[j] not in used:
            out[i] = known[j]
            used.add(known[j])
    return out


def replay(snapshots: Iterable[tuple[datetime, list[str], list[list[str]]]],
           kind: str = "orders") -> History:
    """Build the history from (timestamp, fields, rows) snapshots, oldest first.

    `kind` picks the match weights ("orders" or "reservations"). Pure: reading the
    files is snapshot_history's job, so tests can feed synthetic snapshots.
    """
    all_weights = _MATCH_WEIGHTS[kind]
    times: list[datetime] = []
    by_user: dict[str, list[str]] = {}     # lowercased user -> keys, first-seen order
    last: dict[str, dict] = {}             # key -> its row in the latest snapshot
    info: dict[str, dict] = {}             # key -> orders-table row
    # (key, field) -> runs of [value, first_seen, last_seen, after]
    runs: dict[tuple[str, str], list] = {}
    prev_ts = None
    for ts, fields, rows in snapshots:
        times.append(ts)
        tracked = [f for f in fields if f not in _UNTRACKED]
        # Only fields this snapshot has can agree: an absent one would match
        # itself as "" on both sides and count as evidence.
        weights = {f: w for f, w in all_weights.items() if f in fields}
        groups: dict[str, list[dict]] = {}
        for r in rows:
            row = dict(zip(fields, r))
            groups.setdefault(row["user"].lower(), []).append(row)
        seen: set[str] = set()
        for user, urows in groups.items():
            known = by_user.setdefault(user, [])
            for row, key in zip(urows, _match(known, last, urows, weights)):
                if key is None:
                    key = user if not known else "%s#%d" % (user, len(known) + 1)
                    known.append(key)
                    info[key] = {"key": key, "user": row["user"], "first_seen": ts,
                                 "after": prev_ts}
                seen.add(key)
                last[key] = row
                info[key].update(user=row["user"], orig_num=row.get("orig_num", ""),
                                 last_seen=ts)
                for f in tracked:
                    v = row.get(f, "")
                    rs = runs.setdefault((key, f), [])
                    if rs and rs[-1][0] == v:
                        rs[-1][2] = ts
                    else:
                        rs.append([v, ts, ts, prev_ts])
        # An order missing from this snapshot has left the sheet (so far: if it
        # comes back, gone_after is cleared on its next appearance).
        for key, rec in info.items():
            if key not in seen and rec.get("gone_after") is None:
                rec["gone_after"] = ts
            elif key in seen:
                rec["gone_after"] = None
        prev_ts = ts

    orders = pd.DataFrame(list(info.values()),
                          columns=["key", "user", "orig_num", "first_seen", "after",
                                   "last_seen", "gone_after"])
    events = pd.DataFrame(
        [(k, f, v, first, lst, after)
         for (k, f), rs in runs.items() for v, first, lst, after in rs],
        columns=["key", "field", "value", "first_seen", "last_seen", "after"])
    return History(times, orders, events)


def snapshot_history(slug: str, headers: dict, ignored: list, label: str,
                     kind: str, raw_dir: str | None = None) -> History:
    """Replay every cache of one sheet."""
    def read():
        for ts, source in snapshot_files(slug, raw_dir):
            fields, rows = read_sheet(read_cache(source), headers, ignored, label)
            yield ts, fields, rows
    return replay(read(), kind)


def orders_history(raw_dir: str | None = None) -> History:
    return snapshot_history(ORDERS_SLUG, ORDERS_HEADERS, ORDERS_IGNORED,
                            ORDERS_LABEL, "orders", raw_dir)


def reservations_history(raw_dir: str | None = None) -> History:
    return snapshot_history(RESV_SLUG, RESERVATIONS_COLUMNS, RESV_IGNORED,
                            RESV_LABEL, "reservations", raw_dir)


def field_changes(h: History) -> pd.DataFrame:
    """Every value that replaced an earlier one: the event runs after each
    (key, field)'s first. Each row is one field changing in one snapshot."""
    e = h.events
    return e[e.groupby(["key", "field"]).cumcount() > 0]


def summary(h: History) -> dict:
    """Headline counts, for the cleaning report.

    changed_orders  orders with at least one field change
    change_events   (order, snapshot) pairs where the order changed — several
                    fields edited at once count once
    field_changes   individual field changes
    """
    ch = field_changes(h)
    return {"snapshots": len(h.snapshots), "orders": len(h.orders),
            "gone": int(h.orders["gone_after"].notna().sum()),
            "changed_orders": int(ch["key"].nunique()),
            "change_events": len(ch[["key", "first_seen"]].drop_duplicates()),
            "field_changes": len(ch)}


def current_keys(h: History) -> dict[str, str]:
    """"#" -> order key for the rows of the newest snapshot, which is the one the
    loader cleans. Orders that have left the sheet are not in it."""
    if not h.snapshots:
        return {}
    o = h.orders[(h.orders["last_seen"] == h.snapshots[-1])]
    return dict(zip(o["orig_num"], o["key"]))


def current_runs(h: History) -> dict[tuple[str, str], tuple]:
    """(key, field) -> (value, first_seen, after) of each field's CURRENT value:
    what the sheet says now, and the window in which it started saying it."""
    if not h.snapshots:
        return {}
    e = h.events[h.events["last_seen"] == h.snapshots[-1]]
    return {(k, f): (v, first, None if pd.isna(a) else a)
            for k, f, v, first, a in zip(e["key"], e["field"], e["value"],
                                         e["first_seen"], e["after"])}
