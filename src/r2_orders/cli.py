"""Command-line orchestration: fetch both sheets, clean, write the tidy CSV,
build the dashboard, and print the cleaning report.
"""
import os

import pandas as pd

from .config import (CLEAN_CSV, DASHBOARD, ORDERS_GID, ORDERS_KEY, ORDERS_LABEL,
                     ORDERS_SLUG, RESV_GID, RESV_KEY, RESV_LABEL, RESV_SLUG)
from .dashboard import build_dashboard
from .fetch import fetch_sheet
from .loaders import load_and_clean, load_reservations


def main():
    orders_text, orders_meta = fetch_sheet(ORDERS_KEY, ORDERS_GID, ORDERS_SLUG,
                                           ORDERS_LABEL)
    df, report, parsed = load_and_clean(orders_text, orders_meta)

    resv_text, resv_meta = fetch_sheet(RESV_KEY, RESV_GID, RESV_SLUG,
                                       RESV_LABEL)
    resv, resv_report = load_reservations(resv_text, set(df["user"]))
    report["orders_meta"] = orders_meta
    report["resv_meta"] = resv_meta
    report["resv"] = resv_report

    # Persist cleaned data (tidy formatting: dates as YYYY-MM-DD, int miles,
    # nullable-int VIN sequence).
    keep = ["user", "state", "region", "dist_mi", "buylease", "trim", "color",
            "wheels_short", "interior", "opted_autonomy", "opted_tow",
            "opted_spare", "vin_seq", "vin_present", "vin_obfuscated",
            "resv_date", "order_date", "delivery_est", "delivery_min",
            "delivery_max", "delivery_type", "delivery_anchor_fallback",
            "delivery_raw", "r1_owner", "r1_model"]
    out = df[keep].copy()
    out["dist_mi"] = out["dist_mi"].round(0).astype("Int64")
    out["vin_seq"] = out["vin_seq"].astype("Int64")
    for c in ("resv_date", "order_date", "delivery_est", "delivery_min",
              "delivery_max"):
        out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.to_csv(CLEAN_CSV, index=False)

    build_dashboard(df, report, resv)

    def _fmt(meta):
        f = meta["fetched_at"].strftime("%Y-%m-%d %H:%M")
        u = meta["updated_at"].strftime("%Y-%m-%d %H:%M") if meta["updated_at"] else "—"
        tag = "" if meta["live"] else " [offline: cached]"
        chg = "  <-- CHANGED THIS FETCH" if meta["changed"] else ""
        return "fetched %s%s | last updated %s%s" % (f, tag, u, chg)

    print("=" * 64)
    print("R2 ORDER DATA — CLEANING REPORT")
    print("=" * 64)
    print("Orders source            : %s" % report["source"])
    print("                           %s" % _fmt(orders_meta))
    print("Rows in source           : %d" % report["n_raw"])
    print("Duplicate usernames      : %s" % ", ".join(report["dupes"]))
    print("Unique orders kept       : %d" % report["n_dedup"])
    print("VINs recovered           : %d (%d were obfuscated with X's)"
          % (report["vin_present"], report["vin_obfuscated"]))
    print("Discarded order dates    : %d (outside 2026-06-09 … today)"
          % report["bad_order"])
    print("Discarded reservations   : %d (outside 2024-03-07 … today)"
          % report["bad_resv"])
    print("Delivery estimate types  : %s" % report["delivery_counts"])
    print("Window anchor fallbacks  : %d (bad/early order date -> as-of date)"
          % report["anchor_fallback"])
    print("-" * 64)
    print("Reservations source      : %s" % resv_meta["label"])
    print("                           %s" % _fmt(resv_meta))
    print("Rows in sheet            : %d" % resv_report["n_raw"])
    print("Within-sheet duplicates  : %d (removed)" % resv_report["n_self_dupes"])
    print("Matched to orders        : %d (removed — already counted as orders)"
          % resv_report["n_matched"])
    print("Invalid dates cleared    : %d (< 2024-03-07)" % resv_report["n_bad_dates"])
    print("Incomplete reservations  : %d" % resv_report["n_incomplete"])
    print("Total demand             : %d orders + %d reservations = %d"
          % (report["n_dedup"], resv_report["n_incomplete"],
             report["n_dedup"] + resv_report["n_incomplete"]))
    print("-" * 64)
    print("Delivery parse check (unique raw -> normalized):")
    seen = {}
    for raw, p in sorted(zip(df["delivery_raw"], parsed), key=lambda x: x[0].lower()):
        if raw in seen:
            continue
        seen[raw] = True
        est = p["est"].strftime("%Y-%m-%d") if not pd.isna(p["est"]) else "—"
        print("  %-42s -> %-8s %s" % (repr(raw), p["type"], est))
    print("-" * 64)
    print("Sanitized entries (also shown as stat-card hovers in the dashboard):")
    for label, rows in report["sanitized"].items():
        print("  %s (%d):" % (label, len(rows)))
        for i, u, d in rows:
            print("     #%-4s %-20s %s" % (i, u, d))
    issues = report["quality"]["override_issues"]
    if issues:
        print("  ! Override issues (%d):" % len(issues))
        for i, u, d in issues:
            print("     #%-4s %-20s %s" % (i, u, d))
    print("-" * 64)
    for m in (orders_meta, resv_meta):
        if m["changed"] and m["cache"]:
            print("Cached (new data)  : %s" % os.path.basename(m["cache"]))
    print("Wrote: %s" % os.path.basename(CLEAN_CSV))
    print("Wrote: %s" % os.path.basename(DASHBOARD))
