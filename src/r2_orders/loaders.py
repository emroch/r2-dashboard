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

from .config import (AS_OF, OPTED_IN_TOKENS, ORDER_DATE_MIN, ORDERS_COLUMNS,
                     OVERRIDES, RESERVATIONS_COLUMNS, RESV_DATE_MIN,
                     SPARE_TOKENS, UNKNOWN_SUBSTRINGS, UNKNOWN_TOKENS,
                     WHEELS_21_CONTAINS, WHEELS_LABEL_20, WHEELS_LABEL_21)
from .parsing import (clean_vin, geo_enrich, haversine_mi, parse_delivery,
                      parse_simple_date)


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


def load_and_clean(text, meta):
    # The orders sheet export carries title/notes rows above the header AND a
    # leading blank column (so "#" sits at index 1, not 0). Parse with the csv
    # module (robust to quoted newlines in the title cells), find the header
    # record by locating "Username", then slice the fixed 20-column block
    # starting at "#" — anchoring columns by content, not absolute position.
    records = list(csv.reader(io.StringIO(text)))
    hdr_idx = next((i for i, r in enumerate(records)
                    if any(c.strip() == "Username" for c in r)), 0)
    header = [c.strip() for c in records[hdr_idx]]
    start = header.index("#") if "#" in header else 0
    ncol = len(header)
    names = ORDERS_COLUMNS
    rows = [((r + [""] * ncol)[start:start + len(names)]) for r in records[hdr_idx + 1:]]
    df = pd.DataFrame(rows, columns=names)
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["user"] != ""].reset_index(drop=True)  # drop blank spacer rows
    n_raw = len(df)

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
    df = df.drop_duplicates("_ukey", keep="first").sort_index()
    n_dedup = len(df)

    # --- Manual fix-ups (applied to raw fields before cleaning) ---
    override_records, override_issues = _apply_overrides(df, OVERRIDES)

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

    # --- Discard nonsensical dates (unrecoverable) ---
    # Valid order dates fall in [2026-06-09 (ordering opened), today]; valid
    # reservations in [2024-03-07 (reveal), today]. Values before the floor are
    # usually the reservation date typed into the order field; values after
    # today are typos (often a delivery date). Null them either way.
    bad_order = df["order_date"].notna() & ((df["order_date"] < ORDER_DATE_MIN)
                                            | (df["order_date"] > AS_OF))
    bad_resv = df["resv_date"].notna() & ((df["resv_date"] < RESV_DATE_MIN)
                                          | (df["resv_date"] > AS_OF))
    n_bad_order, n_bad_resv = int(bad_order.sum()), int(bad_resv.sum())
    date_records = []
    for _, r in df[bad_order].iterrows():
        why = "future" if r["order_date"] > AS_OF else "too early"
        date_records.append((r["orig_num"], r["user"],
                             "order date %s → dropped (%s)" % (r["order_raw"], why)))
    for _, r in df[bad_resv].iterrows():
        why = "future" if r["resv_date"] > AS_OF else "too early"
        date_records.append((r["orig_num"], r["user"],
                             "reservation %s → dropped (%s)" % (r["resv_raw"], why)))
    df.loc[bad_order, "order_date"] = pd.NaT
    df.loc[bad_resv, "resv_date"] = pd.NaT

    # --- Delivery estimate (windows anchored to order date) ---
    parsed = [parse_delivery(r, o)
              for r, o in zip(df["delivery_raw"], df["order_date"])]
    df["delivery_est"] = [p["est"] for p in parsed]
    df["delivery_min"] = [p["min"] for p in parsed]
    df["delivery_max"] = [p["max"] for p in parsed]
    df["delivery_type"] = [p["type"] for p in parsed]
    df["delivery_anchor_fallback"] = [p["anchor_fallback"] for p in parsed]

    # --- Config normalization ---
    df["wheels_short"] = np.where(df["wheels"].str.contains(WHEELS_21_CONTAINS),
                                  WHEELS_LABEL_21, WHEELS_LABEL_20)
    df["opted_autonomy"] = df["autonomy"].str.lower().isin(OPTED_IN_TOKENS)
    df["opted_tow"] = df["tow"].str.lower().isin(OPTED_IN_TOKENS)
    df["opted_spare"] = df["spare"].str.lower().isin(SPARE_TOKENS)

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
        "dupes": list(dupe_keys),
        "vin_present": int(df["vin_present"].sum()),
        "vin_obfuscated": int((df["vin_obfuscated"] & df["vin_present"]).sum()),
        "delivery_counts": df["delivery_type"].value_counts().to_dict(),
        "anchor_fallback": int(df["delivery_anchor_fallback"].sum()),
        "bad_order": n_bad_order, "bad_resv": n_bad_resv,
        "sanitized": {
            "Duplicates removed": dup_records,
            "VINs de-obfuscated": deobf_records,
            "VINs recovered": unrec_records,
            "Invalid dates dropped": date_records,
            "Manual fix-ups": override_records,
        },
        "quality": {
            "unparseable": unparseable,
            "fuzzy_dups": fuzzy_dups,
            "vin_unrec": unrec_records,
            "bad_dates": date_records,
            "conversions": conversions,
            "override_issues": override_issues,
        },
    }
    return df, report, parsed


def load_reservations(text, order_users):
    """Parse the reservations-only sheet and return (resv_df, resv_report).

    Different layout from the orders sheet (columns: #, Username, R2 reservation
    date, Location, R1-owner questions — no order/VIN/config/delivery), so map
    by header name rather than by position. Steps: drop within-sheet duplicate
    usernames; drop holders already present in the orders sheet (they are
    counted as orders — the remainder are "incomplete" orders); null pre-reveal
    (<2024-03-07) reservation dates; geo-enrich by state.
    """
    records = list(csv.reader(io.StringIO(text)))
    hdr_idx = next((i for i, r in enumerate(records)
                    if any(c.strip() == "Username" for c in r)), 0)
    header = [c.strip() for c in records[hdr_idx]]
    idx = {name: j for j, name in enumerate(header)}

    def col(row, header):
        j = idx.get(header)
        return row[j].strip() if (j is not None and j < len(row)) else ""

    fields = RESERVATIONS_COLUMNS  # internal field -> sheet header name
    user_hdr = fields["user"]
    rows = [{field: col(r, hdr) for field, hdr in fields.items()}
            for r in records[hdr_idx + 1:] if col(r, user_hdr)]
    resv = pd.DataFrame(rows, columns=list(fields.keys()))
    n_raw = len(resv)

    # Within-sheet duplicate usernames: keep first, record the rest.
    resv["_ukey"] = resv["user"].str.lower()
    dup_mask = resv["_ukey"].duplicated(keep="first")
    self_dupe_records = [(r["orig_num"], r["user"], "repeat entry (kept first)")
                         for _, r in resv[dup_mask].iterrows()]
    resv = resv[~dup_mask]
    n_self_dupes = int(dup_mask.sum())

    # Remove reservation-holders who already appear in the orders sheet.
    order_keys = {u.lower() for u in order_users}
    matched = resv["_ukey"].isin(order_keys)
    matched_records = [(r["orig_num"], r["user"], "already in orders sheet")
                       for _, r in resv[matched].iterrows()]
    n_matched = int(matched.sum())
    resv = resv[~matched].drop(columns="_ukey").reset_index(drop=True)

    # Reservation date must fall in [2024-03-07 reveal, today]; null others.
    resv["resv_date"] = resv["resv_raw"].apply(parse_simple_date)
    bad = resv["resv_date"].notna() & ((resv["resv_date"] < RESV_DATE_MIN)
                                       | (resv["resv_date"] > AS_OF))
    resv.loc[bad, "resv_date"] = pd.NaT
    geo_enrich(resv)

    resv_report = {
        "n_raw": n_raw, "n_self_dupes": n_self_dupes, "n_matched": n_matched,
        "n_bad_dates": int(bad.sum()), "n_incomplete": len(resv),
        "self_dupe_records": self_dupe_records, "matched_records": matched_records,
    }
    return resv, resv_report
