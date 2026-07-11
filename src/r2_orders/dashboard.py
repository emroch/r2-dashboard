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
:root{
 --bg:#fafafa; --fg:#1c1c1c;
 --card-bg:#ffffff; --card-bd:#e6e6e6; --card-sh:rgba(0,0,0,.04);
 --sec-title:#12261f; --desc:#555555;
 --tip-bg:#ffffff; --tip-fg:#223333; --tip-bd:#ccdddd; --tip-cap:#12261f;
 --tip-th:#dddddd; --tip-thc:#667080; --tip-td1:#8a90a0;
 --footer:#888888; --code-bg:#eeeeee; --code-fg:inherit;
 --btn-bg:rgba(255,255,255,.14); --btn-fg:#eafff4; --btn-bd:rgba(255,255,255,.32);
}
html[data-theme="dark"]{
 --bg:#15171c; --fg:#dfe4ea;
 --card-bg:#1e2127; --card-bd:#2f343d; --card-sh:rgba(0,0,0,.45);
 --sec-title:#bfe6d2; --desc:#aab3bd;
 --tip-bg:#242830; --tip-fg:#d7dde3; --tip-bd:#3a404a; --tip-cap:#bfe6d2;
 --tip-th:#3a404a; --tip-thc:#9aa4b0; --tip-td1:#8a93a0;
 --footer:#8a929c; --code-bg:#2a2f37; --code-fg:#dfe4ea;
 --btn-bg:rgba(255,255,255,.10); --btn-fg:#eafff4; --btn-bd:rgba(255,255,255,.24);
}
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
 margin:0;background:var(--bg);color:var(--fg);
 transition:background .2s ease,color .2s ease;}
header{position:relative;background:#12261f;color:#fff;padding:28px 40px;}
header h1{margin:0 0 6px;font-size:24px;padding-right:120px;}
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
.themebtn{position:absolute;top:22px;right:28px;background:var(--btn-bg);
 color:var(--btn-fg);border:1px solid var(--btn-bd);border-radius:20px;
 padding:6px 14px;font-size:12.5px;cursor:pointer;line-height:1;}
.themebtn:hover{filter:brightness(1.15);}
.wrap{max-width:1180px;margin:0 auto;padding:8px 24px 60px;}
section{background:var(--card-bg);border:1px solid var(--card-bd);border-radius:10px;
 margin:26px 0;padding:18px 22px;box-shadow:0 1px 3px var(--card-sh);
 transition:background .2s ease,border-color .2s ease;}
section h2{margin:0 0 4px;font-size:19px;color:var(--sec-title);}
section p.desc{margin:0 0 8px;color:var(--desc);font-size:13.5px;line-height:1.45;}
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
 background:var(--tip-bg);color:var(--tip-fg);border:1px solid var(--tip-bd);
 border-radius:8px;font-weight:400;
 box-shadow:0 6px 20px rgba(0,0,0,.22);padding:9px 11px;max-height:300px;overflow:auto;}
.stat:hover .tip{display:block;}
.tipcap{font-weight:600;color:var(--tip-cap);margin-bottom:5px;font-size:12px;}
.tip table{border-collapse:collapse;font-size:11.5px;}
.tip th,.tip td{text-align:left;padding:2px 12px 2px 0;white-space:nowrap;}
.tip th{border-bottom:1px solid var(--tip-th);color:var(--tip-thc);}
.tip td:first-child{color:var(--tip-td1);}
footer{color:var(--footer);font-size:12px;text-align:center;padding:20px;}
footer a{color:#4c78a8;text-decoration:none;}
footer code{background:var(--code-bg);color:var(--code-fg);padding:1px 4px;border-radius:3px;}
"""

# Runs in <head> before first paint: set the theme (saved > OS preference) so
# the page chrome never flashes the wrong colors.
HEAD_JS = """
(function(){try{var t=localStorage.getItem('r2theme');
if(t!=='dark'&&t!=='light'){t=(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
"""

# Runs at end of <body>: wire the toggle and re-theme the (already-rendered)
# Plotly charts. Data-encoding colors (markers/bars/paints) are left untouched;
# only chart chrome — text, gridlines, geo land/borders, legend boxes, and the
# transparent backgrounds that let the themed card show through — is swapped.
THEME_JS = """
(function(){
var LIGHT={text:'#1c1c1c',grid:'#e9e9e9',line:'#c9c9c9',land:'#f2f2f0',
 sub:'#c4c4c4',country:'#9e9e9e',legbg:'rgba(255,255,255,0.75)',legbd:'#dddddd',
 edge:'#2b2b2b',star:'#111111'};
var DARK={text:'#d7dde3',grid:'#333941',line:'#4a515a',land:'#2a2d33',
 sub:'#474d56',country:'#5c636d',legbg:'rgba(30,33,38,0.85)',legbd:'#4a515a',
 edge:'#aab0b8',star:'#e8e8e8'};
function themeCharts(dark){
 if(!window.Plotly)return;
 var t=dark?DARK:LIGHT;
 document.querySelectorAll('.js-plotly-plot').forEach(function(gd){
  if(!gd.layout)return;
  var up={'font.color':t.text,'paper_bgcolor':'rgba(0,0,0,0)',
          'plot_bgcolor':'rgba(0,0,0,0)'};
  Object.keys(gd.layout).forEach(function(k){
   if(/^xaxis|^yaxis/.test(k)){
    up[k+'.gridcolor']=t.grid;up[k+'.zerolinecolor']=t.grid;up[k+'.linecolor']=t.line;
   }else if(/^geo/.test(k)){
    up[k+'.bgcolor']='rgba(0,0,0,0)';up[k+'.landcolor']=t.land;
    up[k+'.subunitcolor']=t.sub;up[k+'.countrycolor']=t.country;
   }else if(/^legend/.test(k)){
    up[k+'.bgcolor']=t.legbg;up[k+'.bordercolor']=t.legbd;
    up[k+'.font.color']=t.text;up[k+'.title.font.color']=t.text;
   }
  });
  try{window.Plotly.relayout(gd,up);}catch(e){}
  var managed=['#2b2b2b','#aab0b8'],idx=[],staridx=[];
  (gd.data||[]).forEach(function(tr,i){
   var lc=tr.marker&&tr.marker.line?tr.marker.line.color:null;
   if(typeof lc==='string'&&managed.indexOf(lc.toLowerCase())>=0)idx.push(i);
   if(tr.marker&&tr.marker.symbol==='star')staridx.push(i);
  });
  if(idx.length){try{window.Plotly.restyle(gd,{'marker.line.color':t.edge},idx);}catch(e){}}
  if(staridx.length){try{window.Plotly.restyle(gd,{'marker.color':t.star},staridx);}catch(e){}}
 });
}
function apply(t){
 document.documentElement.setAttribute('data-theme',t);
 var b=document.getElementById('themeToggle');
 if(b)b.textContent=(t==='dark'?'\\u2600 Light':'\\u263e Dark');
 themeCharts(t==='dark');
}
window.addEventListener('load',function(){
 apply(document.documentElement.getAttribute('data-theme')||'light');
 var b=document.getElementById('themeToggle');
 if(b)b.addEventListener('click',function(){
  var cur=document.documentElement.getAttribute('data-theme')==='dark'?'dark':'light';
  var nt=cur==='dark'?'light':'dark';
  try{localStorage.setItem('r2theme',nt);}catch(e){}
  apply(nt);
 });
});
})();
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
        # Transparent backgrounds let the themed section card show through, so
        # the charts adapt to light/dark (chrome is re-tinted by THEME_JS).
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)")
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
<title>Rivian R2 Orders — Dashboard</title><style>%s</style>
<script>%s</script></head><body>
<header><button id="themeToggle" class="themebtn" type="button" aria-label="Toggle color theme">☾ Dark</button>
%s
<div class="statwrap">%s</div></header>
<div class="wrap">%s</div>
<footer>Generated by <code>r2_orders</code> · <a href="https://github.com/emroch" target="_blank" rel="noopener">emroch</a> · built with AI assistance.</footer>
<script>%s</script>
</body></html>""" % (PAGE_CSS, HEAD_JS, header_html, stat_html, "".join(parts), THEME_JS)

    with open(DASHBOARD, "w") as fh:
        fh.write(html)
