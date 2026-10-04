"""Cross-snapshot sanity checks: what the history says about the current data.

Data layer stage 3 (docs/data-layer.md, issue #83). Each check reads the snapshot
history (ingest/history.py) and lists orders for the data-quality panel. Like the
entry-error checks (ingest/outliers.py), nothing here corrects anything. These
are prompts to look, because a value that moved can be a fix as easily as a
mistake.

  vin_changes          a VIN replaced by a DIFFERENT VIN after one was set.
                       Formatting (leading zeros) and de-obfuscation (X8556 →
                       08556) are not changes. A change that reverts to an
                       earlier value is called out, since A → B → A usually means
                       someone edited the wrong row and then put it back.
  order_date_changes   an order date replaced by a different date. Most are typo
                       fixes (8/19/2024 → 8/19/2026), but a date that moves by
                       weeks changes every window measured from it.
  firm_to_vague        a firm delivery date replaced by something vaguer
                       ("TBD", "Delayed - No ETA") and still vague. Usually a
                       real delay, which the dashboard can only see as the
                       estimate going vague; worth asking for an update.
  left_sheet           an order that disappeared from the sheet without a
                       curated deletion: a silent cancellation, or a row removed
                       by mistake. Its history ends there.

Considered and left out: "a delivery estimate moved earlier after it had
passed". On this data it only found people replacing an expected date with the
earlier day they actually took delivery, which is benign.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from .history import History
from .parsing import clean_vin, parse_delivery, parse_simple_date

Record = tuple[str, str, str]   # (sheet "#", username, detail), as the QA panel lists


def _window(after, first) -> str:
    if after is None or pd.isna(after):
        return "by %s" % first.date()
    lo, hi = after.date(), first.date()
    return "on %s" % hi if lo == hi else "between %s and %s" % (lo, hi)


def _who(h: History) -> dict[str, tuple[str, str]]:
    """key -> (sheet "#", username) as last seen."""
    return {str(k): (str(o), str(u))
            for k, o, u in zip(h.orders["key"], h.orders["orig_num"], h.orders["user"])}


def _sequences(h: History, field: str) -> dict[str, list[tuple]]:
    """key -> [(value, first_seen, after), ...] in time order, for one field."""
    e = h.events[h.events["field"] == field].sort_values(["key", "first_seen"])
    out: dict[str, list[tuple]] = {}
    for k, v, f, a in zip(e["key"], e["value"], e["first_seen"], e["after"]):
        out.setdefault(k, []).append((v, f, None if pd.isna(a) else a))
    return out


def _changes(h: History, field: str,
             norm: Callable[[str], object | None]) -> list[Record]:
    """Orders whose `field` moved from one meaningful value to a different one.

    `norm` maps a raw value to what it means, or None when it means nothing yet
    (blank, unparseable). Values that normalize alike are the same value, so
    reformatting is not a change, and nothing counts until a first meaningful
    value has been set.
    """
    who = _who(h)
    out = []
    for key, seq in _sequences(h, field).items():
        meant = [(v, norm(v), f, a) for v, f, a in seq]
        meant = [m for m in meant if m[1] is not None]
        steps = [(b, m) for b, m in zip(meant, meant[1:]) if b[1] != m[1]]
        if not steps:
            continue
        values = [meant[0][0]] + [m[0] for _, m in steps]
        _, last = steps[-1]
        detail = "%s (last change %s)" % (" → ".join(values),
                                          _window(last[3], last[2]))
        seen = [meant[0][1]] + [m[1] for _, m in steps]
        if any(x in seen[:i] for i, x in enumerate(seen) if i):
            detail += (" — returned to an earlier value; possibly an edit to the "
                       "wrong row")
        out.append((*who[key], detail))
    return out


def _vin(v: str) -> int | None:
    seq, present, _ = clean_vin(v)
    return seq if present else None


def _date(v: str):
    d = parse_simple_date(v)
    return None if pd.isna(d) else d


def _firm_to_vague(h: History) -> list[Record]:
    who = _who(h)
    gone = set(h.orders.loc[h.orders["gone_after"].notna(), "key"])
    order_dates = {k: seq[-1][0] for k, seq in _sequences(h, "order_raw").items()}
    out = []
    for key, seq in _sequences(h, "delivery_raw").items():
        anchor = parse_simple_date(order_dates.get(key, ""))
        typed = [(v, parse_delivery(v, anchor)["type"], f, a) for v, f, a in seq]
        # Only while it is STILL vague: a delay that has since been given a new
        # firm date is resolved, and listing it would be noise.
        if len(typed) < 2 or key in gone:
            continue
        (v0, t0, _, _), (v1, t1, f1, a1) = typed[-2], typed[-1]
        if t0 == "explicit" and t1 != "explicit":
            out.append((*who[key], "%r → %r (%s)" % (v0, v1, _window(a1, f1))))
    return out


def _left_sheet(h: History) -> list[Record]:
    gone = h.orders[h.orders["gone_after"].notna()]
    # The last snapshot that still had the row, and the first that didn't.
    return [(str(o), str(u),
             "last seen as #%s %s; gone by %s — a silent cancellation, or a row "
             "removed by mistake" % (o, last.date(), g.date()))
            for o, u, last, g in zip(gone["orig_num"], gone["user"],
                                     gone["last_seen"], gone["gone_after"])]


def timeline_issues(h: History, curated: set[tuple[str, str]] | None = None,
                    ) -> dict[str, list[Record]]:
    """The four QA lists, keyed as the data-quality panel's categories.

    `curated` holds (lowercased username, field) pairs that overrides.yaml
    already sets. The sheet's history of such a field no longer reaches the
    dashboard, so it isn't listed.
    """
    curated = curated or set()

    def keep(field: str, records: list[Record]) -> list[Record]:
        return [r for r in records if (r[1].lower(), field) not in curated]

    return {"vin_changes": keep("vin_raw", _changes(h, "vin_raw", _vin)),
            "order_date_changes": keep("order_raw",
                                       _changes(h, "order_raw", _date)),
            "firm_to_vague": keep("delivery_raw", _firm_to_vague(h)),
            "left_sheet": _left_sheet(h)}
