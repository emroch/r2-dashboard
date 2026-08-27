"""Data loading and cleaning for the orders and reservations sheets.

Both are hand-maintained spreadsheet exports with quirks (leading blank column,
title/notes rows above the header, quoted newlines), so columns are anchored by
content rather than absolute position. Produces a cleaned orders DataFrame plus
a per-sheet cleaning report, and a reservations DataFrame with duplicates and
already-ordered holders removed.
"""
import csv
import io

import numpy as np
import pandas as pd

from config import (ADDITIONS, AS_OF, AVAILABILITY, DELETIONS_ORDERS,
                     DELETIONS_RESV, OPTED_IN_TOKENS,
                     ORDER_DATE_MIN, ORDERS_COLUMNS, ORDERS_HEADERS,
                     ORDERS_IGNORED, OVERRIDES, RESERVATIONS_COLUMNS,
                     RESV_DATE_MIN, RESV_IGNORED, RESV_LABEL, SPARE_TOKENS,
                     UNKNOWN_SUBSTRINGS, UNKNOWN_TOKENS)
from .parsing import (clean_vin, geo_enrich, haversine_mi, parse_delivery,
                      parse_simple_date, reconcile_r1_owner, wheel_label)
from .pricing import PRICE_PARTS, price_order, reconcile_launch_options
from .schema_check import find_header, map_columns


def _extract(records, hdr_idx, idx, fields):
    """Pull the mapped columns out of a sheet's data records into a string
    DataFrame, in `fields` order.

    `idx` is the field -> column index map resolved from the header, so which
    columns are read is decided by name and nothing depends on their position.
    Rows that stop short of a mapped column (these exports have ragged trailing
    commas) get an empty cell rather than raising.
    """
    fields = list(fields)
    cols = [idx[f] for f in fields]
    rows = [[(rec[j] if j < len(rec) else "") for j in cols]
            for rec in records[hdr_idx + 1:]]
    df = pd.DataFrame(rows, columns=fields)
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def _apply_overrides(df, overrides):
    """Apply manual fix-ups (username -> {raw field: value}) in place, before
    cleaning, so the values flow through the normal pipeline. Case-insensitive
    username match; validates field names against the schema. Idempotent.
    Returns (applied_records, issue_records) for the report/QA panel."""
    valid = set(ORDERS_COLUMNS)
    idx_by_user = {u.lower(): i for i, u in zip(df.index, df["user"])}
    applied, issues = [], []
    for uname, fields in (overrides or {}).items():
        i = idx_by_user.get(str(uname).lower())
        if i is None:
            issues.append(("—", str(uname), "no matching order row"))
            continue
        onum, disp = df.at[i, "orig_num"], df.at[i, "user"]
        for field, value in (fields or {}).items():
            if field not in valid:
                issues.append((onum, disp, "unknown field '%s'" % field))
                continue
            old, new = df.at[i, field], str(value).strip()
            if old != new:
                df.at[i, field] = new
                applied.append((onum, disp, "%s: %r → %r" % (field, old, new)))
    return applied, issues


def _apply_additions(df, additions):
    """Append forum-only orders (username -> {raw field: value}) that are NOT in
    the sheet, as new rows, so they flow through cleaning like any other row.
    Case-insensitive; validates field names; guards against names already in the
    sheet (use overrides for those) and duplicate additions; tags each new row
    orig_num='add'. Returns (add_df | None, added_records, issue_records)."""
    valid = set(ORDERS_COLUMNS)
    sheet_users = {str(u).lower() for u in df["user"]}
    seen, new_rows, added, issues = set(), [], [], []
    for uname, fields in (additions or {}).items():
        key = str(uname).lower()
        if key in sheet_users:
            issues.append(("—", str(uname),
                           "addition already in orders sheet (use overrides)"))
            continue
        if key in seen:
            issues.append(("—", str(uname), "duplicate addition entry (skipped)"))
            continue
        seen.add(key)
        row = {c: "" for c in ORDERS_COLUMNS}
        row["user"], row["orig_num"] = str(uname), "add"
        set_fields = []
        for field, value in (fields or {}).items():
            if field not in valid:
                issues.append(("add", str(uname), "unknown field '%s'" % field))
                continue
            row[field] = str(value).strip()
            set_fields.append(field)
        new_rows.append(row)
        added.append(("add", str(uname),
                      "manual entry — " + ", ".join(sorted(set_fields))))
    add_df = pd.DataFrame(new_rows, columns=ORDERS_COLUMNS) if new_rows else None
    return add_df, added, issues


# Column -> human noun for the drop reason (matches the sheet's own wording).
_AVAIL_NOUN = {"trim": "trim", "color": "paint", "interior": "interior"}


def _apply_deletions(df, deletions, what, valid_fields=()):
    """Drop entries the person has said no longer exist — a cancellation.

    These rows are otherwise perfectly valid: nothing in the data marks them, so
    the only evidence is the forum post recorded as the reason in overrides.yaml.
    That makes them different from every other drop in this module, which are all
    derived from the data itself, and it is why the reason travels with the record
    into the report and the data-quality panel.

    A value is either a plain reason string, or a mapping of `reason` plus a
    `match` of raw field -> value which scopes the deletion to one specific entry.

    The matcher matters because a username is NOT a stable key for an order. If
    someone cancels and later orders again under the same name, a username-only
    deletion silently removes the new order as well — the name still matches, so
    nothing is reported. Scoping it to the cancelled order (its order date, say)
    means a replacement fails the match and the now-stale entry gets reported
    instead of quietly suppressing a live order.

    Matched case-insensitively on username, and every row that passes the matcher
    goes, so a name with duplicate rows can't half-survive. A username that isn't
    present at all, or one whose rows no longer pass the matcher, is reported
    rather than ignored: a stale entry should be cleaned up, not kept forever.

    Returns (drop_mask aligned to df.index, records, issues).
    """
    def _same(a, b):
        return " ".join(str(a).split()).lower() == " ".join(str(b).split()).lower()

    by_user = {}
    for i, u in zip(df.index, df["user"]):
        by_user.setdefault(str(u).strip().lower(), []).append(i)
    drop, records, issues = [], [], []
    for uname, spec in (deletions or {}).items():
        if isinstance(spec, dict):
            reason = str(spec.get("reason", "")).strip()
            match = dict(spec.get("match") or {})
        else:
            reason, match = str(spec).strip(), {}
        for field in [f for f in match if valid_fields and f not in valid_fields]:
            issues.append(("—", str(uname),
                           "deletion matcher uses unknown field '%s'" % field))
            match.pop(field)
        hits = by_user.get(str(uname).strip().lower(), [])
        if not hits:
            issues.append(("—", str(uname),
                           "deletion has no matching %s row" % what))
            continue
        # A matcher field the frame doesn't carry counts as a NON-match, not as a
        # skipped condition: skipping would make the deletion broader than what
        # was written, which is the wrong way for this to fail.
        scoped = [i for i in hits
                  if all(f in df.columns and _same(df.at[i, f], v)
                         for f, v in match.items())]
        if not scoped:
            issues.append(("—", str(uname),
                           "deletion no longer matches this %s (%s) — a later "
                           "entry may have replaced the cancelled one"
                           % (what, ", ".join("%s=%r" % kv
                                              for kv in sorted(match.items())))))
            continue
        for i in scoped:
            drop.append(i)
            records.append((df.at[i, "orig_num"], df.at[i, "user"],
                            "%s: %s" % (what, reason)))
    return pd.Series(df.index.isin(drop), index=df.index), records, issues


def _availability_mask(df):
    """Flag orders whose selected trim/paint/interior wasn't orderable yet on the
    order date — the config wasn't buildable, so it isn't a real confirmed order.

    AVAILABILITY maps each column to (prefix, available_from) rules; available_from
    is None for "unreleased" options (never orderable yet). Prefixes match the
    sheet value case-insensitively, so "Standard" catches every Standard-* trim.
    Compares against the (already sanitized) order date: an unreleased option, or a
    still-future/unreleased option whose order date is missing/typo'd (nulled just
    above), drops regardless; an available option with a missing date is kept
    (can't be disproven). Returns (drop_mask aligned to df.index, drop_records)."""
    reasons = {}  # df index -> reason string (first matching option wins)
    for col, rules in AVAILABILITY.items():
        if col not in df.columns or not rules:
            continue
        vals = df[col].astype(str).str.strip()
        low = vals.str.lower()
        for prefix, avail in rules:
            for i in df.index[low.str.startswith(prefix)]:
                if i in reasons:
                    continue
                od = df.at[i, "order_date"]
                what = "%s %s" % (vals.at[i], _AVAIL_NOUN.get(col, col))
                if avail is None:
                    reasons[i] = "%s not orderable yet (unreleased)" % what
                elif pd.isna(od):
                    if avail > AS_OF:  # config still unavailable as of today
                        reasons[i] = ("%s not orderable until %s (no order date)"
                                      % (what, avail.date()))
                elif od < avail:
                    reasons[i] = ("%s not orderable until %s (order %s)"
                                  % (what, avail.date(), df.at[i, "order_raw"]))
    mask = pd.Series(df.index.isin(list(reasons)), index=df.index)
    records = [(df.at[i, "orig_num"], df.at[i, "user"], reasons[i])
               for i in df.index if i in reasons]
    return mask, records


def load_and_clean(text, meta):
    # The orders sheet export carries title/notes rows above the header AND a
    # leading blank column. Parse with the csv module (robust to quoted newlines
    # in the title cells), find the header record by locating "Username", then
    # read the mapped columns BY NAME — so the sheet can be reordered or gain
    # questions freely, and only a column we actually need going missing is an
    # error (see schema_check.py).
    records = list(csv.reader(io.StringIO(text)))
    hdr_idx, header = find_header(records, ORDERS_HEADERS["user"], meta["label"])
    idx, schema_notices = map_columns(header, ORDERS_HEADERS, ORDERS_IGNORED,
                                      meta["label"])
    df = _extract(records, hdr_idx, idx, ORDERS_COLUMNS)
    df = df[df["user"] != ""].reset_index(drop=True)  # drop blank spacer rows
    n_raw = len(df)

    # --- Cancellations, before everything else ---
    # Ahead of the dedup so a cancelled name loses ALL of its rows together: run
    # after, and the duplicates audit reports "duplicate of #N (kept)" about a row
    # that was then deleted. Ahead of the data-derived checks too, so a cancelled
    # order isn't also reported as a premature config or a bad date.
    del_mask, del_records, del_issues = _apply_deletions(
        df, DELETIONS_ORDERS, "order", ORDERS_COLUMNS)
    cancelled_users = [u for _, u, _ in del_records]
    df = df[~del_mask].reset_index(drop=True)

    # --- Dedup by username, keeping the most complete record ---
    df["_score"] = (df != "").sum(axis=1)
    df["_ukey"] = df["user"].str.lower()
    df = df.sort_values("_score", ascending=False, kind="mergesort")
    dupe_keys = df["_ukey"][df["_ukey"].duplicated(keep=False)].unique()
    dup_records = []
    for key in dupe_keys:
        grp = df[df["_ukey"] == key]        # sorted best-first
        kept = grp.iloc[0]
        for _, r in grp.iloc[1:].iterrows():
            dup_records.append((r["orig_num"], r["user"],
                                "duplicate of #%s (kept)" % kept["orig_num"]))
    df = (df.drop_duplicates("_ukey", keep="first").sort_index()
          .drop(columns=["_score", "_ukey"]).reset_index(drop=True))
    n_sheet = len(df)  # unique orders from the sheet (before manual additions)

    # --- Manual curation (overrides.yaml): fix-ups edit existing rows, additions
    #     append forum-only orders not in the sheet. Both feed the cleaning below. ---
    override_records, override_issues = _apply_overrides(df, OVERRIDES)
    add_df, add_records, add_issues = _apply_additions(df, ADDITIONS)
    if add_df is not None:
        df = pd.concat([df, add_df], ignore_index=True)
    # n_dedup (the final cohort size the dashboard counts) is set after the
    # not-yet-orderable-config drop below, so it excludes those rows.

    # --- VIN ---
    vin = df["vin_raw"].apply(clean_vin)
    df["vin_seq"] = [v[0] for v in vin]
    df["vin_present"] = [v[1] for v in vin]
    df["vin_obfuscated"] = [v[2] for v in vin]
    deobf_records, unrec_records = [], []
    for _, r in df.iterrows():
        raw = r["vin_raw"]
        if raw == "":
            continue
        if r["vin_present"] and r["vin_obfuscated"]:
            deobf_records.append((r["orig_num"], r["user"],
                                  "%s → %d" % (raw, int(r["vin_seq"]))))
        elif not r["vin_present"]:
            unrec_records.append((r["orig_num"], r["user"], "%s → dropped" % raw))

    # --- Simple dates ---
    df["resv_date"] = df["resv_raw"].apply(parse_simple_date)
    df["order_date"] = df["order_raw"].apply(parse_simple_date)
    # .apply returns Timestamp/None as object dtype on pandas >= 2 (1.x inferred
    # datetime64); pin so the range checks below and the .dt accessor still work.
    df["resv_date"] = pd.to_datetime(df["resv_date"], errors="coerce")
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")

    # --- Discard nonsensical dates + drop not-yet-orderable configs ---
    # Valid order dates fall in [2026-06-09 (ordering opened), today]; valid
    # reservations in [2024-03-07 (reveal), today]. Values before the floor are
    # usually the reservation date typed into the order field; values after today
    # are typos (often a delivery date). Null them either way — FIRST, so a
    # future/typo order date can't shield a not-yet-orderable config from the drop
    # below (the availability check reads a nulled date as "no order date").
    order_future = df["order_date"] > AS_OF
    resv_future = df["resv_date"] > AS_OF
    bad_order = df["order_date"].notna() & (order_future
                                            | (df["order_date"] < ORDER_DATE_MIN))
    bad_resv = df["resv_date"].notna() & (resv_future
                                          | (df["resv_date"] < RESV_DATE_MIN))
    df.loc[bad_order, "order_date"] = pd.NaT
    df.loc[bad_resv, "resv_date"] = pd.NaT

    # Orders whose trim/paint/interior wasn't orderable on the order date aren't
    # real confirmed orders — drop the whole row (see _availability_mask).
    drop_mask, premature_records = _availability_mask(df)

    # Report each out-of-range date as a stat-card / QA entry, but not for rows
    # we're dropping outright — those surface under "Premature configs dropped"
    # instead, so each cleaned entry lands in exactly one category.
    keep_bad_order = bad_order & ~drop_mask
    keep_bad_resv = bad_resv & ~drop_mask
    n_bad_order, n_bad_resv = int(keep_bad_order.sum()), int(keep_bad_resv.sum())
    date_records = []
    for i in df.index[keep_bad_order]:
        why = "future" if order_future.at[i] else "too early"
        date_records.append((df.at[i, "orig_num"], df.at[i, "user"],
                             "order date %s → dropped (%s)" % (df.at[i, "order_raw"], why)))
    for i in df.index[keep_bad_resv]:
        why = "future" if resv_future.at[i] else "too early"
        date_records.append((df.at[i, "orig_num"], df.at[i, "user"],
                             "reservation %s → dropped (%s)" % (df.at[i, "resv_raw"], why)))

    df = df[~drop_mask].reset_index(drop=True)
    n_dedup = len(df)  # final cohort: dedup + additions − not-yet-orderable drops

    # --- Delivery estimate (windows anchored to order date) ---
    parsed = [parse_delivery(r, o)
              for r, o in zip(df["delivery_raw"], df["order_date"])]
    df["delivery_est"] = [p["est"] for p in parsed]
    df["delivery_min"] = [p["min"] for p in parsed]
    df["delivery_max"] = [p["max"] for p in parsed]
    df["delivery_type"] = [p["type"] for p in parsed]
    df["delivery_anchor_fallback"] = [p["anchor_fallback"] for p in parsed]
    # Same object-dtype pitfall (pandas >= 2): the est/min/max lists mix
    # Timestamp and NaT/None, so pin them to datetime64 for .dt and whiskers.
    for _c in ("delivery_est", "delivery_min", "delivery_max"):
        df[_c] = pd.to_datetime(df[_c], errors="coerce")

    # --- Inferred deliveries ---
    # An estimate whose whole span has passed is treated as delivered: the
    # customer most likely took the car and never came back to update the sheet.
    # A ROUGH inference, and it can err both ways — a delayed car still looks
    # delivered, and a delivery ahead of a vague estimate doesn't. A "delivered"
    # or "delayed" forum post can be curated in via overrides.yaml, which is why
    # this reads the parsed estimate rather than hardcoding a rule per person.
    #
    # Any estimate with a known upper bound counts, not just exact dates: a
    # relative window ("4-8 weeks") that finished a month ago is no less past
    # than a quoted date. Strictly before today, so an estimate landing today
    # isn't called done yet, and "unknown" never qualifies (no bound to pass).
    df["delivered_inferred"] = (df["delivery_max"].notna()
                                & (df["delivery_max"] < AS_OF))

    # --- Config normalization ---
    df["wheels_short"] = [wheel_label(w) for w in df["wheels"]]
    # Reconcile the bundled options against the Launch Package column, which is
    # authoritative — see reconcile_launch_options. The raw columns are kept as
    # reported; the *_effective ones are what the take-rates and price use.
    recon = [reconcile_launch_options(l, autonomy=a, tow=t)
             for l, a, t in zip(df["launch"], df["autonomy"], df["tow"])]
    df["autonomy_effective"] = [r[0]["autonomy"] for r in recon]
    df["tow_effective"] = [r[0]["tow"] for r in recon]
    # Contradictory answers, reconciled rather than dropped: the bundled options
    # above, plus the R1-owner gate vs. its model follow-up. Both report what was
    # assumed so a confirmed case can get an overrides.yaml entry instead.
    conflicts = [(onum, user, msg)
                 for (_, msgs), onum, user in zip(recon, df["orig_num"],
                                                  df["user"])
                 for msg in msgs]
    r1 = [reconcile_r1_owner(o, m)
          for o, m in zip(df["r1_owner"], df["r1_model"])]
    df["r1_owner_effective"] = [v for v, _ in r1]
    conflicts += [(onum, user, msg)
                  for (_, msg), onum, user in zip(r1, df["orig_num"], df["user"])
                  if msg]
    df["opted_autonomy"] = df["autonomy_effective"].str.lower().isin(OPTED_IN_TOKENS)
    df["opted_tow"] = df["tow_effective"].str.lower().isin(OPTED_IN_TOKENS)
    df["opted_spare"] = df["spare"].str.lower().isin(SPARE_TOKENS)

    # --- Configured price (pricing.yaml) ---
    # Base + drive system + package + paint + wheels + interior + add-ons, with a
    # per-category breakdown kept for the "where the money goes" panel. Options
    # the sheet claims but the trim doesn't offer are flagged for review, not
    # corrected — the order keeps a best-effort price and stays in the stats.
    priced = [price_order(trim=t, launch=l, color=c, interior=i, wheels=w,
                          autonomy=a, tow=tw, spare=s)
              for t, l, c, i, w, a, tw, s
              in zip(df["trim"], df["launch"], df["color"], df["interior"],
                     df["wheels"], df["autonomy_effective"],
                     df["tow_effective"], df["spare"])]
    for col in PRICE_PARTS + ("price", "price_trim", "price_drive_system"):
        df[col] = [p[0].get(col) for p in priced]
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    price_issues = [(onum, user, msg)
                    for (_, msgs), onum, user in zip(priced, df["orig_num"],
                                                     df["user"])
                    for msg in msgs]

    # --- Location / geo ---
    geo_enrich(df)
    df["dist_mi"] = [haversine_mi(la, lo) for la, lo in zip(df["lat"], df["lon"])]

    # Display helpers for hover.
    df["vin_display"] = np.where(df["vin_present"],
                                 df["vin_seq"].astype("Int64").astype(str),
                                 "—")
    df["order_display"] = df["order_date"].dt.strftime("%b %d, %Y").fillna("—")
    df["est_display"] = df["delivery_est"].dt.strftime("%b %d, %Y").fillna("—")

    # --- Data-quality flags (surfaced in the QA panel; not auto-corrected) ---
    # Delivery text that isn't a known "no date" placeholder yet still didn't
    # parse into a date/range/window — i.e. a genuine parse miss worth review.
    unparseable = []
    for _, r in df.iterrows():
        low = r["delivery_raw"].strip().lower()
        if (r["delivery_type"] == "unknown" and low
                and low not in UNKNOWN_TOKENS
                and not any(s in low for s in UNKNOWN_SUBSTRINGS)):
            unparseable.append((r["orig_num"], r["user"], r["delivery_raw"]))
    # Usernames that normalize alike (case/space/punctuation) but weren't merged
    # by the exact-lowercase dedup — possibly the same person entered twice.
    by_norm = {}
    for _, r in df.iterrows():
        key = "".join(ch for ch in r["user"].lower() if ch.isalnum())
        by_norm.setdefault(key, []).append((r["orig_num"], r["user"]))
    fuzzy_dups = []
    for recs in by_norm.values():
        users = [u for _, u in recs]
        if len(set(users)) > 1:
            for onum, u in recs:
                others = ", ".join(sorted(set(users) - {u}))
                fuzzy_dups.append((onum, u, "normalizes like: %s" % others))

    # Delivery-string -> parsed date/range for the audit panel: each distinct
    # raw that produced a date, so the normalization can be eyeballed.
    seen, conversions = set(), []
    for raw, prs in zip(df["delivery_raw"], parsed):
        r = raw.strip()
        if not r or r in seen or prs["type"] == "unknown":
            continue
        seen.add(r)
        if pd.notna(prs["min"]) and pd.notna(prs["max"]) and prs["max"] > prs["min"]:
            res = "%s → %s" % (prs["min"].strftime("%Y-%m-%d"),
                               prs["max"].strftime("%Y-%m-%d"))
        elif pd.notna(prs["est"]):
            res = prs["est"].strftime("%Y-%m-%d")
        else:
            res = "—"
        # Windows are relative, so record the anchor they were measured from
        # (order date, or the as-of date when that is missing/invalid). Absolute
        # types (explicit/range/month) have no anchor.
        anchor = ""
        if prs["type"] == "window" and pd.notna(prs["anchor"]):
            anchor = prs["anchor"].strftime("%Y-%m-%d")
            if prs["anchor_fallback"]:
                anchor += " (as-of)"
        conversions.append((r, prs["type"], res, anchor))
    conversions.sort(key=lambda t: t[0].lower())

    report = {
        "source": meta["label"],
        "n_raw": n_raw, "n_dedup": n_dedup,
        "n_sheet": n_sheet, "n_added": len(add_records),
        "dupes": list(dupe_keys),
        "vin_present": int(df["vin_present"].sum()),
        "vin_obfuscated": int((df["vin_obfuscated"] & df["vin_present"]).sum()),
        "delivery_counts": df["delivery_type"].value_counts().to_dict(),
        "anchor_fallback": int(df["delivery_anchor_fallback"].sum()),
        "bad_order": n_bad_order, "bad_resv": n_bad_resv,
        "n_premature": len(premature_records),
        # Configured-price summary. n_unpriced counts orders whose configuration
        # hit a price that isn't published yet — reported as its own bucket so the
        # mean/median are never quietly computed over a subset.
        "price": {
            "n_priced": int(df["price"].notna().sum()),
            "n_unpriced": int(df["price"].isna().sum()),
            "mean": (float(df["price"].mean()) if df["price"].notna().any()
                     else None),
            "median": (float(df["price"].median()) if df["price"].notna().any()
                       else None),
            "min": (float(df["price"].min()) if df["price"].notna().any()
                    else None),
            "max": (float(df["price"].max()) if df["price"].notna().any()
                    else None),
            "total": float(df["price"].sum()) if df["price"].notna().any() else 0.0,
            "part_means": {c: float(df[c].fillna(0).mean()) for c in PRICE_PARTS},
        },
        "sanitized": {
            "Duplicates removed": dup_records,
            "VINs de-obfuscated": deobf_records,
            "VINs recovered": unrec_records,
            "Invalid dates dropped": date_records,
            "Premature configs dropped": premature_records,
            "Manual fix-ups": override_records,
            "Manual additions": add_records,
            "Cancellations removed": del_records,
        },
        "quality": {
            "schema_notices": schema_notices,
            "unparseable": unparseable,
            "fuzzy_dups": fuzzy_dups,
            "vin_unrec": unrec_records,
            "bad_dates": date_records,
            "availability_drops": premature_records,
            "price_issues": price_issues,
            "answer_conflicts": conflicts,
            "conversions": conversions,
            "override_issues": override_issues + add_issues + del_issues,
            # Its own list, not the one in `sanitized`: the pipeline appends the
            # reservation cancellations here so one panel category covers both
            # sheets, and sharing the object made that append silently inflate the
            # orders-only count in the report and the stat card.
            "deletions": list(del_records),
        },
        # Names whose ORDER was cancelled. The reservations sheet needs them: they
        # have left the orders cohort, and must not resurface there as outstanding
        # reservations just because they are no longer counted as orders.
        "cancelled_users": cancelled_users,
    }
    return df, report, parsed


def load_reservations(text, order_users, cancelled_users=()):
    """Parse the reservations-only sheet and return (resv_df, resv_report).

    A different form from the orders sheet (columns: #, Username, R2 reservation
    date, Location, R1-owner questions — no order/VIN/config/delivery), and its
    R1 answers aren't charted, so only four columns are mapped; they're located
    by name exactly as the orders sheet's are. Steps: drop within-sheet duplicate
    usernames; drop reservations cancelled via overrides.yaml; drop holders
    already present in the orders sheet (they are counted as orders — the
    remainder are "incomplete" orders) and anyone whose order was cancelled, since
    they have left the dataset rather than reverted to holding a reservation; null
    pre-reveal (<2024-03-07) reservation dates; geo-enrich by state.
    """
    records = list(csv.reader(io.StringIO(text)))
    hdr_idx, header = find_header(records, RESERVATIONS_COLUMNS["user"],
                                 RESV_LABEL)
    idx, schema_notices = map_columns(header, RESERVATIONS_COLUMNS,
                                      RESV_IGNORED, RESV_LABEL)
    resv = _extract(records, hdr_idx, idx, RESERVATIONS_COLUMNS)
    resv = resv[resv["user"] != ""].reset_index(drop=True)
    n_raw = len(resv)

    # Within-sheet duplicate usernames: keep first, record the rest.
    resv["_ukey"] = resv["user"].str.lower()
    dup_mask = resv["_ukey"].duplicated(keep="first")
    self_dupe_records = [(r["orig_num"], r["user"], "repeat entry (kept first)")
                         for _, r in resv[dup_mask].iterrows()]
    resv = resv[~dup_mask]
    n_self_dupes = int(dup_mask.sum())

    # Cancelled reservations, before the data-derived drops below.
    del_mask, del_records, del_issues = _apply_deletions(
        resv, DELETIONS_RESV, "reservation", RESERVATIONS_COLUMNS)
    resv = resv[~del_mask]

    # Remove reservation-holders who already appear in the orders sheet, and
    # anyone whose ORDER was cancelled — the latter have left the dataset, so
    # dropping out of the orders cohort must not float them back up here.
    order_keys = {u.lower() for u in order_users}
    cancelled_keys = {str(u).strip().lower() for u in cancelled_users}
    matched = resv["_ukey"].isin(order_keys)
    matched_records = [(r["orig_num"], r["user"], "already in orders sheet")
                       for _, r in resv[matched].iterrows()]
    n_matched = int(matched.sum())
    resv = resv[~matched]
    was_cancelled = resv["_ukey"].isin(cancelled_keys)
    n_order_cancelled = int(was_cancelled.sum())
    del_records += [(r["orig_num"], r["user"], "reservation: order was cancelled")
                    for _, r in resv[was_cancelled].iterrows()]
    resv = resv[~was_cancelled].drop(columns="_ukey").reset_index(drop=True)

    # Reservation date must fall in [2024-03-07 reveal, today]; null others.
    resv["resv_date"] = resv["resv_raw"].apply(parse_simple_date)
    resv["resv_date"] = pd.to_datetime(resv["resv_date"], errors="coerce")
    bad = resv["resv_date"].notna() & ((resv["resv_date"] < RESV_DATE_MIN)
                                       | (resv["resv_date"] > AS_OF))
    resv.loc[bad, "resv_date"] = pd.NaT
    geo_enrich(resv)

    resv_report = {
        "n_raw": n_raw, "n_self_dupes": n_self_dupes, "n_matched": n_matched,
        "n_bad_dates": int(bad.sum()), "n_incomplete": len(resv),
        "self_dupe_records": self_dupe_records, "matched_records": matched_records,
        "schema_notices": schema_notices,
        "n_deleted": len(del_records), "n_order_cancelled": n_order_cancelled,
        "deletion_records": del_records, "deletion_issues": del_issues,
    }
    return resv, resv_report
