"""Dashboard assembly: the section registry, template loading, HTML helpers,
and the build_dashboard entry point that renders every chart into one HTML file.

The page's static assets — the stylesheet, the head/theme/nav scripts, and the
page shell — live as real files under templates/; this module fills them with
the computed chart fragments, stat cards, and generated theme variables.
"""
import json
import re
import pandas as pd
from pathlib import Path
from textwrap import dedent

from .charts import (fig_certainty_by_vin, fig_color_wheel_heatmap,
                     fig_config_dashboard, fig_delivery_timeline,
                     fig_delivery_vs_vin, fig_dest_vs_delivery, fig_geo,
                     fig_order_timeline, fig_vin_by_config, fig_vin_vs_order)
from config import CHART_CHROME, COLOR_HEX, DASHBOARD, THEME_CSS

# templates/ sits alongside this render/ package, under the src/ root.
_TPL_DIR = Path(__file__).resolve().parents[1] / "templates"


def _tpl(name):
    """Read a template file (CSS/JS/HTML shell) from templates/."""
    return (_TPL_DIR / name).read_text(encoding="utf-8")


def _fill(tpl, **ctx):
    """Replace each {{name}} token in `tpl` with ctx[name]. Single-pass, so
    injected values (chart HTML, stat cards) are not rescanned for tokens."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: ctx[m.group(1)], tpl)


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

PAGE_CSS = _THEME_VARS_CSS + _tpl("styles.css")

# Runs in <head> before first paint: set the theme (saved > OS preference) so
# the page chrome never flashes the wrong colors.
HEAD_JS = _tpl("head.js")

# The light/dark chart-chrome objects come from theme.yaml (config.CHART_CHROME),
# injected into the script below so THEME_JS and the baked-in chart colors agree.
_CHROME_JS = "var LIGHT=%s;var DARK=%s;" % (
    json.dumps(CHART_CHROME["light"], separators=(",", ":")),
    json.dumps(CHART_CHROME["dark"], separators=(",", ":")))

# Runs at end of <body>: wire the toggle and re-theme the (already-rendered)
# Plotly charts. Data-encoding colors (markers/bars/paints) are left untouched;
# only chart chrome — text, gridlines, geo land/borders, legend boxes, and the
# transparent backgrounds that let the themed card show through — is swapped.
THEME_JS = _tpl("theme.js").replace("/*__CHROME_JS__*/", _CHROME_JS)

# Chart-navigation sidebar: hamburger toggle (narrow screens) + scroll-spy that
# highlights the section currently in view via IntersectionObserver.
NAV_JS = _tpl("nav.js")


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

    html = _fill(_tpl("page.html"),
                 page_css=PAGE_CSS, chrome_css=chrome_css, head_js=HEAD_JS,
                 title=title_html, disclaimer=disclaimer_html,
                 sidebar=sidebar_html, intro=intro_html, stats=stat_html,
                 sections="".join(parts), scripts=THEME_JS + NAV_JS)

    with open(DASHBOARD, "w") as fh:
        fh.write(html)
