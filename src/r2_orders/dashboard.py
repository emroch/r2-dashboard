"""Dashboard assembly: the section registry, page CSS, HTML helpers, and the
build_dashboard entry point that renders every chart into a single HTML file.
"""
import pandas as pd

from .charts import (fig_certainty_by_vin, fig_color_wheel_heatmap,
                     fig_config_dashboard, fig_delivery_timeline,
                     fig_delivery_vs_vin, fig_dest_vs_delivery, fig_geo,
                     fig_order_timeline, fig_vin_vs_order)
from .config import DASHBOARD

SECTIONS = [
    ("1 · Delivery date vs. VIN sequence",
     "Each point is an order with both a VIN and a delivery estimate. Color = "
     "paint, marker shape = wheels; whiskers span the quoted delivery window "
     "(firm single-date estimates show as bare points). Clusters of one color "
     "across a VIN range hint at same-config cars built in sequence. Swatch "
     "colors are brightened from the measured paints for on-screen separation.",
     fig_delivery_vs_vin),
    ("2 · Destination vs. delivery date",
     "States ordered by distance from the Normal, IL plant (closest at bottom). "
     "A downward-right tilt would mean farther destinations deliver later.",
     fig_dest_vs_delivery),
    ("3 · VIN sequence vs. order date",
     "Does ordering earlier win a lower (earlier-built) VIN? Slope/scatter shows "
     "how tightly production sequence tracks order timing.",
     fig_vin_vs_order),
    ("4 · Configuration take-rates",
     "What this cohort ordered. (Trim, Launch Package, Autonomy+ and Tow are ~100% "
     "uniform across the cohort, so they are omitted here.)",
     fig_config_dashboard),
    ("5 · Color × wheels combinations",
     "Most common full builds — the combos that would form the clusters in chart 1.",
     fig_color_wheel_heatmap),
    ("6 · Reservation & order timeline",
     "The top panel stacks reservation-only holders (incomplete orders, from "
     "the separate reservations sheet) beneath those who have since locked an "
     "order. The 3/7/2024 reveal week is ~20x the next-biggest week, so the "
     "y-axis is clipped just above the tail (the reveal bar is annotated with "
     "its true height) to keep the 2-year trickle readable. The bottom shows "
     "when orders were finalized (clustering in June 2026).",
     fig_order_timeline),
    ("7 · Estimated delivery timeline",
     "When the cohort expects delivery, stacked by how firm the estimate is.",
     fig_delivery_timeline),
    ("8 · Geographic demand",
     "Three stacked maps of demand around the Normal, IL plant, each with its "
     "own legend: orders with an assigned VIN, all orders, and total demand "
     "(orders + incomplete reservations). Bubble area = count; the first two "
     "share a scale, while total demand (~20x larger) scales to its own. Skews "
     "to CA / Pacific NW / TX.",
     fig_geo),
    ("9 · Estimate certainty vs. VIN status",
     "Orders with an assigned VIN carry far more firm dates — a sanity check and a "
     "signal of how far along each order is.",
     fig_certainty_by_vin),
]

PAGE_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
 margin:0;background:#fafafa;color:#1c1c1c;}
header{background:#12261f;color:#fff;padding:28px 40px;}
header h1{margin:0 0 6px;font-size:24px;}
header p{margin:0;color:#cfe0d8;font-size:14px;}
header p.src{margin:3px 0;font-size:13px;color:#dCe9e2;}
header p.src a{color:#8fe3bf;text-decoration:none;border-bottom:1px dotted #6cae91;}
header p.src a:hover{color:#b9f2d6;}
header p.meth{margin:10px 0 0;color:#9fb8ad;font-size:12.5px;line-height:1.5;}
header p.disclaimer{margin:8px 0 12px;padding:7px 12px;font-weight:600;
 font-size:13px;color:#ffe0b0;background:rgba(255,180,80,.12);
 border-left:3px solid #f0a24b;border-radius:4px;}
header .warn{color:#ffd27f;}
header .chg{color:#a9e8a9;font-weight:600;}
header .dim{color:#8ba79b;}
.wrap{max-width:1180px;margin:0 auto;padding:8px 24px 60px;}
section{background:#fff;border:1px solid #e6e6e6;border-radius:10px;
 margin:26px 0;padding:18px 22px;box-shadow:0 1px 3px rgba(0,0,0,.04);}
section h2{margin:0 0 4px;font-size:19px;color:#12261f;}
section p.desc{margin:0 0 8px;color:#555;font-size:13.5px;line-height:1.45;}
.statwrap{margin-top:14px;}
.statgroup{margin-top:12px;}
.sglabel{display:block;font-size:10.5px;text-transform:uppercase;
 letter-spacing:.08em;color:#8fae9f;margin:0 0 5px 2px;}
.stats{display:flex;flex-wrap:wrap;gap:12px;}
.stat{position:relative;background:#1c3a2e;color:#fff;border-radius:8px;
 padding:10px 18px;font-size:12.5px;white-space:nowrap;min-width:96px;}
.stat b{font-size:18px;display:block;line-height:1.25;}
.stat.has-tip{cursor:help;}
.stat .i{opacity:.55;font-size:11px;margin-left:2px;}
.stat .tip{display:none;position:absolute;left:0;top:calc(100% + 8px);z-index:30;
 background:#fff;color:#233;border:1px solid #cdd;border-radius:8px;font-weight:400;
 box-shadow:0 6px 20px rgba(0,0,0,.22);padding:9px 11px;max-height:300px;overflow:auto;}
.stat:hover .tip{display:block;}
.tipcap{font-weight:600;color:#12261f;margin-bottom:5px;font-size:12px;}
.tip table{border-collapse:collapse;font-size:11.5px;}
.tip th,.tip td{text-align:left;padding:2px 12px 2px 0;white-space:nowrap;}
.tip th{border-bottom:1px solid #dde;color:#667;}
.tip td:first-child{color:#8a90a0;}
footer{color:#888;font-size:12px;text-align:center;padding:20px;}
footer a{color:#4c78a8;text-decoration:none;}
footer code{background:#eee;padding:1px 4px;border-radius:3px;}
"""


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _stat_card(label, value, rows=None, caption="", cap=60):
    """A header stat card; with `rows` it gains a hover tooltip listing the
    affected entries (original #, username, what changed). Long lists are
    truncated to `cap` rows with a '… and N more' footer."""
    if not rows:
        return '<div class="stat"><b>%s</b>%s</div>' % (_esc(value), _esc(label))
    body = "".join("<tr><td>#%s</td><td>%s</td><td>%s</td></tr>"
                   % (_esc(i), _esc(u), _esc(d)) for i, u, d in rows[:cap])
    if len(rows) > cap:
        body += ('<tr><td></td><td></td><td>&hellip; and %d more</td></tr>'
                 % (len(rows) - cap))
    tip = ('<div class="tip"><div class="tipcap">%s</div><table>'
           "<tr><th>#</th><th>user</th><th>detail</th></tr>%s</table></div>"
           % (_esc(caption), body))
    return ('<div class="stat has-tip"><b>%s</b>%s<span class="i">&#9432;</span>%s</div>'
            % (_esc(value), _esc(label), tip))


def _src_line(name, meta, extra):
    """One header line: linked sheet name, count, fetched + last-updated times,
    and offline/changed badges."""
    fetched = meta["fetched_at"].strftime("%Y-%m-%d %H:%M")
    updated = meta["updated_at"].strftime("%Y-%m-%d %H:%M") if meta["updated_at"] else "—"
    live = ("" if meta["live"]
            else ' <span class="warn">(offline — showing cached copy)</span>')
    return ('<p class="src"><a href="%s" target="_blank" rel="noopener">%s</a> — %s '
            '<span class="dim">·</span> fetched %s%s '
            '<span class="dim">·</span> last updated %s</p>'
            % (meta["view_url"], _esc(name), _esc(extra), fetched, live,
               updated))


def build_dashboard(df, report, resv):
    parts = []
    for i, (title, desc, builder) in enumerate(SECTIONS):
        fig = (builder(df, resv) if builder in (fig_geo, fig_order_timeline)
               else builder(df))
        frag = fig.to_html(full_html=False,
                           include_plotlyjs=(True if i == 0 else False),
                           default_width="100%")
        parts.append(
            '<section><h2>%s</h2><p class="desc">%s</p>%s</section>'
            % (title, desc, frag))

    dc = report["delivery_counts"]
    firm = dc.get("explicit", 0)
    san = report["sanitized"]
    rr, om, rm = report["resv"], report["orders_meta"], report["resv_meta"]
    captions = {
        "Order duplicates": "Rows removed as duplicates in the orders sheet",
        "Reservation duplicates": "Repeat usernames in the reservations sheet (kept first)",
        "Reservations already ordered": "Reservation-holders already counted in the orders sheet",
        "VINs de-obfuscated": "Obfuscated VINs recovered (original → value)",
        "VINs recovered": "VINs that could not be recovered (dropped)",
        "Invalid dates dropped": "Order/reservation dates cleared as out-of-range (original → dropped)",
    }
    stat_groups = [
        ("Cohort", [
            ("Unique orders", report["n_dedup"], None),
            ("Incomplete reservations", rr["n_incomplete"], None),
            ("Total demand", report["n_dedup"] + rr["n_incomplete"], None),
        ]),
        ("Duplicates removed", [
            ("Order duplicates", report["n_raw"] - report["n_dedup"],
             san["Duplicates removed"]),
            ("Reservation duplicates", rr["n_self_dupes"], rr["self_dupe_records"]),
            ("Reservations already ordered", rr["n_matched"], rr["matched_records"]),
        ]),
        ("VIN recovery", [
            ("VINs recovered", report["vin_present"], san["VINs recovered"]),
            ("VINs de-obfuscated", report["vin_obfuscated"], san["VINs de-obfuscated"]),
        ]),
        ("Delivery dates", [
            ("Firm delivery dates", firm, None),
            ("Invalid dates dropped", report["bad_order"] + report["bad_resv"],
             san["Invalid dates dropped"]),
        ]),
    ]
    stat_html = "".join(
        '<div class="statgroup"><span class="sglabel">%s</span>'
        '<div class="stats">%s</div></div>'
        % (_esc(gtitle), "".join(_stat_card(k, v, rows, captions.get(k, ""))
                                 for k, v, rows in cards))
        for gtitle, cards in stat_groups)

    header_html = (
        '<h1>Rivian R2 Orders — Production &amp; Logistics Dashboard</h1>'
        '<p class="disclaimer">All data is self-reported by forum users — '
        'treat as indicative, not official.</p>'
        '<p>Sources:</p>'
        + _src_line("Orders & Deliveries sheet", om,
                    "%d unique orders" % report["n_dedup"])
        + _src_line("Reservations sheet", rm,
                    "%d incomplete reservations (of %d rows)"
                    % (rr["n_incomplete"], rr["n_raw"]))
        + '<p class="meth">Delivery windows are measured from each customer&#8217;s '
          'R2 order date. Order dates before 2026-06-09 and reservations before '
          '2024-03-07 are treated as invalid; reservations already present in the '
          'orders sheet are dropped as duplicates. &#8220;Last updated&#8221; is '
          'when a sheet&#8217;s contents last changed between fetches. Hover the '
          'highlighted stat cards (&#9432;) for the sanitized entries.</p>')

    html = """<!doctype html><html><head><meta charset="utf-8">
<title>Rivian R2 Orders — Dashboard</title><style>%s</style></head><body>
<header>%s
<div class="statwrap">%s</div></header>
<div class="wrap">%s</div>
<footer>Generated by <code>r2_orders</code> · <a href="https://github.com/emroch" target="_blank" rel="noopener">emroch</a> · built with AI assistance.</footer>
</body></html>""" % (PAGE_CSS, header_html, stat_html, "".join(parts))

    with open(DASHBOARD, "w") as fh:
        fh.write(html)
