"""Dashboard assembly: the section registry, page CSS, HTML helpers, and the
build_dashboard entry point that renders every chart into a single HTML file.
"""
import json
import pandas as pd
from textwrap import dedent

from .charts import (fig_certainty_by_vin, fig_color_wheel_heatmap,
                     fig_config_dashboard, fig_delivery_timeline,
                     fig_delivery_vs_vin, fig_dest_vs_delivery, fig_geo,
                     fig_order_timeline, fig_vin_by_config, fig_vin_vs_order)
from .config import CHART_CHROME, COLOR_HEX, DASHBOARD, THEME_CSS

# Display order = list order. Section numbers (chart titles + sidebar links) are
# assigned from position at render time, so reordering this list is all it takes;
# grouped here as build -> timing -> production/VIN -> geography.
SECTIONS = [
    ("Configuration take-rates",
     dedent("""What this cohort ordered. (Trim, Launch Package, Autonomy+ and Tow are ~100% uniform across the cohort,
               so they are omitted here.)"""),
     fig_config_dashboard),
    ("Color × wheels combinations",
     dedent("""Most common full builds — the combos that would form the clusters in the delivery-vs-VIN chart."""),
     fig_color_wheel_heatmap),
    ("Reservation & order timeline",
     dedent("""The top panel stacks reservation-only holders (incomplete orders, from the separate reservations sheet)
               above those who have since locked an order. The 3/7/2024 reveal week is ~20x the next-biggest week, so
               the y-axis is clipped just above the tail to keep the 2-year trickle readable. The bottom shows when
               orders were finalized."""),
     fig_order_timeline),
    ("Estimated delivery timeline",
     dedent("""When the cohort expects delivery, stacked by how firm the estimate is."""),
     fig_delivery_timeline),
    ("Estimate certainty vs. VIN status",
     dedent("""Share of orders with known delivery dates."""),
     fig_certainty_by_vin),
    ("VIN sequence vs. order date",
     dedent("""Does ordering earlier win a lower (earlier-built) VIN? Slope/scatter shows how tightly production
               sequence tracks order timing. Click a config in the legend to hide it, or double-click to isolate
               one."""),
     fig_vin_vs_order),
    ("Delivery date vs. VIN sequence",
     dedent("""Each point is an order with both a VIN and a delivery estimate. Color = paint, marker shape = wheels;
               whiskers span the quoted delivery window. Clusters of one color across a VIN range hint at same-config
               cars built in sequence. Click a config in the legend to hide it, or double-click to isolate one."""),
     fig_delivery_vs_vin),
    ("VIN sequence by configuration",
     dedent("""Each VIN-assigned order at its production sequence (x), grouped into rows by full configuration (trim ·
               color · wheels); marker fill = paint, shape = wheels. Clusters along a row suggest same-config cars were
               built in a batch."""),
     fig_vin_by_config),
    ("Geographic demand",
     dedent("""Three stacked maps of demand around the Normal, IL plant: orders with an assigned VIN, all orders, and
               total demand (orders + incomplete reservations). Bubble area = count; the first two share a scale, while
               total demand (~20x larger) scales to its own."""),
     fig_geo),
    ("Destination vs. delivery date",
     dedent("""States ordered by distance from the Normal, IL plant (closest at bottom). An upward-right tilt would mean
               farther destinations deliver later. Whiskers span each order's quoted delivery window. Click a region in
               the legend to hide it, or double-click to isolate one."""),
     fig_dest_vs_delivery),
]

def _css_block(sel, vars_):
    """One CSS rule of `--name:value;` custom properties from a {name: value} map."""
    return "%s{%s}" % (sel, "".join("--%s:%s;" % (k, v) for k, v in vars_.items()))


# :root carries the light theme plus the theme-independent `fixed` chrome (the
# always-green header/sidebar/disclaimer); the dark block overrides only what
# changes. Every value lives in theme.yaml — see config.THEME_CSS.
_THEME_VARS_CSS = "\n%s\n%s\n" % (
    _css_block(":root", dict(THEME_CSS["light"], **THEME_CSS["fixed"])),
    _css_block('html[data-theme="dark"]', THEME_CSS["dark"]))

PAGE_CSS = _THEME_VARS_CSS + """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
 margin:0;background:var(--bg);color:var(--fg);
 transition:background .2s ease,color .2s ease;}
html{scroll-behavior:smooth;}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto;}}
/* Pinned bar: spans the full width across the top; the sidebar tucks in beneath
   it. Hamburger + title + theme toggle + disclaimer stay visible. */
.topbar{position:sticky;top:0;z-index:60;background:var(--header-bg);
 color:var(--topbar-fg);padding:12px 40px;box-shadow:0 2px 8px var(--topbar-sh);}
.topbar-row{display:flex;align-items:flex-start;gap:14px;}
.topbar-head{flex:1;min-width:0;}
.topbar h1{margin:0;font-size:20px;}
/* Disclaimer lives in the title column, so it insets to align with the title. */
.topbar p.disclaimer{margin:8px 0 0;padding:5px 10px;font-weight:600;
 font-size:12.5px;color:var(--disc-fg);background:var(--disc-bg);
 border-left:3px solid var(--disc-bd);border-radius:4px;}
/* Intro is a normal body-section card now (see the `section` rules below); only
   its inner text/links need styling, themed like the rest of the page. */
.intro p{margin:0;color:var(--fg);font-size:14px;}
.intro p.src{margin:3px 0;font-size:13px;color:var(--desc);}
.intro p.src a{color:var(--link);text-decoration:none;border-bottom:1px dotted currentColor;}
.intro p.src a:hover{filter:brightness(1.15);}
.intro p.meth{margin:10px 0 0;color:var(--desc);font-size:12.5px;line-height:1.5;}
.intro .warn{color:var(--warn);font-weight:600;}
.intro .chg{color:var(--chg);font-weight:600;}
.intro .dim{color:var(--desc);}
.themebtn{flex:none;background:var(--btn-bg);color:var(--btn-fg);
 border:1px solid var(--btn-bd);border-radius:20px;padding:6px 14px;
 font-size:12.5px;cursor:pointer;line-height:1;white-space:nowrap;}
.themebtn:hover{filter:brightness(1.15);}
.navbtn{flex:none;background:var(--btn-bg);color:var(--btn-fg);
 border:1px solid var(--btn-bd);border-radius:8px;padding:5px 11px;font-size:15px;
 line-height:1;cursor:pointer;}
.navbtn:hover{filter:brightness(1.15);}
/* Chart-nav sidebar: Launch-Green rail, hidden by default, toggled by the
   hamburger (nav-shown on <html>); pushes content on wide, overlays on narrow. */
.sidebar{position:fixed;top:var(--header-h,92px);left:0;bottom:0;width:220px;overflow-y:auto;
 z-index:55;background:var(--side-bg,#8C9A83);border-right:1px solid var(--side-bd);
 box-shadow:2px 0 10px var(--side-sh);transform:translateX(-100%);
 transition:transform .2s ease;}
html.nav-shown .sidebar{transform:translateX(0);}
.side-title{padding:14px 16px 8px;font-size:10.5px;text-transform:uppercase;
 letter-spacing:.08em;color:var(--side-title);}
.sidebar a{display:block;padding:6px 14px;font-size:12.5px;color:var(--side-fg);
 text-decoration:none;border-left:3px solid transparent;line-height:1.35;}
.sidebar a:hover{background:var(--side-hover);}
.sidebar a.active{border-left-color:var(--side-active-bd);color:var(--side-active-fg);font-weight:600;
 background:var(--side-active-bg);}
.nav-backdrop{display:none;}
.main{margin-left:0;transition:margin-left .2s ease;}
@media (min-width:901px){html.nav-shown .main{margin-left:220px;}}
@media (max-width:900px){
 html.nav-shown .nav-backdrop{display:block;position:fixed;z-index:54;
  top:var(--header-h,92px);left:0;right:0;bottom:0;background:var(--backdrop);}
}
section{scroll-margin-top:calc(var(--header-h,92px) + 8px);}
.wrap{max-width:1180px;margin:0 auto;padding:8px 24px 60px;}
section{background:var(--card-bg);border:1px solid var(--card-bd);border-radius:10px;
 margin:26px 0;padding:18px 22px;box-shadow:0 1px 3px var(--card-sh);
 transition:background .2s ease,border-color .2s ease;}
section h2{margin:0 0 4px;font-size:19px;color:var(--sec-title);}
section p.desc{margin:0 0 8px;color:var(--desc);font-size:13.5px;line-height:1.45;}
.statwrap{margin-top:14px;}
.statgroup{margin-top:12px;}
.sglabel{display:block;font-size:10.5px;text-transform:uppercase;
 letter-spacing:.08em;color:var(--desc);margin:0 0 5px 2px;}
.stats{display:flex;flex-wrap:wrap;gap:12px;}
.stat{position:relative;background:var(--stat-bg);color:var(--chip-fg);border-radius:8px;
 padding:10px 18px;font-size:12.5px;white-space:nowrap;min-width:96px;}
.stat b{font-size:18px;display:block;line-height:1.25;}
.stat.has-tip{cursor:help;}
.stat .i{opacity:.55;font-size:11px;margin-left:2px;}
.stat .tip{display:none;position:absolute;left:0;top:calc(100% + 8px);z-index:30;
 background:var(--tip-bg);color:var(--tip-fg);border:1px solid var(--tip-bd);
 border-radius:8px;font-weight:400;
 box-shadow:0 6px 20px var(--tip-sh);padding:9px 11px;max-height:300px;overflow:auto;}
.stat:hover .tip{display:block;}
.tipcap{font-weight:600;color:var(--tip-cap);margin-bottom:5px;font-size:12px;}
.tip table{border-collapse:collapse;font-size:11.5px;}
.tip th,.tip td{text-align:left;padding:2px 12px 2px 0;white-space:nowrap;}
.tip th{border-bottom:1px solid var(--tip-th);color:var(--tip-thc);}
.tip td:first-child{color:var(--tip-td1);}
.qa{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
 gap:16px;margin-top:6px;}
.qa-cat{border:1px solid var(--card-bd);border-radius:8px;padding:10px 12px;}
.qa-cat h3{margin:0 0 3px;font-size:13.5px;color:var(--sec-title);}
.qa-n{display:inline-block;min-width:18px;text-align:center;padding:0 6px;
 margin-left:7px;border-radius:10px;background:var(--tip-th);color:var(--fg);
 font-size:11px;font-weight:600;}
.qa-note{margin:0 0 7px;color:var(--desc);font-size:11.5px;line-height:1.4;}
.qa table{border-collapse:collapse;font-size:11.5px;width:100%;display:block;
 max-height:220px;overflow:auto;}
.qa th,.qa td{text-align:left;padding:2px 10px 2px 0;white-space:nowrap;}
.qa th{border-bottom:1px solid var(--tip-th);color:var(--tip-thc);
 position:sticky;top:0;background:var(--card-bg);}
.qa td:first-child{color:var(--tip-td1);}
.qa-none{margin:2px 0 0;color:var(--desc);font-size:12px;}
.qa-conv{margin-top:16px;border:1px solid var(--card-bd);border-radius:8px;
 padding:10px 12px;}
.qa-conv h3{margin:0 0 3px;font-size:13.5px;color:var(--sec-title);}
.qa-conv table{border-collapse:collapse;font-size:11.5px;width:100%;
 display:block;max-height:260px;overflow:auto;}
.qa-conv th,.qa-conv td{text-align:left;padding:2px 16px 2px 0;white-space:nowrap;}
.qa-conv th{border-bottom:1px solid var(--tip-th);color:var(--tip-thc);
 position:sticky;top:0;background:var(--card-bg);}
footer{color:var(--footer);font-size:12px;text-align:center;padding:20px;}
footer a{color:var(--footer-link);text-decoration:none;}
footer code{background:var(--code-bg);color:var(--code-fg);padding:1px 4px;border-radius:3px;}
"""

# Runs in <head> before first paint: set the theme (saved > OS preference) so
# the page chrome never flashes the wrong colors.
HEAD_JS = """
(function(){try{var t=localStorage.getItem('r2theme');
if(t!=='dark'&&t!=='light'){t=(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);
if(window.innerWidth>900)document.documentElement.classList.add('nav-shown');
}catch(e){}})();
"""

# The light/dark chart-chrome objects come from theme.yaml (config.CHART_CHROME),
# injected into the script below so THEME_JS and the baked-in chart colors agree.
_CHROME_JS = "var LIGHT=%s;var DARK=%s;" % (
    json.dumps(CHART_CHROME["light"], separators=(",", ":")),
    json.dumps(CHART_CHROME["dark"], separators=(",", ":")))

# Runs at end of <body>: wire the toggle and re-theme the (already-rendered)
# Plotly charts. Data-encoding colors (markers/bars/paints) are left untouched;
# only chart chrome — text, gridlines, geo land/borders, legend boxes, and the
# transparent backgrounds that let the themed card show through — is swapped.
THEME_JS = """
(function(){
%s
function themeCharts(dark){
 if(!window.Plotly)return;
 var t=dark?DARK:LIGHT;
 document.querySelectorAll('.js-plotly-plot').forEach(function(gd){
  if(!gd.layout)return;
  var managed=[LIGHT.edge,DARK.edge];
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
  (gd.layout.shapes||[]).forEach(function(sh,i){
   var sc=sh.line&&sh.line.color?String(sh.line.color).toLowerCase():null;
   if(sc&&managed.indexOf(sc)>=0)up['shapes['+i+'].line.color']=t.edge;
  });
  (gd.layout.annotations||[]).forEach(function(an,i){
   var ac=an.font&&an.font.color?String(an.font.color).toLowerCase():null;
   if(ac&&managed.indexOf(ac)>=0)up['annotations['+i+'].font.color']=t.edge;
  });
  // Filter dropdowns/buttons keep a fixed light background + dark text (not
  // theme-swapped): their hover highlight is a fixed bright fill, so dark text
  // stays legible in both idle and hover states, in light or dark mode.
  try{window.Plotly.relayout(gd,up);}catch(e){}
  var idx=[],staridx=[];
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
""" % _CHROME_JS

# Chart-navigation sidebar: hamburger toggle (narrow screens) + scroll-spy that
# highlights the section currently in view via IntersectionObserver.
NAV_JS = """
(function(){
 var el=document.documentElement;
 function close(){el.classList.remove('nav-shown');}
 var tgl=document.getElementById('navToggle');
 if(tgl)tgl.addEventListener('click',function(){el.classList.toggle('nav-shown');});
 var bd=document.getElementById('navBackdrop');
 if(bd)bd.addEventListener('click',close);
 var links={};
 document.querySelectorAll('.sidebar a[data-sec]').forEach(function(a){
  links[a.getAttribute('data-sec')]=a;
  a.addEventListener('click',function(){if(window.innerWidth<=900)close();});
 });
 var secs=document.querySelectorAll('section[id]');
 if(secs.length&&'IntersectionObserver' in window){
  var obs=new IntersectionObserver(function(entries){
   entries.forEach(function(e){
    if(e.isIntersecting)for(var k in links)links[k].classList.toggle('active',k===e.target.id);
   });
  },{rootMargin:'-45% 0px -50% 0px',threshold:0});
  secs.forEach(function(s){obs.observe(s);});
 }
 // Tuck the sidebar/backdrop below the full-width header (its height is dynamic).
 function setHeaderH(){var h=document.querySelector('.topbar');
  if(h)el.style.setProperty('--header-h',h.offsetHeight+'px');}
 setHeaderH();
 window.addEventListener('resize',setHeaderH);
 window.addEventListener('load',setHeaderH);
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


# Data-quality categories: (report["quality"] key, heading, one-line note).
_QA_CATS = [
    ("unparseable", "Unparseable delivery estimates",
     "Non-empty delivery text that didn't normalize to a date, range, or window."),
    ("fuzzy_dups", "Possible duplicate usernames",
     "Usernames that normalize alike (case/space/punctuation) but weren't merged "
     "by the exact-duplicate dedup."),
    ("vin_unrec", "Unrecoverable VINs",
     "VIN tokens too redacted to recover a sequence number."),
    ("bad_dates", "Invalid dates dropped",
     "Order/reservation dates outside the plausible window, cleared."),
    ("override_issues", "Override issues",
     "Manual fix-ups or additions in overrides.yaml that referenced an unknown "
     "field, a username with no matching order, or an addition already in the "
     "sheet."),
]


def _quality_section(quality, num, cap=40):
    """The data-quality / anomaly panel: things flagged for human review rather
    than auto-corrected. Each category lists the affected (#, user, detail)."""
    blocks = []
    for key, name, note in _QA_CATS:
        rows = quality.get(key, [])
        if rows:
            body = "".join("<tr><td>#%s</td><td>%s</td><td>%s</td></tr>"
                           % (_esc(i), _esc(u), _esc(d)) for i, u, d in rows[:cap])
            if len(rows) > cap:
                body += ('<tr><td></td><td></td><td>&hellip; and %d more</td></tr>'
                         % (len(rows) - cap))
            content = ('<table><tr><th>#</th><th>user</th><th>detail</th></tr>'
                       '%s</table>' % body)
        else:
            content = '<p class="qa-none">None &#10003;</p>'
        blocks.append('<div class="qa-cat"><h3>%s<span class="qa-n">%d</span></h3>'
                      '<p class="qa-note">%s</p>%s</div>'
                      % (_esc(name), len(rows), _esc(note), content))
    conv = quality.get("conversions", [])
    conv_body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                        % (_esc(r), _esc(t), _esc(anc), _esc(res))
                        for r, t, res, anc in conv)
    conv_html = (
        '<div class="qa-conv"><h3>Delivery date parsing'
        '<span class="qa-n">%d</span></h3>'
        '<p class="qa-note">Every distinct delivery string that parsed, and the '
        'date or range it became — for sanity-checking the normalization. Window '
        'estimates are relative, so the anchor they were measured from (the order '
        'date, or the as-of date as a fallback) is shown.</p>'
        '<table><tr><th>raw</th><th>type</th><th>anchor</th><th>parsed</th></tr>'
        '%s</table></div>'
        % (len(conv), conv_body))
    return ('<section id="sec-%d"><h2>%d · Data quality &amp; anomalies</h2>'
            '<p class="desc">Rows flagged for human review — surfaced here, not '
            'auto-corrected. An empty category means nothing tripped that '
            'check.</p><div class="qa">%s</div>%s</section>'
            % (num, num, "".join(blocks), conv_html))


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
        # Numbering (DOM order): the summary card is section 1, so charts are
        # 2..N+1 and the data-quality panel is N+2.
        parts.append(
            '<section id="sec-%d"><h2>%d · %s</h2><p class="desc">%s</p>%s</section>'
            % (i + 2, i + 2, _esc(title), desc, frag))
    parts.append(_quality_section(report["quality"], len(SECTIONS) + 2))

    dc = report["delivery_counts"]
    firm = dc.get("explicit", 0)
    rangewin = dc.get("window", 0) + dc.get("range", 0) + dc.get("month", 0)
    unparseable = report["quality"]["unparseable"]
    # unknown = "no date given" (missing/placeholder) + unparseable; split them.
    no_date = dc.get("unknown", 0) - len(unparseable)
    san = report["sanitized"]
    rr, om, rm = report["resv"], report["orders_meta"], report["resv_meta"]
    captions = {
        "Order duplicates": "Rows removed as duplicates in the orders sheet",
        "Reservation duplicates": "Repeat usernames in the reservations sheet (kept first)",
        "Reservations already ordered": "Reservation-holders already counted in the orders sheet",
        "VINs de-obfuscated": "Obfuscated VINs recovered (original → value)",
        "VINs recovered": "VINs that could not be recovered (dropped)",
        "Invalid dates dropped": "Order/reservation dates cleared as out-of-range (original → dropped)",
        "Unparseable": "Non-empty delivery text that didn't parse to a date/range",
        "Manual fix-ups": "Fields set or corrected via overrides.yaml (field: old → new)",
        "Manual additions": "Forum-only orders appended via overrides.yaml (not in the sheet)",
    }
    stat_groups = [
        ("Cohort", [
            ("Unique orders", report["n_dedup"], None),
            ("Manual additions", report["n_added"], san["Manual additions"]),
            ("Incomplete reservations", rr["n_incomplete"], None),
            ("Total demand", report["n_dedup"] + rr["n_incomplete"], None),
        ]),
        ("Cleaned / removed", [
            ("Order duplicates", len(san["Duplicates removed"]),
             san["Duplicates removed"]),
            ("Reservation duplicates", rr["n_self_dupes"], rr["self_dupe_records"]),
            ("Reservations already ordered", rr["n_matched"], rr["matched_records"]),
            ("Invalid dates dropped", report["bad_order"] + report["bad_resv"],
             san["Invalid dates dropped"]),
            ("Manual fix-ups", len(san["Manual fix-ups"]), san["Manual fix-ups"]),
        ]),
        ("VIN recovery", [
            ("VINs recovered", report["vin_present"], san["VINs recovered"]),
            ("VINs de-obfuscated", report["vin_obfuscated"], san["VINs de-obfuscated"]),
        ]),
        # Partitions all orders: firm + range/window + no date + unparseable = total.
        ("Delivery estimate (of %d orders)" % report["n_dedup"], [
            ("Firm date", firm, None),
            ("Range / window", rangewin, None),
            ("No date given", no_date, None),
            ("Unparseable", len(unparseable), unparseable),
        ]),
    ]
    stat_html = "".join(
        '<div class="statgroup"><span class="sglabel">%s</span>'
        '<div class="stats">%s</div></div>'
        % (_esc(gtitle), "".join(_stat_card(k, v, rows, captions.get(k, ""))
                                 for k, v, rows in cards))
        for gtitle, cards in stat_groups)

    title_html = '<h1>Rivian R2 Orders — Production &amp; Logistics Dashboard</h1>'
    disclaimer_html = ('<p class="disclaimer">All data is self-reported by forum '
                       'users — treat as indicative, not official.</p>')
    intro_html = (
        '<h2>1 · Sources &amp; summary</h2>'
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
          'highlighted stat cards (&#9432;) for the sanitized entries. Charts with '
          'a legend are interactive &mdash; click an entry to hide that series, '
          'double-click to isolate one; see each chart&#8217;s note for its '
          'paint, region, and wheel filters.</p>')

    # Chart-navigation sidebar: the summary card (1), each chart (2..N+1), and
    # the QA panel (N+2), numbered by position to match the section headings.
    nav_items = [("sec-1", "1 · Sources & summary")]
    nav_items += [("sec-%d" % (i + 2), "%d · %s" % (i + 2, t))
                  for i, (t, _, _) in enumerate(SECTIONS)]
    qa_num = len(SECTIONS) + 2
    nav_items.append(("sec-%d" % qa_num, "%d · Data quality & anomalies" % qa_num))
    nav_links = "".join('<a href="#%s" data-sec="%s">%s</a>' % (sid, sid, _esc(t))
                        for sid, t in nav_items)
    sidebar_html = ('<nav class="sidebar" id="sidebar"><div class="side-title">'
                    'Sections</div>%s</nav>' % nav_links)

    # Header/sidebar chrome takes its greens from the palette (a nod to the
    # Rivian paints): Forest Green for the header, Launch Green for the sidebar.
    chrome_css = ":root{--header-bg:%s;--side-bg:%s;}" % (
        COLOR_HEX.get("Forest Green", "#226222"),
        COLOR_HEX.get("Launch Green", "#91aa81"))

    html = """<!doctype html><html><head><meta charset="utf-8">
<title>Rivian R2 Orders — Dashboard</title><style>%s
%s</style>
<script>%s</script></head><body>
<header class="topbar"><div class="topbar-row"><button id="navToggle" class="navbtn" type="button" aria-label="Toggle chart menu">☰</button><div class="topbar-head">%s%s</div><button id="themeToggle" class="themebtn" type="button" aria-label="Toggle color theme">☾ Dark</button></div></header>
%s<div class="nav-backdrop" id="navBackdrop"></div>
<div class="main">
<div class="wrap">
<section class="intro" id="sec-1">%s
<div class="statwrap">%s</div></section>
%s</div>
<footer>Generated by <code>r2_orders</code> · <a href="https://github.com/emroch" target="_blank" rel="noopener">emroch</a> · built with Claude Code.</footer>
</div>
<script>%s</script>
</body></html>""" % (PAGE_CSS, chrome_css, HEAD_JS, title_html, disclaimer_html,
                     sidebar_html, intro_html, stat_html, "".join(parts),
                     THEME_JS + NAV_JS)

    with open(DASHBOARD, "w") as fh:
        fh.write(html)
