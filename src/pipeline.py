"""Pipeline orchestration: fetch both sheets, clean, write the tidy CSV,
build the dashboard, and print the cleaning report.
"""
import json
import os
import time

import pandas as pd

from config import (CLEAN_CSV, DASHBOARD, DIMENSIONS_JSON, ORDER_DATE_MIN,
                    ORDERS_GID, ORDERS_KEY, ORDERS_LABEL, ORDERS_SLUG,
                    OVERRIDES, RESV_GID, RESV_KEY, RESV_LABEL, RESV_SLUG,
                    SERIES_JSON, VIEW_JSON)
from render.aggregates import ReconcileError
from render.page import build_dashboard
from render.view import build as build_view
from render.view import unknown_categories, view_json
from ingest.fetch import fetch_sheet
from ingest.history import (current_keys, current_runs, orders_history,
                            reservations_history, summary)
from ingest.contract import dimensions, series
from ingest.curation import entries
from ingest.loaders import load_and_clean, load_reservations
from ingest.milestones import milestones
from ingest.timeline import timeline_issues


def main():
    orders_text, orders_meta = fetch_sheet(ORDERS_KEY, ORDERS_GID, ORDERS_SLUG,
                                           ORDERS_LABEL)
    resv_text, resv_meta = fetch_sheet(RESV_KEY, RESV_GID, RESV_SLUG,
                                       RESV_LABEL)

    # Snapshot replay (ingest/history.py), after both fetches so the newest cache
    # is the text being cleaned. It gives the cleaning its order keys (for
    # user#n curation) and when each current value took hold (for the
    # stale-override check), and is summarized below with its cost.
    histories, timed = {}, []
    for name, build in (("orders", orders_history),
                        ("reservations", reservations_history)):
        t0 = time.perf_counter()
        histories[name] = build()
        timed.append((name, summary(histories[name]), time.perf_counter() - t0))
    oh = histories["orders"]
    df, report, parsed = load_and_clean(orders_text, orders_meta,
                                        keys=current_keys(oh),
                                        changed=current_runs(oh))

    # Cross-snapshot checks (ingest/timeline.py) join the data-quality panel.
    # Fields an override already sets are left out: their sheet history no
    # longer reaches the dashboard.
    curated = {(e.target.split("#")[0].lower(), f)
               for e in entries(OVERRIDES) for f in (e.body or {})}
    report["quality"].update(timeline_issues(oh, curated))
    # Milestone dates for each order's final VIN and delivery date (#99):
    # internal, for the series below; never exported per order.
    df, report["quality"]["milestone_issues"] = milestones(df, oh)

    # cancelled_users keeps a cancelled ORDER from reappearing as an outstanding
    # reservation just because it left the orders cohort.
    resv, resv_report = load_reservations(resv_text, set(df["user"]),
                                          report["cancelled_users"])
    report["orders_meta"] = orders_meta
    report["resv_meta"] = resv_meta
    report["resv"] = resv_report
    # Both sheets' schema notices share one data-quality category — the panel
    # reads report["quality"], and a newly added column is equally newsworthy
    # whichever sheet grew it. (Drift that would mis-map data already raised.)
    report["quality"]["schema_notices"] += resv_report["schema_notices"]
    # Both sheets' cancellations share one panel category; the record text names
    # which sheet each came from.
    report["quality"]["deletions"] += resv_report["deletion_records"]
    report["quality"]["override_issues"] += resv_report["deletion_issues"]

    # Persist cleaned data (tidy formatting: dates as YYYY-MM-DD, int miles,
    # nullable-int VIN sequence).
    keep = ["user", "state", "region", "dist_mi", "buylease", "trim", "color",
            "wheels_short", "interior", "opted_autonomy", "opted_tow",
            "opted_spare", "price", "vin_seq", "vin_present", "vin_obfuscated",
            "resv_date", "order_date", "delivery_est", "delivery_min",
            "delivery_max", "delivery_type", "delivery_anchor_fallback",
            "delivered_inferred", "delivery_raw", "r1_owner_effective",
            "r1_model"]
    out = df[keep].copy()
    # Export the reconciled owner flag under the plain name — the CSV is the
    # cleaned dataset, so it should agree with the dashboard.
    out = out.rename(columns={"r1_owner_effective": "r1_owner"})
    out["dist_mi"] = out["dist_mi"].round(0).astype("Int64")
    out["vin_seq"] = out["vin_seq"].astype("Int64")
    out["price"] = out["price"].astype("Int64")
    for c in ("resv_date", "order_date", "delivery_est", "delivery_min",
              "delivery_max"):
        out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.to_csv(CLEAN_CSV, index=False)

    # The presentation layer's aggregates and components (render/view.py): every
    # aggregate must add back up to the cohort it counts, or the build stops,
    # the same rule as the series check below.
    try:
        view = build_view(df)
    except ReconcileError as exc:
        raise SystemExit(str(exc)) from exc
    build_dashboard(df, report, resv, view)

    # The published data contract (ingest/contract.py): dimension metadata plus
    # the event-dated daily series, built from this build's cleaned data. Its last
    # point plus what has no date must add up to this build's totals; a mismatch
    # means the series no longer describes the dashboard, which is worth a failed
    # build rather than a silently wrong file.
    converted = {str(u).lower() for _, u, _ in resv_report["matched_records"]}
    t0 = time.perf_counter()
    ser = series(df, resv, converted,
                 pd.Timestamp(oh.snapshots[0]) if oh.snapshots else None,
                 ORDER_DATE_MIN)
    series_secs = time.perf_counter() - t0
    totals = {"orders": report["n_dedup"],
              "vin_assigned": int(df["vin_present"].sum()),
              "delivered": int(df["delivered_inferred"].astype(bool).sum())}
    for name, total in totals.items():
        got = ser["values"][name][-1] + ser["undated"][name]
        if got != total:
            raise SystemExit("series %s ends at %d (+ undated) but this build "
                             "counts %d" % (name, got, total))
    with open(DIMENSIONS_JSON, "w") as fh:
        json.dump(dimensions(), fh, indent=1)
    with open(SERIES_JSON, "w") as fh:
        json.dump(ser, fh, indent=1)
    with open(VIEW_JSON, "w") as fh:
        json.dump(view_json(view), fh, indent=1)


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
    print("Premature configs dropped: %d (option not orderable on the order date)"
          % report["n_premature"])
    print("Removed by curation      : %d orders, %d reservations (overrides.yaml)"
          % (len(report["sanitized"]["Removed by curation"]),
             resv_report["n_deleted"]))
    print("Delivery estimate types  : %s" % report["delivery_counts"])
    _pz = report["price"]
    print("Configured price         : mean $%s | median $%s | %d priced, %d unpriced"
          % (format(round(_pz["mean"] or 0), ","),
             format(round(_pz["median"] or 0), ","),
             _pz["n_priced"], _pz["n_unpriced"]))
    print("Window anchor fallbacks  : %d (bad/early order date -> as-of date)"
          % report["anchor_fallback"])
    print("-" * 64)
    print("Reservations source      : %s" % resv_meta["label"])
    print("                           %s" % _fmt(resv_meta))
    print("Rows in sheet            : %d" % resv_report["n_raw"])
    print("Within-sheet duplicates  : %d (removed)" % resv_report["n_self_dupes"])
    print("Matched to orders        : %d (removed — already counted as orders)"
          % resv_report["n_matched"])
    print("Order-cancelled holders  : %d (removed — left the dataset, not reverted)"
          % resv_report["n_order_cancelled"])
    print("Invalid dates cleared    : %d (< 2024-03-07)" % resv_report["n_bad_dates"])
    print("Incomplete reservations  : %d" % resv_report["n_incomplete"])
    print("Total demand             : %d orders + %d reservations = %d"
          % (report["n_dedup"], resv_report["n_incomplete"],
             report["n_dedup"] + resv_report["n_incomplete"]))
    print("-" * 64)
    print("Snapshot history (internal):")
    for name, sm, secs in timed:
        print("  %-13s %d snapshots, %d keys (%d gone), %d changed in %d events "
              "(%d field changes) — %.1fs"
              % (name, sm["snapshots"], sm["orders"], sm["gone"],
                 sm["changed_orders"], sm["change_events"], sm["field_changes"],
                 secs))
    print("-" * 64)
    print("Delivery parse check (unique raw -> normalized):")
    seen = {}
    for raw, p in sorted(zip(df["delivery_raw"], parsed), key=lambda x: x[0].lower()):
        if raw in seen:
            continue
        seen[raw] = True
        est = p["est"].strftime("%Y-%m-%d") if not pd.isna(p["est"]) else "—"
        anc = ""
        if p["type"] == "window" and not pd.isna(p["anchor"]):
            anc = "  [anchor %s%s]" % (p["anchor"].strftime("%Y-%m-%d"),
                                       ", as-of" if p["anchor_fallback"] else "")
        print("  %-42s -> %-8s %s%s" % (repr(raw), p["type"], est, anc))
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
    notices = report["quality"]["schema_notices"]
    if notices:
        print("  ! Unmapped source columns (%d):" % len(notices))
        for _, sheet, detail in notices:
            print("     %s — %s" % (sheet, detail))
    print("-" * 64)
    for m in (orders_meta, resv_meta):
        if m["changed"] and m["cache"]:
            print("Cached (new data)  : %s" % os.path.basename(m["cache"]))
    print("Data contract: %d daily series points (%.2fs), %d dimensions"
          % (len(ser["dates"]), series_secs, len(dimensions()["dimensions"])))
    unknown = unknown_categories(view)
    print("View: %d aggregates reconciled, %d HTML + %d browser-drawn components%s"
          % (len(view.aggregates), len(view.static), len(view.components),
             "; NOT IN dimensions.yaml: " + ", ".join(unknown) if unknown else ""))
    print("Wrote: %s" % os.path.basename(CLEAN_CSV))
    print("Wrote: %s, %s, %s" % (os.path.basename(DIMENSIONS_JSON),
                                 os.path.basename(SERIES_JSON),
                                 os.path.basename(VIEW_JSON)))
    print("Wrote: %s" % os.path.basename(DASHBOARD))


if __name__ == "__main__":
    main()
